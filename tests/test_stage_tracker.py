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
