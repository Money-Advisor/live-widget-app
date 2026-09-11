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

def test_the_scrollbar_is_off_while_the_panel_is_moving():
    """Mid-animation the viewport is briefly shorter than the content it is
    about to fit, so a bar appears for a few frames and goes again. On a
    panel that changes shape every time a check goes green, that flicker is
    constant - and it is a good part of what reads as the widget blipping."""
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
    # Stop the height animation before letting go of the panel. _retarget
    # starts it and _settle does not stop it, so without this it keeps
    # ticking against an object being torn down - which took the whole
    # widget suite out with a hard crash, on a test that passed alone.
    anim = getattr(p, "_grow", None)
    if anim is not None:
        anim.stop()
    p.hide()
    p.deleteLater()
