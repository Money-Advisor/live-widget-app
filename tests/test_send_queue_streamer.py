"""A slow connection may delay a call's audio. It must never lose it.

Bilal, 4 Nov 2026: on a busy network the widget's sends slowed down; the capture
threads were the ones sending, so they stopped reading the sound devices, Windows threw
away what it could not hold (~0.175 s), and recordings came out with the client's side
silent for minutes. Since GF1 a live call's audio goes through one ordered queue and a
sender thread. These tests pin what that must guarantee: send_audio never waits; the
order on the wire is exactly the order of capture; stop / session_end / close wait
behind the audio; PCI pause is decided at capture; a dying socket still spools in order.
"""
import json
import os
import struct
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

import main


class SlowWS:
    """A socket whose sends take `delay` seconds each (a busy network), that can be
    told to fail after `fail_after` frames (the link dying mid-backlog), or to block
    until released (a send that never completes)."""

    def __init__(self, delay=0.0, fail_after=None):
        self.delay, self.fail_after = delay, fail_after
        self.sent = []
        self.closed = False
        self.release = threading.Event()
        self.release.set()
        self._lock = threading.Lock()

    def _go(self, item):
        self.release.wait()
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            if self.fail_after is not None and len(self.sent) >= self.fail_after:
                raise OSError("socket dead")
            self.sent.append(item)

    def send_binary(self, data):
        self._go(("bin", data))

    def send(self, data):
        self._go(("json", json.loads(data)))

    def close(self):
        self.closed = True

    def settimeout(self, _t):
        pass


def frame(stream_type, pcm):
    tb = stream_type.encode()
    return struct.pack("I", len(tb)) + tb + pcm


@pytest.fixture
def make(tmp_path, monkeypatch):
    """A connected-looking streamer with its sender running, on a given socket."""
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    made = []

    def _make(ws):
        st = main.AudioStreamer(
            "ws://test.invalid", "client-1", "sess-1", "agent-1",
            "Cust", "cust-1", "REF1", token="tok", register_for_dialer=False)
        st._ws = ws
        st._session_live.set()
        st._reconnect_loop = lambda: None
        st._start_sender()
        made.append(st)
        return st

    yield _make
    for st in made:
        st._closing.set()


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def binaries(ws):
    return [d for k, d in ws.sent if k == "bin"]


def commands(ws):
    return [d.get("command") for k, d in ws.sent if k == "json"]


# ── the capture never waits ─────────────────────────────────────────────────
def test_a_slow_socket_never_holds_up_send_audio(make):
    """THE fix. Each send takes 0.3 s (far over the 0.175 s Windows holds for the
    capture thread); handing a chunk over must still take no time at all."""
    ws = SlowWS(delay=0.3)
    st = make(ws)
    worst = 0.0
    for i in range(10):
        t0 = time.perf_counter()
        st.send_audio("mic", b"%05d" % i)
        worst = max(worst, time.perf_counter() - t0)
    assert worst < 0.05, f"send_audio waited {worst:.3f}s on the network"
    assert wait_for(lambda: len(binaries(ws)) == 10)
    assert binaries(ws) == [frame("mic", b"%05d" % i) for i in range(10)]


def test_mic_and_speaker_keep_their_capture_order_on_the_wire(make):
    ws = SlowWS(delay=0.002)
    st = make(ws)
    expect = []

    def capture(st_type):
        for i in range(200):
            pcm = st_type[:1].encode() + struct.pack("<I", i)
            st.send_audio(st_type, pcm)

    ts = [threading.Thread(target=capture, args=(s,)) for s in ("mic", "speaker")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert wait_for(lambda: len(binaries(ws)) == 400)
    for s in ("mic", "speaker"):
        seq = [struct.unpack("<I", b[-4:])[0] for b in binaries(ws)
               if b[4:4 + len(s)] == s.encode()]
        assert seq == list(range(200)), f"{s} chunks reordered or lost"


# ── the end of a call waits behind its audio ────────────────────────────────
def test_stop_and_session_end_go_after_every_queued_chunk(make):
    """The server closes a stream's WAV on 'stop' and finalises on 'session_end'.
    Either one overtaking queued audio throws the end of the call away."""
    ws = SlowWS(delay=0.05)
    st = make(ws)
    st.start_stream("mic", 1, 48000)
    st.start_stream("speaker", 2, 48000)
    for i in range(8):
        st.send_audio("mic", b"m%d" % i)
        st.send_audio("speaker", b"s%d" % i)
    t0 = time.perf_counter()
    st.stop_stream("mic")
    st.stop_stream("speaker")
    st.end_session()
    assert time.perf_counter() - t0 < 0.05, "stopping the call waited on the network"
    assert wait_for(lambda: "session_end" in commands(ws))
    kinds = [k if k == "bin" else d["command"] for k, d in ws.sent]
    assert kinds[:2] == ["start", "start"]
    assert kinds[2:18] == ["bin"] * 16
    assert kinds[18:] == ["stop", "stop", "session_end"]


def test_close_waits_for_the_backlog_then_closes(make):
    ws = SlowWS(delay=0.05)
    st = make(ws)
    for i in range(10):
        st.send_audio("mic", b"%d" % i)
    st.end_session()
    t0 = time.perf_counter()
    st.close()
    assert time.perf_counter() - t0 < 0.05
    assert not ws.closed, "closed with audio still waiting to be sent"
    assert wait_for(lambda: ws.closed)
    assert len(binaries(ws)) == 10
    assert commands(ws) == ["session_end"]
    assert st._closing.is_set()
    assert wait_for(lambda: not st._sender_thread.is_alive())


def test_close_called_twice_closes_once(make):
    ws = SlowWS(delay=0.02)
    st = make(ws)
    st.send_audio("mic", b"x")
    st.close()
    st.close()
    assert wait_for(lambda: ws.closed)
    assert st._close_queued


def test_quit_flush_waits_until_session_end_has_gone(make):
    ws = SlowWS(delay=0.05)
    st = make(ws)
    for i in range(5):
        st.send_audio("mic", b"%d" % i)
    st.end_session()
    assert st.flush(5.0) is True
    assert commands(ws)[-1] == "session_end"


def test_flush_gives_up_at_its_timeout_on_a_stuck_send(make):
    ws = SlowWS()
    ws.release.clear()                       # the send never completes
    st = make(ws)
    st.send_audio("mic", b"x")
    t0 = time.perf_counter()
    assert st.flush(0.3) is False
    assert time.perf_counter() - t0 < 1.0
    ws.release.set()


# ── PCI pause ────────────────────────────────────────────────────────────────
def test_pause_is_decided_when_the_sound_is_captured_not_when_it_is_sent(make):
    """Card details must never be recorded. Audio captured BEFORE the pause still goes
    (the advisor said it before pausing); audio captured during it never enters."""
    ws = SlowWS(delay=0.05)
    st = make(ws)
    for i in range(5):
        st.send_audio("mic", b"before%d" % i)
    st.set_paused(True)                       # while those 5 are still queued
    for i in range(3):
        st.send_audio("mic", b"card%d" % i)
    st.set_paused(False)
    for i in range(2):
        st.send_audio("mic", b"after%d" % i)
    assert wait_for(lambda: len(binaries(ws)) == 7)
    time.sleep(0.2)
    got = [b[7:] for b in binaries(ws)]
    assert got == [b"before%d" % i for i in range(5)] + [b"after0", b"after1"]


# ── a dying socket, a long slowdown ─────────────────────────────────────────
def test_the_link_dying_mid_backlog_spools_the_rest_in_order(make, tmp_path):
    ws = SlowWS(delay=0.01, fail_after=4)
    st = make(ws)
    for i in range(12):
        st.send_audio("mic", b"%02d" % i)
    assert wait_for(lambda: st._sendq.empty() and st._sendq.idle())
    assert st._degraded.is_set()
    spooled = []
    while True:
        p = st._spool_next()
        if p is None:
            break
        spooled.append(p)
    assert binaries(ws) + spooled == [frame("mic", b"%02d" % i) for i in range(12)]


def test_a_long_backlog_moves_to_disk_and_still_arrives_in_order(make):
    ws = SlowWS()
    ws.release.clear()                        # the network stalls...
    st = make(ws)
    st._sendq._max = 4000
    for i in range(60):
        st.send_audio("speaker", bytes([i]) * 500)
    assert st._sendq.spills >= 1
    path = st._sendq._spill_path
    assert path.exists() and path.name == "sess-1.queue.spool"
    ws.release.set()                          # ...and recovers
    assert wait_for(lambda: len(binaries(ws)) == 60)
    assert binaries(ws) == [frame("speaker", bytes([i]) * 500) for i in range(60)]
    assert wait_for(lambda: not path.exists())


# ── telling the agent's log and the server ──────────────────────────────────
def test_a_growing_backlog_is_logged_and_reported_to_the_server(make, capsys):
    ws = SlowWS(delay=0.02)
    st = make(ws)
    st.start_stream("mic", 1, 8000)           # 16,000 bytes of PCM a second
    chunk = b"\x01\x02" * 800                 # 0.1 s each
    for _ in range(40):                       # 4 s queued at once
        st.send_audio("mic", chunk)
    assert wait_for(lambda: len(binaries(ws)) == 40)
    assert wait_for(lambda: any(k == "json" and d.get("state") == "ok"
                                for k, d in ws.sent))
    out = capsys.readouterr().out
    assert "[send] the connection to the server is slow" in out
    assert "nothing is lost" in out
    assert "[send] caught up - the backlog peaked at" in out
    status = [d for k, d in ws.sent if k == "json" and d.get("command") == "link_status"]
    assert status[0]["state"] == "slow" and status[0]["backlog_seconds"] >= 2.0
    assert status[0]["session_id"] == "sess-1" and status[0]["client_id"] == "client-1"
    assert status[-1]["state"] == "ok"
    # The "slow" report went out AHEAD of the backlog, not after it.
    first_status = next(i for i, (k, d) in enumerate(ws.sent)
                        if k == "json" and d.get("command") == "link_status")
    assert first_status < len(ws.sent) - 5


def test_no_status_is_sent_on_a_dead_link(make):
    ws = SlowWS(fail_after=0)
    st = make(ws)
    st._degraded.set()
    st._report_link("slow", 9.0)
    time.sleep(0.2)
    assert not [d for k, d in ws.sent if k == "json"]


def test_a_healthy_call_reports_nothing(make, capsys):
    ws = SlowWS()
    st = make(ws)
    st.start_stream("mic", 1, 48000)
    for _ in range(20):
        st.send_audio("mic", b"\x01" * 8192)
        time.sleep(0.005)
    assert wait_for(lambda: len(binaries(ws)) == 20)
    assert "[send]" not in capsys.readouterr().out
    assert commands(ws) == ["start"]


def test_audio_still_queued_when_we_give_up_is_dropped_not_spooled(make, tmp_path):
    """Once the resume deadline has passed the server has finalised the call; audio
    that was still waiting in the queue can never be delivered and must not grow the
    spool on the agent's disk."""
    ws = SlowWS()
    ws.release.clear()
    st = make(ws)
    for i in range(30):
        st.send_audio("mic", b"x" * 4096)
    st._gave_up.set()
    ws.release.set()
    assert wait_for(lambda: st._sendq.empty() and st._sendq.idle())
    assert len(binaries(ws)) <= 1             # at most the one already in flight
    assert not list(tmp_path.glob("sess-1.spool"))


# ── connect() turns the queue on; the window's quit waits for it ────────────
class _HandshakeWS(SlowWS):
    """Answers identify + session_start, then behaves as a (slow) live socket."""

    def __init__(self, delay):
        super().__init__(delay=delay)
        self._replies = [{"status": "identified"},
                         {"status": "session_started", "live_pipeline": True}]

    def recv(self):
        if self._replies:
            return json.dumps(self._replies.pop(0))
        time.sleep(0.5)
        raise main._websocket.WebSocketTimeoutException("idle")

    def send(self, data):
        if self._replies:                     # handshake frames: instant
            self.sent.append(("json", json.loads(data)))
            return
        super().send(data)


def test_connect_puts_a_live_call_on_the_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    ws = _HandshakeWS(delay=0.3)
    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: ws)
    st = main.AudioStreamer("ws://test.invalid", "c", "sess-9", "a", "n", "i", "r",
                            token="t", register_for_dialer=False)
    st.connect()
    try:
        assert st._sender_thread is not None and st._sender_thread.is_alive()
        t0 = time.perf_counter()
        for _ in range(5):
            st.send_audio("mic", b"z" * 100)
        assert time.perf_counter() - t0 < 0.05, "a connected call's send_audio waited"
        assert wait_for(lambda: len(binaries(ws)) == 5)
    finally:
        st._receiver_stop.set()
        st._closing.set()


def test_quitting_mid_call_waits_for_the_queued_end_of_call(monkeypatch):
    """MainWindow._quit used to send stop + session_end directly before the process
    ended. They are queued now, so quit must give them a moment to go out."""
    from types import SimpleNamespace
    flushed = []
    streamer = SimpleNamespace(flush=lambda t: flushed.append(t) or True)
    win = SimpleNamespace(_recording=True, _pa=None)
    win._stop_recording = lambda: setattr(win, "_closing_streamer", streamer)
    win._stop_control_connection = lambda: None
    monkeypatch.setattr(main.QApplication, "quit", staticmethod(lambda: None))
    main.MainWindow._quit(win)
    assert flushed == [5.0]


def test_the_sender_survives_a_failed_read_and_a_failed_report(make, monkeypatch):
    """If the sender thread ever died, everything still queued would never be sent.
    A queue read that raises and a backlog report that raises must both be shrugged
    off, and every frame still delivered in order."""
    ws = SlowWS()
    st = make(ws)
    real_get, real_watch = st._sendq.get, st._watch_backlog
    boom = {"get": 1, "watch": 1}

    def flaky_get(timeout=None):
        if boom["get"]:
            boom["get"] -= 1
            raise OSError("disk hiccup")
        return real_get(timeout)

    def flaky_watch():
        if boom["watch"]:
            boom["watch"] -= 1
            raise RuntimeError("report hiccup")
        return real_watch()

    monkeypatch.setattr(st._sendq, "get", flaky_get)
    monkeypatch.setattr(st, "_watch_backlog", flaky_watch)
    for i in range(6):
        st.send_audio("mic", b"%d" % i)
    assert wait_for(lambda: len(binaries(ws)) == 6)
    assert binaries(ws) == [frame("mic", b"%d" % i) for i in range(6)]
    assert st._sender_thread.is_alive()
    assert boom == {"get": 0, "watch": 0}


def test_an_unopenable_backlog_file_does_not_wedge_the_queue(tmp_path, monkeypatch, capsys):
    from send_queue import SendQueue, AUDIO
    q = SendQueue(tmp_path / "q.spool", max_memory_bytes=100)
    for i in range(4):
        q.put(AUDIO, b"y" * 80)
    monkeypatch.setattr(SendQueue, "_reader_locked",
                        lambda self: (_ for _ in ()).throw(OSError("locked by AV")))
    assert q.get(timeout=0.2) is None
    assert q.idle(), "the queue was left 'busy' and flush() would hang"
    assert "could not read the backlog file back" in capsys.readouterr().out


# ── the paths that must stay as they were ───────────────────────────────────
def test_a_streamer_that_never_connected_still_sends_synchronously(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    st = main.AudioStreamer("ws://x", "c", "s", "a", "n", "i", "r")
    ws = SlowWS()
    st._ws = ws
    st._session_live.set()
    st.send_audio("mic", b"now")
    st.end_session()
    assert binaries(ws) == [frame("mic", b"now")]
    assert commands(ws) == ["session_end"]
    assert st._sendq is None


def test_finish_after_resume_does_not_depend_on_the_sender(make):
    """Closed while offline: the sender has ended; the reconnect thread must still
    deliver stop + session_end itself once the resume lands."""
    ws = SlowWS()
    st = make(ws)
    st.start_stream("mic", 1, 48000)
    st._degraded.set()
    st.end_session()
    st.close()
    assert wait_for(lambda: not st._sender_thread.is_alive())
    assert st._final_stop.is_set()
    st._degraded.clear()
    st._finish_after_resume()
    assert commands(ws)[-2:] == ["stop", "session_end"]
