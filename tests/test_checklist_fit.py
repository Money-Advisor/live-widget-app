# -*- coding: utf-8 -*-
"""What the checklist draws, after the first real call with compliance.

Three things came out of that call, and all three are about the panel
telling the advisor something untrue.

A QUESTION THE CUSTOMER RULED OUT looked exactly like one still to ask. The
advisor asked "have you ever had any debt solution", the client said no, and
all four follow-ups sat there as outstanding - with the tally stuck at 1/5,
so the check could never be finished. The server had retired them and was
sending `na` on each one. The panel had never read the field.

A SCROLLBAR, on a panel nobody scrolls mid-call. Thirty outstanding rows and
twenty-eight completed ones, each with a quote, is 1945px of a 600px panel.
Those rows were not available, they were off-screen - and a count says the
same thing honestly in one line.

Sizes are not asserted here. These run on the offscreen platform, which has
no fonts, so every glyph is a tofu box wider than the real character. The
pixels are measured in measure_panel.py; this is about behaviour.
"""
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
SRV = APP.parent / "live-widget-server"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(SRV))

from PyQt6.QtWidgets import (QApplication, QLabel,               # noqa: E402
                             QPushButton)

app = QApplication.instance() or QApplication([])

import main as m                                                 # noqa: E402


def check(cid, label, done=False, parts=None, na_from=None):
    """One check as the server sends it. `na_from` retires parts at and after
    that index, which is what a customer's "no" does."""
    rows = []
    for i, text in enumerate(parts or []):
        retired = na_from is not None and i >= na_from
        rows.append({"text": text, "done": done and not retired,
                     "na": retired, "evidence": None})
    return {"id": cid, "label": label, "done": done, "severity": "high",
            "evidence": "yes that is right" if done else None,
            "prompt": None if done else "Ask them the thing.",
            "missing_parts": [], "parts": rows}


PRIOR_SOLUTIONS = check(
    "ff.prior_solutions", "Q4 - Prior debt solutions", done=False,
    parts=["whether the client ever actually entered a debt solution",
           "type of each solution actually entered",
           "start/end or termination timing and current outcome",
           "reason for failure/termination where applicable",
           "Breathing Space in the last 12 months asked"],
    na_from=1)


@pytest.fixture
def acc():
    a = m.SectionAccordion()
    a.move(-3000, -3000)
    a.show()
    for _ in range(4):
        app.processEvents()
    yield a
    a.hide()
    a.deleteLater()


def texts(w):
    return [l.text() for l in w.findChildren(QLabel)
            if l.isVisibleTo(w) and l.text().strip()]


def tally(w):
    """The chip on a check row - "2/3" and an arrow.

    A QPushButton, not a label. Reading labels instead picked up the section
    header's own ratio and made both tally tests pass on the wrong widget.
    """
    return [b.text().split()[0] for b in w.findChildren(QPushButton)
            if b.isVisibleTo(w) and "/" in b.text()]


# -- a retired part is not a job ------------------------------------------

def test_a_part_the_customer_ruled_out_is_marked_not_applicable(acc):
    """It was drawn identically to one still outstanding."""
    acc._open.add("ff.prior_solutions")
    acc.update_section("Fact Find", [PRIOR_SOLUTIONS])
    for _ in range(4):
        app.processEvents()
    assert "n/a" in texts(acc)


def test_the_retired_parts_leave_the_tally(acc):
    """1/5 with four of them ruled out is a check that can never finish. The
    denominator is what is still a job: one part, still to do."""
    acc.update_section("Fact Find", [PRIOR_SOLUTIONS])
    for _ in range(4):
        app.processEvents()
    assert tally(acc) == ["0/1"], tally(acc)


def test_a_check_with_nothing_ruled_out_is_unchanged(acc):
    """The fix must not quietly shrink an ordinary check."""
    plain = check("x.plain", "Something", parts=["one", "two", "three"])
    acc.update_section("Fact Find", [plain])
    for _ in range(4):
        app.processEvents()
    assert tally(acc) == ["0/3"], tally(acc)


def test_a_retired_part_is_never_shown_as_done(acc):
    """The advisor did not ask it and never should have. Crediting them is
    as wrong as nagging them."""
    acc._open.add("ff.prior_solutions")
    acc.update_section("Fact Find", [PRIOR_SOLUTIONS])
    for _ in range(4):
        app.processEvents()
    shown = texts(acc)
    assert "type of each solution actually entered" in " ".join(shown)
    assert "n/a" in shown


# -- the panel stops growing without limit --------------------------------

def many(n_todo, n_done):
    out = [check(f"t{i}", f"Outstanding thing number {i}") for i in range(n_todo)]
    out += [check(f"d{i}", f"Completed thing number {i}", done=True)
            for i in range(n_done)]
    return out


def test_a_long_outstanding_list_is_capped_and_counted(acc):
    acc.update_section("Available Options", many(30, 0))
    for _ in range(4):
        app.processEvents()
    joined = " ".join(texts(acc))
    assert "still to do in this stage" in joined
    rows = [t for t in texts(acc) if t.startswith("Outstanding thing")]
    assert len(rows) <= acc.MAX_TODO_ROWS


def test_a_long_done_list_is_capped_and_counted(acc):
    acc.update_section("Available Options", many(2, 28))
    for _ in range(4):
        app.processEvents()
    joined = " ".join(texts(acc))
    assert "already done" in joined
    rows = [t for t in texts(acc) if t.startswith("Completed thing")]
    assert len(rows) <= acc.MAX_DONE_ROWS


def test_a_short_stage_is_never_capped(acc):
    """Nothing is hidden that fits."""
    acc.update_section("Situation Summary", many(2, 2))
    for _ in range(4):
        app.processEvents()
    joined = " ".join(texts(acc))
    assert "still to do in this stage" not in joined
    assert "already done" not in joined


def test_the_count_is_the_true_number_left(acc):
    acc.update_section("Available Options", many(30, 0))
    for _ in range(4):
        app.processEvents()
    shown = len([t for t in texts(acc) if t.startswith("Outstanding thing")])
    line = next(t for t in texts(acc) if "still to do in this stage" in t)
    assert str(30 - shown) in line


def test_something_the_advisor_opened_survives_the_cap(acc):
    """They opened it on purpose. Folding it away under them is worse than
    the scrollbar this is avoiding."""
    checks = many(30, 0)
    last = checks[-1]["id"]
    acc._open.add(last)
    acc.update_section("Available Options", checks)
    for _ in range(4):
        app.processEvents()
    assert f"Outstanding thing number 29" in " ".join(texts(acc))


def test_a_new_stage_starts_from_a_full_budget(acc):
    """A trimmed long stage must not leave the next short one trimmed."""
    acc.update_section("Available Options", many(30, 0))
    for _ in range(4):
        app.processEvents()
    acc._todo_limit = 2                       # as if the panel had wound it down
    acc.update_section("Situation Summary", many(3, 0))
    for _ in range(4):
        app.processEvents()
    assert acc._todo_limit == acc.MAX_TODO_ROWS
    assert len([t for t in texts(acc) if t.startswith("Outstanding thing")]) == 3


# -- the scrollbar ---------------------------------------------------------

def test_the_scrollbar_is_off_while_the_panel_is_moving_and_back_at_rest():
    """Mid-animation the viewport is briefly shorter than the content it is
    about to fit, so a bar appears for a few frames and goes again. On a
    panel that changes shape every time a check goes green that flicker is
    constant, and it is a good part of what reads as the widget blipping.

    At rest it comes back, because it means something there - compliance
    asked for it on 2026-09-15 after a spell with no bar at all.
    """
    from PyQt6.QtCore import Qt
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    p.show_live()
    p._retarget(animate=True)
    assert p._scroll.verticalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    p._settle(p._target_height())
    assert p._scroll.verticalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert p._scroll._scrollable is True


def test_the_panel_bar_is_styled_like_the_summary_cards():
    """Compliance picked the summary card's bar and asked for the same one on
    the checklist: narrow, rounded, no arrow buttons, no track.

    Both are the same widget class, so this is really a guard that the style
    is not quietly dropped or widened - it is the difference between a
    position marker and a control sitting on a 340px panel.
    """
    p = m.ComplianceAlertPanel()
    css = p._scroll.styleSheet()
    assert "width:6px" in css.replace(" ", "")
    assert "border-radius:3px" in css.replace(" ", "")
    # arrows off, track invisible
    assert "add-line:vertical" in css and "height:0" in css.replace(" ", "")
    assert "add-page:vertical" in css
    # and the summary card's list is the very same class, so it matches
    s = m.SummaryScreen()
    assert type(s._list) is type(p._scroll)
    assert s._list.styleSheet() == css
    p.deleteLater()
    s.deleteLater()
    # Stop the height animation before letting go of the panel. _retarget
    # starts it and _settle does not stop it, so without this it keeps
    # ticking against an object being torn down - which took the whole
    # widget suite out with a hard crash, on a test that passed alone.
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_the_idle_screen_can_never_show_a_scrollbar():
    """Reported as still there after the live checklist was fixed. The idle
    page is a status chip, one sentence and three figures - there is nothing
    to scroll, so a bar over it is always wrong.

    The live checklist is a different case and keeps its bar: compliance
    asked for it back on 2026-09-15, styled like the summary card's.
    """
    from PyQt6.QtCore import Qt
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    p.show_idle()
    assert p._scroll.verticalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    # Idle has nothing below the fold, so the wheel is off too.
    assert p._scroll._scrollable is False
    # ...and a call hands BOTH back, because a long stage genuinely needs them.
    p.show_live()
    assert p._scroll.verticalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert p._scroll._scrollable is True
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_the_idle_screen_is_one_compact_block():
    """No decoration that carries nothing.

    There was a 48px ring above "Waiting for a call" - empty, static, never
    referenced again, standing in for an icon from the mockup that was never
    drawn. It read as a spinner that had stopped, and it cost a fifth of the
    panel's height between calls for that. What is left is the four things
    the screen is actually for.
    """
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(6):
        app.processEvents()
    p.show_idle()
    for _ in range(6):
        app.processEvents()

    said = [l.text() for l in p.findChildren(QLabel)
            if l.isVisibleTo(p) and l.text().strip()]
    assert "Waiting for a call" in said
    assert "THIS SHIFT" in said
    assert {"CALLS", "AVERAGE", "FLAGS"} <= set(said)

    # Nothing on it is a bare fixed-size decoration. A label with no text and
    # a hard size is exactly what the ring was.
    empty = [l for l in p.findChildren(QLabel)
             if l.isVisibleTo(p) and not l.text().strip()
             and l.minimumWidth() > 20 and l.minimumHeight() > 20]
    assert empty == [], [l.styleSheet() for l in empty]

    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


# -- the wheel ------------------------------------------------------------

def _spin(scroll, clicks=-5):
    """One flick of the mouse wheel over the panel."""
    from PyQt6.QtCore import Qt, QPoint, QPointF
    from PyQt6.QtGui import QWheelEvent
    ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50),
                     QPoint(0, clicks * 120), QPoint(0, clicks * 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(scroll.viewport(), ev)
    for _ in range(3):
        app.processEvents()


def _panel_with_a_scroll_range():
    """A panel whose contents genuinely do not fit, so the wheel has
    somewhere to go. Without forcing this the test proves nothing: the
    range is zero anyway and every wheel event is a no-op."""
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    p.show_live()
    p._accordion.update_section("Available Options", many(30, 0))
    p._scroll.setMaximumHeight(120)          # brutally short, on purpose
    for _ in range(6):
        app.processEvents()
    return p


def test_the_wheel_does_nothing_on_the_idle_screen():
    """Hiding the bar never stopped the wheel. Hovering the idle panel and
    scrolling slid the COMPLIANCE header off the top of a card that had
    nothing underneath it to reach - which reads as the panel breaking."""
    p = _panel_with_a_scroll_range()
    assert p._scroll.verticalScrollBar().maximum() > 0, "no range to test"
    p.show_idle()
    for _ in range(4):
        app.processEvents()
    _spin(p._scroll)
    assert p._scroll.verticalScrollBar().value() == 0
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_going_idle_scrolls_back_to_the_top():
    """A call that was scrolled must not leave the READY screen halfway
    down itself."""
    p = _panel_with_a_scroll_range()
    p._scroll.verticalScrollBar().setValue(
        p._scroll.verticalScrollBar().maximum())
    assert p._scroll.verticalScrollBar().value() > 0
    p.show_idle()
    for _ in range(4):
        app.processEvents()
    assert p._scroll.verticalScrollBar().value() == 0
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_the_wheel_still_works_during_a_call_that_overflows():
    """The guard must not take scrolling away where it is the honest answer
    to a stage that genuinely does not fit."""
    p = _panel_with_a_scroll_range()
    assert p._scroll._scrollable is True
    before = p._scroll.verticalScrollBar().value()
    _spin(p._scroll, clicks=-5)
    assert p._scroll.verticalScrollBar().value() > before
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_a_wheel_flick_with_nowhere_to_go_is_refused_even_during_a_call():
    """Qt scrolls a range of a couple of pixels - layout rounding, not
    content - and does not stop at zero either."""
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    p.show_live()
    p._accordion.update_section("Situation Summary", many(2, 0))
    # Let the panel take its content's height, which is the condition that
    # actually holds in the app. A bare panel that has never retargeted sits
    # at whatever height it was born with and has a range for that reason
    # alone - which is the test's setup showing, not the app's behaviour.
    p._retarget(animate=False)
    for _ in range(6):
        app.processEvents()
    assert p._scroll.verticalScrollBar().maximum() == 0, "no range to refuse"
    _spin(p._scroll)
    assert p._scroll.verticalScrollBar().value() == 0
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_the_shift_tiles_are_not_crammed_against_the_bottom_edge():
    """They are the last thing on the idle page and they sit on a tinted
    panel of their own, so the card's edge right underneath them reads as
    the screen being cut off rather than finished.

    Geometry, not text, so the offscreen platform's missing fonts cannot
    make this lie: margins are the same width whatever typeface is loaded.
    """
    from PyQt6.QtWidgets import QFrame
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(6):
        app.processEvents()
    p.show_idle()
    for _ in range(8):
        app.processEvents()

    tiles = [t for t in p.findChildren(QFrame)
             if t.objectName() == "tile" and t.isVisibleTo(p)]
    assert len(tiles) == 3, "CALLS, AVERAGE and FLAGS"
    lowest = max(t.mapTo(p, t.rect().bottomLeft()).y() for t in tiles)
    assert p.height() - lowest >= 45, (
        f"only {p.height() - lowest}px under the shift tiles")

    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_the_checklist_does_not_waste_away_during_a_stage():
    """It used to. A pass wound the row caps down whenever the content was
    briefly taller than the panel's ceiling, and nothing ever put a row
    back until the stage turned over - so a few minutes in, Onboarding was
    one outstanding row, two "N more" lines and half an empty card.

    The things that make it briefly taller are ordinary and constant: a
    check goes green and gains the advisor's quote, a dropdown opens, a
    prompt wraps. Each one took a row away for good.

    It was removed rather than made two-way, because it was not worth
    having: measured, going from nine rows to one shrinks the accordion by
    193px and the PANEL by 15px. The panel's height comes from the header,
    the stage tracker and the due card, none of which a row cap touches.
    """
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    p.show_live()

    seen = []
    for done in (0, 1, 3, 5, 8):
        p._accordion.update_section("Onboarding", many(9 - done, done))
        for _ in range(4):
            app.processEvents()
        seen.append((p._accordion._todo_limit, p._accordion._done_limit))

    assert len(set(seen)) == 1, f"the caps drifted as the stage went on: {seen}"
    assert seen[0] == (m.SectionAccordion.MAX_TODO_ROWS,
                       m.SectionAccordion.MAX_DONE_ROWS)

    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_nothing_winds_the_row_caps_up_and_down_per_render():
    """The mechanism itself is gone, not just disabled."""
    assert not hasattr(m.ComplianceAlertPanel, "_fit_rows")


# -- vulnerability follow-ups shown early ---------------------------------

def urgent_check(cid, label):
    c = check(cid, label)
    c["urgent"] = True
    c["urgent_reason"] = "A vulnerability has been disclosed - ask these now"
    c["section_label"] = "Vulnerability"
    return c


def test_disclosure_follow_ups_are_captioned_not_just_dropped_in(acc):
    """A Vulnerability question appearing in the middle of Fact Find with
    no explanation reads as the checklist losing its place."""
    acc.update_section("Fact Find",
                       [urgent_check("v1", "Q1 - Repayment impact")]
                       + many(5, 0))
    for _ in range(4):
        app.processEvents()
    joined = " ".join(texts(acc)).lower()
    assert "vulnerability has been disclosed" in joined


def test_they_come_before_the_ordinary_outstanding_work(acc):
    """This is the conversation the advisor is having right now."""
    acc.update_section("Fact Find",
                       many(5, 0)
                       + [urgent_check("v1", "Q1 - Repayment impact")])
    for _ in range(4):
        app.processEvents()
    shown = texts(acc)
    assert shown.index("Q1 - Repayment impact") < \
        shown.index("Outstanding thing number 0")


def test_an_urgent_row_is_never_summarised_away_by_the_cap(acc):
    """The cap exists to stop the panel overflowing. Using it to hide a
    safeguarding question a customer just prompted would be the panel
    deciding which one the advisor gets to skip."""
    urgents = [urgent_check(f"v{i}", f"Q{i} - vulnerability follow-up")
               for i in range(8)]
    acc.update_section("Fact Find", urgents + many(20, 0))
    for _ in range(4):
        app.processEvents()
    shown = " ".join(texts(acc))
    for u in urgents:
        assert u["label"] in shown, u["label"]


def test_the_count_of_what_is_hidden_ignores_the_urgent_ones(acc):
    """They were never in the running to be hidden, so counting them would
    overstate what is left."""
    acc.update_section("Fact Find",
                       [urgent_check("v1", "Q1 - Repayment impact")]
                       + many(20, 0))
    for _ in range(4):
        app.processEvents()
    line = next(t for t in texts(acc) if "still to do in this stage" in t)
    shown_ordinary = len([t for t in texts(acc)
                          if t.startswith("Outstanding thing")])
    assert str(20 - shown_ordinary) in line


def test_a_disclosure_arriving_actually_redraws_the_panel(acc):
    """The panel skips the rebuild when its signature matches. Urgency
    changes nothing else about a check, so if it is not in the signature
    eight questions become due and the screen carries on as before."""
    plain = many(3, 0)
    acc.update_section("Fact Find", plain)
    for _ in range(4):
        app.processEvents()
    before = " ".join(texts(acc))
    now_urgent = [dict(c, urgent=True,
                       urgent_reason="A vulnerability has been disclosed - "
                                     "ask these now",
                       section_label="Vulnerability") for c in plain]
    acc.update_section("Fact Find", now_urgent)
    for _ in range(4):
        app.processEvents()
    assert " ".join(texts(acc)) != before


def test_a_part_being_retired_also_redraws(acc):
    """Same trap, and it would have quietly undone the n/a fix: a
    customer's "no" changes only each part's `na` flag."""
    plain = check("x", "Something", parts=["one", "two", "three"])
    acc.update_section("Fact Find", [plain])
    for _ in range(4):
        app.processEvents()
    before = tally(acc)
    retired = check("x", "Something", parts=["one", "two", "three"], na_from=1)
    acc.update_section("Fact Find", [retired])
    for _ in range(4):
        app.processEvents()
    assert tally(acc) != before, "the panel never redrew"
    assert tally(acc) == ["0/1"]


def test_the_window_changes_width_in_one_step_not_two():
    """Bilal, 2026-09-15: the moment the red safety card opened its column,
    the checklist beside it came out chopped and "fixed itself after a while".

    That is move() then resize() - two separate geometry changes. Qt lays the
    children out against the first one before the second arrives, so for one
    frame the checklist is laid out at the old width; the queued layout pass
    is the "after a while". One setGeometry cannot produce that frame.

    Driven through a stand-in window that records what it was asked to do,
    because the fault is the NUMBER of calls, not the final size - and the
    final size is identical either way, which is why this went unnoticed.
    """
    from PyQt6.QtCore import QRect

    class FakeLayout:
        def __init__(self):
            self.activated = 0

        def activate(self):
            self.activated += 1

    class FakeWindow:
        """Wide enough to need shrinking, so the width branch is taken."""

        def __init__(self):
            self.calls = []
            self._lay = FakeLayout()
            self._geo = QRect(500, 100, 900, 600)

        def isVisible(self):
            return True

        def screen(self):
            return None

        def layout(self):
            return self._lay

        def x(self):
            return self._geo.x()

        def y(self):
            return self._geo.y()

        def width(self):
            return self._geo.width()

        def height(self):
            return self._geo.height()

        def sizeHint(self):
            from PyQt6.QtCore import QSize
            return QSize(640, 600)

        def minimumWidth(self):
            return 0

        def minimumHeight(self):
            return 0

        def move(self, *a):
            self.calls.append("move")

        def resize(self, *a):
            self.calls.append("resize")

        def setGeometry(self, x, y, w, h):
            self.calls.append("setGeometry")
            self._geo = QRect(x, y, w, h)

    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    fake = FakeWindow()
    p.window = lambda: fake
    p._sync_window()

    assert "setGeometry" in fake.calls, "the width branch never ran"
    assert "move" not in fake.calls and "resize" not in fake.calls, (
        "width and position must land together, not as two changes: "
        f"{fake.calls}")
    # ...and the children are laid out at the new width in the same pass,
    # rather than one paint later.
    assert fake._lay.activated >= 1
    # the window still ends up the right size - the fix is the how, not the what
    assert fake.width() == 640
    # and it grew leftward, keeping the call card where the advisor left it
    assert fake.x() == 500 + (900 - 640)

    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


# -- opening a disclosure must not move the window -------------------------

STAGE = [{"key": "INTRODUCTION", "label": "Onboarding"}]


def settle(p, spins=60):
    """Land the panel on its target height, deterministically.

    Two ways to get this wrong, and this file has now had both.

    A fixed handful of processEvents() calls reads the height MID-ANIMATION,
    so two arbitrary points on the same easing curve compare equal often
    enough to pass - that is how the first version of these tests went green
    against a panel that was still visibly stretching.

    Looping on wall-clock time until the height stopped changing fixed that
    and broke something worse: spinning the event loop for a second at a time
    also runs every other test file's leftover timers and half-torn-down
    widgets, and the whole suite stopped dead. Alone this file passed in 9s;
    with the rest it never finished.

    So: pump a BOUNDED number of turns, which is enough for the queued
    retarget to fire, then finish the animation directly. The assertions here
    are about the target the panel chooses, not about the easing.
    """
    for _ in range(spins):
        app.processEvents()
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p._retarget(animate=False)
    for _ in range(5):
        app.processEvents()
    return p._scroll.height()


def _panel_with_parts():
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    p.show_live()
    checks = [check(f"c{i}", f"Requirement number {i}",
                    parts=[f"part {i}.{j}" for j in range(4)])
              for i in range(6)]
    p.update_stage("Onboarding", STAGE, checks)
    settle(p)
    return p, checks


def _stop(p):
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()


def test_opening_a_check_does_not_resize_the_panel():
    """Bilal, 2026-09-15: the widget grew every time he opened a sub-list, so
    Stop Recording moved while he was reading. The parts open INSIDE the
    height the panel already has.
    """
    p, checks = _panel_with_parts()
    before = p._scroll.height()
    assert before > 0
    p._accordion._toggle("c0")
    settle(p)
    assert p._scroll.height() == before, (
        f"the panel resized on a toggle: {before} -> {p._scroll.height()}")
    _stop(p)


def test_new_data_may_still_resize_the_panel():
    """The guard that stops the fix being written too wide. A new stage with
    a different number of rows is not the advisor's hand on the panel, and
    gliding to fit it is the behaviour that was always wanted.
    """
    p, checks = _panel_with_parts()
    sig = []
    p._accordion.contents_changed.connect(lambda ok: sig.append(ok))
    p._accordion._toggle("c0")
    for _ in range(4):
        app.processEvents()
    assert sig == [False], f"a toggle must not license a resize: {sig}"
    sig.clear()
    p.update_stage("Fact Find", [{"key": "FACT_FIND", "label": "Fact Find"}],
                   [check("f0", "A different requirement")])
    for _ in range(4):
        app.processEvents()
    assert sig == [True], f"new data must license a resize: {sig}"
    _stop(p)


def test_the_check_the_advisor_opened_is_scrolled_into_view():
    """Growing was solving a real problem - the parts opened below the fold
    and only appeared if the advisor thought to scroll. Removing the growth
    without this would put that back.
    """
    p, checks = _panel_with_parts()
    last = checks[-1]["id"]
    p._accordion._toggle(last)
    settle(p)
    # the accordion hands the id over exactly once, and the panel takes it
    assert p._accordion._just_opened is None, (
        "the panel never collected the opened check")
    row = p._accordion._row_by_id.get(last)
    assert row is not None, "the opened row is not in the render"
    # it is inside the viewport, not below it
    top = row.mapTo(p._scroll.viewport(), row.rect().topLeft()).y()
    assert top < p._scroll.viewport().height(), (
        f"the opened check is below the fold at y={top}")
    _stop(p)


def test_closing_a_check_does_not_yank_the_view():
    """Nothing above it moved, so taking the view somewhere would be the
    panel deciding for the advisor."""
    p, checks = _panel_with_parts()
    p._accordion._toggle("c0")
    settle(p)
    p._accordion._toggle("c0")          # close it again
    settle(p)
    assert p._accordion._just_opened is None
    _stop(p)


def test_the_panel_stays_put_through_the_servers_next_tick():
    """The one the first attempt missed, and the reason it shipped broken.

    Suppressing the animated retarget on a toggle is not enough. The server
    resends the checklist about twice a second, and every one of those runs
    show_live -> _sync_window -> _retarget(animate=False), which re-measured
    the contents and grew the window about half a second AFTER the toggle.
    A test that only toggled could never see it.
    """
    p, checks = _panel_with_parts()
    p._accordion._toggle("c0")
    after_toggle = settle(p)

    # ...now the server says exactly what it said before, four times over
    for _ in range(4):
        p.update_stage("Onboarding", STAGE, checks)
        p._sync_window()
        settle(p, 250)
    assert p._scroll.height() == after_toggle, (
        f"the server tick resized it: {after_toggle} -> {p._scroll.height()}")
    _stop(p)


def test_a_check_going_green_does_not_jump_an_open_list():
    """Genuinely new data, but resizing under an open disclosure looks
    exactly like the bug it is not."""
    p, checks = _panel_with_parts()
    p._accordion._toggle("c0")
    held = settle(p)
    greened = [dict(c) for c in checks]
    greened[3]["done"] = True
    p.update_stage("Onboarding", STAGE, greened)
    settle(p)
    assert p._scroll.height() == held
    _stop(p)


def test_an_id_opened_in_an_earlier_stage_does_not_pin_the_rest_of_the_call():
    """_open keeps ids across a stage change, so "is anything open" has to
    mean "in THIS render" or the panel freezes at one height for good."""
    p, checks = _panel_with_parts()
    p._accordion._toggle("c0")
    settle(p)
    p.update_stage("Fact Find", [{"key": "FACT_FIND", "label": "Fact Find"}],
                   [check("f0", "A different requirement")])
    settle(p)
    assert "c0" in p._accordion._open, "the set genuinely still holds it"
    assert p._accordion.has_open() is False
    assert p._pinned_height is None
    _stop(p)


# -- the scroll handle is the same length everywhere -----------------------

def _handle_px(scroll):
    """The handle rectangle the style actually draws.

    Not the stylesheet: reading that only proves what we ASKED Qt for, and
    the first attempt at this asked with `max-height`, which Qt ignores on a
    scrollbar subcontrol. Twenty rows still drew a 143px handle and the
    stylesheet looked correct the whole time.
    """
    from PyQt6.QtWidgets import QStyle, QStyleOptionSlider
    bar = scroll.verticalScrollBar()
    opt = QStyleOptionSlider()
    opt.initFrom(bar)
    opt.orientation = bar.orientation()
    opt.minimum, opt.maximum = bar.minimum(), bar.maximum()
    opt.sliderPosition = bar.value()
    opt.sliderValue = bar.value()
    opt.pageStep = bar.pageStep()
    opt.singleStep = bar.singleStep()
    return bar.style().subControlRect(
        QStyle.ComplexControl.CC_ScrollBar, opt,
        QStyle.SubControl.SC_ScrollBarSlider, bar).height()


def _scroller(rows, height=300):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    s = m._PanelScroll()
    s.resize(340, height)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(0, 0, 0, 0)
    for i in range(rows):
        lab = QLabel(f"Requirement number {i}")
        lab.setFixedHeight(24)
        lay.addWidget(lab)
    s.setWidget(inner)
    s.move(-3000, -3000)
    s.show()
    for _ in range(30):
        app.processEvents()
    return s


def test_the_scroll_handle_is_the_same_length_whatever_it_holds():
    """Bilal: the checklist's bar is much longer than the summary card's.

    It was, and correctly so - Qt sizes the handle as the share of content
    that fits, and the summary card holds 113 finished checks where a stage
    holds nine. Same stylesheet, two completely different-looking controls.
    Pinned now, so every scroller in the widget matches.
    """
    want = m._PanelScroll.HANDLE_H
    seen = []
    for rows in (20, 120, 400):
        s = _scroller(rows)
        assert s.verticalScrollBar().maximum() > 0, (
            f"{rows} rows did not overflow, so there is no handle to measure")
        seen.append(_handle_px(s))
        s.hide()
        s.deleteLater()
    assert seen == [want, want, want], (
        f"handle lengths differ by content: {seen}, wanted {want}")


def test_a_taller_panel_still_gets_the_same_handle():
    """The pin is recomputed from the track, so a different panel height must
    not change the handle - the summary card is 300px and a stage can be 600.
    """
    want = m._PanelScroll.HANDLE_H
    a = _scroller(200, height=300)
    b = _scroller(200, height=600)
    assert _handle_px(a) == want
    assert _handle_px(b) == want
    for s in (a, b):
        s.hide()
        s.deleteLater()


def test_pinning_the_handle_does_not_break_scrolling():
    """pageStep is the lever, and pageStep is also how far a track click
    jumps - so check the thing that matters is untouched: the full content is
    still reachable, and the wheel still moves in singleSteps.
    """
    s = _scroller(200)
    bar = s.verticalScrollBar()
    top = bar.value()
    bar.setValue(bar.maximum())
    assert bar.value() == bar.maximum(), "the bottom must still be reachable"
    assert bar.maximum() > top
    assert bar.singleStep() > 0
    s.hide()
    s.deleteLater()


# -- the pin must not survive the call it was taken in ---------------------

def test_the_idle_page_is_no_taller_than_what_it_holds():
    """The thing the advisor actually saw. A panel taller than its rows is
    what stretched the pill, so measure the gap rather than the pill.
    """
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(6):
        app.processEvents()
    p.show_idle()
    settle(p)
    inner = p._scroll.widget()
    assert inner is not None
    slack = p._scroll.height() - inner.sizeHint().height()
    assert slack <= 4, (
        f"the idle panel is {slack}px taller than its contents, so the "
        f"layout has spare space to stretch things into")
    _stop(p)


# -- one height for the whole call ----------------------------------------

def test_the_panel_is_one_height_for_the_whole_call():
    """Every resize complaint on this panel came from the height chasing the
    content: the window stretched when a check was opened, the idle page
    spread four rows down a tall card, a stage scrolled with empty screen
    below it. Pinning fixed the first two and caused the third.

    A panel that is simply always as tall as the screen allows has nothing
    left to get wrong, so this asserts the one rule that replaced all of it.
    """
    p, checks = _panel_with_parts()
    start = p._scroll.height()
    assert start > 0

    p._accordion._toggle("c0")                      # open a disclosure
    settle(p)
    assert p._scroll.height() == start

    greened = [dict(c) for c in checks]
    greened[2]["done"] = True                       # a check goes green
    p.update_stage("Onboarding", STAGE, greened)
    settle(p)
    assert p._scroll.height() == start

    p.update_stage("Fact Find",                     # a whole new stage
                   [{"key": "FACT_FIND", "label": "Fact Find"}],
                   [check(f"f{i}", f"Another requirement {i}")
                    for i in range(14)])
    settle(p)
    assert p._scroll.height() == start, "a longer stage resized the panel"
    _stop(p)


def test_the_idle_page_keeps_its_own_small_height():
    """Four rows do not want a full-height card, which is what turned the
    READY pill into a green block down the side of the panel."""
    p, checks = _panel_with_parts()
    live = p._scroll.height()
    p.show_idle()
    settle(p)
    assert p._scroll.height() < live
    inner = p._scroll.widget()
    assert p._scroll.height() - inner.sizeHint().height() <= 4
    _stop(p)


# -- what was left behind is still reachable ------------------------------

LEFT = [
    {"id": "cc.totals", "label": "Summary - Totals stated",
     "section_label": "Creditor Check", "severity": "high"},
    {"id": "cc.pref", "label": "Wrap-up - Preferential payments",
     "section_label": "Creditor Check", "severity": "high"},
    {"id": "vuln.q7", "label": "Q7 - Support network",
     "section_label": "Vulnerability", "severity": "high"},
]


def _still(rows=LEFT):
    w = m.StillToDo()
    w.move(-3000, -3000)
    w.show()
    w.set_rows(rows)
    for _ in range(6):
        app.processEvents()
    return w


def test_nothing_left_behind_means_no_list_at_all():
    """A panel that shows an empty box is a panel saying something untrue."""
    w = _still([])
    assert not w.isVisible()
    assert w.count() == 0
    w.deleteLater()


def test_the_list_says_how_many_and_stays_shut():
    """An advisor mid-call is reading the stage they are in. A list that
    opened itself would push that stage off the screen."""
    w = _still()
    assert w.isVisible()
    assert "3" in w._toggle.text()
    assert not w._body.isVisible(), "it must start collapsed"
    w.deleteLater()


def test_opening_it_shows_every_stage_it_came_from():
    """One list for the whole call - compliance: "a single dropdown covering
    all sections, not a separate dropdown for each" - so each row has to say
    which stage it belongs to or the advisor cannot go back to it."""
    w = _still()
    w._flip()
    for _ in range(6):
        app.processEvents()
    assert w._body.isVisible()
    shown = " ".join(texts(w))
    # Title case, not shouted: these name a stage to go back to, so they
    # read as headings rather than as the faint captions they started as.
    assert "Creditor Check" in shown and "Vulnerability" in shown
    assert "Summary - Totals stated" in shown
    assert "Q7 - Support network" in shown
    w.deleteLater()


def test_a_long_stage_is_summarised_rather_than_endless():
    w = _still([{"id": f"x{i}", "label": f"Requirement number {i}",
                 "section_label": "Available Options", "severity": "high"}
                for i in range(11)])
    w._flip()
    for _ in range(6):
        app.processEvents()
    shown = texts(w)
    rows = [t for t in shown if t.startswith("Requirement number")]
    assert len(rows) == m.StillToDo.MAX_PER_SECTION
    assert any("more in this stage" in t for t in shown)
    w.deleteLater()


def test_the_same_rows_again_do_not_rebuild_it():
    """The server sends this twice a second. Rebuilding on every message is
    what the panel's flicker has always been."""
    w = _still()
    w._flip()
    for _ in range(4):
        app.processEvents()
    before = [w._body_lay.itemAt(i).widget() for i in range(w._body_lay.count())]
    w.set_rows(list(LEFT))
    after = [w._body_lay.itemAt(i).widget() for i in range(w._body_lay.count())]
    assert before == after, "identical rows rebuilt the list"
    w.deleteLater()


def test_the_panel_passes_the_list_through():
    p, checks = _panel_with_parts()
    p.set_still_to_do(LEFT)
    settle(p)
    assert p._still.count() == 3
    assert p._still.isVisible()
    # ...and going idle between calls clears it
    p.show_idle()
    settle(p)
    assert p._still.count() == 0
    _stop(p)


def test_a_short_stage_does_not_stretch_its_own_rows():
    """The panel is always as tall as the screen allows, and a QVBoxLayout
    with no stretch shares spare height out among its children - which blew
    the count badge into a purple column down the side of the card and left
    the heading floating in an empty panel.

    One stretch at the end takes the slack instead, so every row keeps the
    height it asked for.
    """
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(6):
        app.processEvents()
    p.show_live()
    p.update_stage("Onboarding", STAGE, [check("c0", "One short thing")])
    settle(p)
    # the count badge must be its own size, not a column
    badge = p._count
    assert badge.height() <= badge.sizeHint().height() + 2, (
        f"the badge stretched to {badge.height()}px against a natural "
        f"{badge.sizeHint().height()}px")
    assert p._heading.height() <= p._heading.sizeHint().height() + 2
    _stop(p)


# -- a long check opens up into the parts that are missing ----------------

MULTI = [
    {"id": "cc.missing_debts", "label": "Step 6 - Missing-debts checklist",
     "section_label": "Creditor Check", "severity": "high",
     "missing_parts": ["car finance or HP", "catalogues",
                       "payday or short-term loans", "council tax arrears"]},
    {"id": "cc.pref", "label": "Wrap-up - Preferential payments",
     "section_label": "Creditor Check", "severity": "high",
     "missing_parts": []},
]


def test_a_one_line_row_stays_one_line():
    """Most rows are a single requirement. Nothing to open, nothing to hint
    at - an arrow on every line would say there is more behind all of them."""
    w = _still(MULTI)
    w._flip()
    for _ in range(6):
        app.processEvents()
    shown = texts(w)
    assert "Wrap-up - Preferential payments" in shown
    # the open circle, not the closed-arrow marker
    assert "\u25cb" in shown
    w.deleteLater()


def test_a_multi_part_check_opens_up_into_its_parts():
    """Bilal, 16 Sep: "if advisor misses something from a long checklist, for
    example additional debt, advisor will not be able to understand from the
    still to do list which exactly point was missed".

    "Step 6 - Missing-debts checklist" is one line here and twelve questions
    in the rulebook. The parts were in the payload all along and the widget
    threw them away.
    """
    w = _still(MULTI)
    w._flip()
    for _ in range(6):
        app.processEvents()
    shut = texts(w)
    assert "Step 6 - Missing-debts checklist" in shut
    assert not any("catalogues" in t for t in shut), \
        "it must start closed - four parts on every row is the old wall of text"
    # the count is on the row, so the advisor knows there is something behind it
    assert "4" in shut

    w._flip_row("cc.missing_debts")
    for _ in range(6):
        app.processEvents()
    opened = " ".join(texts(w))
    for part in MULTI[0]["missing_parts"]:
        assert part in opened, f"missing part not shown: {part}"

    w._flip_row("cc.missing_debts")
    for _ in range(6):
        app.processEvents()
    assert not any("catalogues" in t for t in texts(w)), "it must close again"
    w.deleteLater()


def test_an_opened_row_survives_the_next_message_from_the_server():
    """The server speaks every 25 seconds. A row that shut itself each time
    would be unreadable - the advisor opens it, reads one line, loses it."""
    w = _still(MULTI)
    w._flip()
    w._flip_row("cc.missing_debts")
    for _ in range(6):
        app.processEvents()
    assert any("catalogues" in t for t in texts(w))

    w.set_rows([dict(r) for r in MULTI])       # same content, sent again
    for _ in range(6):
        app.processEvents()
    assert any("catalogues" in t for t in texts(w)), "the row shut itself"
    w.deleteLater()


def test_a_part_that_gets_done_leaves_the_row():
    """Keyed on ids alone the list looked unchanged while the advisor worked
    through the twelve categories one at a time, so it never redrew and the
    parts they had since covered stayed on it."""
    w = _still(MULTI)
    w._flip()
    w._flip_row("cc.missing_debts")
    for _ in range(6):
        app.processEvents()
    assert any("catalogues" in t for t in texts(w))

    fewer = [dict(MULTI[0], missing_parts=["car finance or HP"]), MULTI[1]]
    w.set_rows(fewer)
    for _ in range(6):
        app.processEvents()
    shown = texts(w)
    assert not any("catalogues" in t for t in shown), \
        "a part the advisor has since covered is still on the list"
    assert any("car finance or HP" in t for t in shown)
    w.deleteLater()
