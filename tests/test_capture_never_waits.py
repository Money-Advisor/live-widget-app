"""In real time: a slow connection must not cost the capture a single frame.

The 4 Nov 2026 failure end to end, with real threads and a real clock. A fake sound
device makes sound in real time and, like Windows (measured 0.174-0.185 s at 48 kHz),
holds only two chunks and a little for the capture thread - anything more is lost.
The socket is slow: each 16 KB send takes 0.3 s, a link carrying about a quarter of
what the call needs.

  - Sent the old way (the capture thread waits on each send - what every widget up to
    2.9.67 did), the device overflows and the gap-fill pastes silence: exactly Bilal's
    "[gapfill] ... stopped producing" on a working headset.
  - Sent through the queue (GF1), the capture never waits: zero frames lost, zero
    silence inserted, and every frame reaches the server in order once the link allows.
"""
import os
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

import main

RATE, CH = 48000, 2
FRAME = 2 * CH


class RealtimeDevice:
    CAPACITY = 2 * main.CHUNK + 512

    def __init__(self):
        self.t = time.monotonic()
        self.avail = 0.0
        self.lost = 0.0
        self.lock = threading.Lock()

    def _update(self):
        now = time.monotonic()
        add = (now - self.t) * RATE
        self.t = now
        room = self.CAPACITY - self.avail
        if add > room:
            self.lost += add - room
            add = room
        self.avail += add

    def get_read_available(self):
        with self.lock:
            self._update()
            return int(self.avail)

    def read(self, n, exception_on_overflow=False):
        with self.lock:
            self._update()
            n = min(n, int(self.avail))
            self.avail -= n
        return b"\x11\x22" * (n * CH)        # never exact zero: real sound

    def stop_stream(self):
        pass

    def close(self):
        pass


class FakePA:
    def __init__(self, dev):
        self.dev = dev

    def is_format_supported(self, rate, **kw):
        return rate == RATE and kw.get("input_channels") == CH

    def open(self, **kw):
        return self.dev

    def terminate(self):
        pass


class SlowWS:
    def __init__(self, delay):
        self.delay = delay
        self.sent = []

    def send_binary(self, data):
        time.sleep(self.delay)
        self.sent.append(data)

    def send(self, data):
        time.sleep(self.delay)

    def close(self):
        pass

    def settimeout(self, _t):
        pass


def _streamer(tmp_path, monkeypatch, queued):
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    st = main.AudioStreamer("ws://test.invalid", "c", "s", "a", "n", "i", "r")
    st._ws = SlowWS(delay=0.3)
    st._session_live.set()
    st._reconnect_loop = lambda: None
    if queued:
        st._start_sender()
    return st


def _capture(monkeypatch, send, seconds=2.5, ws=None, slow_for=None):
    """Capture for `seconds`; if `slow_for` is given the link recovers after that
    long (a slow spell, as on 4 Nov - not a link that never comes back)."""
    dev = RealtimeDevice()
    monkeypatch.setattr(main.pyaudio, "PyAudio", lambda: FakePA(dev))
    t = main.RecordingThread(1, "speaker", RATE, CH, send,
                             is_loopback=True, keepalive_device_index=-1)
    t._start_ack.set()
    run = threading.Thread(target=t.run)
    run.start()
    if slow_for is not None:
        time.sleep(slow_for)
        ws.delay = 0.0
        time.sleep(seconds - slow_for)
    else:
        time.sleep(seconds)
    t.stop()
    run.join(15)
    assert not run.is_alive(), "the capture thread did not stop"
    return t, dev


def _sound(ws):
    """(seconds of real sound, seconds of inserted silence) the server received."""
    real = zero = 0
    for d in ws.sent:
        pcm = d[4 + len(b"speaker"):]
        if pcm.strip(b"\x00"):
            real += len(pcm)
        else:
            zero += len(pcm)
    return real / (FRAME * RATE), zero / (FRAME * RATE)


def test_sent_the_old_way_a_slow_link_loses_sound_and_fills_it_with_silence(tmp_path, monkeypatch):
    """The failure, reproduced - and put down to the widget, not the device. A 1.5 s
    slow spell, then the link recovers and the capture finds the hole it left."""
    st = _streamer(tmp_path, monkeypatch, queued=False)
    t, dev = _capture(monkeypatch, st.send_audio, ws=st._ws, slow_for=1.5)
    assert dev.lost / RATE > 0.8, "the device never overflowed - the test proves nothing"
    assert t.gaps_filled >= 1
    assert t.seconds_lost_held_up > 0.8
    assert t.seconds_lost_held_up == pytest.approx(t.seconds_filled)
    real, zero = _sound(st._ws)
    assert zero > 0.8, "the lost sound should have reached the server as silence"


def test_through_the_queue_a_slow_link_loses_nothing(tmp_path, monkeypatch):
    """THE fix, in real time: the same slow spell costs nothing."""
    st = _streamer(tmp_path, monkeypatch, queued=True)
    t, dev = _capture(monkeypatch, st.send_audio, ws=st._ws, slow_for=1.5)
    assert dev.lost == 0.0, f"Windows threw away {dev.lost / RATE:.2f}s of sound"
    assert t.gaps_filled == 0
    assert t.seconds_filled == 0.0
    assert t.held_up_seconds == 0.0
    assert st.flush(10.0)
    real, zero = _sound(st._ws)
    assert zero == 0.0, f"{zero:.2f}s of silence reached the server"
    assert real == pytest.approx(2.5, abs=0.3), "sound captured but never delivered"


def test_through_the_queue_the_order_survives_a_slow_link(tmp_path, monkeypatch):
    """Every frame the capture handed over arrives, in the order it was handed over."""
    st = _streamer(tmp_path, monkeypatch, queued=True)
    handed = []

    def send(stream_type, data):
        handed.append(data)
        st.send_audio(stream_type, data)

    _capture(monkeypatch, send, seconds=1.5)
    st._ws.delay = 0.0
    assert st.flush(10.0)
    assert [d[4 + len(b"speaker"):] for d in st._ws.sent] == handed
