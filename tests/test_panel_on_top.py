"""The widget pins itself above other windows while the compliance panel shows.

An advisor works in Aryza and a browser for the whole call. A prompt that slides
behind them is a prompt nobody acts on, and the point of the live layer is to catch
a breach BEFORE the customer rings off.

Two things must not break, and both are asserted here rather than trusted:
focus must never be stolen (advisors are typing customer details elsewhere), and
the signed-out sticky mode must keep the flag it owns.
"""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import main


_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class FakeWindow(main.QMainWindow):
    """A real QMainWindow so the flag behaviour is Qt's, not a stub's."""

    def __init__(self):
        super().__init__()
        self.activated = 0

    def activateWindow(self):     # noqa: N802 - Qt's name
        self.activated += 1
        super().activateWindow()


def _on_top(w):
    return bool(w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def test_it_pins_when_compliance_appears_and_releases_when_it_goes():
    _app()
    win = FakeWindow()
    assert not _on_top(win)
    main.MainWindow.set_compliance_on_top(win, True)
    assert _on_top(win)
    main.MainWindow.set_compliance_on_top(win, False)
    assert not _on_top(win)


def test_it_never_steals_keyboard_focus():
    """The advisor is typing customer details into another window."""
    _app()
    win = FakeWindow()
    main.MainWindow.set_compliance_on_top(win, True)
    assert win.activated == 0, "pinning must not call activateWindow()"


def test_the_signed_out_warning_keeps_the_flag_it_owns():
    """Sticky mode pins the 'calls are NOT recording' warning for its own reason.

    A call ending must not unpin it, or that warning drifts behind a browser and
    the advisor keeps taking calls that are not being recorded.
    """
    _app()
    win = FakeWindow()
    win._logged_out_sticky = True
    win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    main.MainWindow.set_compliance_on_top(win, False)
    assert _on_top(win), "sticky mode still owns the flag"


def test_repeating_the_same_state_does_not_touch_the_window():
    """Re-setting a window flag hides and re-shows it — that reads as a flicker."""
    _app()
    win = FakeWindow()
    main.MainWindow.set_compliance_on_top(win, True)
    shown_before = win.isVisible()
    main.MainWindow.set_compliance_on_top(win, True)
    assert win.isVisible() == shown_before
    assert _on_top(win)
