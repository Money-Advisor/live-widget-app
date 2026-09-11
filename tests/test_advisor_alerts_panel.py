# -*- coding: utf-8 -*-
"""The left column holds three different moments in a call.

    the safety card   a customer at risk. Never dismissed, never removed.
    a CORRECTION      something already said that has to be repaired now,
                      with compliance's words to do it.
    the reminders     standing advice for a mistake not yet made.

They compete for one 300px column on whatever screen the advisor has, and
there is no scrollbar to fall back on - so what happens when they do not all
fit is a design decision, not an accident. These tests hold that decision:

    the safety card condenses but never goes, and only to make room for a
      repair. Every helpline and the 999 bar survive it.
    a correction is trimmed to one, never to none.
    the reminders go first and go completely.

Sizes are measured, not asserted against constants. The offscreen platform
has no fonts, so a hard pixel number here would be measuring tofu boxes
rather than Plus Jakarta Sans.
"""
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
SRV = APP.parent / "live-widget-server"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(SRV))

from PyQt6.QtWidgets import (QApplication, QLabel,               # noqa: E402
                             QScrollArea, QAbstractScrollArea)

app = QApplication.instance() or QApplication([])

import main as m                                                 # noqa: E402
import crisis                                                    # noqa: E402
import q17_handling as Q                                         # noqa: E402

CORRECTIONS = [Q.render(t, None) for t in sorted(Q.all_ids())]
LONGEST = sorted(CORRECTIONS,
                 key=lambda r: -len((r["script"] or "") + r["message"]))
WARNINGS = [{"id": f"w{i}", "severity": "critical" if i < 2 else "high",
             "text": f"Do not do the {i}th thing that cannot be undone."}
            for i in range(14)]


@pytest.fixture
def panel():
    p = m.AdvisorAlertsPanel()
    p.move(-3000, -3000)               # laid out for real, never on a screen
    p.show()
    for _ in range(6):
        app.processEvents()
    yield p
    p.hide()
    p.deleteLater()


def settle(p, n=10):
    for _ in range(n):
        app.processEvents()
    p._fit()
    for _ in range(4):
        app.processEvents()


def labels(p):
    return [l for l in p.findChildren(QLabel)
            if l.isVisibleTo(p) and l.text().strip()]


def clipped(p):
    out = []
    for lab in labels(p):
        need = (lab.heightForWidth(lab.width()) if lab.wordWrap()
                else lab.sizeHint().height())
        if need > lab.height() + 1:
            out.append((lab.text()[:50], lab.height(), need))
    return out


# -- it shows up at all ----------------------------------------------------

def test_a_correction_reaches_the_screen(panel):
    panel.set_trigger_actions([CORRECTIONS[0]])
    settle(panel)
    assert panel.isVisible()
    text = " ".join(l.text() for l in labels(panel))
    assert "PUT THIS RIGHT" in text


def test_the_script_is_on_screen_because_it_is_the_point(panel):
    row = next(r for r in CORRECTIONS if r["script"])
    panel.set_trigger_actions([row])
    settle(panel)
    text = " ".join(l.text() for l in labels(panel))
    assert "SAY THIS" in text
    assert row["script"] in text


def test_an_irreversible_one_says_so_instead_of_leaving_a_gap(panel):
    row = Q.render("q17.omitted_numeric_policy_value", None)
    panel.set_trigger_actions([row])
    settle(panel)
    text = " ".join(l.text() for l in labels(panel))
    assert "SAY THIS" not in text
    assert "nothing to say to undo this" in text


def test_nothing_shows_when_there_is_nothing_to_show(panel):
    panel.set_trigger_actions([])
    settle(panel)
    assert not panel.isVisible()


def test_no_bracket_ever_reaches_the_screen(panel):
    """Every correction, with no details extracted at all."""
    for row in CORRECTIONS:
        panel.set_trigger_actions([row])
        settle(panel, 4)
        for lab in labels(panel):
            assert "[" not in lab.text(), (row["id"], lab.text())


# -- nothing is cut off, and there is no scrollbar -------------------------

def test_the_worst_case_column_gives_way_in_the_right_order(panel):
    """Safety card, the two longest corrections, and every reminder.

    Behaviour, not pixels. These run on the offscreen platform, which has no
    fonts - every glyph is a tofu box wider than the real character, and it
    once claimed 31 prompts were clipped when the true number was five. A
    height assertion here would be measuring the wrong typeface. The real
    measurement is measure_panel.py, which runs with Plus Jakarta Sans.
    """
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions([dict(r, severity="critical")
                               for r in LONGEST[:2]] + CORRECTIONS[:4])
    panel.set_warnings(WARNINGS)
    settle(panel)
    # the reminders went first, and went completely
    assert panel._shown_warnings == 0
    # a correction survived, and the safety card was not removed
    assert panel._shown_actions >= 1
    assert panel._crisis_box.count() == 1
    # nothing hidden without saying so
    assert "more to put right" in " ".join(l.text() for l in labels(panel))


def test_there_is_never_a_scrollbar(panel):
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions(CORRECTIONS[:6])
    panel.set_warnings(WARNINGS)
    settle(panel)
    assert panel.findChildren(QScrollArea) == []
    assert panel.findChildren(QAbstractScrollArea) == []


def test_no_two_cards_overlap(panel):
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions(CORRECTIONS[:3])
    panel.set_warnings(WARNINGS)
    settle(panel)
    kids = []
    for box in (panel._crisis_box, panel._action_box, panel._warn_box):
        kids += [box.itemAt(i).widget() for i in range(box.count())
                 if box.itemAt(i).widget() is not None]
    for i, a in enumerate(kids):
        for b in kids[i + 1:]:
            assert not a.geometry().intersects(b.geometry())


# -- what gives way, and in what order -------------------------------------

def test_the_reminders_go_before_a_correction_does(panel):
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions([dict(r, severity="critical")
                               for r in LONGEST[:2]])
    panel.set_warnings(WARNINGS)
    settle(panel)
    assert panel._shown_warnings == 0
    assert panel._shown_actions >= 1


def test_a_correction_is_never_trimmed_to_none(panel):
    """Asks the trim directly rather than hoping the column overflows.

    Whether it overflows depends on the screen and, in these tests, on the
    offscreen platform's idea of text size - so driving it through a real
    overflow made this pass with the floor removed entirely.
    """
    panel.set_trigger_actions(CORRECTIONS[:3])
    settle(panel)
    panel._render_actions(0)            # trim as hard as it can be asked to
    settle(panel)
    assert panel._shown_actions == 1
    cards = [panel._action_box.itemAt(i).widget()
             for i in range(panel._action_box.count())]
    assert [w for w in cards if w.objectName() == "actionCard"]


def test_whatever_is_hidden_is_counted_rather_than_vanishing(panel):
    panel.set_trigger_actions(CORRECTIONS[:6])
    settle(panel)
    text = " ".join(l.text() for l in labels(panel))
    assert "more to put right" in text


# -- the safety card --------------------------------------------------------

def test_the_safety_card_is_left_alone_when_nothing_needs_the_room(panel):
    """It condenses only for a repair. On its own it stays as approved."""
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_warnings(WARNINGS)
    settle(panel)
    assert panel._crisis_compact is False
    text = " ".join(l.text() for l in labels(panel))
    assert "Thank you for telling me that" in text


def test_condensing_keeps_every_number_and_the_999_bar(panel):
    """The approved script is what goes. Nothing else.

    Condensing is asked for directly. Driving it through a real overflow
    made this pass with the condensing removed altogether - the full card
    carries the same numbers, so "the numbers are there" is true either way.
    """
    panel.show_crisis(crisis.payload("I can't go on", True))
    settle(panel)
    full = " ".join(l.text() for l in labels(panel))
    assert "Thank you for telling me that" in full

    panel._render_crisis(True)
    settle(panel)
    short = " ".join(l.text() for l in labels(panel))
    assert "Thank you for telling me that" not in short, "the script stayed"
    assert "CUSTOMER SAFETY" in short
    for number in ("116 123", "85258", "0300 123 3393"):
        assert number in short, number
    assert "999" in short
    assert "Support signposted" in short


# Compliance's wording, held independently of the code that renders it -
# the same guard the approved script itself gets. Bilal signed this off on
# 2026-09-11 after being shown exactly what the card keeps and what it
# drops, so it is no more ours to reword than the script is.
APPROVED_CONDENSED = ("Support signposted. These numbers stay here for the "
                      "rest of the call.")


def test_the_condensed_line_is_the_wording_compliance_approved(panel):
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel._render_crisis(True)
    settle(panel)
    assert APPROVED_CONDENSED in " ".join(l.text() for l in labels(panel))


def test_condensing_actually_makes_it_shorter(panel):
    """Otherwise it is a rewrite that buys nothing."""
    panel.show_crisis(crisis.payload("I can't go on", True))
    settle(panel)
    tall = panel._crisis_box.itemAt(0).widget().sizeHint().height()
    panel._render_crisis(True)
    settle(panel)
    assert panel._crisis_box.itemAt(0).widget().sizeHint().height() < tall


def test_the_safety_card_is_never_removed_to_make_room(panel):
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions(CORRECTIONS[:6])
    panel.set_warnings(WARNINGS)
    settle(panel)
    assert panel._crisis_box.count() == 1


def test_a_new_call_gets_the_full_script_back(panel):
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions([dict(r, severity="critical")
                               for r in LONGEST[:2]])
    panel.set_warnings(WARNINGS)
    settle(panel)
    panel.clear_crisis()
    panel.clear_trigger_actions()
    panel.clear_warnings()
    assert panel._crisis_compact is False
    panel.show_crisis(crisis.payload("I can't go on", False))
    settle(panel)
    text = " ".join(l.text() for l in labels(panel))
    assert "Thank you for telling me that" in text


# -- the re-entrancy that duplicated a line --------------------------------

def test_rebuilding_does_not_leave_a_duplicate_line_behind(panel):
    """Adding a card resizes the panel, resizeEvent calls _fit, and _fit
    trims by rebuilding. Left unguarded those two run inside one another and
    the layout keeps a line from the pass that was interrupted."""
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions(CORRECTIONS[:5])
    settle(panel)
    texts = [l.text() for l in labels(panel)]
    assert len(texts) == len(set(texts)), texts


def test_the_count_matches_what_is_actually_on_screen(panel):
    panel.set_trigger_actions(CORRECTIONS[:5])
    settle(panel)
    cards = [panel._action_box.itemAt(i).widget()
             for i in range(panel._action_box.count())]
    on_screen = [w for w in cards if w.objectName() == "actionCard"]
    assert len(on_screen) == panel._shown_actions


def test_the_same_corrections_twice_do_not_rebuild(panel):
    panel.set_trigger_actions(CORRECTIONS[:2])
    settle(panel)
    before = [panel._action_box.itemAt(i).widget()
              for i in range(panel._action_box.count())]
    panel.set_trigger_actions(CORRECTIONS[:2])
    settle(panel)
    after = [panel._action_box.itemAt(i).widget()
             for i in range(panel._action_box.count())]
    assert before == after, "rebuilt identical content, which flickers"


# -- ordering ---------------------------------------------------------------

def test_a_correction_sits_above_the_reminders(panel):
    """An advisor who has just invented a figure does not need to be told,
    underneath, not to invent figures."""
    panel.set_trigger_actions([CORRECTIONS[0]])
    panel.set_warnings(WARNINGS[:2])
    settle(panel)
    action = panel._action_box.itemAt(0).widget()
    warn = panel._warn_box.itemAt(0).widget()
    assert action.y() < warn.y()


def test_the_safety_card_sits_above_everything(panel):
    panel.show_crisis(crisis.payload("I can't go on", False))
    panel.set_trigger_actions([CORRECTIONS[0]])
    settle(panel)
    assert panel._crisis_box.itemAt(0).widget().y() < \
        panel._action_box.itemAt(0).widget().y()


# -- the second of distortion when the card lands -------------------------

def test_the_column_does_not_fade_in_while_it_is_still_moving(panel):
    """It used to become visible, start the fade, and only THEN measure,
    trim and condense - so the fade ran over a layout that was still
    changing shape, under a frameless window resizing beneath it. That is
    the second of mess compliance saw when the safety card appeared.

    Now: visible at zero opacity (a hidden widget cannot be measured), fit
    in the dark, fade once the geometry has stopped.
    """
    panel.show_crisis(crisis.payload("I can't go on", True))
    # _restyle arms the fade; it must not have started it.
    assert panel._fade.state() != panel._fade.State.Running or \
        panel._fx.opacity() > 0.0
    settle(panel)
    for _ in range(8):
        app.processEvents()
    assert panel.isVisible()


def test_the_fade_timer_belongs_to_the_panel(panel):
    """A free-standing singleShot keeps firing after the panel's C++ side is
    gone, and touching a deleted graphics effect from it takes the process
    down rather than raising - which is exactly what it did."""
    assert panel._reveal_timer.parent() is panel
    assert panel._reveal_timer.isSingleShot()
