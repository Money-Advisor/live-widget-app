import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless Qt

from PyQt6.QtWidgets import QApplication

import main  # the widget module


def _win(app, mic_done=True):
    w = main.MainWindow()
    # Pretend the agent is logged in + idle (the manual "ready" state).
    w._token = "tok"
    w._user = {"id": "u1", "email": "agent@x.test"}
    w._recording = False
    # By default represent a fully set-up agent (mic chosen) so the first-run
    # mic gate is satisfied; gate tests pass mic_done=False to exercise it.
    if mic_done:
        w._settings.setValue("audio/mic_name", "Headset (Realtek)")
    else:
        w._settings.remove("audio/mic_name")
    return w


def test_dialer_activate_starts_like_button(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    calls = {"start": 0, "stop": 0}
    monkeypatch.setattr(w, "_start_recording", lambda *a, **k: calls.__setitem__("start", calls["start"] + 1))
    monkeypatch.setattr(w, "_stop_recording", lambda *a, **k: calls.__setitem__("stop", calls["stop"] + 1))

    w._handle_server_message({
        "type": "dialer_activate", "action": "start",
        "customer_reference": "REF123", "lead_id": "L9",
    })

    assert calls["start"] == 1                       # started via the SAME path as the button
    assert w._reference_edit.text() == "REF123"      # reference prefilled
    assert w._customer_name_edit.text() == ""        # customer name left blank (CRM resolves)


def test_activate_falls_back_to_lead_id(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    monkeypatch.setattr(w, "_start_recording", lambda *a, **k: None)
    w._handle_server_message({
        "type": "dialer_activate", "action": "start",
        "customer_reference": "", "lead_id": "L9",
    })
    assert w._reference_edit.text() == "L9"           # empty reference -> lead_id


def test_double_activate_is_ignored(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    started = {"n": 0}
    monkeypatch.setattr(w, "_start_recording", lambda *a, **k: started.__setitem__("n", started["n"] + 1))

    w._recording = True  # already on a call
    w._handle_server_message({"type": "dialer_activate", "action": "start", "customer_reference": "X"})
    assert started["n"] == 0                          # double-start guarded


def test_dialer_stop_stops(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    stopped = {"n": 0}
    monkeypatch.setattr(w, "_stop_recording", lambda *a, **k: stopped.__setitem__("n", stopped["n"] + 1))

    w._recording = True
    w._handle_server_message({"type": "dialer_stop", "action": "stop"})
    assert stopped["n"] == 1


def test_dialer_stop_ignored_when_idle(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    stopped = {"n": 0}
    monkeypatch.setattr(w, "_stop_recording", lambda *a, **k: stopped.__setitem__("n", stopped["n"] + 1))

    w._recording = False
    w._handle_server_message({"type": "dialer_stop", "action": "stop"})
    assert stopped["n"] == 0                          # nothing to stop


def test_unknown_message_ignored():
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._handle_server_message({"type": "totally_unknown"})  # must not raise


def test_identify_includes_agent_identity(monkeypatch):
    """connect() must send agent_email + agent_id in the identify message."""
    import json
    sent = []

    class FakeWS:
        def __init__(self):
            self._responses = [
                json.dumps({"status": "identified"}),
                json.dumps({"status": "session_started"}),
            ]
        def send(self, data):
            sent.append(data)
        def recv(self):
            if self._responses:
                return self._responses.pop(0)
            raise OSError("closed")  # ends the receiver loop cleanly
        def settimeout(self, *_a):
            pass
        def close(self):
            pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())

    s = main.AudioStreamer(
        server_url="ws://x", client_id="c1", session_id="s1",
        agent_id="u1", customer_name="", customer_id="", reference_id="R1",
        token="tok", agent_email="Agent@X.Test",
    )
    s.connect()
    identify = json.loads(sent[0])
    assert identify["command"] == "identify"
    assert identify["agent_email"] == "Agent@X.Test"
    assert identify["agent_id"] == "u1"
    s._receiver_stop.set()


def test_manual_start_requires_customer_name(monkeypatch):
    """Manual Start (require_name=True) blocks on a blank Customer Name."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._mic_devices = [{"d": 1}]
    w._spk_devices = [{"d": 1}]
    w._reference_edit.setText("R1")
    w._customer_name_edit.clear()
    warned = {"n": 0}
    built = {"n": 0}
    monkeypatch.setattr(main.QMessageBox, "warning", lambda *a, **k: warned.__setitem__("n", warned["n"] + 1))
    monkeypatch.setattr(main, "AudioStreamer", lambda *a, **k: built.__setitem__("n", built["n"] + 1))

    w._start_recording()  # manual path
    assert warned["n"] == 1     # blocked with "Missing Info"
    assert built["n"] == 0      # never reached the streamer


def test_dialer_start_skips_name_requirement(monkeypatch):
    """Dialer start (require_name=False) passes the gate with a blank name."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._mic_devices = [{"d": 1}]
    w._spk_devices = [{"d": 1}]
    w._reference_edit.setText("R1")
    w._customer_name_edit.clear()
    warned = {"n": 0}
    monkeypatch.setattr(main.QMessageBox, "warning", lambda *a, **k: warned.__setitem__("n", warned["n"] + 1))
    monkeypatch.setattr(main.QMessageBox, "critical", lambda *a, **k: None)

    class FakeStreamer:
        def __init__(self, *a, **k): pass
        def connect(self): raise RuntimeError("bail after the name gate")

    monkeypatch.setattr(main, "AudioStreamer", FakeStreamer)

    w._start_recording(require_name=False)
    assert warned["n"] == 0     # name gate did NOT block the dialer


def test_session_start_includes_department(monkeypatch):
    """session_start carries the active department key when one is set."""
    import json
    sent = []

    class FakeWS:
        def __init__(self):
            self._responses = [
                json.dumps({"status": "identified"}),
                json.dumps({"status": "session_started"}),
            ]
        def send(self, data):
            sent.append(data)
        def recv(self):
            if self._responses:
                return self._responses.pop(0)
            raise OSError("closed")
        def settimeout(self, *_a):
            pass
        def close(self):
            pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())

    s = main.AudioStreamer(
        server_url="ws://x", client_id="c1", session_id="s1",
        agent_id="u1", customer_name="C", customer_id="C", reference_id="R1",
        token="tok", agent_email="a@x.test", department="advisor",
    )
    s.connect()
    session = json.loads(sent[1])
    assert session["command"] == "session_start"
    assert session["department"] == "advisor"
    s._receiver_stop.set()


def test_session_start_omits_department_when_blank(monkeypatch):
    """No department set -> the key is omitted (server stays backward compatible)."""
    import json
    sent = []

    class FakeWS:
        def __init__(self):
            self._responses = [
                json.dumps({"status": "identified"}),
                json.dumps({"status": "session_started"}),
            ]
        def send(self, data):
            sent.append(data)
        def recv(self):
            if self._responses:
                return self._responses.pop(0)
            raise OSError("closed")
        def settimeout(self, *_a):
            pass
        def close(self):
            pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    s = main.AudioStreamer(
        server_url="ws://x", client_id="c1", session_id="s1",
        agent_id="u1", customer_name="C", customer_id="C", reference_id="R1",
        token="tok", agent_email="a@x.test",
    )
    s.connect()
    assert "department" not in json.loads(sent[1])
    s._receiver_stop.set()


def test_dialer_activate_stashes_call_metadata(monkeypatch):
    """The dialer leg's metadata is stashed so the next session_start can store it."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    monkeypatch.setattr(w, "_start_recording", lambda *a, **k: None)
    w._handle_server_message({
        "type": "dialer_activate", "action": "start",
        "customer_reference": "REF123", "lead_id": "L9", "campaign_id": "C1",
        "call_direction": "Out", "is_transfer": True, "department": "advisor",
    })
    assert w._pending_dialer_meta == {
        "customer_reference": "REF123", "lead_id": "L9", "campaign_id": "C1",
        "call_direction": "Out", "is_transfer": True, "department": "advisor",
    }


def test_manual_start_has_no_dialer_metadata(monkeypatch):
    """A manual call carries no dialer metadata (pending stash stays empty)."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    assert w._pending_dialer_meta is None


def test_start_recording_passes_dialer_metadata_then_clears(monkeypatch):
    """_start_recording forwards stashed dialer metadata to the streamer once, then
    clears it so a following manual call does not inherit it."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._mic_devices = [{"index": 1, "maxInputChannels": 1, "defaultSampleRate": 16000}]
    w._spk_devices = [{"index": 2, "maxInputChannels": 2, "defaultSampleRate": 48000}]
    w._reference_edit.setText("R1")
    w._pending_dialer_meta = {"lead_id": "L9", "campaign_id": "C1"}
    captured = {}

    class FakeStreamer:
        def __init__(self, *a, **k):
            captured.update(k)
        def connect(self):
            raise RuntimeError("bail after construction")

    monkeypatch.setattr(main, "AudioStreamer", FakeStreamer)
    monkeypatch.setattr(main.QMessageBox, "critical", lambda *a, **k: None)

    w._start_recording(require_name=False)
    assert captured.get("dialer_metadata") == {"lead_id": "L9", "campaign_id": "C1"}
    assert w._pending_dialer_meta is None     # one-shot: cleared after use


class _Sig:
    """Minimal stand-in for a pyqtSignal (just needs .connect/.emit) in tests."""
    def __init__(self): self._slots = []
    def connect(self, fn): self._slots.append(fn)
    def emit(self, *a):
        for fn in list(self._slots):
            fn(*a)


def test_start_recording_is_non_blocking(monkeypatch):
    """Start must not run connect() on the UI thread — it launches a worker and
    enters a 'starting' state; recording only begins once the worker connects."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._mic_devices = [{"index": 1, "maxInputChannels": 1, "defaultSampleRate": 16000}]
    w._spk_devices = [{"index": 2, "maxInputChannels": 2, "defaultSampleRate": 48000}]
    w._reference_edit.setText("R1")
    w._customer_name_edit.setText("Cust")
    sync_connect = {"n": 0}

    class FakeStreamer:
        def __init__(self, *a, **k): self.live_pipeline = True; self.on_message = None
        def connect(self): sync_connect["n"] += 1

    class FakeWorker:
        def __init__(self, streamer): self.streamer = streamer; self.connected = _Sig(); self.failed = _Sig()
        def start(self): started["n"] += 1

    started = {"n": 0}
    monkeypatch.setattr(main, "AudioStreamer", FakeStreamer)
    monkeypatch.setattr(main, "StartCallWorker", FakeWorker)

    w._start_recording()

    assert started["n"] == 1          # worker launched
    assert sync_connect["n"] == 0     # connect did NOT run on the UI thread
    assert w._recording is False      # not recording until connected
    assert w._starting is True


def test_call_failed_resets_to_idle(monkeypatch):
    """A failed connection clears the starting state and never marks recording."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._starting = True
    w._pending_streamer = object()
    monkeypatch.setattr(main.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(w._tray, "showMessage", lambda *a, **k: None)

    w._on_call_failed("connection refused")

    assert w._starting is False
    assert w._recording is False
    assert w._pending_streamer is None


def test_stop_recording_shows_no_tray_toast(monkeypatch):
    """The 'Recording stopped' tray toast plays a Windows ding that the loopback
    captures into the recording — it must not fire."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._recording = True
    toasts = []
    monkeypatch.setattr(w._tray, "showMessage", lambda *a, **k: toasts.append(a))

    w._stop_recording()

    assert toasts == []


def test_call_connected_shows_no_tray_toast(monkeypatch):
    """The 'Recording started' toast ding gets recorded too — must not fire."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._mic_devices = [{"index": 1, "maxInputChannels": 1, "defaultSampleRate": 16000}]
    w._spk_devices = [{"index": 2, "maxInputChannels": 2, "defaultSampleRate": 48000}]
    w._mic_combo.clear(); w._mic_combo.addItem("mic")
    w._spk_combo.clear(); w._spk_combo.addItem("spk")
    streamer = type("S", (), {"live_pipeline": True, "send_audio": lambda *a: None,
                              "on_message": None})()
    w._pending_streamer = streamer
    w._starting = True

    class FakeRec:
        def __init__(self, **k):
            self.error_occurred = _Sig(); self.stream_ready = _Sig()
        def start(self): pass
    monkeypatch.setattr(main, "RecordingThread", FakeRec)
    toasts = []
    monkeypatch.setattr(w._tray, "showMessage", lambda *a, **k: toasts.append(a))

    w._on_call_connected()

    assert toasts == []


def test_login_starts_control_connection(monkeypatch):
    """Entering the main screen opens the persistent control connection so the
    dialer can reach the idle widget."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    started = {"n": 0}

    class FakeControl:
        def __init__(self, *a, **k):
            self.message = _Sig()
        def start(self): started["n"] += 1
        def stop(self): pass
    monkeypatch.setattr(main, "ControlConnection", FakeControl)
    monkeypatch.setattr(w, "_rescan_devices", lambda: None)
    monkeypatch.setattr(w, "_maybe_show_mic_gate", lambda: None)

    w._enter_main()

    assert started["n"] == 1
    assert w._control is not None


def test_logout_stops_control_connection(monkeypatch):
    """Logging out tears down the control connection (no orphan socket)."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    stopped = {"n": 0}
    w._control = type("C", (), {"stop": lambda self: stopped.__setitem__("n", stopped["n"] + 1),
                                "wait": lambda self, *a: None})()

    w._logout()

    assert stopped["n"] == 1
    assert w._control is None


def test_login_reapplies_saved_device_selection(monkeypatch):
    """Entering the main screen (post-login) re-scans + re-selects the saved
    device, so a headset connected before login (or named late) is used."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    calls = {"n": 0}
    monkeypatch.setattr(w, "_rescan_devices", lambda: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr(w, "_maybe_show_mic_gate", lambda: None)

    w._enter_main()

    assert calls["n"] == 1


def test_summary_card_saved_only_hides_compliance():
    """Recording-only confirmation: a checkmark + duration, no score/lists."""
    app = QApplication.instance() or QApplication([])
    card = main.SummaryScreen()
    card.show_saved_only(65)
    assert card._score.text() == "✓"
    assert card._covered_lbl.text() == ""
    assert card._missed_lbl.text() == ""
    assert "01:05" in card._duration.text()


def test_stop_shows_saved_confirmation_in_recording_only(monkeypatch):
    """Recording-only: no compliance scorecard on stop — just a saved confirmation."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._live_pipeline = False
    w._recording = True
    calls = {"scorecard": 0, "saved": 0}
    monkeypatch.setattr(w, "_show_local_summary", lambda *a, **k: calls.__setitem__("scorecard", calls["scorecard"] + 1))
    monkeypatch.setattr(w, "_show_saved_confirmation", lambda *a, **k: calls.__setitem__("saved", calls["saved"] + 1))

    w._stop_recording()

    assert calls["scorecard"] == 0
    assert calls["saved"] == 1


def test_stop_shows_scorecard_when_pipeline_on(monkeypatch):
    """Pipeline on: the compliance scorecard still shows (unchanged behaviour)."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    w._live_pipeline = True
    w._recording = True
    calls = {"scorecard": 0, "saved": 0}
    monkeypatch.setattr(w, "_show_local_summary", lambda *a, **k: calls.__setitem__("scorecard", calls["scorecard"] + 1))
    monkeypatch.setattr(w, "_show_saved_confirmation", lambda *a, **k: calls.__setitem__("saved", calls["saved"] + 1))

    w._stop_recording()

    assert calls["scorecard"] == 1
    assert calls["saved"] == 0


def test_connect_captures_live_pipeline_flag(monkeypatch):
    """The streamer records the server's live_pipeline flag from session_started."""
    import json
    seq = [json.dumps({"status": "identified"}),
           json.dumps({"status": "session_started", "live_pipeline": False})]

    class FakeWS:
        def send(self, data): pass
        def recv(self):
            return seq.pop(0) if seq else (_ for _ in ()).throw(OSError("closed"))
        def settimeout(self, *_a): pass
        def close(self): pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    s = main.AudioStreamer(server_url="ws://x", client_id="c1", session_id="s1",
                           agent_id="u1", customer_name="C", customer_id="C",
                           reference_id="R1", token="tok", agent_email="a@x.test")
    s.connect()
    assert s.live_pipeline is False
    s._receiver_stop.set()


def test_connect_defaults_live_pipeline_true_when_absent(monkeypatch):
    """Old servers don't send the flag -> default True (compliance summary as before)."""
    import json
    seq = [json.dumps({"status": "identified"}),
           json.dumps({"status": "session_started"})]

    class FakeWS:
        def send(self, data): pass
        def recv(self):
            return seq.pop(0) if seq else (_ for _ in ()).throw(OSError("closed"))
        def settimeout(self, *_a): pass
        def close(self): pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    s = main.AudioStreamer(server_url="ws://x", client_id="c1", session_id="s1",
                           agent_id="u1", customer_name="C", customer_id="C",
                           reference_id="R1", token="tok", agent_email="a@x.test")
    s.connect()
    assert s.live_pipeline is True
    s._receiver_stop.set()


def test_session_start_includes_dialer_metadata(monkeypatch):
    """session_start carries dialer_metadata when the streamer was given it."""
    import json
    sent = []

    class FakeWS:
        def __init__(self):
            self._responses = [
                json.dumps({"status": "identified"}),
                json.dumps({"status": "session_started"}),
            ]
        def send(self, data):
            sent.append(data)
        def recv(self):
            if self._responses:
                return self._responses.pop(0)
            raise OSError("closed")
        def settimeout(self, *_a):
            pass
        def close(self):
            pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    s = main.AudioStreamer(
        server_url="ws://x", client_id="c1", session_id="s1",
        agent_id="u1", customer_name="C", customer_id="C", reference_id="R1",
        token="tok", agent_email="a@x.test",
        dialer_metadata={"lead_id": "L9", "campaign_id": "C1"},
    )
    s.connect()
    session = json.loads(sent[1])
    assert session["dialer_metadata"] == {"lead_id": "L9", "campaign_id": "C1"}
    s._receiver_stop.set()


def test_session_start_omits_dialer_metadata_when_absent(monkeypatch):
    """No dialer metadata -> key omitted (manual call, backward compatible)."""
    import json
    sent = []

    class FakeWS:
        def __init__(self):
            self._responses = [
                json.dumps({"status": "identified"}),
                json.dumps({"status": "session_started"}),
            ]
        def send(self, data):
            sent.append(data)
        def recv(self):
            if self._responses:
                return self._responses.pop(0)
            raise OSError("closed")
        def settimeout(self, *_a):
            pass
        def close(self):
            pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    s = main.AudioStreamer(
        server_url="ws://x", client_id="c1", session_id="s1",
        agent_id="u1", customer_name="C", customer_id="C", reference_id="R1",
        token="tok", agent_email="a@x.test",
    )
    s.connect()
    assert "dialer_metadata" not in json.loads(sent[1])
    s._receiver_stop.set()


def test_control_connection_identifies_and_dispatches(monkeypatch):
    """The persistent control connection identifies the agent (registers for the
    dialer) and forwards inbound messages (e.g. dialer_activate) to the widget."""
    import json
    sent = []
    got = []

    class FakeWS:
        def __init__(self):
            self._r = [json.dumps({"status": "identified"}),
                       json.dumps({"type": "dialer_activate", "action": "start"})]
        def send(self, d): sent.append(d)
        def recv(self):
            if self._r:
                return self._r.pop(0)
            raise OSError("closed")        # ends the inner receive loop
        def settimeout(self, *_a): pass
        def close(self): pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    c = main.ControlConnection("ws://x", "ctl-1", "u1", "agent@x.test")
    c.message.connect(lambda m: got.append(m))

    c._serve_once()   # one connect→identify→receive pass (no reconnect)

    identify = json.loads(sent[0])
    assert identify["command"] == "identify"
    assert identify["agent_email"] == "agent@x.test"
    assert identify["agent_id"] == "u1"
    assert got == [{"type": "dialer_activate", "action": "start"}]


def test_control_connection_skips_dispatch_if_not_identified(monkeypatch):
    """If the server never confirms identify, no messages are dispatched."""
    import json
    got = []

    class FakeWS:
        def __init__(self): self._r = [json.dumps({"status": "error"})]
        def send(self, d): pass
        def recv(self):
            if self._r:
                return self._r.pop(0)
            raise OSError("closed")
        def settimeout(self, *_a): pass
        def close(self): pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    c = main.ControlConnection("ws://x", "ctl-1", "u1", "agent@x.test")
    c.message.connect(lambda m: got.append(m))
    c._serve_once()
    assert got == []


def test_recording_streamer_can_skip_dialer_registration(monkeypatch):
    """The per-call recording connection must NOT register for the dialer, or it
    would clobber the persistent control connection's registration."""
    import json
    sent = []

    class FakeWS:
        def __init__(self):
            self._r = [json.dumps({"status": "identified"}),
                       json.dumps({"status": "session_started"})]
        def send(self, d): sent.append(d)
        def recv(self):
            if self._r:
                return self._r.pop(0)
            raise OSError("closed")
        def settimeout(self, *_a): pass
        def close(self): pass

    monkeypatch.setattr(main._websocket, "create_connection", lambda *a, **k: FakeWS())
    s = main.AudioStreamer(server_url="ws://x", client_id="c1", session_id="s1",
                           agent_id="u1", customer_name="C", customer_id="C",
                           reference_id="R1", token="tok", agent_email="a@x.test",
                           register_for_dialer=False)
    s.connect()
    identify = json.loads(sent[0])
    assert identify["command"] == "identify"
    assert not identify.get("agent_email")   # omitted -> won't register
    assert not identify.get("agent_id")
    s._receiver_stop.set()


def test_needs_mic_gate_when_logged_in_without_saved_mic():
    assert main._needs_mic_gate("tok", "") is True


def test_no_mic_gate_when_mic_saved():
    assert main._needs_mic_gate("tok", "Headset (Realtek)") is False


def test_no_mic_gate_when_not_logged_in():
    # Not logged in -> the login screen handles it, no gate.
    assert main._needs_mic_gate("", "") is False


def test_dialer_activate_blocked_and_surfaces_gate_when_not_set_up(monkeypatch):
    """Auto-start must NOT record when the agent hasn't picked a mic yet — it
    holds and surfaces the setup gate instead (no silent/wrong-mic recording)."""
    app = QApplication.instance() or QApplication([])
    w = _win(app, mic_done=False)
    started = {"n": 0}
    gated = {"n": 0}
    monkeypatch.setattr(w, "_start_recording", lambda *a, **k: started.__setitem__("n", started["n"] + 1))
    monkeypatch.setattr(w, "_show_mic_gate", lambda *a, **k: gated.__setitem__("n", gated["n"] + 1))
    monkeypatch.setattr(w, "_show_window", lambda *a, **k: None)

    w._handle_server_message({"type": "dialer_activate", "action": "start",
                              "customer_reference": "REF1"})

    assert started["n"] == 0      # did NOT record
    assert gated["n"] == 1        # surfaced the gate instead


def test_dialer_activate_proceeds_when_mic_is_set_up(monkeypatch):
    """With a mic saved, auto-start behaves normally (gate does not interfere)."""
    app = QApplication.instance() or QApplication([])
    w = _win(app, mic_done=True)
    started = {"n": 0}
    monkeypatch.setattr(w, "_start_recording", lambda *a, **k: started.__setitem__("n", started["n"] + 1))
    monkeypatch.setattr(w, "_show_mic_gate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gate should not show")))

    w._handle_server_message({"type": "dialer_activate", "action": "start",
                              "customer_reference": "REF1"})

    assert started["n"] == 1


def test_picking_mic_clears_the_gate(monkeypatch):
    """Once the agent picks a mic, the gate is released."""
    app = QApplication.instance() or QApplication([])
    w = _win(app, mic_done=False)
    w._mic_devices = [{"name": "Headset (Realtek)"}]
    w._mic_gate_active = True

    w._on_mic_selected(0)

    assert w._mic_gate_active is False


def test_mic_gate_overlay_lifecycle(monkeypatch):
    """Real overlay path (not monkeypatched): show -> populate picker -> confirm
    -> save device -> clear gate -> hide overlay."""
    app = QApplication.instance() or QApplication([])
    w = _win(app, mic_done=False)
    w.show()
    w._mic_devices = [{"name": "Headset (Realtek)"}, {"name": "Webcam Mic"}]

    w._show_mic_gate()
    assert w._mic_gate_active is True
    assert not w._mic_gate_overlay.isHidden()
    assert w._gate_combo.count() == 2

    w._gate_combo.setCurrentIndex(0)
    w._confirm_gate_mic()

    assert w._mic_gate_active is False
    assert w._mic_gate_overlay.isHidden()
    assert w._settings.value("audio/mic_name", "") == "Headset (Realtek)"
    w._settings.remove("audio/mic_name")


def test_dialer_activate_honors_department(monkeypatch):
    """A dialer leg's department becomes the active scope for the call."""
    app = QApplication.instance() or QApplication([])
    w = _win(app)
    # Avoid spawning a real network refresh worker.
    monkeypatch.setattr(main, "ConfigRefreshWorker", lambda *a, **k: type(
        "X", (), {"loaded": type("S", (), {"connect": lambda *a, **k: None})(), "start": lambda *a, **k: None})())
    monkeypatch.setattr(w, "_start_recording", lambda *a, **k: None)

    w._handle_server_message({
        "type": "dialer_activate", "action": "start",
        "customer_reference": "REF123", "department": "advisor",
    })
    assert w._active_department == "advisor"
