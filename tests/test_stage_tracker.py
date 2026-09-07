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
