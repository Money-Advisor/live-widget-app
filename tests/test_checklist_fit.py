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

def test_the_scrollbar_is_off_in_every_state_including_mid_animation():
    """The bar is gone for good, not just while the panel is moving.

    It used to come back the moment the panel settled, and that is what
    Bilal kept reporting - four separate call sites handed it back. The
    panel now refuses the setting outright, so this asserts the state the
    old test asserted the opposite of: still off after it settles.
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
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    # ...and asking for it back does nothing, which is the point: a fifth
    # call site cannot reintroduce it.
    p._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    assert p._scroll.verticalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    # Losing the bar must not lose the scrolling - a long stage still has to
    # be reachable with the wheel.
    assert p._scroll._scrollable is True
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
    to scroll, so a bar over it is always wrong."""
    from PyQt6.QtCore import Qt
    p = m.ComplianceAlertPanel()
    p.move(-3000, -3000)
    p.show()
    for _ in range(4):
        app.processEvents()
    p.show_idle()
    assert p._scroll.verticalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    # Idle has nothing below the fold, so the wheel is off too and the
    # "more below" fade must not be showing.
    assert p._scroll._scrollable is False
    assert not p._scroll._fade.isVisible()
    # ...and a call hands the WHEEL back, because a long stage genuinely needs
    # it. The bar itself never comes back in any state.
    p.show_live()
    assert p._scroll.verticalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
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


def settle(p, ms=1200):
    """Spin until the growth animation has finished and the height holds.

    A fixed number of processEvents() calls is not enough and gives a
    MID-ANIMATION reading, which is how the first version of these tests
    managed to compare two arbitrary points on the same curve and pass.
    """
    import time
    end = time.time() + ms / 1000
    last, stable = None, 0
    while time.time() < end:
        app.processEvents()
        h = p._scroll.height()
        stable = stable + 1 if h == last else 0
        last = h
        if stable > 40:
            break
        time.sleep(0.005)
    return last


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


def test_closing_everything_lets_the_panel_fit_itself_again():
    """The pin is not permanent - it is released the moment the advisor has
    nothing open, or the panel would be stuck at one height all call."""
    p, checks = _panel_with_parts()
    natural = p._scroll.height()
    p._accordion._toggle("c0")
    settle(p)
    assert p._pinned_height, "opening must pin the height"
    p._accordion._toggle("c0")          # close it again
    settle(p)
    assert p._pinned_height is None, "closing must release the pin"
    assert p._scroll.height() == natural
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
