# -*- coding: utf-8 -*-
"""A CAT mismatch card draws in the SHIPPED widget, with no new build.

The recording server sends a CAT conflict in `trigger_actions`, in the shape of
a Q17 correction card, precisely so that every widget already on an agent's PC
can draw it. That is only true if this panel really does draw it - so the row
here is built by the server's own code (cat_integration.CatWatch.cards()), not
typed out by hand, and a change to either side that breaks the other fails here.
"""
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
SRV = APP.parent / "live-widget-server"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(SRV))

from PyQt6.QtWidgets import QApplication, QLabel               # noqa: E402

app = QApplication.instance() or QApplication([])

import main as m                                               # noqa: E402
import cat_integration as C                                    # noqa: E402
import q17_handling as Q                                       # noqa: E402


def cat_row(cat="food", label="Food and housekeeping", cat_value=180.0, heard=320.0):
    w = C.CatWatch("REF-W", client=None)
    w.case = C.CatCase("complete", {cat: C.CatItem(cat, label, cat_value)})
    w.observe([{"category": cat, "amount": heard, "amount_high": None,
                "period": "monthly", "approximate": False,
                "put_forward_by": "advisor", "quote": f"put {heard} for {cat}"}], [])
    rows = w.cards()
    assert len(rows) == 1
    return rows[0]


@pytest.fixture
def panel():
    p = m.AdvisorAlertsPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(6):
        app.processEvents()
    yield p
    p.hide()
    p.deleteLater()


def settle(p):
    for _ in range(10):
        app.processEvents()
    p._fit()
    for _ in range(4):
        app.processEvents()


def texts(p):
    return [lab.text() for lab in p.findChildren(QLabel)
            if lab.isVisibleTo(p) and lab.text().strip()]


def test_a_cat_card_draws_its_message_and_what_to_do(panel):
    row = cat_row()
    panel.set_trigger_actions([row])
    settle(panel)
    shown = texts(panel)
    assert row["message"] in shown, "the mismatch itself must be on screen"
    assert row["action"] in shown, "with no script, the widget draws `action`"
    assert not any(t in ("SAY THIS", "OR SAY THIS") for t in shown), \
        "there is no approved script for a CAT card, so none may be implied"


def test_the_card_says_both_figures(panel):
    panel.set_trigger_actions([cat_row(cat_value=180.0, heard=320.0)])
    settle(panel)
    msg = next(t for t in texts(panel) if "CAT shows" in t)
    assert "£180" in msg and "£320" in msg


def test_a_cat_card_sits_alongside_a_q17_correction(panel):
    q17 = Q.render("q17.omitted_unsupported_expenditure_amount", None)
    q17["occurrence"] = 1
    row = cat_row()
    panel.set_trigger_actions([q17, row])
    settle(panel)
    shown = texts(panel)
    assert row["message"] in shown and q17["message"] in shown


def test_two_cat_cards_are_both_drawn(panel):
    # That each category gets its own id is the server's job, pinned in
    # live-widget-server tests/test_cat_integration.py; this is the drawing.
    panel.set_trigger_actions([cat_row("food", "Food"), cat_row("rent", "Rent", 600, 900)])
    settle(panel)
    shown = texts(panel)
    assert sum(1 for t in shown if "CAT shows" in t) == 2


def test_a_cleared_cat_card_leaves_the_screen(panel):
    panel.set_trigger_actions([cat_row()])
    settle(panel)
    panel.set_trigger_actions([])
    settle(panel)
    assert not any("CAT shows" in t for t in texts(panel))
