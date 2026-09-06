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
