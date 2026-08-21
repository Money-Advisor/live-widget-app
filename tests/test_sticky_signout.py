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


# --- the manual "Log Out" button ---------------------------------------------
#
# Sticky mode was wired only into _on_validate_bad (expired/revoked session) and the
# cold start with no token. Pressing Log Out just swapped the stack to the login page,
# so the window still hid on close/minimise and the sign-out could be lost behind other
# windows for the rest of the shift — the same failure the feature was built to prevent.
# Reported from the field on 2026-08-21.

class _FakeSettings:
    """QSettings stand-in: _logout only removes keys, and we must not touch the real
    registry of whoever is running the tests."""

    def __init__(self):
        self.removed = []

    def remove(self, key):
        self.removed.append(key)

    def value(self, key, default=None, type=None):   # noqa: A002 - QSettings' own name
        return default

    def setValue(self, key, value):
        pass


@pytest.fixture
def signed_in(win):
    win._settings = _FakeSettings()
    win._recording = False
    return win


def test_manual_logout_pins_the_window(signed_in):
    signed_in._logout()
    assert signed_in._logged_out_sticky, "Log Out must be as sticky as an expired session"
    assert signed_in.isVisible()
    assert _on_top(signed_in)
    assert signed_in._stack.currentWidget() is signed_in._page_login


def test_manual_logout_then_close_stays_visible(signed_in, app):
    """The exact behaviour reported: Log Out, press X, and it vanished to the tray."""
    signed_in._logout()
    signed_in.close()
    app.processEvents()
    assert signed_in.isVisible()


def test_manual_logout_then_minimise_stays_visible(signed_in, app):
    signed_in._logout()
    signed_in.showMinimized()
    app.processEvents()
    assert signed_in.isVisible()


def test_manual_logout_still_clears_the_session(signed_in):
    """The fix must not weaken the sign-out itself: the long-lived refresh token has to
    go, or the session could simply be resumed."""
    signed_in._logout()
    assert signed_in._token == "" and signed_in._refresh_token == ""
    assert signed_in._user == {}
    for key in ("auth/token", "auth/refresh_token", "auth/user"):
        assert key in signed_in._settings.removed


def test_manual_logout_then_signing_in_unpins(signed_in, app):
    signed_in._logout()
    signed_in._exit_logged_out_mode()
    assert not signed_in._logged_out_sticky
    assert not _on_top(signed_in)
    signed_in.close()
    app.processEvents()
    assert not signed_in.isVisible()


def test_manual_logout_starts_the_resurface_timer(signed_in):
    signed_in._logout()
    assert signed_in._resurface_timer.isActive()
