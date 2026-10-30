# -*- coding: utf-8 -*-
"""On a call whose live AI is on, the panel stays open (2.9.64, W2 - Faseeh, 30 Oct 2026).

It unfolds when such a call connects and cannot be folded to the bar, hidden to
the tray or minimised by Windows until the call ends; the agent's own fold comes
back then (the page's part: focus_dev/minimise_e2e.py). A call with live AI off,
and every moment between calls, behave exactly as before.

The page greys its fold button out; these prove the second lock, in Python,
whatever the page or Windows sends. The real FocusWindow and MainWindow with a
stand-in for the web view, as in test_focus_ui.py.
"""
import json

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

import main
import focus_ui


@pytest.fixture(scope="module", autouse=True)
def _never_the_real_widget_settings(tmp_path_factory):
    """MainWindow builds QSettings(ORG, APP) - the REAL registry key - unless the
    class is swapped (see test_focus_ui.py). Dead local server addresses too: a
    blank store falls back to the built-in production ones."""
    from PyQt6.QtCore import QSettings
    path = str(tmp_path_factory.mktemp("keep-open-settings") / "widget.ini")
    s = QSettings(path, QSettings.Format.IniFormat)
    s.setValue("ws/url", "ws://127.0.0.1:9")
    s.setValue("api/base_url", "http://127.0.0.1:9")
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
    return QApplication.instance() or QApplication([])


class FakeView(QWidget):
    pass


def make(app):
    win = focus_ui.FocusWindow(view_factory=lambda: FakeView(), start=True)
    win.show()
    app.processEvents()
    assert not win._token, "never signed in: nothing here calls a server"
    # Shown as signed in (as minimise_e2e.py does). Signed out, the classic widget
    # keeps itself on screen whatever is pressed - that is not what is tested here.
    win._logged_out_sticky = False
    win._stack.setCurrentWidget(win._page_main)
    app.processEvents()
    return win


def on_call(win, live=True):
    """A connected call, as _on_call_connected leaves the flags."""
    win._starting = False
    win._recording = True
    win._live_pipeline = live


def call_ended(win):
    win._recording = False


def settle(app, rounds=5):
    for _ in range(rounds):
        app.processEvents()


def layout(ctl, mode):
    ctl.on_action("layout", json.dumps({"mode": mode, "pin": False, "peek": False}))


def windows_minimises(win):
    """As a taskbar click or Win+M does: the state changes, nothing is shown.
    (QWidget.showMinimized() would show the window again itself, straight after,
    and hide what is being tested - probed 30 Oct, offscreen and real platform.)"""
    from PyQt6.QtCore import Qt
    win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)


# ── when it applies ─────────────────────────────────────────────────────────
def test_it_applies_only_to_a_connected_call_whose_live_ai_is_on(app):
    win = make(app)
    assert win.keep_open() is False, "between calls"
    win._starting, win._live_pipeline = True, True
    assert win.keep_open() is False, "connecting: the call's live AI is not known yet"
    on_call(win, live=False)
    assert win.keep_open() is False, "a call with live AI off"
    on_call(win, live=True)
    assert win.keep_open() is True
    win._paused = True
    assert win.keep_open() is True, "paused for a card payment is still the call"
    win._paused = False
    call_ended(win)
    assert win.keep_open() is False, "the call has ended"


def test_the_page_is_told(app):
    win = make(app)
    assert win._focus.snapshot()["keepOpen"] is False
    on_call(win, live=True)
    assert win._focus.snapshot()["keepOpen"] is True
    on_call(win, live=False)
    assert win._focus.snapshot()["keepOpen"] is False


# ── the bar ─────────────────────────────────────────────────────────────────
def test_folding_to_the_bar_is_refused_on_a_coached_call(app):
    win = make(app)
    on_call(win, live=True)
    layout(win._focus, "strip")
    assert win._focus.layout["mode"] == "panel"
    assert win.width() == focus_ui.PANEL_W


def test_folding_is_allowed_on_a_call_with_live_ai_off(app):
    win = make(app)
    on_call(win, live=False)
    layout(win._focus, "strip")
    assert win._focus.layout["mode"] == "strip"
    assert win.width() == focus_ui.STRIP_W


def test_folding_is_allowed_between_calls(app):
    win = make(app)
    layout(win._focus, "strip")
    assert win._focus.layout["mode"] == "strip"
    assert win.width() == focus_ui.STRIP_W


def test_a_bar_left_from_before_the_call_opens_when_it_connects(app):
    """Folded between calls (2.9.62 keeps it folded through a call): a coached call
    opens it straight away, without waiting for the page."""
    win = make(app)
    layout(win._focus, "strip")
    assert win.width() == focus_ui.STRIP_W
    on_call(win, live=True)
    win._focus.push_state()
    assert win._focus.layout["mode"] == "panel"
    assert win.width() == focus_ui.PANEL_W


def test_a_bar_stays_a_bar_on_a_call_with_live_ai_off(app):
    win = make(app)
    layout(win._focus, "strip")
    on_call(win, live=False)
    win._focus.push_state()
    assert win._focus.layout["mode"] == "strip"
    assert win.width() == focus_ui.STRIP_W


# ── hiding: the page's "x", Windows' minimise, Alt+F4 ───────────────────────
def test_hide_is_refused_on_a_coached_call(app):
    win = make(app)
    on_call(win, live=True)
    win._focus.on_action("hide", "{}")
    settle(app)
    assert win.isVisible()


def test_windows_minimising_it_brings_it_straight_back(app):
    """A taskbar click or Win+M minimises the window; the classic widget then hides
    to the tray. On a coached call it comes straight back instead."""
    win = make(app)
    on_call(win, live=True)
    windows_minimises(win)
    settle(app)
    assert win.isVisible() and not win.isMinimized()


def test_minimising_on_a_call_with_live_ai_off_is_unchanged(app):
    win = make(app)
    on_call(win, live=False)
    windows_minimises(win)
    settle(app)
    assert not win.isVisible(), "the classic widget hides to the tray when minimised"


def test_minimising_between_calls_is_unchanged(app):
    win = make(app)
    windows_minimises(win)
    settle(app)
    assert not win.isVisible()


def test_closing_it_is_refused_on_a_coached_call(app):
    """Alt+F4 on the widget sends a close; the classic widget hides to the tray."""
    win = make(app)
    on_call(win, live=True)
    win.close()
    settle(app)
    assert win.isVisible()


def test_closing_it_on_a_call_with_live_ai_off_is_unchanged(app):
    win = make(app)
    on_call(win, live=False)
    win.close()
    settle(app)
    assert not win.isVisible()


def test_closing_it_between_calls_is_unchanged(app):
    win = make(app)
    win.close()
    settle(app)
    assert not win.isVisible()


def test_after_the_call_it_can_be_folded_and_hidden_again(app):
    win = make(app)
    on_call(win, live=True)
    layout(win._focus, "strip")
    assert win._focus.layout["mode"] == "panel"
    call_ended(win)
    layout(win._focus, "strip")
    assert win._focus.layout["mode"] == "strip"
    win._focus.on_action("hide", "{}")
    settle(app)
    assert not win.isVisible()
