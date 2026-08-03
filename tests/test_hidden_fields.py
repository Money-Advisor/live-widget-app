"""The superadmin 'hide customer fields' toggle.

Hiding the Customer Name + Reference ID inputs is cosmetic — the values still come
from the dialer and are still stored. But if the manual Start button keeps DEMANDING
values the agent can no longer see or type, manual recording becomes impossible. These
tests cover both halves: the fields really hide, and Start still works when they do.
"""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

import main


_APP = None


def _app():
    """Create the QApplication once and KEEP a reference — letting it be garbage
    collected takes the whole process down with it."""
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def _win(hide: bool):
    w = main.MainWindow()
    w._token = "tok"
    w._user = {"id": "u1", "email": "agent@x.test"}
    w._recording = False
    w._settings.setValue("audio/mic_name", "Headset (Realtek)")
    # Pretend devices exist so _start_recording gets past the device check.
    w._mic_devices = [{"name": "Mic", "index": 0}]
    w._spk_devices = [{"name": "Spk", "index": 1}]
    w._config = {"hide_customer_fields": hide}
    w._apply_customer_field_visibility()
    return w


def _fields(w):
    return (w._customer_name_edit, w._reference_edit, w._cust_lbl, w._ref_lbl)


# isHidden() (not isVisibleTo) is the right probe: the widget lives on a
# QStackedWidget page that isn't current in a headless test, so isVisibleTo is False
# either way. isHidden reflects the explicit setVisible() this feature controls.
def test_fields_visible_by_default():
    _app()
    w = _win(False)
    assert not any(f.isHidden() for f in _fields(w))


def test_toggle_hides_both_fields_and_their_labels():
    _app()
    w = _win(True)
    assert all(f.isHidden() for f in _fields(w)), "both inputs AND their labels hide"


def test_toggle_is_reversible():
    _app()
    w = _win(True)
    w._config = {"hide_customer_fields": False}
    w._apply_customer_field_visibility()
    assert not any(f.isHidden() for f in _fields(w))


def test_manual_start_still_blocked_when_fields_are_shown_and_empty(monkeypatch):
    """Normal setup is unchanged: empty fields must still be rejected."""
    _app()
    w = _win(False)
    warned = {"n": 0}
    monkeypatch.setattr(main.QMessageBox, "warning",
                        lambda *a, **k: warned.__setitem__("n", warned["n"] + 1))
    started = {"n": 0}
    monkeypatch.setattr(main, "StartCallWorker",
                        lambda *a, **k: started.__setitem__("n", started["n"] + 1))

    w._customer_name_edit.setText("")
    w._reference_edit.setText("")
    w._start_recording(require_name=True)

    assert warned["n"] == 1, "the agent should be told what's missing"
    assert started["n"] == 0


def test_hidden_fields_with_no_reference_points_at_the_dialer(monkeypatch):
    """With the fields hidden the agent has nothing to type, but the server still
    requires a reference — so starting anyway would just be rejected. Say where the
    call should come from instead of failing obscurely."""
    _app()
    w = _win(True)
    warned = {"n": 0}
    informed = {"n": 0}
    monkeypatch.setattr(main.QMessageBox, "warning",
                        lambda *a, **k: warned.__setitem__("n", warned["n"] + 1))
    monkeypatch.setattr(main.QMessageBox, "information",
                        lambda *a, **k: informed.__setitem__("n", informed["n"] + 1))
    started = {"n": 0}
    monkeypatch.setattr(main, "StartCallWorker",
                        lambda *a, **k: started.__setitem__("n", started["n"] + 1))

    w._customer_name_edit.setText("")
    w._reference_edit.setText("")
    w._start_recording(require_name=True)

    assert warned["n"] == 0, "must not nag for fields the agent cannot see"
    assert informed["n"] == 1, "should explain that the dialer starts these calls"
    assert started["n"] == 0, "must not start a call the server would reject"


def test_hidden_fields_start_works_once_the_dialer_supplies_a_reference(monkeypatch):
    """THE fix: the dialer fills the (hidden) reference, and Start must then work
    WITHOUT demanding a customer name the agent cannot see or type."""
    _app()
    w = _win(True)
    warned = {"n": 0}
    informed = {"n": 0}
    monkeypatch.setattr(main.QMessageBox, "warning",
                        lambda *a, **k: warned.__setitem__("n", warned["n"] + 1))
    monkeypatch.setattr(main.QMessageBox, "information",
                        lambda *a, **k: informed.__setitem__("n", informed["n"] + 1))
    reached = {"n": 0}

    def fake_worker(*a, **k):
        reached["n"] += 1
        raise RuntimeError("stop here")

    monkeypatch.setattr(main, "StartCallWorker", fake_worker)

    w._customer_name_edit.setText("")      # hidden -> stays blank
    w._reference_edit.setText("REF-123")   # set programmatically by the dialer
    try:
        w._start_recording(require_name=True)
    except RuntimeError:
        pass

    assert warned["n"] == 0 and informed["n"] == 0
    assert reached["n"] == 1, "start should proceed with only a reference"
