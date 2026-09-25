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

def test_the_worst_case_column_keeps_everything_and_scrolls(panel):
    """Safety card, the two longest corrections, four more, every reminder.

    This used to be a test of what got THROWN AWAY, and in what order:
    reminders first, then corrections down to one, then the safety card's
    approved script rewritten short. That was the only defence a column with
    no scrollbar had. Bilal saw the result on 16 Sep - cards cut off at the
    screen edge, and "+1 more to put right" standing where a repair he
    needed the words for should have been. Nothing is discarded now.

    Behaviour, not pixels. These run on the offscreen platform, which has no
    fonts - every glyph is a tofu box wider than the real character, and it
    once claimed 31 prompts were clipped when the true number was five. A
    height assertion here would be measuring the wrong typeface. The real
    measurement is measure_panel.py, which runs with Plus Jakarta Sans.
    """
    panel.show_crisis(crisis.payload("I can't go on", True))
    rows = [dict(r, severity="critical") for r in LONGEST[:2]] + CORRECTIONS[:4]
    panel.set_trigger_actions(rows)
    panel.set_warnings(WARNINGS)
    settle(panel)
    # the reminders stayed - capped at MAX_WARNINGS by choice, not by room
    assert panel._shown_warnings == panel.MAX_WARNINGS
    # every correction stayed, and the safety card kept its full script
    assert panel._shown_actions == len(rows)
    assert panel._crisis_box.count() == 1
    assert panel._crisis_compact is False
    # ...and the column still does not run off the bottom of the screen
    assert panel.sizeHint().height() <= panel._room()


def test_the_column_scrolls_rather_than_running_off_the_screen(panel):
    """It had no scrollbar at all, which is precisely why it had to trim.

    Both halves matter. There must BE a scroller, and the column must still
    be capped at the screen - a scroller whose parent is free to grow is
    just a taller column running off the bottom.
    """
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions(CORRECTIONS[:6])
    panel.set_warnings(WARNINGS)
    settle(panel)

    scrolls = panel.findChildren(QScrollArea)
    assert len(scrolls) == 1, "the alerts column needs exactly one scroller"
    assert panel.sizeHint().height() <= panel._room()
    # more content than fits, and it is reachable rather than discarded
    assert scrolls[0].widget().sizeHint().height() > panel._room()
    assert scrolls[0].verticalScrollBar().maximum() > 0


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

def test_the_reminders_are_no_longer_sacrificed_for_a_correction(panel):
    """They used to come off the bottom to make room. Nothing has to now."""
    panel.show_crisis(crisis.payload("I can't go on", True))
    panel.set_trigger_actions([dict(r, severity="critical")
                               for r in LONGEST[:2]])
    panel.set_warnings(WARNINGS)
    settle(panel)
    assert panel._shown_warnings == panel.MAX_WARNINGS
    assert panel._shown_actions == 2


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


def test_nothing_is_hidden_at_all_any_more(panel):
    """Bilal, 16 Sep: "it shows +1 instead, all should be displayed there".

    The card carries the WORDS TO SAY, so a correction that is counted
    rather than drawn is a repair the advisor cannot make.
    """
    rows = CORRECTIONS[:6]
    panel.set_trigger_actions(rows)
    settle(panel)
    text = " ".join(l.text() for l in labels(panel))
    assert "more to put right" not in text
    assert panel._shown_actions == len(rows)
    for r in rows:
        assert r["message"] in text, "correction not on screen: " + str(r["id"])


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
    rebuilds. Left unguarded those two run inside one another and the layout
    keeps a line from the pass that was interrupted.

    Checked per correction rather than "every label on the panel is unique".
    That shortcut only held while at most two cards were ever drawn: each
    card carries its own "PUT THIS RIGHT NOW" heading, so six cards share
    five headings quite legitimately - the shortcut would call that a
    duplicate, while missing a genuinely repeated card.
    """
    panel.show_crisis(crisis.payload("I can't go on", True))
    rows = CORRECTIONS[:5]
    panel.set_trigger_actions(rows)
    settle(panel)
    texts = [l.text() for l in labels(panel)]
    for r in rows:
        n = texts.count(r["message"])
        assert n == 1, str(r["id"]) + " is on the panel " + str(n) + " times"


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


def _quiesce(panel):
    """Stop everything still ticking before the fixture lets the panel go.

    Clearing an expired card runs the panel's normal redraw, which starts its
    reveal timer and its opacity animation. Both then fire against a widget
    deleteLater() has already queued for destruction - and because that
    happens on a LATER file's event loop, the whole suite died inside
    test_call_buffering while this file passed on its own.
    """
    panel.clear_trigger_actions()
    for attr in ("_reveal_timer", "_fade"):
        thing = getattr(panel, attr, None)
        if thing is not None:
            thing.stop()


# -- the two breaches that cannot be taken back ---------------------------

def _texts(panel):
    """Every visible label on the panel, whichever box it sits in.

    This used to walk _action_box alone, which made it silently blind to any
    card added anywhere else - the open-criticals column read as empty while
    its three cards were on screen.
    """
    return [l.text() for l in panel.findChildren(QLabel)
            if l.text().strip() and l.isVisibleTo(panel)]


def test_a_no_repair_card_comes_off_the_screen_by_itself(panel):
    """Bilal, 2026-09-15: for a breach with no genuine in-call recovery,
    "show the warning for 1 minute, then clear it from the live screen". The
    audit finding stays; this is the advisor's screen only.

    Driven with a 0ms expiry rather than by waiting a minute - the duration
    is the server's to choose and is asserted separately.
    """
    rows = [{"id": "q17.omitted_numeric_policy_value",
             "message": "You disclosed a guideline figure.",
             "severity": "critical", "auto_clear_seconds": 0},
            {"id": "q17.partial_category_steering",
             "message": "Withdraw the category suggestion.",
             "severity": "high"}]
    panel.set_trigger_actions(rows)
    assert any("guideline figure" in t for t in _texts(panel))
    for _ in range(20):
        app.processEvents()
    shown = " ".join(_texts(panel))
    assert "guideline figure" not in shown, "the minute card is still up"
    # ...and the one that CAN be repaired is untouched
    assert "Withdraw the category suggestion" in shown
    _quiesce(panel)


def test_an_expired_card_does_not_come_back_on_the_next_message(panel):
    """The server keeps sending it - the finding is permanent and it cannot
    know what the advisor has had time to read. Without remembering the
    expiry the card would reappear about half a second later, which is worse
    than never clearing it.
    """
    rows = [{"id": "q17.omitted_iva_di_control",
             "message": "You worked the figures towards an IVA target.",
             "severity": "critical", "auto_clear_seconds": 0}]
    panel.set_trigger_actions(rows)
    for _ in range(20):
        app.processEvents()
    assert "IVA target" not in " ".join(_texts(panel))
    panel.set_trigger_actions(rows)          # the server says it again
    for _ in range(10):
        app.processEvents()
    assert "IVA target" not in " ".join(_texts(panel)), "it came back"
    _quiesce(panel)


def test_a_new_call_forgets_what_expired_in_the_last_one(panel):
    """Otherwise an advisor who made the same mistake on two calls in a row
    would only be told once."""
    rows = [{"id": "q17.omitted_iva_di_control", "message": "IVA target.",
             "severity": "critical", "auto_clear_seconds": 0}]
    panel.set_trigger_actions(rows)
    for _ in range(20):
        app.processEvents()
    assert panel._expired_actions
    panel.clear_trigger_actions()
    assert not panel._expired_actions
    assert not panel._expiry_timers
    panel.set_trigger_actions(rows)
    assert "IVA target." in " ".join(_texts(panel))
    _quiesce(panel)


def test_an_ordinary_correction_card_never_expires(panel):
    """Only the no-repair ones clear themselves. Everything else waits for
    the advisor to put it right."""
    panel.set_trigger_actions([
        {"id": "q17.partial_monthly_conversion_not_verbalised",
         "message": "Say the monthly figure out loud.", "severity": "high"}])
    for _ in range(20):
        app.processEvents()
    assert "Say the monthly figure out loud." in " ".join(_texts(panel))
    assert not panel._expiry_timers, "an ordinary card was given a clock"
    _quiesce(panel)


# -- criticals left behind travel as cards --------------------------------

CRITS = [
    {"id": "vuln.opening_question", "label": "Opening question asked",
     "section_label": "Vulnerability",
     "prompt": "Ask the vulnerability question covering all eight areas.",
     "missing_parts": ["bereavement", "addictions"]},
    {"id": "onb.dpa_dob", "label": "Date of birth confirmed",
     "section_label": "Onboarding",
     "prompt": "Take the date of birth before discussing anything else.",
     "missing_parts": []},
    {"id": "clos.final_confirmation", "label": "Final confirmation",
     "section_label": "Closing & Consents",
     "prompt": "Confirm the client is happy to proceed.",
     "missing_parts": []},
]


def test_every_outstanding_critical_is_shown_not_just_the_first(panel):
    """Compliance: if several are live "they should all remain available in
    the same popup area, with scrolling if needed so none are lost".

    No cap here on purpose. The panel scrolls; a "+2 more" line would be
    hiding a critical, which is the one thing this exists to prevent.
    """
    panel.set_open_criticals(CRITS)
    settle(panel)
    shown = " ".join(_texts(panel))
    for row in CRITS:
        assert row["label"] in shown, row["label"]
    assert panel._open_crit_box.count() == 3


def test_a_critical_card_says_which_stage_it_was_left_in(panel):
    """The panel follows the conversation now, so a card can be about a
    stage the advisor left ten minutes ago. Without the stage name it is an
    instruction with no context."""
    panel.set_open_criticals(CRITS[:1])
    settle(panel)
    shown = " ".join(_texts(panel))
    assert "VULNERABILITY" in shown
    assert "all eight areas" in shown
    assert "bereavement" in shown


def test_the_same_criticals_again_do_not_rebuild_the_cards(panel):
    """Sent twice a second. Rebuilding every time is the panel's flicker."""
    panel.set_open_criticals(CRITS)
    settle(panel)
    before = [panel._open_crit_box.itemAt(i).widget() for i in range(3)]
    panel.set_open_criticals(list(CRITS))
    after = [panel._open_crit_box.itemAt(i).widget() for i in range(3)]
    assert before == after


def test_a_critical_that_gets_done_leaves_the_column(panel):
    panel.set_open_criticals(CRITS)
    settle(panel)
    panel.set_open_criticals(CRITS[1:])
    settle(panel)
    shown = " ".join(_texts(panel))
    assert "Opening question asked" not in shown
    assert "Date of birth confirmed" in shown


def test_a_new_call_starts_with_an_empty_column(panel):
    panel.set_open_criticals(CRITS)
    settle(panel)
    panel.clear_open_criticals()
    settle(panel)
    assert panel._open_crit_box.count() == 0


# -- the column has to APPEAR for a critical, on its own -------------------

OPEN_CRITICALS = [
    {"id": "vuln.suicide_signposting",
     "label": "Current/recent suicide or self-harm - signposting",
     "section_label": "Vulnerability",
     "prompt": "Disclose the approved mental-health support details now.",
     "missing_parts": []},
    {"id": "vuln.texas_consent", "label": "Consent to note on file",
     "section_label": "Vulnerability",
     "prompt": "Ask for consent to record this on the file.",
     "missing_parts": ["consent asked", "answer captured"]},
]


def test_a_critical_on_its_own_brings_the_column_up(panel):
    """16 Sep: a client said they were suicidal, the follow-ups opened on the
    checklist, and the red column never appeared at all.

    The cards were built, added and shown - and then _restyle asked
    has_content() whether there was anything worth showing, was told no,
    and hid the column with the cards inside it. _open_crit_box was simply
    missing from that list.

    It only ever looked like it worked because a Q17 correction usually
    arrives alongside one: that fills _action_box, which WAS on the list, so
    the column came up and the criticals rode in with it.
    """
    panel.set_open_criticals(OPEN_CRITICALS)
    settle(panel)
    assert panel.has_content(), "the panel does not know it has criticals"
    assert panel.isVisible(), "the red column stayed hidden"
    text = " ".join(l.text() for l in labels(panel))
    for r in OPEN_CRITICALS:
        assert r["label"] in text, f"critical not on screen: {r['id']}"


def test_the_column_goes_away_again_when_the_criticals_are_done(panel):
    panel.set_open_criticals(OPEN_CRITICALS)
    settle(panel)
    assert panel.isVisible()
    panel.set_open_criticals([])
    settle(panel)
    assert not panel.isVisible(), "an empty red column is still a red column"


# -- the column must not measure itself short --------------------------------

def test_the_column_is_as_tall_as_its_contents_need(panel):
    """Bilal, 17 Sep: "the red card has a scrolling effect - half the message
    appears and you have to scroll for the rest, and there is a lot of space
    below it".

    The column pins itself to what its contents say they need, and the three
    synchronous passes that work it out run against sizes Qt has not
    committed to yet. In the running app the real geometry lands a turn
    later, so a pin made before it leaves the column short and the card
    inside it scrolls with the screen half empty underneath.
    """
    panel.show_crisis(crisis.payload("I can't go on", True))
    settle(panel)
    need = panel._body.sizeHint().height()
    room = panel._room()
    if need >= room:
        pytest.skip("this card genuinely does not fit; scrolling is correct")
    assert panel._scroll.maximumHeight() >= need, (
        f"column pinned to {panel._scroll.maximumHeight()}px for content "
        f"that needs {need}px, with {room}px of room available")
    assert panel._scroll.verticalScrollBar().maximum() == 0, \
        "it scrolls even though it fits"


def test_the_recheck_cannot_run_away_with_itself(panel):
    """It re-pins on the UI thread, so an unbounded loop here freezes the
    advisor's widget rather than merely looking wrong."""
    panel.show_crisis(crisis.payload("I can't go on", True))
    settle(panel)
    panel._rechecks_left = 2
    for _ in range(12):
        panel._recheck_height()
    assert panel._rechecks_left <= 0, "the recheck never runs out"


def test_a_settled_column_is_left_alone(panel):
    """A re-pin that changes nothing still costs a relayout on every message
    the server sends, which is twice a second."""
    panel.show_crisis(crisis.payload("I can't go on", True))
    settle(panel)
    before = panel._scroll.maximumHeight()
    panel._rechecks_left = 2
    panel._recheck_height()
    assert panel._scroll.maximumHeight() == before


# -- every wording that would put it right, not just the first -------------

ALT_ROW = {
    "id": "q17.omitted_affordability_misstatement",
    "severity": "critical",
    "message": "Correct the affordability statement and ask the customer to "
               "state their affordable amount again without suggesting a figure.",
    "script": "I'm sorry, I incorrectly repeated the amount you said you "
              "could afford. Can you tell me again what amount you feel you "
              "can genuinely afford each month?",
    "alternatives": [
        "I'm sorry, I shouldn't have suggested a different amount as what "
        "you can afford. What amount do you feel you can genuinely afford?",
        "Apologies, you told me you could afford \u00a3110 per month. Can "
        "you confirm that is still the amount you feel you can genuinely "
        "afford?",
    ],
}


def test_the_second_way_to_put_it_right_is_on_the_screen(panel):
    """Faseeh, 17 Sep: "it still does not contain the second recovery action
    which I told you at least 50 times... it is still showing 1 only."

    He was right, and it was never the rulebook. The server has sent
    `alternatives` with every correction card since the handling file was
    adopted, and main.py did not contain the word - so every alternative
    wording compliance ever wrote arrived at the widget and was thrown away.
    No amount of fixing the data was ever going to put it on screen.
    """
    panel.set_trigger_actions([ALT_ROW])
    settle(panel)
    shown = " ".join(l.text() for l in labels(panel))
    assert ALT_ROW["script"] in shown, "the main script vanished"
    for alt in ALT_ROW["alternatives"]:
        assert alt in shown, f"alternative not drawn: {alt[:50]}"
    assert "OR SAY THIS" in shown, \
        "the alternatives are drawn but not introduced, so they read as " \
        "part of the sentence above them"


def test_a_card_with_one_wording_gains_nothing(panel):
    """Most triggers have a single script. They must not sprout an empty
    "OR SAY THIS" heading."""
    panel.set_trigger_actions([dict(ALT_ROW, alternatives=[])])
    settle(panel)
    shown = " ".join(l.text() for l in labels(panel))
    assert ALT_ROW["script"] in shown
    assert "OR SAY THIS" not in shown


def test_an_alternative_identical_to_the_script_is_not_repeated(panel):
    panel.set_trigger_actions([dict(ALT_ROW,
                                    alternatives=[ALT_ROW["script"], ""])])
    settle(panel)
    shown = [l.text() for l in labels(panel)]
    assert shown.count(ALT_ROW["script"]) == 1
    assert "OR SAY THIS" not in " ".join(shown)


# -- the card log -------------------------------------------------------------
#
# REF545, 25 Sep: Bilal saw a card "flash for a second" and two cards land
# 40-50s after the breach, where the server record says 10s and 29s. His
# widget.log could settle neither: no clock on any line, and nothing ever said
# a card was drawn or taken down.

import re                                                        # noqa: E402

STAMP = r"\d\d:\d\d:\d\d\.\d{3}"


def _card_lines(capsys):
    return [l for l in capsys.readouterr().out.splitlines()
            if l.startswith("[cards]")]


def test_the_log_says_when_each_card_appears_and_goes_and_why(panel, capsys):
    a = {"id": "q17.partial_category_steering", "message": "Withdraw it.",
         "severity": "high"}
    b = {"id": "q17.omitted_pip_dla_mishandling", "message": "Offset it.",
         "severity": "critical"}
    capsys.readouterr()
    panel.set_trigger_actions([a, b])
    shown = _card_lines(capsys)
    assert len(shown) == 2, shown
    for line, cid in zip(shown, (a["id"], b["id"])):
        assert re.match(rf"\[cards\] {STAMP} SHOWN {re.escape(cid)} #1 ", line), line
        assert "(server)" in line or "; server)" in line, line

    panel.set_trigger_actions([b])                 # the server dropped `a`
    gone = _card_lines(capsys)
    assert gone == [l for l in gone if "GONE" in l] and len(gone) == 1, gone
    assert a["id"] in gone[0] and "(server)" in gone[0]

    panel.set_trigger_actions([b])                 # unchanged: nothing to say
    assert _card_lines(capsys) == []

    panel.clear_trigger_actions()
    end = _card_lines(capsys)
    assert len(end) == 1 and b["id"] in end[0] and "(new call)" in end[0], end
    _quiesce(panel)


def test_a_second_occurrence_is_logged_as_its_own_card(panel, capsys):
    row = {"id": "q17.partial_category_steering", "message": "Withdraw it.",
           "severity": "high"}
    capsys.readouterr()
    panel.set_trigger_actions([row, dict(row, occurrence=2)])
    lines = _card_lines(capsys)
    assert any("#1 " in l for l in lines) and any("#2 " in l for l in lines), lines
    _quiesce(panel)


def test_a_card_that_times_out_is_logged_as_timing_out(panel, capsys):
    """Otherwise a one-minute card going reads exactly like the server
    taking it down, and those are the two explanations for a vanishing card
    that most need telling apart."""
    capsys.readouterr()
    panel.set_trigger_actions([{"id": "q17.omitted_iva_di_control",
                                "message": "IVA target.", "severity": "critical",
                                "auto_clear_seconds": 0}])
    for _ in range(20):
        app.processEvents()
    lines = _card_lines(capsys)
    assert any("GONE" in l and "its minute ran out" in l for l in lines), lines
    _quiesce(panel)


def test_the_card_log_never_carries_the_customers_words(panel, capsys):
    """The quote is what the customer or advisor said on a regulated call.
    It has no place in a log file on an advisor's PC."""
    capsys.readouterr()
    panel.set_trigger_actions([{
        "id": "q17.partial_category_steering", "message": "Withdraw it.",
        "severity": "high", "quote": "my rent is 812 pounds at 14 Acacia Road",
        "script": "Say this instead."}])
    panel.clear_trigger_actions()
    out = "\n".join(_card_lines(capsys))
    assert out, "nothing was logged at all"
    assert "Acacia" not in out and "812" not in out
    _quiesce(panel)


def test_every_log_stamp_is_wall_clock_to_the_millisecond():
    assert re.fullmatch(STAMP, m._stamp()), m._stamp()
