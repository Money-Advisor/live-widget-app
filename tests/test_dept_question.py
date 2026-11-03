# -*- coding: utf-8 -*-
"""After a call: "which department was this call for?" (2.9.65, OUTSTANDING MD2).

Bilal + Faseeh, 3 Nov 2026: asked on the summary of a call of 30 seconds or more, of
an agent who works for two or more departments that file calls by department. The
answer files the call over the dialer's code (a manager's move by hand still
stands - the backend's rule). Until it is answered the panel stays open, as on a
coached call, and "Ready for the next call" waits. Recording never waits on it: a
new call drops the question. A failed save frees the agent at once.

The real FocusWindow and MainWindow with a stand-in for the web view (as in
test_keep_open.py), driven through the real connect and stop; the two backend
calls are stand-ins, so nothing reaches a network. The page's part:
focus_dev/qt_e2e.py and the harness scenarios.
"""
import json
import threading
import time
import types

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

import main
import focus_ui

# Held for the whole run: a QApplication that is let go crashes the next MainWindow.
_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module", autouse=True)
def _never_the_real_widget_settings(tmp_path_factory):
    """MainWindow builds QSettings(ORG, APP) - the REAL registry key - unless the
    class is swapped (see test_keep_open.py)."""
    from PyQt6.QtCore import QSettings
    path = str(tmp_path_factory.mktemp("dept-question-settings") / "widget.ini")
    s = QSettings(path, QSettings.Format.IniFormat)
    s.setValue("ws/url", "ws://127.0.0.1:9")
    s.setValue("api/base_url", "http://127.0.0.1:9")
    s.setValue("audio/mic_name", "Headset")
    s.sync()
    real = main.QSettings
    main.QSettings = lambda *a, **k: QSettings(path, QSettings.Format.IniFormat)
    yield
    main.QSettings = real


@pytest.fixture(scope="module", autouse=True)
def _no_modal_boxes():
    from PyQt6.QtWidgets import QMessageBox
    shown = []
    saved = {n: getattr(QMessageBox, n) for n in ("critical", "warning", "information", "question")}
    for n in saved:
        setattr(QMessageBox, n, staticmethod(lambda *a, _n=n, **k: shown.append(_n)))
    yield shown
    for n, f in saved.items():
        setattr(QMessageBox, n, f)


@pytest.fixture(scope="module")
def app():
    return _APP


# Customer Service DMP is the agent's main department; Annual Review files by code
# too; Case Assessment does not, so it is never offered.
ME = {"departments": [
    {"id": "d-cs", "name": "Customer Service DMP", "key": "customer-service-dmp", "main": True, "file_by_code": True},
    {"id": "d-ar", "name": "Annual Review", "key": "annual-review", "main": False, "file_by_code": True},
    {"id": "d-ca", "name": "Case Assessment", "key": "case-assessment", "main": False, "file_by_code": False},
]}


@pytest.fixture
def server(monkeypatch):
    """The backend's two calls, recorded."""
    s = types.SimpleNamespace(me=ME, me_threads=[], gate=None, answers=[], reply=None, fail=None)

    def get_me(base_url, token):
        s.me_threads.append(threading.current_thread() is threading.main_thread())
        if s.gate is not None:
            s.gate.wait(5)
        if isinstance(s.me, Exception):
            raise s.me
        return s.me

    def answer(base_url, token, session_id, department_id):
        s.answers.append((session_id, department_id))
        if s.fail:
            raise main.BackendError(s.fail)
        return s.reply or {"department_id": department_id, "result": "filed"}

    monkeypatch.setattr(main, "api_get_me", get_me)
    monkeypatch.setattr(main, "api_answer_department", answer)
    return s


class FakeView(QWidget):
    pass


class _Sig:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a):
        for fn in list(self._slots):
            fn(*a)


class FakeRec:
    """The audio threads: nothing is captured."""
    def __init__(self, **k):
        self.error_occurred = _Sig()
        self.stream_ready = _Sig()

    def start(self):
        pass

    def stop(self):
        pass

    def wait(self, *_a):
        return True


def settle(app, rounds=5):
    for _ in range(rounds):
        app.processEvents()


def wait_until(app, cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def sent_within(app, cond, timeout=1.0):
    """For "nothing is sent": a worker thread sends a moment after it is started, so
    looking straight away proves nothing - give it a full second to do it."""
    return wait_until(app, cond, timeout)


def make(app, monkeypatch):
    monkeypatch.setattr(main, "RecordingThread", FakeRec)
    win = focus_ui.FocusWindow(view_factory=lambda: FakeView(), start=True)
    win.show()
    settle(app)
    assert win.focus_active()
    # Signed in, at a stand-in token and a dead local address: the two backend
    # calls are replaced by the `server` fixture.
    win._token = "tok"
    win._api_base = "http://127.0.0.1:9"
    win._user = {"id": "u1", "email": "agent@x.test"}
    win._config = {}
    win._logged_out_sticky = False
    win._stack.setCurrentWidget(win._page_main)
    win._mic_devices = [{"index": 1, "name": "mic", "maxInputChannels": 1, "defaultSampleRate": 16000}]
    win._spk_devices = [{"index": 2, "name": "spk", "maxInputChannels": 2, "defaultSampleRate": 48000}]
    win._mic_combo.clear()
    win._mic_combo.addItem("mic")
    win._spk_combo.clear()
    win._spk_combo.addItem("spk")
    settle(app)
    return win


def connect(app, win, row="row-1", live=False):
    """A call connects through the real _on_call_connected, the server's ack giving
    the call's row (`row`) and whether its live AI is on."""
    streamer = types.SimpleNamespace(
        live_pipeline=live, db_session_id=row, on_message=None,
        send_audio=lambda *a: None, stop_stream=lambda *a: None,
        end_session=lambda: None, close=lambda: None)
    win._pending_streamer = streamer
    win._starting = True
    win._on_call_connected()
    assert win._recording
    return streamer


def loaded(app, win):
    assert wait_until(app, lambda: win._dept_call is not None and win._dept_call["choices"] is not None)


def end(app, win, secs):
    win._elapsed = secs
    win._stop_recording()
    settle(app)


def question(win):
    return win._focus.snapshot()["deptQuestion"]


def asked_call(app, monkeypatch, server, live=False, secs=45):
    win = make(app, monkeypatch)
    connect(app, win, live=live)
    loaded(app, win)
    end(app, win, secs)
    assert question(win) is not None
    return win


def answer(app, win, dept):
    win._focus.on_action("deptAnswer", json.dumps({"id": dept}))
    assert wait_until(app, lambda: not win._dept_q["busy"])


# ── who is asked, and which departments ────────────────────────────────────
def test_the_choices_are_the_main_department_and_those_that_file_by_code():
    assert main.department_choices(ME) == [
        {"id": "d-cs", "name": "Customer Service DMP", "main": True},
        {"id": "d-ar", "name": "Annual Review", "main": False},
    ]


def test_the_main_department_comes_first_whatever_the_order():
    me = {"departments": [ME["departments"][1], ME["departments"][0]]}
    assert [c["id"] for c in main.department_choices(me)] == ["d-cs", "d-ar"]


def test_no_question_while_the_main_department_does_not_file_by_code():
    me = {"departments": [dict(ME["departments"][0], file_by_code=False), ME["departments"][1]]}
    assert main.department_choices(me) == []


def test_no_question_for_an_agent_of_one_department():
    assert main.department_choices({"departments": [ME["departments"][0]]}) == []
    # Two departments, but only the main one files by code: one choice is no question.
    assert main.department_choices({"departments": [ME["departments"][0], ME["departments"][2]]}) == []


def test_a_missing_or_odd_profile_asks_nothing():
    assert main.department_choices(None) == []
    assert main.department_choices({}) == []
    assert main.department_choices({"departments": None}) == []
    assert main.department_choices({"departments": ["x", {"id": "", "name": "A"}, {"main": True}]}) == []


# ── the backend call ───────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, body=None, bad_json=False):
        self.status_code = status
        self._body = body
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._body


def test_the_answer_is_posted_for_that_call(monkeypatch):
    sent = {}

    def post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, json=json)
        return _Resp(200, {"department_id": "d-ar", "result": "filed"})
    monkeypatch.setattr(main.requests, "post", post)
    reply = main.api_answer_department("http://api.test/", "tok", "row-1", "d-ar")
    assert reply == {"department_id": "d-ar", "result": "filed"}
    assert sent["url"] == "http://api.test/api/widget/calls/row-1/department"
    assert sent["headers"] == {"Authorization": "Bearer tok"}
    assert sent["json"] == {"department_id": "d-ar"}


def test_a_refusal_carries_the_backends_reason(monkeypatch):
    monkeypatch.setattr(main.requests, "post",
                        lambda *a, **k: _Resp(400, {"detail": "That is not one of your departments."}))
    with pytest.raises(main.BackendError, match="That is not one of your departments."):
        main.api_answer_department("http://api.test", "tok", "row-1", "d-x")
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: _Resp(400, bad_json=True))
    with pytest.raises(main.BackendError, match="did not take the answer"):
        main.api_answer_department("http://api.test", "tok", "row-1", "d-x")


def test_a_server_error_or_no_network_is_a_plain_failure(monkeypatch):
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: _Resp(503))
    with pytest.raises(main.BackendError, match="server error 503"):
        main.api_answer_department("http://api.test", "tok", "row-1", "d-ar")

    def down(*a, **k):
        raise main.requests.ConnectionError("down")
    monkeypatch.setattr(main.requests, "post", down)
    with pytest.raises(main.BackendError, match="Could not reach the server"):
        main.api_answer_department("http://api.test", "tok", "row-1", "d-ar")


# ── the call's row, from the server's ack ──────────────────────────────────
def _streamer_after_ack(monkeypatch, ack):
    seq = [json.dumps({"status": "identified"}), json.dumps(ack)]

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
    s._receiver_stop.set()
    return s


def test_the_streamer_keeps_the_calls_row_from_the_ack(monkeypatch):
    s = _streamer_after_ack(monkeypatch, {"status": "session_started", "db_session_id": "row-9"})
    assert s.db_session_id == "row-9"


def test_an_older_server_sends_no_row(monkeypatch):
    s = _streamer_after_ack(monkeypatch, {"status": "session_started"})
    assert s.db_session_id is None
    s = _streamer_after_ack(monkeypatch, {"status": "session_started", "db_session_id": None})
    assert s.db_session_id is None


# ── when it is asked ───────────────────────────────────────────────────────
def test_a_call_of_30_seconds_or_more_is_asked_on_its_summary(app, monkeypatch, server):
    win = make(app, monkeypatch)
    assert question(win) is None, "between calls"
    connect(app, win)
    loaded(app, win)
    assert question(win) is None, "never during the call"
    assert server.me_threads == [False], "loaded once, when the call connected, off the UI thread"
    end(app, win, 30)
    assert win._focus.phase() == "summary"
    q = question(win)
    assert q == {"choices": [{"id": "d-cs", "name": "Customer Service DMP", "main": True},
                             {"id": "d-ar", "name": "Annual Review", "main": False}],
                 "answer": None, "busy": None, "error": "", "kept": False}
    assert win.keep_open() is True
    assert win._focus.snapshot()["keepOpen"] is True


def test_a_call_under_30_seconds_is_not_asked(app, monkeypatch, server):
    win = make(app, monkeypatch)
    connect(app, win)
    loaded(app, win)
    end(app, win, 29)
    assert win._focus.phase() == "summary"
    assert question(win) is None
    assert win.keep_open() is False


def test_an_agent_with_one_choice_is_not_asked(app, monkeypatch, server):
    server.me = {"departments": [ME["departments"][0], ME["departments"][2]]}
    win = make(app, monkeypatch)
    connect(app, win)
    loaded(app, win)
    end(app, win, 300)
    assert question(win) is None
    assert win.keep_open() is False


def test_no_row_from_the_server_asks_nothing_and_loads_nothing(app, monkeypatch, server):
    win = make(app, monkeypatch)
    connect(app, win, row=None)
    assert not sent_within(app, lambda: server.me_threads)
    end(app, win, 300)
    assert server.me_threads == []
    assert question(win) is None


def test_departments_that_fail_to_load_ask_nothing(app, monkeypatch, server):
    server.me = main.BackendError("Could not reach the server.")
    win = make(app, monkeypatch)
    connect(app, win)
    loaded(app, win)
    end(app, win, 300)
    assert question(win) is None
    assert win.keep_open() is False


def test_departments_that_arrive_after_the_call_ended_still_ask(app, monkeypatch, server):
    server.gate = threading.Event()
    win = make(app, monkeypatch)
    connect(app, win)
    end(app, win, 45)
    assert question(win) is None, "not loaded yet"
    server.gate.set()
    assert wait_until(app, lambda: question(win) is not None)
    assert win.keep_open() is True


def test_it_comes_back_on_screen_for_the_question(app, monkeypatch, server):
    """Bilal: the widget must come up for it. On a call with live AI off the agent
    may have minimised it to the tray."""
    win = make(app, monkeypatch)
    connect(app, win, live=False)
    loaded(app, win)
    win.hide()
    settle(app)
    assert not win.isVisible()
    end(app, win, 45)
    assert win.isVisible()


# ── until it is answered ───────────────────────────────────────────────────
def test_the_next_call_button_waits_for_the_answer(app, monkeypatch, server):
    win = asked_call(app, monkeypatch, server)
    sent = []
    win._focus._send = sent.append
    win._focus.on_action("newcall", "{}")
    assert win._focus.phase() == "summary", "still on the summary"
    assert question(win) is not None
    assert {"kind": "summary", "data": win._focus.summary} in sent, "the page gets its summary back"


def test_it_cannot_be_folded_hidden_or_minimised_until_answered(app, monkeypatch, server):
    from PyQt6.QtCore import Qt
    win = asked_call(app, monkeypatch, server)
    win._focus.on_action("layout", json.dumps({"mode": "strip", "pin": False, "peek": False}))
    assert win._focus.layout["mode"] == "panel"
    win._focus.on_action("hide", "{}")
    settle(app)
    assert win.isVisible()
    win.close()
    settle(app)
    assert win.isVisible()
    win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)
    settle(app)
    assert win.isVisible() and not win.isMinimized()


def test_the_pages_x_does_not_even_try_to_close_it(app, monkeypatch, server):
    """Refused before the close - not closed and brought back (closeEvent's lock)."""
    win = asked_call(app, monkeypatch, server)
    closes = []
    monkeypatch.setattr(win, "close", lambda: closes.append(1))
    win._focus.on_action("hide", "{}")
    assert closes == []


def test_a_bar_from_before_the_call_opens_for_the_question(app, monkeypatch, server):
    win = make(app, monkeypatch)
    win._focus.on_action("layout", json.dumps({"mode": "strip", "pin": False, "peek": False}))
    assert win._focus.layout["mode"] == "strip"
    connect(app, win, live=False)
    loaded(app, win)
    assert win._focus.layout["mode"] == "strip", "a call with live AI off stays a bar"
    end(app, win, 45)
    assert win._focus.layout["mode"] == "panel"
    assert win.width() == focus_ui.PANEL_W


def test_a_coached_call_goes_straight_from_its_lock_to_the_questions(app, monkeypatch, server):
    """The page is never told the panel may fold between the call and its question."""
    win = make(app, monkeypatch)
    connect(app, win, live=True)
    loaded(app, win)
    states = []
    real_send = win._focus._send
    win._focus._send = lambda p: (states.append(p["data"]) if p.get("kind") == "state" else None, real_send(p))
    end(app, win, 45)
    assert states, "the end of the call was sent"
    assert all(s["keepOpen"] for s in states), [(s["phase"], s["keepOpen"]) for s in states]
    assert states[-1]["phase"] == "summary" and states[-1]["deptQuestion"] is not None


# ── the answer ─────────────────────────────────────────────────────────────
def test_answering_files_the_call_and_frees_the_panel(app, monkeypatch, server):
    win = asked_call(app, monkeypatch, server)
    answer(app, win, "d-ar")
    assert server.answers == [("row-1", "d-ar")]
    assert question(win)["answer"] == "d-ar"
    assert win.keep_open() is False
    win._focus.on_action("layout", json.dumps({"mode": "strip", "pin": False, "peek": False}))
    assert win._focus.layout["mode"] == "strip", "the agent's fold is back"
    win._focus.on_action("layout", json.dumps({"mode": "panel", "pin": False, "peek": False}))
    win._focus.on_action("newcall", "{}")
    assert win._focus.phase() == "idle"
    assert question(win) is None
    assert win._dept_q is None, "gone, not just hidden"


def test_the_answer_is_sent_off_the_ui_thread(app, monkeypatch, server):
    win = asked_call(app, monkeypatch, server)
    on_ui = []
    real = main.api_answer_department
    monkeypatch.setattr(main, "api_answer_department",
                        lambda *a: (on_ui.append(threading.current_thread() is threading.main_thread()), real(*a))[1])
    answer(app, win, "d-ar")
    assert on_ui == [False]


def test_while_it_saves_the_panel_stays_locked(app, monkeypatch, server):
    gate = threading.Event()
    real = main.api_answer_department
    monkeypatch.setattr(main, "api_answer_department", lambda *a: (gate.wait(5), real(*a))[1])
    win = asked_call(app, monkeypatch, server)
    win._focus.on_action("deptAnswer", json.dumps({"id": "d-ar"}))
    settle(app)
    assert question(win)["busy"] == "d-ar"
    assert win.keep_open() is True
    win._focus.on_action("deptAnswer", json.dumps({"id": "d-cs"}))
    gate.set()
    assert wait_until(app, lambda: not win._dept_q["busy"])
    assert server.answers == [("row-1", "d-ar")], "one answer at a time"


def test_an_answer_that_is_not_one_of_the_choices_is_refused(app, monkeypatch, server):
    win = asked_call(app, monkeypatch, server)
    for dept in ("d-ca", "", "nope"):
        win._focus.on_action("deptAnswer", json.dumps({"id": dept}))
    assert not sent_within(app, lambda: server.answers)
    assert server.answers == []
    assert win.keep_open() is True


def test_the_answer_can_be_changed(app, monkeypatch, server):
    win = asked_call(app, monkeypatch, server)
    answer(app, win, "d-ar")
    answer(app, win, "d-cs")
    assert server.answers == [("row-1", "d-ar"), ("row-1", "d-cs")]
    assert question(win)["answer"] == "d-cs"
    win._focus.on_action("deptAnswer", json.dumps({"id": "d-cs"}))
    assert not sent_within(app, lambda: len(server.answers) > 2), "the same answer again sends nothing"


def test_a_failed_save_frees_the_agent_and_can_be_tried_again(app, monkeypatch, server):
    server.fail = "Could not reach the server. Check your connection."
    win = asked_call(app, monkeypatch, server)
    answer(app, win, "d-ar")
    q = question(win)
    assert q["answer"] is None and q["error"] == "Could not reach the server. Check your connection."
    assert win.keep_open() is False, "never stuck behind a server that is down"
    server.fail = None
    answer(app, win, "d-ar")
    q = question(win)
    assert q["answer"] == "d-ar" and q["error"] == ""


def test_a_failed_save_lets_the_agent_carry_on(app, monkeypatch, server):
    server.fail = "That is not one of your departments."
    win = asked_call(app, monkeypatch, server)
    answer(app, win, "d-ar")
    win._focus.on_action("newcall", "{}")
    assert win._focus.phase() == "idle"


def test_a_managers_move_by_hand_stands(app, monkeypatch, server):
    server.reply = {"department_id": "d-cs", "result": "kept_hand_move"}
    win = asked_call(app, monkeypatch, server)
    answer(app, win, "d-ar")
    q = question(win)
    assert q["kept"] is True and q["answer"] == "d-cs", "where the manager put it"
    assert win.keep_open() is False
    win._focus.on_action("deptAnswer", json.dumps({"id": "d-ar"}))
    assert not sent_within(app, lambda: len(server.answers) > 1), "nothing more to answer"


# ── recording never waits on it ────────────────────────────────────────────
def test_a_new_call_drops_the_question(app, monkeypatch, server):
    class FakeStart:
        def __init__(self, streamer):
            self.connected = _Sig()
            self.failed = _Sig()

        def start(self):
            pass
    monkeypatch.setattr(main, "StartCallWorker", FakeStart)
    win = asked_call(app, monkeypatch, server)
    win._reference_edit.setText("R2")
    win._start_recording(require_name=False)
    assert win._starting
    assert question(win) is None
    assert win.keep_open() is False
    assert win._dept_q is None
    # The new call cannot connect: the screen goes back to the old summary, without
    # the question - the call it was about is filed by the dialer's code.
    win._on_call_failed("no server")
    settle(app)
    assert win._focus.phase() == "summary"
    assert question(win) is None
    assert win.keep_open() is False


def test_a_new_call_connecting_drops_the_question(app, monkeypatch, server):
    win = asked_call(app, monkeypatch, server)
    connect(app, win, row="row-2")
    assert question(win) is None
    assert win._dept_q is None
    loaded(app, win)
    end(app, win, 10)
    assert question(win) is None, "the last call's question never comes back"


def test_the_dialers_next_call_brings_nothing_up(app, monkeypatch, server):
    """A dialer start while a call records ends that call and starts the next
    (_end_superseded_call): nothing comes up for the call just ended."""
    win = make(app, monkeypatch)
    connect(app, win)
    loaded(app, win)
    came_up = []
    monkeypatch.setattr(win, "_back_on_screen", lambda: came_up.append(1))
    win._elapsed = 300
    win._end_superseded_call()
    settle(app, 10)
    assert came_up == []
    assert question(win) is None
    assert win.keep_open() is False


def test_signing_out_asks_nothing(app, monkeypatch, server):
    win = make(app, monkeypatch)
    connect(app, win)
    loaded(app, win)
    win._elapsed = 300
    win._logout()
    settle(app)
    assert win._dept_q is None
    assert question(win) is None
    assert win._leaving is False


def test_quitting_asks_nothing(app, monkeypatch, server):
    win = make(app, monkeypatch)
    connect(app, win)
    loaded(app, win)
    monkeypatch.setattr(main.QApplication, "quit", staticmethod(lambda: None))
    monkeypatch.setattr(main, "_end_pyaudio", lambda pa: None)
    win._elapsed = 300
    win._quit()
    assert win._dept_q is None
