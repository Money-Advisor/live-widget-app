"""A dropped connection must not cost us any of the call.

When the socket dies mid-call the widget spools PCM to disk instead of discarding it,
reconnects, resumes the SAME server session, replays the spool in order, and only then
returns to live streaming. These tests pin the ordering guarantees and the "never lose
a chunk, never leave PII behind" rules.
"""
import os
import struct
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

import main


class FakeWS:
    """Stand-in socket. `fail` makes every send raise, like a dead connection."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_binary(self, data):
        if self.fail:
            raise OSError("socket dead")
        self.sent.append(data)

    def send(self, data):
        if self.fail:
            raise OSError("socket dead")
        self.sent.append(data)

    def close(self):
        pass

    def settimeout(self, _t):
        pass


@pytest.fixture
def streamer(tmp_path, monkeypatch):
    """An AudioStreamer wired to a fake socket, spooling into tmp_path, with the
    reconnect thread stubbed out (reconnection itself is exercised separately)."""
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    st = main.AudioStreamer(
        "ws://test.invalid", "client-1", "sess-1", "agent-1",
        "Cust", "cust-1", "REF1", token="tok", register_for_dialer=False)
    st._ws = FakeWS()
    st._session_live.set()          # pretend session_start already succeeded
    st._reconnect_loop = lambda: None   # don't spawn real reconnect attempts
    return st


def frame(stream_type: str, pcm: bytes) -> bytes:
    tb = stream_type.encode()
    return struct.pack("I", len(tb)) + tb + pcm


# ── healthy path is unchanged ───────────────────────────────────────────────
def test_healthy_send_goes_straight_to_the_socket(streamer, tmp_path):
    streamer.send_audio("mic", b"\x01\x02")
    assert streamer._ws.sent == [frame("mic", b"\x01\x02")]
    assert not streamer._degraded.is_set()
    assert list(tmp_path.glob("*.spool")) == [], "no spool while healthy"


def test_pause_still_drops_audio(streamer):
    """PCI pause must keep working — paused audio is never sent OR spooled."""
    streamer.set_paused(True)
    streamer.send_audio("mic", b"card-digits")
    assert streamer._ws.sent == []
    assert not streamer._degraded.is_set()
    streamer._spool_r = None
    assert streamer._spool_next() is None, "paused audio must never reach the spool"


# ── the drop ────────────────────────────────────────────────────────────────
def test_send_failure_buffers_the_chunk_instead_of_losing_it(streamer):
    streamer._ws.fail = True
    streamer.send_audio("mic", b"important")

    assert streamer._degraded.is_set(), "a failed send must switch to buffering"
    got = streamer._spool_next()
    assert got == frame("mic", b"important"), "the failed chunk must be kept, not dropped"


def test_while_degraded_everything_is_buffered_in_order(streamer):
    streamer._enter_degraded("test")
    for i in range(5):
        streamer.send_audio("mic", bytes([i]))
    streamer.send_audio("speaker", b"\xaa")

    read = []
    while True:
        p = streamer._spool_next()
        if p is None:
            break
        read.append(p)
    assert read == [frame("mic", bytes([i])) for i in range(5)] + [frame("speaker", b"\xaa")]


def test_degraded_does_not_touch_the_dead_socket(streamer):
    streamer._enter_degraded("test")
    streamer._ws = FakeWS(fail=True)   # any send would raise
    streamer.send_audio("mic", b"x")   # must not even try
    assert streamer._ws.sent == []


# ── the recovery ────────────────────────────────────────────────────────────
def test_drain_replays_in_order_then_returns_to_live(streamer, tmp_path):
    streamer._enter_degraded("test")
    for i in range(4):
        streamer.send_audio("mic", bytes([i]))

    streamer._ws = FakeWS()            # reconnected
    assert streamer._drain_spool() is True

    assert streamer._ws.sent == [frame("mic", bytes([i])) for i in range(4)], \
        "buffered audio must be replayed in the order it was captured"
    assert not streamer._degraded.is_set(), "back to live streaming after the drain"
    assert list(tmp_path.glob("*.spool")) == [], "local copy deleted once delivered"


def test_live_audio_after_drain_goes_to_the_socket(streamer):
    streamer._enter_degraded("test")
    streamer.send_audio("mic", b"buffered")
    streamer._ws = FakeWS()
    streamer._drain_spool()
    streamer.send_audio("mic", b"live")

    assert streamer._ws.sent == [frame("mic", b"buffered"), frame("mic", b"live")], \
        "the replayed chunk must land BEFORE the new live one"


def test_drop_during_replay_keeps_the_undelivered_frame(streamer, tmp_path):
    """If the link dies again mid-replay, the frame in flight must survive."""
    streamer._enter_degraded("test")
    streamer.send_audio("mic", b"a")
    streamer.send_audio("mic", b"b")

    class FlakyWS(FakeWS):
        def send_binary(self, data):
            if len(self.sent) >= 1:
                raise OSError("dropped again")
            self.sent.append(data)

    streamer._ws = FlakyWS()
    assert streamer._drain_spool() is False
    assert streamer._degraded.is_set(), "still degraded after a failed replay"
    assert list(tmp_path.glob("*.spool")), "spool must be kept for another attempt"

    # The frame that failed is still first in line for the next attempt.
    streamer._ws = FakeWS()
    assert streamer._drain_spool() is True
    assert streamer._ws.sent == [frame("mic", b"b")]


def test_chunks_arriving_during_the_drain_are_not_reordered(streamer):
    """Capture never stops. A chunk produced mid-drain must go behind the backlog."""
    streamer._enter_degraded("test")
    streamer.send_audio("mic", b"old-1")
    streamer.send_audio("mic", b"old-2")

    ws = FakeWS()
    original = ws.send_binary

    def send_and_inject(data):
        original(data)
        if len(ws.sent) == 1:          # mid-drain: the mic thread produces more
            streamer.send_audio("mic", b"new-1")

    ws.send_binary = send_and_inject
    streamer._ws = ws
    assert streamer._drain_spool() is True
    assert ws.sent == [frame("mic", b"old-1"), frame("mic", b"old-2"), frame("mic", b"new-1")]
    assert not streamer._degraded.is_set()


def test_chunk_landing_in_the_final_check_window_is_not_dropped(streamer):
    """Regression: the drain does a second 'is it empty?' check under the send lock.
    If a chunk arrives in that window it is consumed by the check — it must be SENT,
    not silently discarded (that would lose ~93ms of the call)."""
    streamer._enter_degraded("test")
    streamer.send_audio("mic", b"first")
    ws = FakeWS()
    streamer._ws = ws

    # Land a chunk in the EXACT window: after the drain's first "empty?" read returns
    # None, but before the re-check under the lock. That re-check consumes it, so the
    # buggy version dropped it on the floor.
    real_next = streamer._spool_next
    state = {"injected": False}

    def next_with_injection():
        packet = real_next()
        if packet is None and not state["injected"]:
            state["injected"] = True
            streamer._spool_write(frame("mic", b"last-gasp"))
        return packet

    streamer._spool_next = next_with_injection

    assert streamer._drain_spool() is True
    assert ws.sent == [frame("mic", b"first"), frame("mic", b"last-gasp")], \
        "the chunk consumed by the emptiness check must still be delivered"
    assert not streamer._degraded.is_set()


def test_partial_header_does_not_desync_the_spool(streamer, tmp_path):
    """A torn write must not shift the read cursor off the frame boundary, or every
    later frame would be garbage."""
    streamer._enter_degraded("test")
    streamer.send_audio("mic", b"good-frame")

    # Simulate a writer caught mid-flush: only the first 2 bytes of the next record's
    # 4-byte length header have hit the disk.
    nxt = frame("mic", b"xy")
    hdr = struct.pack("<I", len(nxt))
    with open(streamer._spool_path, "ab") as fh:
        fh.write(hdr[:2])

    assert streamer._spool_next() == frame("mic", b"good-frame")
    assert streamer._spool_next() is None          # torn tail -> nothing readable yet

    # Now the rest of the record lands. It must read back intact — if the torn read
    # had left the cursor 2 bytes in, every frame from here on would be garbage.
    with open(streamer._spool_path, "ab") as fh:
        fh.write(hdr[2:] + nxt)
    assert streamer._spool_next() == nxt


def test_stale_receiver_does_not_break_the_resumed_connection(streamer):
    """After a resume there is briefly an old receiver thread unwinding on the previous
    socket. Its death must NOT be mistaken for the new connection dying — that would
    kick a perfectly healthy call back into buffering."""
    old_ws = streamer._ws
    new_ws = FakeWS()
    streamer._ws = new_ws                      # the resume already swapped it in
    streamer._receiver_stop.clear()

    class Dead:
        def settimeout(self, _t): pass
        def recv(self): raise OSError("old socket closed")

    # The stale thread was bound to the OLD socket, so it must stay quiet.
    streamer._receiver_loop(Dead())
    assert not streamer._degraded.is_set(), \
        "a stale receiver must not degrade the new, working connection"

    # ...but a failure on the CURRENT socket must still be reported.
    class DeadCurrent:
        def settimeout(self, _t): pass
        def recv(self): raise OSError("current socket died")

    streamer._ws = None
    dc = DeadCurrent()
    streamer._ws = dc
    streamer._receiver_loop(dc)
    assert streamer._degraded.is_set(), "a real drop on the live socket must be caught"


# ── control frames ──────────────────────────────────────────────────────────
def test_control_failure_before_a_session_raises(tmp_path, monkeypatch):
    """During connect() there is no session to resume — the caller must see the error."""
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    st = main.AudioStreamer("ws://x", "c", "s", "a", "n", "i", "r")
    st._ws = FakeWS(fail=True)
    st._reconnect_loop = lambda: None
    with pytest.raises(OSError):
        st._send_json({"command": "identify"})
    assert not st._degraded.is_set(), "must not try to resume a session that never started"


def test_control_failure_mid_call_starts_buffering(streamer):
    streamer._ws.fail = True
    streamer._send_json({"command": "stop", "stream_type": "mic"})
    assert streamer._degraded.is_set()


def test_control_frames_are_not_queued_while_offline(streamer):
    """Replaying stale control frames after a resume would confuse the server."""
    streamer._enter_degraded("test")
    streamer._send_json({"command": "stop"})
    assert streamer._spool_next() is None, "control frames must not enter the audio spool"


# ── shutdown ────────────────────────────────────────────────────────────────
def test_close_while_offline_keeps_the_buffered_audio(streamer, tmp_path):
    """Hanging up during an outage must not delete audio we haven't delivered."""
    streamer._enter_degraded("test")
    streamer.send_audio("mic", b"undelivered")
    streamer.close()

    assert streamer._final_stop.is_set(), "resume should still finish the call off"
    assert list(tmp_path.glob("*.spool")), "undelivered audio must be kept"


def test_close_when_healthy_leaves_nothing_behind(streamer, tmp_path):
    streamer.send_audio("mic", b"x")
    streamer.close()
    assert list(tmp_path.glob("*.spool")) == []


def test_finish_after_resume_closes_the_call_properly(streamer):
    """After a late resume the server must get stop+session_end, or it would time the
    session out and mark a complete recording as dropped."""
    streamer.start_stream("mic", 1, 44100)
    streamer.start_stream("speaker", 2, 44100)
    streamer._ws = FakeWS()
    streamer._ws.sent.clear()
    streamer._degraded.clear()
    streamer._finish_after_resume()

    cmds = [main.json.loads(m)["command"] for m in streamer._ws.sent]
    assert cmds == ["stop", "stop", "session_end"]


# ── retention ───────────────────────────────────────────────────────────────
def test_purge_removes_only_stale_spools(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    fresh = tmp_path / "new.spool"
    stale = tmp_path / "old.spool"
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")
    old = time.time() - 8 * 86400
    os.utime(stale, (old, old))

    assert main.purge_old_spools(max_age_days=7) == 1
    assert fresh.exists() and not stale.exists()


def test_resume_deadline_is_inside_the_server_grace_window():
    """The widget must give up BEFORE the server finalizes the session, or it would
    reconnect to a call that no longer exists."""
    assert main.AudioStreamer._RESUME_DEADLINE_SECS < 180


# ── agent-facing status ─────────────────────────────────────────────────────
def test_connection_status_is_shown_to_the_agent(monkeypatch):
    """During an outage the agent must see that the call is still being recorded,
    not be left guessing (or hang up thinking it broke)."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    assert app is not None
    w = main.MainWindow()
    w._recording = True

    w._handle_server_message({"type": "connection_status", "state": "buffering"})
    assert "Reconnecting" in w._status_chip.text()
    assert "still recording" in w._status_chip.text()

    w._handle_server_message({"type": "connection_status", "state": "resumed"})
    assert "Recording Live" in w._status_chip.text()

    w._handle_server_message({"type": "connection_status", "state": "failed"})
    assert "Saved locally" in w._status_chip.text()


def test_connection_status_ignored_when_not_recording():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    assert app is not None
    w = main.MainWindow()
    w._recording = False
    before = w._status_chip.text()
    w._handle_server_message({"type": "connection_status", "state": "buffering"})
    assert w._status_chip.text() == before


def test_unknown_status_state_is_ignored():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    assert app is not None
    w = main.MainWindow()
    w._recording = True
    before = w._status_chip.text()
    w._handle_server_message({"type": "connection_status", "state": "who-knows"})
    assert w._status_chip.text() == before
