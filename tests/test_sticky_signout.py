"""A sign-out must be impossible to miss.

Before this, _on_validate_bad switched the stack to the login page — but the window
hides on BOTH close and minimise, so a revoked session left the agent looking at nothing
while their calls went unrecorded. The signal existed; it just had nowhere to appear.
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import main


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    w = main.MainWindow()
    w._exit_logged_out_mode()          # start from a known signed-in state
    yield w
    w._exit_logged_out_mode()
    w.hide()


def _on_top(w):
    return bool(w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def test_signing_out_pins_the_window_on_screen(win):
    win._enter_logged_out_mode("revoked")
    assert win._logged_out_sticky
    assert win.isVisible()
    assert _on_top(win)
    assert win._stack.currentWidget() is win._page_login


def test_close_cannot_hide_a_signed_out_window(win, app):
    win._enter_logged_out_mode("revoked")
    win.close()
    app.processEvents()
    assert win.isVisible(), "closing must not hide the sign-out — that was the bug"


def test_minimise_cannot_hide_a_signed_out_window(win, app):
    win._enter_logged_out_mode("revoked")
    win.showMinimized()
    app.processEvents()
    assert win.isVisible(), "minimising must not bury the sign-out"


def test_signing_in_restores_normal_behaviour(win, app):
    win._enter_logged_out_mode("revoked")
    win._exit_logged_out_mode()
    assert not win._logged_out_sticky
    assert not _on_top(win), "must not stay pinned above the dialer once signed in"
    win.close()
    app.processEvents()
    assert not win.isVisible(), "close should hide to tray again once signed in"


def test_resurface_timer_runs_only_while_signed_out(win):
    win._enter_logged_out_mode("revoked")
    assert win._resurface_timer.isActive()
    win._exit_logged_out_mode()
    assert not win._resurface_timer.isActive()


def test_resurface_brings_a_buried_window_back(win, app):
    win._enter_logged_out_mode("revoked")
    win.hide()                          # simulate it having been buried/hidden somehow
    app.processEvents()
    win._resurface_if_buried()
    app.processEvents()
    assert win.isVisible()


def test_resurface_does_nothing_once_signed_in(win, app):
    win._exit_logged_out_mode()
    win.hide()
    app.processEvents()
    win._resurface_if_buried()
    app.processEvents()
    assert not win.isVisible(), "must not drag the window up while the agent is working"


def test_entering_twice_is_harmless(win):
    win._enter_logged_out_mode("first")
    win._enter_logged_out_mode("second")
    assert win._logged_out_sticky and _on_top(win)


def test_it_never_steals_keyboard_focus():
    """Agents type customer details into the dialer; grabbing focus mid-call could send
    half a phone number into our window. Raise, don't activate."""
    import inspect
    src = inspect.getsource(main.MainWindow._surface_login_window)
    assert "raise_()" in src
    assert "activateWindow" not in src
