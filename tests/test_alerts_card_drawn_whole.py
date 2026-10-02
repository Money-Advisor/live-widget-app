# -*- coding: utf-8 -*-
"""A correction card in the alerts column is drawn whole, first time.

Measured 1 Oct 2026: a card laid out at exactly 153px in a 153px column was
DRAWN with its top border and last line cut off on most runs - the geometry
was right, the picture was stale, and it stayed that way until something
else repainted the column ("it fixed itself after a while", Bilal). The
column was being painted through its fade effect even at full opacity. The
effect is now on only while it fades.

The check: what the column shows at rest must be exactly what a fresh repaint
of it shows. Repeated, because the stale drawing came up on about five runs
in six - one clean run proves nothing.
"""
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
SRV = APP.parent / "live-widget-server"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(SRV))

from PyQt6.QtCore import QEventLoop, QTimer                    # noqa: E402
from PyQt6.QtWidgets import QApplication                       # noqa: E402

app = QApplication.instance() or QApplication([])

import main as m                                               # noqa: E402
import cat_integration as C                                    # noqa: E402


def pump(ms=0):
    for _ in range(20):
        app.processEvents()
    if ms:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
        for _ in range(20):
            app.processEvents()


def card_row():
    cw = C.CatWatch("REF-W", client=None)
    cw.case = C.CatCase("complete", {"food": C.CatItem("food", "Food and housekeeping", 180.0)})
    cw.observe([{"category": "food", "amount": 320.0, "amount_high": None,
                 "period": "monthly", "approximate": False,
                 "put_forward_by": "advisor", "quote": "put 320 for food"}], [])
    return cw.cards()[0]


def live_window():
    w = m.MainWindow()
    w._stack.setCurrentWidget(w._page_main)
    w.move(200, 50)
    w.show()
    pump(ms=600)
    w._recording = True
    w._compliance_panel.show_live()
    return w


def close(w):
    w._recording = False
    w.hide()
    w.deleteLater()
    pump()


@pytest.mark.parametrize("run", range(4))
def test_a_correction_card_is_drawn_whole_without_waiting_for_a_repaint(run):
    w = live_window()
    try:
        w._handle_server_message({
            "type": "compliance_alert", "missing_items": [], "covered_ids": [],
            "stage": "AFFORDABILITY", "sections": [{"key": "AFFORDABILITY",
                                                    "label": "I&E", "current": True}],
            "section_checks": [], "still_to_do": [], "open_criticals": [],
            "warnings": [], "trigger_actions": [card_row()]})
        pump(ms=1200)
        p = w._alerts_panel
        assert p.isVisible()
        at_rest = p.grab().toImage()
        p.update()
        pump(ms=200)
        assert p.grab().toImage() == at_rest, "the column showed a stale drawing"
    finally:
        close(w)


def test_the_column_still_fades_in_and_the_effect_goes_off_once_it_has():
    w = live_window()
    try:
        p = w._alerts_panel
        assert not p._fx.isEnabled()                  # at rest, before anything
        w._handle_server_message({
            "type": "compliance_alert", "missing_items": [], "covered_ids": [],
            "stage": "AFFORDABILITY", "sections": [{"key": "AFFORDABILITY",
                                                    "label": "I&E", "current": True}],
            "section_checks": [], "still_to_do": [], "open_criticals": [],
            "warnings": [], "trigger_actions": [card_row()]})
        assert p._fx.isEnabled() and p._fx.opacity() < 0.01   # armed, invisible
        seen = []
        for _ in range(30):
            pump(ms=15)
            seen.append(p._fx.opacity())
        assert any(0.01 < o < 0.99 for o in seen), "it snapped in instead of fading"
        pump(ms=m.AdvisorAlertsPanel.FADE_MS + 300)
        assert p._fx.opacity() >= 0.999 and not p._fx.isEnabled()
    finally:
        close(w)
