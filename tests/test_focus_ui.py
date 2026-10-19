# -*- coding: utf-8 -*-
"""The Focus screen is laid over the classic widget without changing it.

These drive the real FocusWindow - the real MainWindow underneath, real
workers, real summary card - with a stand-in for the web view, so every wire
between the two is proved without WebEngine or a screen.
"""
import json
import subprocess
from pathlib import Path

import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QWidget

import main
import focus_ui

APP = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def _never_the_real_widget_settings(tmp_path_factory):
    """Point MainWindow's QSettings at a throwaway file for these tests.

    conftest.py's setDefaultFormat does NOT do this: MainWindow builds
    QSettings(ORG, APP), and that constructor always uses the native format -
    the REAL HKCU\\Software\\Spark Flow\\Widget key. Found 15 Oct when a test
    window here came up signed in as the developer, renewed his token and
    opened a dialer connection to the server his widget points at. So the
    class itself is swapped while these tests run.
    """
    from PyQt6.QtCore import QSettings
    path = str(tmp_path_factory.mktemp("focus-settings") / "widget.ini")
    real = main.QSettings
    main.QSettings = lambda *a, **k: QSettings(path, QSettings.Format.IniFormat)
    yield
    main.QSettings = real


@pytest.fixture(scope="module", autouse=True)
def _no_modal_boxes():
    """A modal QMessageBox blocks the test run for ever. Earlier test files can
    leave a call-start worker running whose failure arrives during these tests
    and opens one (_on_call_failed -> QMessageBox.critical): found 19 Oct when
    the full suite hung in this file's first test. Record them instead."""
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
    return QApplication.instance() or QApplication([])


class FakeView(QWidget):
    pass


def make(app, start=True, factory=None):
    win = focus_ui.FocusWindow(view_factory=factory or (lambda: FakeView()), start=start)
    win.show()
    app.processEvents()
    return win


def pushes(ctl):
    got = []
    ctl.bridge.push.connect(lambda s: got.append(json.loads(s)))
    ctl.ready = True
    return got


def flat(got):
    out = []
    for p in got:
        out.extend(p["items"] if p.get("kind") == "batch" else [p])
    return out


def test_these_tests_never_read_or_write_the_real_widget_settings(app):
    from PyQt6.QtCore import QSettings
    win = make(app, start=False)
    assert win._settings.format() == QSettings.Format.IniFormat
    assert win._settings.fileName().endswith("widget.ini")
    assert not win._token                       # nobody is signed in, so nothing calls a server


def test_main_py_differs_from_main_only_by_its_version():
    """The panel replaced the old SCREEN (2.9.59), not the widget: every line
    of main.py - recording, sign-in, dialer, tray, updates - is main's, bar
    the version the auto-updater compares."""
    r = subprocess.run(["git", "diff", "-U0", "main", "--", "main.py"], cwd=APP,
                       capture_output=True, text=True, encoding="utf-8")
    changed = [ln for ln in r.stdout.splitlines()
               if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    assert r.returncode == 0
    assert all(ln[1:].startswith("APP_VERSION = ") for ln in changed), changed


def test_the_installer_ships_the_version_the_widget_reports():
    """The auto-updater compares APP_VERSION with the release; an installer
    built with a different number would reinstall on every start."""
    import re
    iss = (APP / "installer" / "installer.iss").read_text(encoding="utf-8")
    assert re.search(r'#define AppVersion "([^"]+)"', iss).group(1) == main.APP_VERSION


def test_the_installer_replaces_the_old_widget_in_place():
    """Same AppId, exe, folder and Run entry as every earlier Spark Flow - so
    the update lands over the old widget instead of beside it."""
    iss = (APP / "installer" / "installer.iss").read_text(encoding="utf-8")
    assert "AppId={{8E2F1B40-7C2A-4E91-9D3A-NEXCALL00001}" in iss
    assert '#define AppExe "SparkFlow.exe"' in iss and '#define AppName "Spark Flow"' in iss
    assert 'Source: "..\\dist\\SparkFlow\\*"' in iss
    assert 'ValueName: "SparkFlow"' in iss
    build = (APP / "build_all.py").read_text(encoding="utf-8")
    assert 'APP_NAME = "SparkFlow"' in build and '"focus_main.py"' in build


def test_focus_lays_over_the_classic_window_and_hides_it(app):
    win = make(app)
    assert win.focus_active()
    assert win._stack.isHidden()
    assert not win._focus.view.isHidden()


def test_with_focus_off_the_window_is_the_classic_window(app):
    win = make(app, start=False)
    assert not win.focus_active()
    assert not win._stack.isHidden()
    assert (win.minimumWidth(), win.minimumHeight()) == (460, 600)
    assert win.sizeHint() == main.MainWindow.sizeHint(win)


def test_the_focus_exe_offers_no_way_to_the_classic_layout(app):
    # Faseeh, 15 Oct: two exes, two widgets. The tray menu is exactly the
    # classic widget's own, with nothing added.
    win = make(app)
    texts = [a.text() for a in win._tray.contextMenu().actions() if a.text()]
    assert not any("layout" in t.lower() or "classic" in t.lower() for t in texts), texts
    classic = main.MainWindow()
    assert texts == [a.text() for a in classic._tray.contextMenu().actions() if a.text()]
    assert not hasattr(win, "use_layout")


def test_the_page_cannot_ask_for_the_classic_layout(app):
    win = make(app)
    win._focus.on_action("classic", "{}")
    assert win.focus_active() and win._stack.isHidden()


def test_a_saved_classic_choice_from_an_older_build_is_ignored(app):
    win = make(app, start=False)
    win._settings.setValue("ui/layout", "classic")
    win2 = make(app)
    assert win2.focus_active()


def test_a_failure_keeps_recording_while_showing_the_classic_screen(app):
    win = make(app)
    win._recording = True
    win._focus._fail("test")
    assert not win.focus_active() and not win._stack.isHidden() and win._recording
    win._recording = False


def test_a_page_that_never_says_ready_falls_back_to_classic(app):
    win = make(app)
    win._focus._ready_timed_out()
    assert not win.focus_active()
    assert not win._stack.isHidden()
    assert "did not start" in win._focus.failed


def test_a_page_that_fails_to_load_falls_back_to_classic(app):
    win = make(app)
    win._focus._on_load_finished(False)
    assert not win.focus_active() and not win._stack.isHidden()


def test_a_view_that_cannot_be_built_leaves_the_classic_screen(app):
    def boom():
        raise RuntimeError("no WebEngine here")
    win = make(app, factory=boom)
    assert not win.focus_active()
    assert not win._stack.isHidden()
    assert "no WebEngine here" in win._focus.failed


def test_a_ready_page_is_not_failed_by_the_timer(app):
    win = make(app)
    win._focus.on_ready()
    win._focus._ready_timed_out()
    assert win.focus_active()


@pytest.mark.parametrize("action,payload,method,recording", [
    ("stop", {}, "_toggle_recording", True),
    ("pause", {}, "_toggle_pause", True),
    ("newcall", {}, "_on_new_call", False),
    ("rescan", {}, "_rescan_devices", False),
    ("logout", {}, "_logout", False),
    ("forgot", {"email": "a@b.c"}, "_attempt_forgot_password", False),
])
def test_each_button_calls_the_same_method_as_the_classic_button(app, monkeypatch, action, payload, method, recording):
    win = make(app)
    called = []
    monkeypatch.setattr(win, method, lambda *a, **k: called.append(method))
    win._recording = recording
    win._focus.on_action(action, json.dumps(payload))
    win._recording = False
    assert called == [method]


def test_stop_and_pause_do_nothing_when_no_call_is_recording(app, monkeypatch):
    win = make(app)
    called = []
    monkeypatch.setattr(win, "_toggle_recording", lambda: called.append("rec"))
    monkeypatch.setattr(win, "_toggle_pause", lambda: called.append("pause"))
    win._recording = False
    win._focus.on_action("stop", "{}")
    win._focus.on_action("pause", "{}")
    assert called == []


def test_sign_in_goes_through_the_classic_sign_in(app, monkeypatch):
    win = make(app)
    seen = []
    monkeypatch.setattr(win, "_attempt_login", lambda: seen.append((win._email_edit.text(), win._pw_edit.text())))
    win._focus.on_action("login", json.dumps({"email": "sam@example.co.uk", "password": "pw1"}))
    assert seen == [("sam@example.co.uk", "pw1")]


def test_manual_start_fills_the_classic_fields_then_starts(app, monkeypatch):
    win = make(app)
    seen = []
    monkeypatch.setattr(win, "_toggle_recording",
                        lambda: seen.append((win._customer_name_edit.text(), win._reference_edit.text())))
    win._focus.on_action("start", json.dumps({"name": "J Smith", "ref": "REF-1"}))
    assert seen == [("J Smith", "REF-1")]


def test_choosing_a_microphone_saves_it_the_classic_way(app, monkeypatch):
    win = make(app)
    win._mic_devices = [{"name": "A"}, {"name": "B"}]
    win._mic_combo.clear()
    win._mic_combo.addItems(["A", "B"])
    picked = []
    monkeypatch.setattr(win, "_on_mic_selected", lambda i: picked.append(i))
    win._focus.on_action("mic", json.dumps({"index": 1}))
    win._focus.on_action("mic", json.dumps({"index": 7}))     # out of range: ignored
    assert picked == [1] and win._mic_combo.currentIndex() == 1


def test_an_exception_in_a_button_never_escapes_the_bridge(app, monkeypatch):
    win = make(app)
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(win, "_rescan_devices", boom)
    win._focus.bridge.call("rescan", "{}")          # must not raise
    win._focus.bridge.call("mic", "not json at all")


def test_checklist_and_ie_messages_reach_the_page_only_during_a_call(app):
    win = make(app)
    got = pushes(win._focus)
    win._recording = False
    win.server_message.emit({"type": "compliance_alert", "stage": "INCOME", "sections": []})
    win.server_message.emit({"type": "ie_panel", "visible": True})
    assert not [p for p in flat(got) if p["kind"] == "msg"]
    win._recording = True
    win.server_message.emit({"type": "compliance_alert", "stage": "INCOME", "sections": []})
    win._recording = False
    assert [p["data"]["type"] for p in flat(got) if p["kind"] == "msg"] == ["compliance_alert"]


def test_the_safety_card_reaches_the_page_even_when_not_recording(app):
    win = make(app)
    got = pushes(win._focus)
    win._recording = False
    win.server_message.emit({"type": "crisis_alert", "line": "x", "resources": []})
    assert [p["data"]["type"] for p in flat(got) if p["kind"] == "msg"] == ["crisis_alert"]


def test_dialer_messages_are_not_forwarded(app):
    win = make(app)
    got = pushes(win._focus)
    win._recording = True
    win._focus._on_server_message({"type": "dialer_stop"})
    win._recording = False
    assert not [p for p in flat(got) if p["kind"] == "msg"]


def test_a_new_call_gets_a_new_number_before_its_first_message(app):
    win = make(app)
    got = pushes(win._focus)
    before = win._focus.call_seq
    win._recording = True
    win.server_message.emit({"type": "compliance_alert", "stage": "ONB", "sections": [{"key": "ONB"}]})
    win._recording = False
    items = flat(got)
    first_msg = next(i for i, p in enumerate(items) if p["kind"] == "msg")
    states = [p for p in items[:first_msg] if p["kind"] == "state"]
    assert states and states[-1]["data"]["callSeq"] == before + 1


def test_the_summary_follows_the_classic_summary_card(app):
    win = make(app)
    got = pushes(win._focus)
    card = win._summary_card
    card.show_pending(90)
    assert win._focus.summary == {"mode": "pending", "duration": 90}
    card.show_summary(0.82, [{"label": "A", "section": "Onb"}], ["raw.id"], 95)
    s = win._focus.summary
    assert s["mode"] == "score" and s["score"] == 0.82 and s["saved"] is False
    assert s["covered"] == [{"label": "A", "section": "Onb"}]
    assert s["missed"] == [{"label": "raw.id", "section": ""}]
    card.mark_saved()
    assert win._focus.summary["saved"] is True
    assert [p for p in flat(got) if p["kind"] == "summary"][-1]["data"]["saved"] is True


def test_the_server_summary_reaches_the_page_as_the_classic_card_shows_it(app):
    # The real path: the rulebook server's score is a breakdown, which
    # _show_server_summary turns into a fraction before the card sees it.
    win = make(app)
    win._live_pipeline = True
    win._show_server_summary({"type": "session_summary", "duration_seconds": 61,
                              "score": {"covered": 3, "total": 4, "earned": 3.0, "fraction": 0.75},
                              "covered": {"a": {}}, "missing": ["b"],
                              "check_info": {"a": {"label": "Alpha", "section": "Onb"},
                                             "b": {"label": "Beta", "section": "Fees"}}})
    s = win._focus.summary
    assert s["score"] == 0.75 and s["duration"] == 61
    assert s["covered"] == [{"label": "Alpha", "section": "Onb"}]
    assert s["missed"] == [{"label": "Beta", "section": "Fees"}]


def test_a_call_with_no_score_is_shown_as_saved_only(app):
    win = make(app)
    win._live_pipeline = True
    win._show_server_summary({"type": "session_summary", "duration_seconds": 30, "scoring_enabled": False})
    assert win._focus.summary["mode"] == "saved_only"


def test_the_classic_summary_card_still_draws_while_watched(app):
    win = make(app)
    win._summary_card.show_summary(0.5, [], [], 10)
    assert win._summary_card._score.text() == "50%"


def _stage(cards=(), resolved=False):
    return {"type": "compliance_alert", "stage": "INCOME", "sections": [{"key": "INCOME"}],
            "section_checks": [], "trigger_actions": [{"id": c, "occurrence": 1, "message": c} for c in cards],
            "crisis_resolved": resolved}


def test_a_reloaded_page_gets_the_safety_card_card_changes_and_the_newest_state(app):
    win = make(app)
    ctl = win._focus
    win._recording = True
    ctl.push_state()
    for m in [_stage(), _stage(), {"type": "crisis_alert", "line": "x"}, _stage(["A"]), _stage(["A"]),
              _stage(["A", "B"]), _stage(["B"], resolved=True), _stage(["B"], resolved=True),
              {"type": "ie_panel", "visible": True, "n": 1}, {"type": "ie_panel", "visible": True, "n": 2},
              _stage(["B"], resolved=True)]:
        ctl._on_server_message(m)
    win._recording = False
    rep = ctl.replay()
    kinds = [(m["type"], tuple(r["id"] for r in m.get("trigger_actions", [])), m.get("crisis_resolved"), m.get("n"))
             for m in rep]
    assert ("crisis_alert", (), None, None) in kinds
    assert [k for k in kinds if k[0] == "ie_panel"] == [("ie_panel", (), None, 2)]
    card_sets = [k[1] for k in kinds if k[0] == "compliance_alert"]
    assert ("A",) in card_sets and ("A", "B") in card_sets and ("B",) in card_sets
    assert sum(1 for k in kinds if k[0] == "compliance_alert" and k[2]) <= 2   # resolution kept once (+ newest state)
    assert len(rep) < 11


def test_the_safety_card_survives_trimming_on_a_very_long_call(app, monkeypatch):
    win = make(app)
    ctl = win._focus
    monkeypatch.setattr(focus_ui, "MESSAGES_KEPT", 5)
    win._recording = True
    ctl.push_state()
    ctl._on_server_message({"type": "crisis_alert", "line": "x"})
    for i in range(40):
        ctl._on_server_message(_stage([f"C{i}"]))
    win._recording = False
    assert any(m["type"] == "crisis_alert" for m in ctl.replay())


def test_the_window_is_full_height_on_the_chosen_edge(app):
    win = make(app)
    ctl = win._focus
    avail = win.screen().availableGeometry()
    ctl.dock = "right"
    ctl.place()
    g = win.geometry()
    assert (g.x() + g.width(), g.y(), g.height(), g.width()) == (avail.right() + 1, avail.top(), avail.height(), 360)
    ctl.dock = "left"
    ctl.place()
    assert win.geometry().x() == avail.left()


@pytest.mark.parametrize("layout,width", [
    ({"mode": "panel"}, 360), ({"mode": "panel", "pin": True}, 720),
    ({"mode": "strip"}, 64), ({"mode": "strip", "peek": True}, 416),
])
def test_the_window_is_exactly_as_wide_as_what_is_drawn(app, layout, width):
    win = make(app)
    win._focus.dock = "right"
    win._focus.on_action("layout", json.dumps(layout))
    assert win.width() == width


def test_classic_panels_cannot_resize_the_window_while_focus_shows(app):
    win = make(app)
    win._focus.place()
    before = win.geometry()
    win._compliance_panel._sync_window()
    win._compliance_panel._set_panel_height(900)
    win._fit_ie_column(True)
    app.processEvents()
    assert win.geometry() == before


def test_the_fallback_gives_the_classic_screen_its_full_size(app):
    win = make(app)
    win._focus._fail("test")
    assert win.width() >= 460 and win.height() >= 600


def test_the_page_is_told_login_until_signed_in(app):
    win = make(app)
    win._stack.setCurrentWidget(win._page_login)
    assert win._focus.snapshot()["phase"] == "login"
    win._stack.setCurrentWidget(win._page_main)
    win._recording = False
    win._starting = False
    win._summary_card.setVisible(False)
    assert win._focus.snapshot()["phase"] == "idle"
    win._summary_card.setVisible(True)
    assert win._focus.snapshot()["phase"] == "summary"
    win._summary_card.setVisible(False)


def test_a_sign_out_after_being_signed_in_shows_as_signed_out(app):
    win = make(app)
    ctl = win._focus
    win._stack.setCurrentWidget(win._page_main)
    ctl.snapshot()
    win._stack.setCurrentWidget(win._page_login)
    assert ctl.snapshot()["signedOut"] is True


class _NoNetworkWorker:
    def __init__(self, *a, **k):
        from PyQt6.QtCore import pyqtBoundSignal  # noqa: F401
        self.succeeded = self.failed = _Sig()

    def start(self):
        pass


class _Sig:
    def connect(self, *_):
        pass


def test_a_reset_email_confirmation_is_info_not_an_error(app, monkeypatch):
    win = make(app)
    win._on_forgot_sent()
    s = win._focus.snapshot()["login"]
    assert s["info"] and not s["error"]
    # A failed sign-in after it, the real way: _attempt_login first (which
    # turns the line back to red), then the worker's failure.
    monkeypatch.setattr(main, "LoginWorker", _NoNetworkWorker)
    win._email_edit.setText("a@b.c")
    win._pw_edit.setText("x")
    win._attempt_login()
    win._on_login_failed("Incorrect email or password.")
    s = win._focus.snapshot()["login"]
    assert s["error"] == "Incorrect email or password." and not s["info"]


def test_signing_in_does_not_blink_the_window(app):
    """The classic sign-in drops "on top", Focus put it back: two native window
    rebuilds, a visible double blink every time the widget opened (15 Oct)."""
    from PyQt6.QtCore import QObject, QEvent

    class Count(QObject):
        n = 0

        def eventFilter(self, obj, ev):
            if obj is win and ev.type() in (QEvent.Type.Hide, QEvent.Type.WinIdChange):
                Count.n += 1
            return False

    win = make(app)
    win._token = "stand-in"
    win._user = {}                               # no agent id: no dialer connection opened
    win._stack.setCurrentWidget(win._page_main)
    win._focus.push_state(force=True)            # signed in: Focus pins itself on top
    app.processEvents()
    c = Count()
    app.installEventFilter(c)
    try:
        win._on_validate_ok({}, "", {}, "", "", 0)   # the stored session comes back valid
        win._focus.push_state(force=True)
        app.processEvents()
    finally:
        app.removeEventFilter(c)
        win._token = ""
    assert Count.n == 0
    from PyQt6.QtCore import Qt
    assert win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def _veiled_window(app):
    """A window as a real start has it: shown, page not drawn yet."""
    win = make(app, start=False)
    win._veiled = True
    win.setVisible(False)
    win._focus._waits_for_drawn = True
    win._focus.start()
    win.show()
    app.processEvents()
    return win


def test_the_window_is_invisible_until_the_page_has_drawn(app):
    """Opening the widget flashed an empty square: the window at the classic
    default size and place before the page had drawn (15 Oct)."""
    win = _veiled_window(app)
    assert win.isVisible() and win.windowOpacity() == 0.0
    win._focus.on_action("drawn", "{}")
    assert win.windowOpacity() == 1.0
    avail = win.screen().availableGeometry()
    g = win.geometry()
    assert (g.width(), g.height()) == (360, avail.height())


def test_drawn_twice_changes_nothing(app):
    win = _veiled_window(app)
    win._focus.on_action("drawn", "{}")
    win.setWindowOpacity(1.0)
    win._focus.on_action("drawn", "{}")
    assert win.windowOpacity() == 1.0 and not win._veiled


def test_a_failed_page_never_leaves_the_window_invisible(app):
    win = _veiled_window(app)
    win._focus._fail("test")
    assert win.windowOpacity() == 1.0 and not win._stack.isHidden()


def test_the_window_is_shown_even_if_the_page_never_answers(app):
    win = _veiled_window(app)
    win._veil_guard.timeout.emit()
    assert win.windowOpacity() == 1.0


def test_the_veil_guard_is_no_longer_than_the_fallback_needs(app):
    win = make(app)
    win._veiled = True
    win._veil_guard.start(focus_ui.READY_TIMEOUT_MS + 2000)
    assert win._veil_guard.interval() <= focus_ui.READY_TIMEOUT_MS + 2000
    win._unveil()
    assert not win._veil_guard.isActive()


def test_the_page_files_exist_where_the_widget_looks(app):
    for name in ("index.html", "app.js", "app.css", "model.js", "logo.png",
                 "fonts/PlusJakartaSans-latin.woff2", "fonts/JetBrainsMono-latin.woff2"):
        assert (Path(focus_ui.focus_dir()) / name).exists(), name


class _Shows(QObject):
    """An event filter recording Show events."""

    def __init__(self, keep):
        super().__init__()
        self.keep, self.seen = keep, []

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.Show and self.keep(obj):
            # (Qt sends Show just BEFORE the native window appears, so ask
            # whether it is allowed on screen rather than whether it is yet.)
            from PyQt6.QtCore import Qt
            self.seen.append((obj, obj.isWindow(),
                              not obj.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen),
                              getattr(obj, "_focus", "n/a")))
        return False


def _watch_shows(app, keep):
    f = _Shows(keep)
    app.installEventFilter(f)
    return f


def test_the_classic_checklist_panel_never_appears_as_a_window_of_its_own(app):
    """Its constructor shows it before it has a parent: a 356x317 window on the
    desktop for ~20ms - the square on every double-click (15 Oct)."""
    f = _watch_shows(app, lambda o: isinstance(o, main.ComplianceAlertPanel))
    try:
        win = focus_ui.FocusWindow(view_factory=lambda: FakeView(), start=False)
        app.processEvents()
    finally:
        app.removeEventFilter(f)
    assert f.seen, "the panel was never shown at all - the test saw nothing"
    on_screen_alone = [s for s in f.seen if s[1] and s[2]]
    assert not on_screen_alone
    from PyQt6.QtCore import Qt
    panel = win._compliance_panel
    assert not panel.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)   # dropped once parented
    assert panel.parentWidget() is not None


def test_only_the_focus_window_gets_the_quiet_panel(app):
    focus_ui.FocusWindow(view_factory=lambda: FakeView(), start=False)
    assert main.ComplianceAlertPanel is not focus_ui._QuietComplianceAlertPanel
    classic = main.MainWindow()
    assert type(classic._compliance_panel) is main.ComplianceAlertPanel


def test_the_checklist_panel_ends_in_the_same_state_as_classic(app):
    focus = focus_ui.FocusWindow(view_factory=lambda: FakeView(), start=False)
    classic = main.MainWindow()
    app.processEvents()
    a, b = focus._compliance_panel, classic._compliance_panel
    assert (a.isHidden(), a.size(), a._ready.isHidden()) == (b.isHidden(), b.size(), b._ready.isHidden())


def test_a_show_asked_for_while_building_waits_until_the_page_is_there(app):
    """Signed out, the classic code shows the window inside MainWindow.__init__,
    before the page exists - and Windows drew that window solid (15 Oct)."""
    f = _watch_shows(app, lambda o: isinstance(o, focus_ui.FocusWindow))
    try:
        win = focus_ui.FocusWindow(view_factory=lambda: FakeView(), start=True)
        app.processEvents()
    finally:
        app.removeEventFilter(f)
    assert not win._token                       # signed out: the classic code asked for the show
    assert win.isVisible()                      # ... and it still happened
    assert f.seen and all(s[3] is not None for s in f.seen)   # but only once Focus existed


def test_hide_is_refused_while_a_call_is_in_progress(app):
    """19 Oct: an advisor pressed "-" mid-call by mistake. The page greys it
    out; the widget refuses it too, whatever the page sends."""
    win = make(app)
    win._logged_out_sticky = False              # signed in (signed out it never hides)
    for flag in ("_recording", "_starting"):
        setattr(win, flag, True)
        win._focus.on_action("hide", "{}")
        app.processEvents()
        assert win.isVisible(), flag
        setattr(win, flag, False)
    win._focus.on_action("hide", "{}")
    app.processEvents()
    assert not win.isVisible()                  # between calls it still hides


def test_the_page_is_told_when_hide_is_locked(app):
    win = make(app)
    assert win._focus.snapshot()["hideLocked"] is False
    win._starting = True
    assert win._focus.snapshot()["hideLocked"] is True
    win._starting, win._recording = False, True
    assert win._focus.snapshot()["hideLocked"] is True
    win._recording = False


def test_the_old_screens_minimise_is_locked_during_a_call_too(app):
    """The old screen shows only if the panel cannot start - and then its "-"
    must be locked the same way."""
    win = make(app)
    btn = win._classic_minimise
    assert btn is not None and btn.text() == "\u2014"
    assert win._hide_lock_timer.isActive()
    win._recording = True
    win._sync_hide_lock()
    assert not btn.isEnabled()
    win._recording = False
    win._sync_hide_lock()
    assert btn.isEnabled()
