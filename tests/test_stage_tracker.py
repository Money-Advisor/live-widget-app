"""The compliance panel's stage tracker and outstanding-parts line.

Both are fed by fields only the RULEBOOK server sends (`stage`, `sections`,
`alert.missing_parts`). The old matcher sends none of them, and both servers are in
the field at once, so the panel has to stay correct when they are absent — that is
the case these tests guard hardest.

The parts line matters more than it looks. The benchmark showed the SCORE moving
several points between runs of the same call, while the list of what is missing did
not, so the panel tells an advisor "explain the other person stays liable", never
"you are at 78%".
"""
import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

import main


_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def _sections(current_index, n=14):
    return [{"key": f"S{i}", "label": f"Stage {i}",
             "done": 2 if i < current_index else 0, "total": 2,
             "current": i == current_index}
            for i in range(n)]


def test_the_tracker_stays_hidden_without_the_new_fields():
    """The old matcher sends no sections. One widget serves both servers.

    isVisibleTo(), not isVisible(): a child reports invisible whenever an ancestor
    is hidden, and the panel starts hidden, so isVisible() would pass here no
    matter what the tracker did.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.update_stage("CREDITOR_CHECK", _sections(4))   # show it first...
    assert panel._stage.isVisibleTo(panel)
    panel.update_stage(None, None)                        # ...then take it away
    assert not panel._stage.isVisibleTo(panel)


def test_it_names_the_stage_and_counts_position():
    _app()
    panel = main.ComplianceAlertPanel()
    panel.update_stage("CREDITOR_CHECK", _sections(4))
    assert panel._stage._name.text() == "Stage 4"
    assert panel._stage._count.text() == "5 of 14"


def test_one_segment_per_stage_coloured_by_progress():
    _app()
    panel = main.ComplianceAlertPanel()
    panel.update_stage("X", _sections(4))
    bar = panel._stage._bar
    assert bar.count() == 14, "one segment per stage, however many there are"
    colour = lambda i: bar.itemAt(i).widget().styleSheet()
    assert main.StageTracker.DONE in colour(0)      # behind us
    assert main.StageTracker.HERE in colour(4)      # here
    assert main.StageTracker.TODO in colour(13)     # not reached


def test_a_finished_stage_stays_marked_when_the_advisor_doubles_back():
    """Advisors go back to fill something in; a completed stage must not un-tick."""
    _app()
    panel = main.ComplianceAlertPanel()
    secs = _sections(2)
    secs[6] = {"key": "S6", "label": "Stage 6", "done": 2, "total": 2, "current": False}
    panel.update_stage("X", secs)
    assert main.StageTracker.DONE in panel._stage._bar.itemAt(6).widget().styleSheet()


def test_the_parts_line_names_what_is_still_needed():
    _app()
    panel = main.ComplianceAlertPanel()
    panel.set_missing_parts(["explain the other person stays liable"])
    assert panel._parts.isVisibleTo(panel)
    assert "stays liable" in panel._parts.text()


def test_the_parts_line_does_not_run_away_with_a_long_checklist():
    """A nineteen-item expenditure list would fill the panel and hide the alert."""
    _app()
    panel = main.ComplianceAlertPanel()
    panel.set_missing_parts([f"category {i}" for i in range(19)])
    assert panel._parts.text().count("•") == 4, "three shown plus a '+N more' line"
    assert "+16 more" in panel._parts.text()


def test_the_parts_line_hides_when_there_is_nothing_outstanding():
    _app()
    panel = main.ComplianceAlertPanel()
    panel.set_missing_parts(["something"])
    panel.set_missing_parts([])
    assert not panel._parts.isVisibleTo(panel)


def test_clearing_the_checklist_clears_the_parts_line():
    """Otherwise the advisor is told to finish a requirement they just completed."""
    _app()
    panel = main.ComplianceAlertPanel()
    panel.set_missing_parts(["explain the liability"])
    panel.update_missing([])
    assert not panel._parts.isVisibleTo(panel)


def test_the_panel_appears_for_the_stage_tracker_alone():
    """No alert is not a reason to show an advisor nothing.

    Visibility used to be decided solely by update_missing(), so with no alert
    firing the whole panel was hidden — stage tracker and opened-out stage
    included. On a real call with the advisor doing everything right, nothing
    appeared at all, and it read as the feature being broken.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    assert panel.isVisible(), "it starts in the idle state, never invisible"
    assert panel._idle.isVisibleTo(panel)
    panel.update_stage("CREDITOR_CHECK", _sections(4), [
        {"id": "cc.x", "label": "Creditors captured", "done": True,
         "severity": "high", "evidence": "every creditor and balance",
         "prompt": None, "missing_parts": []}])
    assert panel.isVisible(), "the stage tracker must be able to show the panel"


def test_an_empty_alert_list_no_longer_hides_the_stage():
    """The advisor covering everything must still see where they are."""
    _app()
    panel = main.ComplianceAlertPanel()
    panel.update_stage("CREDITOR_CHECK", _sections(4), [
        {"id": "cc.x", "label": "Creditors captured", "done": True,
         "severity": "high", "evidence": "", "prompt": None, "missing_parts": []}])
    panel.update_missing([])          # nothing outstanding — the good case
    assert panel.isVisible()
    assert panel._stage.isVisibleTo(panel)


def test_it_falls_back_to_idle_rather_than_disappearing():
    """Between calls the panel stays put and says READY.

    It used to hide completely, which reads as the feature being broken — that is
    exactly how the panel appeared "not to work" on a real call.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.update_stage("CREDITOR_CHECK", _sections(4), [
        {"id": "x", "label": "A check", "done": True, "severity": "high",
         "evidence": "", "prompt": None, "missing_parts": []}])
    assert not panel._idle.isVisibleTo(panel), "live call hides the idle block"
    panel.update_stage(None, None, None)
    panel.update_missing([])
    assert panel.isVisible(), "the panel itself never disappears"
    assert panel._idle.isVisibleTo(panel), "it returns to the idle block"


def _parts_check(open_id="ie.income"):
    return [{"id": open_id, "label": "Income confirmed", "done": False,
             "severity": "critical", "evidence": None,
             "prompt": "Name every income source.", "missing_parts": ["Child Benefit"],
             "parts": [{"text": "employment income", "done": True, "evidence": None},
                       {"text": "second job", "done": True, "evidence": None},
                       {"text": "Child Benefit", "done": False, "evidence": None}]},
            {"id": "onb.dob", "label": "Date of birth confirmed", "done": True,
             "severity": "critical", "evidence": "your date of birth",
             "prompt": None, "missing_parts": [], "parts": []}]


def test_a_multi_part_check_can_be_opened():
    """A twelve-part check that just says "not done" tells an advisor nothing.

    Opened, it shows which parts are proved and which are still to ask.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage("IE", _sections(0), _parts_check())
    acc = panel._accordion
    closed = acc._rows.count()
    acc._toggle("ie.income")
    assert acc._rows.count() == closed + 1, "the parts block should appear"
    acc._toggle("ie.income")
    assert acc._rows.count() == closed, "and disappear again"


def test_an_open_check_survives_the_next_transcript():
    """Rows are rebuilt on every server message — roughly twice a second.

    If open/closed lived on the row widgets, a check would snap shut the instant
    the advisor said anything, which is worse than not having the control.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage("IE", _sections(0), _parts_check())
    panel._accordion._toggle("ie.income")
    opened = panel._accordion._rows.count()
    panel.update_stage("IE", _sections(0), _parts_check())   # next fragment
    assert panel._accordion._rows.count() == opened, "it must stay open"
    assert "ie.income" in panel._accordion._open


def test_a_single_part_check_has_nothing_to_open():
    """No caret where there is nothing behind it."""
    _app()
    panel = main.ComplianceAlertPanel()
    chk = {"id": "x", "label": "One thing", "done": True, "severity": "high",
           "evidence": "", "prompt": None, "missing_parts": [], "parts": []}
    assert panel._accordion._caret(chk, None) is None


def test_the_parts_show_which_are_done():
    _app()
    panel = main.ComplianceAlertPanel()
    block = panel._accordion._parts_block(_parts_check()[0])
    labels = block.findChildren(main.QLabel)
    text = " ".join(l.text() for l in labels)
    assert "employment income" in text and "Child Benefit" in text
    assert "\u2713" in text, "proved parts are ticked"


def _long_stage():
    """A real stage: seven checks, every label long enough to wrap at 340px."""
    return [
        {"id": "ie.income", "label": "All income sources confirmed and evidenced",
         "done": False, "severity": "critical", "evidence": None,
         "prompt": "Name every income source, including benefits.",
         "missing_parts": ["Child Benefit", "any second job", "pension income"],
         "parts": [{"text": "employment income confirmed", "done": True},
                   {"text": "self-employment or second job", "done": True},
                   {"text": "Child Benefit", "done": False},
                   {"text": "Universal Credit or other benefits", "done": False},
                   {"text": "pension income", "done": False}]},
        {"id": "ie.partner",
         "label": "Partner's income and contribution to the household discussed",
         "done": False, "severity": "high", "evidence": None,
         "prompt": "Ask what the partner earns.", "missing_parts": [], "parts": []},
        {"id": "ie.spend",
         "label": "Expenditure walked through against the trigger figures",
         "done": False, "severity": "high", "evidence": None, "prompt": None,
         "missing_parts": [], "parts": []},
        {"id": "ie.arrears", "label": "Priority arrears identified", "done": False,
         "severity": "critical", "evidence": None, "prompt": None,
         "missing_parts": [], "parts": []},
        {"id": "onb.dob",
         "label": "Date of birth and email address confirmed with the customer",
         "done": True, "severity": "critical",
         "evidence": "Can I just take your date of birth please, and the best "
                     "email address for you?",
         "prompt": None, "missing_parts": [], "parts": []},
        {"id": "ie.freq", "label": "Pay frequency captured", "done": True,
         "severity": "normal", "evidence": "So you're paid every four weeks?",
         "prompt": None, "missing_parts": [], "parts": []},
    ]


def test_only_one_check_is_marked_due():
    """Ten red cards, each with its own guidance, is not a checklist.

    That is exactly what the advisor saw: every outstanding item got the full
    treatment and the text ran into itself. The advisor has ONE next thing to
    say, so exactly one card is red however many items are outstanding.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage("IE", _sections(4), _long_stage())
    acc = panel._accordion
    due = [acc._rows.itemAt(i).widget() for i in range(acc._rows.count())]
    red = [w for w in due if w is not None and w.objectName() == "dueCard"]
    assert len(red) == 1, f"expected one due card, got {len(red)}"


def test_a_full_stage_does_not_inflate_the_panel():
    """A guard against the heightForWidth trap, which cost a rebuild.

    Switching heightForWidth on for the wrapped labels looks correct - QLabel
    really does implement it - but the layout then asks how tall the label would
    be at its minimum width, gets an enormous answer, and adopts it as the
    panel's minimum height. Measured at the time: 533px became 1406px and the
    stage bar alone inflated to 338px, pushing the checklist off the screen.

    Six checks with wrapping labels is an ordinary stage. If this ever needs
    raising, look for a size policy before raising it.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage("IE", _sections(4), _long_stage())
    panel.adjustSize()
    assert panel.height() < 800, f"panel ballooned to {panel.height()}px"
    assert panel._stage.height() < 90, \
        f"stage bar ballooned to {panel._stage.height()}px"


def test_the_dropdown_says_how_many_parts_are_proved():
    """A bare arrow gives an advisor no reason to click it. "2/5" does."""
    _app()
    panel = main.ComplianceAlertPanel()
    chk = _long_stage()[0]
    caret = panel._accordion._caret(chk)
    assert caret is not None
    assert "2/5" in caret.text(), caret.text()
    assert "\u25b8" in caret.text(), "closed shows a right-pointing arrow"
    panel._accordion._open.add(chk["id"])
    assert "\u25be" in panel._accordion._caret(chk).text(), \
        "open shows a down-pointing arrow"


# ── the score shape that aborted the process ──────────────────────────────
# The rulebook server sends a breakdown, the old matcher a bare float. float()
# on the breakdown raises inside a Qt slot, and PyQt6 answers that with
# qFatal() - the widget disappeared a second after every scored call, with no
# traceback, because abort() does not unwind.

RULEBOOK_SCORE = {"covered": 1, "total": 59, "earned": 1.0, "fraction": 0.0169}


def test_the_rulebook_score_shape_does_not_kill_the_widget():
    assert main.score_fraction(RULEBOOK_SCORE) == pytest.approx(0.0169)
    assert main.score_fraction(0.42) == pytest.approx(0.42)   # the old matcher
    assert main.score_fraction(None) is None
    # earned/total when the server omits the fraction
    assert main.score_fraction({"earned": 3.0, "total": 6}) == pytest.approx(0.5)
    # anything unrecognised is a missing score, never an exception
    assert main.score_fraction("nonsense") is None
    assert main.score_fraction({"nothing": "useful"}) is None


def test_the_shift_tiles_survive_a_rulebook_score():
    """record_call_result ran float(score) on the way to the THIS SHIFT tiles."""
    _app()
    panel = main.ComplianceAlertPanel()
    panel.record_call_result(score=RULEBOOK_SCORE, flags=3)
    panel.show_idle()
    assert panel._shift["calls"].text() == "1"
    assert panel._shift["average"].text() == "2%", panel._shift["average"].text()
    assert panel._shift["flags"].text() == "3"


# ── the panel was being squeezed, not scrolled ────────────────────────────

def test_a_short_window_scrolls_the_panel_instead_of_crushing_it():
    """The window only ever grew sideways, so the panel took whatever height
    the call card left it and the layout squeezed every row to fit: the due
    card collapsed to a strip with its pill sliced in half, labels lost their
    descenders, and an opened check drew an empty box.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage("IE", _sections(4), _long_stage())
    panel.adjustSize()
    panel.layout().activate()

    def due_card():
        for w in panel.findChildren(main.QFrame):
            if w.objectName() == "dueCard":
                return w
        raise AssertionError("no due card on the panel")

    natural = due_card().sizeHint().height()
    assert natural > 60, "the due card is a card, not a strip"

    # Squeeze the panel into a third of what the stage needs - which is what a
    # window sized for the call card beside it actually did.
    panel.resize(340, max(150, natural))
    panel.layout().activate()
    QApplication.processEvents()

    got = due_card().height()
    assert got >= natural, (
        f"the due card was crushed to {got}px; it needs {natural}px. "
        "Squeezing rows is what sliced the SAY THIS NOW pill in half.")


# ── the same check was on the panel twice ─────────────────────────────────

def test_a_check_shown_in_the_stage_is_not_repeated_as_a_chip():
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage("IE", _sections(4), _long_stage())
    panel.update_missing([{"id": "ie.income", "label": "All income sources",
                           "level": "red", "suggestion_text": "Ask about income."}])
    assert panel._items_box.count() == 0, "the due card already says this"
    assert panel._suggestion.isVisibleTo(panel) is False


def test_a_check_the_stage_does_not_show_still_gets_a_chip():
    """The old matcher sends no stage at all, so the chips must still work."""
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage(None, None, None)
    panel.update_missing([{"id": "onb.fca_statement", "label": "FCA statement",
                           "level": "red", "suggestion_text": "Say the full name."}])
    assert panel._items_box.count() == 1


# ── the end-of-call summary ───────────────────────────────────────────────
# It showed raw check ids - "onb.dpa_dob, cc.aryza_loaded, ff.duration" - at an
# advisor, because the widget's id -> label map is built from the backend's
# `criteria` config, which is the OLD matcher's list and holds none of the
# rulebook's ids, so every lookup fell through to the id.

def _summary_msg():
    return {
        "type": "session_summary", "duration_seconds": 132,
        "recording_saved": True, "scoring_enabled": True,
        "score": {"covered": 1, "total": 3, "earned": 1.0, "fraction": 0.333},
        "covered": {"onb.fca_statement": {"how": "keyword", "evidence": "fca"}},
        "missing": ["onb.dpa_dob", "ie.income"],
        "check_info": {
            "onb.fca_statement": {"label": "FCA regulated statement",
                                  "section": "Onboarding"},
            "onb.dpa_dob": {"label": "Date of birth confirmed",
                            "section": "Onboarding"},
            "ie.income": {"label": "All income sources confirmed",
                          "section": "Income & Expenditure"}},
    }


def _summary_text(card):
    return " | ".join(
        l.text() for l in card.findChildren(main.QLabel) if l.text())


def test_the_summary_names_checks_the_way_the_checklist_does():
    _app()
    card = main.SummaryScreen()
    msg = _summary_msg()
    info = msg["check_info"]
    covered = [{"label": info[i]["label"], "section": info[i]["section"]}
               for i in msg["covered"]]
    missed = [{"label": info[i]["label"], "section": info[i]["section"]}
              for i in msg["missing"]]
    card.show_summary(0.333, covered, missed, 132)

    text = _summary_text(card)
    assert "Date of birth confirmed" in text
    assert "All income sources confirmed" in text
    for raw in ("onb.dpa_dob", "ie.income", "onb.fca_statement"):
        assert raw not in text, f"the advisor was shown the raw id {raw}"


def test_the_missed_list_is_grouped_by_stage():
    """A call that ends early misses every later stage. Without the headings a
    flat run of fifty reds reads as a catastrophe rather than as a short call.
    """
    _app()
    card = main.SummaryScreen()
    info = _summary_msg()["check_info"]
    missed = [{"label": info["onb.dpa_dob"]["label"], "section": "Onboarding"},
              {"label": info["ie.income"]["label"],
               "section": "Income & Expenditure"}]
    card.show_summary(0.0, [], missed, 132)
    text = _summary_text(card)
    assert "Onboarding" in text and "Income & Expenditure" in text


def test_the_old_matcher_summary_still_reads_properly():
    """No check_info from the old server: plain labels, no stage headings."""
    _app()
    card = main.SummaryScreen()
    card.show_summary(0.5, ["Greeting given"], ["Fee disclosure"], 60)
    text = _summary_text(card)
    assert "Greeting given" in text and "Fee disclosure" in text


# ── the panel flickered, and jumped ───────────────────────────────────────

def test_an_unchanged_message_rebuilds_nothing():
    """The server repeats itself about twice a second.

    Every one of those messages was tearing down ten row widgets and building
    ten more, which is what the advisor saw as flickering. Nothing may be
    rebuilt unless something actually changed.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    checks = _long_stage()
    panel.update_stage("IE", _sections(4), checks)
    acc = panel._accordion
    before = [acc._rows.itemAt(i).widget() for i in range(acc._rows.count())]

    for _ in range(10):
        panel.update_stage("IE", _sections(4), [dict(c) for c in checks])

    after = [acc._rows.itemAt(i).widget() for i in range(acc._rows.count())]
    assert before == after, "the identical message rebuilt the rows"


def test_a_real_change_does_rebuild():
    """The skip must not be so eager that a tick never shows up."""
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    checks = _long_stage()
    panel.update_stage("IE", _sections(4), checks)
    acc = panel._accordion
    before = [acc._rows.itemAt(i).widget() for i in range(acc._rows.count())]

    changed = [dict(c) for c in checks]
    changed[0]["done"] = True
    changed[0]["evidence"] = "and the child benefit, is that everything?"
    panel.update_stage("IE", _sections(4), changed)

    after = [acc._rows.itemAt(i).widget() for i in range(acc._rows.count())]
    assert before != after, "a check going green must redraw the list"


def test_opening_a_check_glides_rather_than_jumping():
    """The height is animated, so the panel grows in one motion.

    The animation is also the thing most easily broken by accident: an earlier
    version started it and then had _sync_window snap straight to the end value
    a millisecond later, and every transition measured as a single step.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.show()
    panel._cap = 2000
    panel.update_stage("IE", _sections(4), _long_stage())
    panel._retarget(animate=False)          # settle at the closed height
    start = panel._scroll.maximumHeight()

    panel._accordion._toggle("ie.income")
    # The real code defers by a zero-length timer precisely so Qt can lay the
    # new rows out first; without turning the event loop here the test would
    # measure the same stale height the production bug did.
    QApplication.processEvents()
    panel._deferred_retarget()              # what the queued timer would do

    anim = panel._grow
    assert anim is not None, "no animation was created"
    assert anim.state() == main.QPropertyAnimation.State.Running, \
        "the animation is not running"
    assert anim.startValue() == start
    assert anim.endValue() > start, "opening a check makes the panel taller"
    anim.stop()


def test_a_checklist_that_fits_gets_no_scrollbar():
    """Reported from a real call: a scrollbar on a ten-row Onboarding panel
    with most of the screen still free.

    The panel was measured with sizeHint(), and a word-wrapped label's plain
    sizeHint is one line - so a ten-row stage came out about 15px shorter than
    it really is, the panel was sized to that, and the content overflowed by
    exactly that much. The labels advertise heightForWidth now and the panel
    asks the layout how tall it is AT THE VIEWPORT WIDTH.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.show()
    panel._cap = 1200                       # plenty of room; nothing to scroll
    panel.update_stage("IE", _sections(0), _long_stage())
    QApplication.processEvents()
    panel._retarget(animate=False)
    QApplication.processEvents()

    inner = panel._scroll.widget()
    have = panel._scroll.viewport().height()
    need = inner.height()
    assert need <= have, (
        f"content is {need}px in a {have}px viewport - {need - have}px overflows, "
        "which is the spurious scrollbar")

    # Note: the overflow only reproduces with real font metrics and this suite
    # runs offscreen, so what this actually pins is the measurement path -
    # _target_height asking the layout for its height AT A WIDTH rather than
    # taking its size hint. Checked by reverting that: this test goes red.


def test_the_panel_still_cannot_inflate_the_window():
    """heightForWidth is back on, and it is what broke the panel once before.

    Paired with a 1px minimum width the layout asks "how tall at 1px?" and
    adopts the answer as a minimum height - 533px became 1406px. The guard is
    that the panel's height is clamped by _set_panel_height, so re-enabling it
    cannot reach the window.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.show()
    panel.update_stage("IE", _sections(0), _long_stage())
    QApplication.processEvents()
    # After processEvents, not before: _sync_window runs on a queued timer and
    # (correctly) recomputes the ceiling from the real screen, which would
    # otherwise overwrite the small one this test is about.
    panel._cap = 400                        # a deliberately small ceiling
    panel._retarget(animate=False)
    assert panel._scroll.maximumHeight() <= 400, \
        f"the panel ignored its ceiling: {panel._scroll.maximumHeight()}px"


# ── the checklist vanished mid-call ───────────────────────────────────────
# Seen live on a 22-minute call: the panel dropped to a bare COMPLIANCE + STAGE
# heading, then the checklist reappeared minutes later. The server sends a
# "good job" message the instant a check goes green - missing_items empty,
# praise set, and NO stage fields - and that was being passed through as
# "there is no checklist any more".

def _praise_msg():
    return {"type": "compliance_alert", "missing_items": [],
            "covered_ids": ["onb.fca_statement"],
            "praise": [{"id": "onb.fca_statement",
                        "label": "FCA regulated statement",
                        "section": "INTRODUCTION"}]}


def _stage_msg(checks):
    return {"type": "compliance_alert", "missing_items": [],
            "stage": "IE", "sections": _sections(4),
            "section_checks": checks}


def test_a_good_job_message_does_not_blank_the_checklist():
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    checks = _long_stage()
    panel.update_stage("IE", _sections(4), checks)
    assert panel._accordion.isVisibleTo(panel)

    # The praise message carries no stage fields at all.
    panel.update_stage(None, None, None)
    # ...and then the next ordinary state message repeats the same checks.
    panel.update_stage("IE", _sections(4), [dict(c) for c in checks])

    assert panel._accordion.isVisibleTo(panel), (
        "the checklist stayed hidden - the unchanged payload was skipped as a "
        "no-op rebuild while the accordion was still hidden")
    assert panel._accordion._rows.count() > 0


def test_the_handler_ignores_a_message_with_no_stage_fields():
    """Belt and braces: the praise message should never reach update_stage."""
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.update_stage("IE", _sections(4), _long_stage())
    before = panel._accordion._rows.count()

    seen = []
    panel.update_stage = lambda *a: seen.append(a)      # spy
    msg = _praise_msg()
    has_stage = bool(msg.get("sections") or msg.get("section_checks")
                     or msg.get("stage"))
    if has_stage:
        panel.update_stage(msg.get("stage"), msg.get("sections"),
                           msg.get("section_checks"))
    assert seen == [], "a praise-only message must not touch the stage"
    assert before > 0


# ── customer safety ───────────────────────────────────────────────────────
# The one message on this panel that must never be missed, never be hidden by
# a silent trial, and never depend on a compliance setting being switched on.

CRISIS = {
    "type": "crisis_alert",
    "line": "I hear you, and I'm really concerned about what you've just told "
            "me. You don't have to deal with this on your own.",
    "resources": [
        {"name": "Samaritans", "detail": "116 123 - free, 24/7, confidential"},
        {"name": "Mind", "detail": "0300 123 3393"},
        {"name": "Crisis Text Line", "detail": "text SHOUT to 85258"},
    ],
    "immediate": False,
    "evidence": "I don't know how to go on",
}

# The same card when the server judges the risk immediate. 999 arrives in its
# own field, not as a fourth helpline - compliance requires it shown
# "prominently", and a row at the bottom of a list is the opposite of that.
CRISIS_IMMEDIATE = dict(
    CRISIS,
    immediate=True,
    escalation="IMMEDIATE RISK TO LIFE - stay with them and call 999 now.",
)

# Deliberately awkward: a name far wider than the rest. The panel renders
# whatever resource list it is handed, so it must line up for any of them, and
# a fixture where every name is a similar width would prove nothing.
CRISIS_WIDE_NAMES = dict(
    CRISIS,
    resources=CRISIS["resources"] + [
        {"name": "Immediate risk to life", "detail": "999"}],
)


def _visible_text(panel):
    return " ".join(l.text() for l in panel.findChildren(main.QLabel)
                    if l.isVisibleTo(panel))


def _long_checks(n=26):
    return [{"id": f"c{i}",
             "label": f"A requirement number {i} long enough to wrap onto "
                      f"two lines of the panel",
             "done": i % 3 == 0, "severity": "high",
             "evidence": "some words the advisor said", "prompt": None,
             "missing_parts": [], "parts": []} for i in range(n)]


def _wrapped_short(panel):
    """Wrapped labels on screen given less height than their text needs."""
    inner = panel._scroll.widget()
    out = []
    for lab in inner.findChildren(main.QLabel):
        if not lab.wordWrap() or not lab.text().strip():
            continue
        if not lab.isVisibleTo(panel) or lab.width() <= 0:
            continue
        if lab.heightForWidth(lab.width()) > lab.height() + 1:
            out.append((lab.text()[:44], lab.width(), lab.height(),
                        lab.heightForWidth(lab.width())))
    return out


def test_a_long_prompt_is_not_cut_off():
    """The advisor loses the END of the instruction, which is the half that
    says what to do.

    Qt's fault, not the rulebook's: the bullet row is a QHBoxLayout holding a
    fixed-width dot and a wrapped label, and that layout under-reports its
    height by a line. Measured with the real font, five prompts lost their
    last line - onb.fca_statement among them, so a CRITICAL instruction was
    being truncated.

    Asserted on every wrapped label, not just the prompt: the same layout
    shape is used for gaps and evidence, so anything short is the same bug.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.resize(360, 900)
    panel.show()
    long_prompt = ("Read the whole regulated statement, then confirm the "
                   "customer understood it and note their answer on the file "
                   "before moving on to the next section.")
    panel.update_stage("VULNERABILITY", _sections(1), [
        {"id": "x.long", "label": "A requirement with a long instruction",
         "done": False, "severity": "critical", "evidence": None,
         "prompt": long_prompt, "missing_parts": [], "parts": []}])
    _app().processEvents()
    _app().processEvents()

    short = _wrapped_short(panel)
    assert not short, f"text cut off: {short}"


def test_growing_a_label_does_not_inflate_the_panel():
    """The guard on the fix above.

    Pairing heightForWidth with setMinimumWidth(1) once made the layout ask
    "how tall at 1px wide", take the enormous answer as the panel's minimum,
    and turn a 533px panel into 1406px with a 338px stage bar. Minimum HEIGHT
    is safe; this is here so nobody reintroduces the other one.
    """
    _app()
    panel = main.ComplianceAlertPanel()
    panel.show_live()
    panel.resize(360, 900)
    panel.show()
    panel._cap = 920
    checks = [{"id": f"c{i}", "label": f"Requirement {i}", "done": False,
               "severity": "high", "evidence": None,
               "prompt": "Ask the question and record what they tell you, "
                         "then confirm it back to them before moving on.",
               "missing_parts": [], "parts": []} for i in range(6)]
    panel.update_stage("VULNERABILITY", _sections(1), checks)
    for _ in range(6):
        _app().processEvents()

    assert not _wrapped_short(panel)
    assert panel.height() <= panel._cap, "the panel must respect its cap"
    assert panel._stage.height() < 120, \
        f"the stage bar has inflated to {panel._stage.height()}px"


def _many_warnings(n=23):
    return [{"id": f"w{i}", "severity": "critical" if i < 13 else "high",
             "text": f"Don't do the {i}th forbidden thing on this call ever."}
            for i in range(n)]


def _room_for_a_couple_of_warnings(panel):
    """A screen big enough for the card and a warning or two, but not four.

    Measured from the card itself rather than hardcoded. A pixel constant
    would be wrong the moment a font or a margin changes, and the first
    version of this used one that turned out to be SMALLER than the card
    alone - so every warning was dropped and the test was measuring
    suppression when it meant to measure trimming.
    """
    panel._room = lambda: 100000          # no budget at all, for the moment
    for _ in range(6):
        _app().processEvents()
    panel._fit()
    card_only = panel.sizeHint().height()
    return card_only + 220


def test_the_column_drops_warnings_rather_than_overflow_the_screen():
    """No scrollbar means nothing may be cut off, so the number of warnings
    is not a constant - it is whatever is left after the safety card.

    Measured before this: card plus four warnings was 686px against 720px
    available. It fitted, with 34px to spare, which is not a margin to rely
    on - a longer quote and the bottom of the column is silently gone.
    """
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    # A short screen, PINNED. Otherwise this passes or fails on whatever
    # monitor happens to be plugged in - and on a big one the budget never
    # bites, so the first version of this test was green with the whole
    # mechanism disabled.
    panel.show_crisis(CRISIS_IMMEDIATE)
    room = _room_for_a_couple_of_warnings(panel)
    panel._room = lambda: room
    panel.set_warnings(_many_warnings())
    for _ in range(6):
        _app().processEvents()
    panel._fit()

    assert panel.sizeHint().height() <= panel._room(), \
        f"{panel.sizeHint().height()}px in {panel._room()}px of screen"
    assert panel._shown_warnings >= 1,         "it dropped every warning - the card alone must not fill the screen"
    assert panel._shown_warnings <= panel.MAX_WARNINGS


def test_the_safety_card_is_never_trimmed_for_space():
    """A disclosure does not give way to a warning. Whatever has to go, goes
    from the warnings."""
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel._room = lambda: 380          # brutally short, and pinned
    panel.show_crisis(CRISIS_IMMEDIATE)
    panel.set_warnings(_many_warnings(40))
    for _ in range(6):
        _app().processEvents()
    panel._fit()

    assert panel._crisis_box.count() == 1, "the card must survive intact"
    text = _visible_text(panel)
    assert "116 123" in text and "999" in text,         "the numbers must still be on screen"


def test_nothing_dropped_disappears_silently():
    """Whatever does not fit is still counted, or an advisor has no idea
    there were more."""
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(CRISIS_IMMEDIATE)
    room = _room_for_a_couple_of_warnings(panel)
    panel._room = lambda: room
    panel.set_warnings(_many_warnings(23))
    for _ in range(6):
        _app().processEvents()
    panel._fit()

    hidden = 23 - panel._shown_warnings
    assert f"+{hidden} more" in _visible_text(panel),         f"{hidden} warnings dropped and the panel does not say so"


def test_the_alerts_column_never_scrolls():
    """Replaces "the card is scrolled into view".

    That test existed because the card went in at the top of the CHECKLIST,
    and an advisor part-way down a long list would never see it - measured at
    1823px above the visible area. In its own column there is nothing above
    it and nothing to scroll past, which is a better fix than scrolling to it.

    So the promise is now stronger and this asserts it: the column has no
    scroll area at all, and nothing in it is clipped.
    """
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(CRISIS_IMMEDIATE)
    panel.set_warnings([
        {"id": "a", "severity": "critical",
         "text": "Don't say a guideline, cap or allowance figure out loud."},
        {"id": "b", "severity": "critical",
         "text": "Don't supply a figure yourself - let them give it."},
    ])
    _app().processEvents()
    _app().processEvents()

    from PyQt6.QtWidgets import QScrollArea, QAbstractScrollArea
    assert not panel.findChildren(QScrollArea), \
        "the alerts column must never need scrolling"
    assert not panel.findChildren(QAbstractScrollArea)

    short = [(l.text()[:40], l.width(), l.height(),
              l.heightForWidth(l.width()))
             for l in panel.findChildren(main.QLabel)
             if l.wordWrap() and l.text().strip() and l.width() > 0
             and l.heightForWidth(l.width()) > l.height() + 1]
    assert not short, f"text clipped in the alerts column: {short}"

def test_the_999_bar_shows_only_on_an_immediate_alert():
    """The panel holds no copy of the policy - it renders the bar when the
    server sends one, and nothing when it does not. Changing when 999 appears
    must never need a new build on every agent's PC."""
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(CRISIS)
    _app().processEvents()
    assert "999" not in _visible_text(panel)

    panel.clear_crisis()
    urgent = dict(CRISIS, escalation="IMMEDIATE RISK TO LIFE - call 999 now.",
                  immediate=True)
    panel.show_crisis(urgent)
    _app().processEvents()

    text = _visible_text(panel)
    assert "999" in text
    bar = [f for f in panel.findChildren(main.QFrame)
           if f.objectName() == "escalate"]
    assert bar and bar[0].isVisibleTo(panel), "999 needs its own bar, on screen"


def test_the_999_bar_sits_above_the_script():
    """It is an action to take, not words to say, so the advisor must meet it
    before the paragraph they are about to read out."""
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(dict(CRISIS, escalation="IMMEDIATE RISK TO LIFE - 999",
                           immediate=True))
    _app().processEvents()

    card = next(f for f in panel.findChildren(main.QFrame)
                if f.objectName() == "crisis")
    bar = next(f for f in card.findChildren(main.QFrame)
               if f.objectName() == "escalate")
    script = next(l for l in card.findChildren(main.QLabel)
                  if l.text() == CRISIS["line"])
    assert (bar.mapTo(card, bar.rect().topLeft()).y()
            < script.mapTo(card, script.rect().topLeft()).y())


def test_every_crisis_number_starts_at_the_same_x():
    """Measured, not eyeballed: 24px out before this was a grid.

    Each resource used to be its own QHBoxLayout, so a name wider than the 96px
    minimum pushed only its own number right. "Immediate risk to life" is wider
    than the rest, so on the one card that must be read at a glance, one line
    sat visibly out of line with the others.
    """
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(CRISIS_WIDE_NAMES)
    _app().processEvents()

    card = next(f for f in panel.findChildren(main.QFrame)
                if f.objectName() == "crisis")
    assert card.isVisibleTo(panel), "the card must actually be on screen"

    wanted = {r["detail"] for r in CRISIS_WIDE_NAMES["resources"]}
    lefts = {lab.text(): lab.mapTo(card, lab.rect().topLeft()).x()
             for lab in card.findChildren(main.QLabel)
             if lab.text() in wanted}

    assert len(lefts) == len(wanted), f"missing rows: {wanted - set(lefts)}"
    assert len(set(lefts.values())) == 1, \
        f"numbers do not line up: {lefts}"


def test_the_card_renders_whatever_resources_it_is_handed():
    """999 is decided by the server, never by the panel.

    The widget must not carry its own copy of the policy - if it did, changing
    when 999 appears would need a widget release to every agent's PC.
    """
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(CRISIS)
    _app().processEvents()

    text = _visible_text(panel)
    assert "116 123" in text and "0300 123 3393" in text and "85258" in text
    assert "999" not in text, "the server did not send it, so it must not show"


def test_the_crisis_card_shows_the_numbers_the_advisor_must_read():
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(CRISIS_IMMEDIATE)

    text = _visible_text(panel)
    assert "CUSTOMER SAFETY" in text
    # The three helplines come from `resources`; 999 from `escalation`. All
    # four have to be readable off one card.
    for number in ("116 123", "0300 123 3393", "85258", "999"):
        assert number in text, f"{number} is not on screen"
    assert "I don't know how to go on" in text, "the customer's own words"


def test_the_safety_card_is_not_in_the_checklist_at_all():
    """It used to go in at the top of the checklist panel and push everything
    down. It is a different KIND of thing - irreversible, not outstanding -
    and it now has its own column, so the checklist does not move when a
    disclosure happens.
    """
    _app()
    checklist = main.ComplianceAlertPanel()
    assert not hasattr(checklist, "show_crisis"), \
        "two homes for the card is two things to drift"
    assert not hasattr(checklist, "_crisis_box")

    alerts = main.AdvisorAlertsPanel()
    alerts.show()
    alerts.show_crisis(CRISIS)
    _app().processEvents()
    assert alerts._crisis_box.count() == 1

def test_it_is_shown_once_however_many_times_it_arrives():
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    for _ in range(4):
        panel.show_crisis(CRISIS)
    assert panel._crisis_box.count() == 1


def test_a_new_call_starts_without_it():
    _app()
    panel = main.AdvisorAlertsPanel()
    panel.show()
    panel.show_crisis(CRISIS)
    assert panel._crisis_box.count() == 1

    panel.clear_crisis()
    assert panel._crisis_box.count() == 0
    panel.show_crisis(CRISIS)
    assert panel._crisis_box.count() == 1, "and it can be raised again next call"


def test_the_column_appears_for_the_card_alone_and_hides_when_empty():
    """It is not a permanent column. The widget is 340px wide because it sits
    beside Aryza and a browser, and a second column that is always there
    takes screen an advisor has not got - so it exists only when it has
    something to say, and goes away again when it does not.
    """
    _app()
    panel = main.AdvisorAlertsPanel()
    assert not panel.isVisible(), "nothing to say yet"

    panel.show_crisis(CRISIS)
    assert panel.isVisible(), "a safety card on its own must bring it up"

    panel.clear_crisis()
    assert not panel.isVisible(), "and it goes away when emptied"

    panel.set_warnings([{"id": "a", "severity": "high", "text": "Don't."}])
    assert panel.isVisible(), "a warning on its own must bring it up too"

