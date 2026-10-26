"""A dialer start while a call is still recording (OUTSTANDING F3, 26 Oct).

The dialer's end for a call never came (24 Oct: the widget recorded one call for
a day), so the next start used to be thrown away - every call after a runaway
went unrecorded. A start for a NEW call now ends the old one and then starts the
new one, never two at once; a start repeated for the SAME call is still ignored.
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless Qt

import time

from PyQt6.QtWidgets import QApplication

import main  # the widget module


app = QApplication.instance() or QApplication([])


def _win():
    w = main.MainWindow()
    w._token = "tok"
    w._config = {}
    w._user = {"id": "u1", "email": "agent@x.test"}
    w._recording = False
    w._settings.setValue("audio/mic_name", "Headset (Realtek)")
    return w


class FakeStreamer:
    """The per-call socket: records what the widget sends on it, in order."""

    def __init__(self, log, name):
        self.log, self.name = log, name
        self.on_message = lambda m: log.append((name, "reached the screen", m.get("type")))
        self.closed = False

    def stop_stream(self, kind):
        self.log.append((self.name, "stop_stream", kind))

    def end_session(self):
        self.log.append((self.name, "session_end"))

    def close(self):
        self.closed = True

    def send_audio(self, *_a):
        pass


def _on_a_call(w, log, meta=None, started_ago=5.0, name="old"):
    """`w` recording a call - from the dialer with `meta`, or manual (None)."""
    w._recording = True
    w._streamer = FakeStreamer(log, name)
    w._call_dialer_meta = meta
    w._call_started_at = time.monotonic() - started_ago
    return w._streamer


def _record_starts(w, monkeypatch, log):
    def start(*a, **k):
        # What the widget looks like at the moment the new call starts.
        log.append(("start", w._reference_edit.text(), {"recording": w._recording,
                    "streamer": w._streamer is not None, "require_name": k.get("require_name")}))
    monkeypatch.setattr(w, "_start_recording", start)


def _activate(w, **fields):
    w._handle_server_message({"type": "dialer_activate", "action": "start", **fields})


def _settle():
    for _ in range(5):
        app.processEvents()
        time.sleep(0.01)


def test_a_new_call_ends_the_old_one_then_starts(monkeypatch):
    w, log = _win(), []
    _on_a_call(w, log, meta={"lead_id": "L1", "customer_reference": "R1"})
    _record_starts(w, monkeypatch, log)

    _activate(w, customer_reference="R2", lead_id="L2")

    # The old call was ended properly - both streams and the session - BEFORE
    # the new one started, and the new one started exactly once, alone.
    assert log == [
        ("old", "stop_stream", "mic"), ("old", "stop_stream", "speaker"), ("old", "session_end"),
        ("start", "R2", {"recording": False, "streamer": False, "require_name": False}),
    ]


def test_the_old_calls_late_messages_cannot_reach_the_new_call(monkeypatch):
    w, log = _win(), []
    old = _on_a_call(w, log, meta={"lead_id": "L1"})
    # A rulebook call: stopping it puts up "working out your score" and arms
    # the 25 s fallback - neither may land on the new call.
    w._live_pipeline, w._rulebook_call = True, True
    _record_starts(w, monkeypatch, log)

    _activate(w, customer_reference="R2", lead_id="L2")

    assert old.on_message is None          # the server's summary of the old call goes nowhere
    assert w._summary_wait is None         # and the fallback will not fire over the new call
    assert not w._front_card.isHidden() and w._summary_card.isHidden()


def test_the_old_socket_is_still_closed_by_its_own_timer(monkeypatch):
    w, log = _win(), []
    timers = []
    monkeypatch.setattr(main.QTimer, "singleShot", lambda ms, fn: timers.append((ms, fn)))
    old = _on_a_call(w, log, meta={"lead_id": "L1"})
    _record_starts(w, monkeypatch, log)

    _activate(w, customer_reference="R2", lead_id="L2")

    # The usual 15 s grace, then closed - even if the NEW call has meanwhile
    # stopped and taken the shared "closing" slot.
    assert w._closing_streamer is None
    w._closing_streamer = FakeStreamer(log, "new")
    for ms, fn in timers:
        if ms == 15000:
            fn()
    assert old.closed


def test_a_repeated_start_for_the_same_call_is_ignored(monkeypatch):
    w, log = _win(), []
    _on_a_call(w, log, meta={"lead_id": "L1", "customer_reference": "R1"}, started_ago=30)
    _record_starts(w, monkeypatch, log)

    _activate(w, customer_reference="R1", lead_id="L1")

    assert log == []                       # nothing stopped, nothing started


def test_the_same_lead_long_after_is_a_new_call(monkeypatch):
    w, log = _win(), []
    _on_a_call(w, log, meta={"lead_id": "L1"}, started_ago=main.MainWindow.DUPLICATE_START_S + 1)
    _record_starts(w, monkeypatch, log)

    _activate(w, customer_reference="R1", lead_id="L1")

    assert [e[0] for e in log][-2:] == ["old", "start"]


def test_a_different_lead_is_a_new_call_even_seconds_later(monkeypatch):
    w, log = _win(), []
    _on_a_call(w, log, meta={"lead_id": "L1", "customer_reference": "R1"}, started_ago=2)
    _record_starts(w, monkeypatch, log)

    _activate(w, customer_reference="R1", lead_id="L2")

    assert log[-1][0] == "start"


def test_without_leads_the_reference_decides_but_never_a_placeholder(monkeypatch):
    w, log = _win(), []
    _on_a_call(w, log, meta={"customer_reference": "R1"})
    _record_starts(w, monkeypatch, log)
    _activate(w, customer_reference="R1")
    assert log == []                       # the same customer: the same call

    _on_a_call(w, log, meta={"customer_reference": "HOTKEY"})
    _activate(w, customer_reference="HOTKEY")
    assert log[-1][0] == "start"           # two hotkey transfers are two calls


def test_a_dialer_start_ends_a_manual_call(monkeypatch):
    w, log = _win(), []
    _on_a_call(w, log, meta=None)
    _record_starts(w, monkeypatch, log)

    _activate(w, customer_reference="R2", lead_id="L2")

    assert log[-1][0] == "start" and ("old", "session_end") in log


def test_a_start_while_connecting_waits_then_goes_ahead_if_that_call_failed(monkeypatch):
    w, log = _win(), []
    _record_starts(w, monkeypatch, log)
    monkeypatch.setattr(main.QMessageBox, "critical", lambda *a, **k: None)
    w._starting = True

    _activate(w, customer_reference="R2", lead_id="L2")
    _activate(w, customer_reference="R3", lead_id="L3")
    assert log == []                       # nothing while a call is connecting

    w._on_call_failed("refused")
    _settle()
    assert log == [("start", "R3", {"recording": False, "streamer": False, "require_name": False})]


class _FakeThread:
    class _Sig:
        def connect(self, *_a):
            pass

    def __init__(self, *a, **k):
        self.error_occurred, self.stream_ready = self._Sig(), self._Sig()

    def start(self):
        pass

    def stop(self):
        pass

    def wait(self, *_a):
        return True


def _connect(w, log, monkeypatch, meta):
    """Let the connecting call come up for real (devices and threads faked)."""
    monkeypatch.setattr(main, "RecordingThread", _FakeThread)
    dev = {"index": 0, "name": "dev", "maxInputChannels": 1, "defaultSampleRate": 16000}
    w._mic_devices, w._spk_devices = [dev], [dev]
    w._pending_streamer = FakeStreamer(log, "first")
    w._pending_dialer_meta = meta
    w._call_dialer_meta, w._call_started_at = meta, time.monotonic()
    w._on_call_connected()


def test_a_start_while_connecting_ends_that_call_once_it_is_up(monkeypatch):
    w, log = _win(), []
    _record_starts(w, monkeypatch, log)
    w._starting = True
    _activate(w, customer_reference="R2", lead_id="L2")

    _connect(w, log, monkeypatch, {"lead_id": "L1", "customer_reference": "R1"})
    assert w._recording                    # the first call came up...
    _settle()
    # ...and was then ended, before the queued call started, exactly once.
    assert log == [
        ("first", "stop_stream", "mic"), ("first", "stop_stream", "speaker"), ("first", "session_end"),
        ("start", "R2", {"recording": False, "streamer": False, "require_name": False}),
    ]


def test_the_same_start_twice_while_connecting_is_one_call(monkeypatch):
    w, log = _win(), []
    _record_starts(w, monkeypatch, log)
    w._starting = True
    _activate(w, customer_reference="R1", lead_id="L1")

    _connect(w, log, monkeypatch, {"lead_id": "L1", "customer_reference": "R1"})
    _settle()

    assert w._recording and log == []      # still the one call, nothing ended
