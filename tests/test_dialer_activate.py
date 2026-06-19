import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless Qt

from PyQt6.QtWidgets import QApplication

import main  # the widget module


def _win(app):
    w = main.MainWindow()
    # Pretend the agent is logged in + idle (the manual "ready" state).
    w._token = "tok"
    w._user = {"id": "u1", "email": "agent@x.test"}
    w._recording = False
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
