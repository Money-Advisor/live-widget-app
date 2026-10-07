# -*- coding: utf-8 -*-
"""The live I&E column draws what the server sends, and touches nothing else.

Every message here is built by the server's own code (ie_panel.Ledger and
panel_payload), not typed by hand, so a change to either side that breaks the
other fails here - the same arrangement as test_cat_card.py.

The other half of "touches nothing else" - the three existing columns are
pixel-identical with this build - is proved by scripts/prove_panels_unchanged.py,
which renders the committed build and this one side by side.
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
import ie_panel as P                                           # noqa: E402

E = "expenditure"


def ledger(stage="income"):
    L = P.Ledger()
    L.apply([
        {"kind": "household", "partner": False, "quote": "q"},
        {"kind": "child", "age": 7, "lives": "full_time", "quote": "q"},
        {"kind": "child", "age": 12, "lives": "full_time", "quote": "q"},
        {"kind": "vehicle", "ownership": "owned", "description": "car", "quote": "q"},
        {"kind": "vehicle", "ownership": "owned", "description": "van", "quote": "q"},
        {"kind": "affordability", "amount": 100, "quote": "q"},
        {"kind": "figure", "side": "income", "group": "earnings", "item": "wages",
         "amount": 1500, "quote": "q"},
        {"kind": "figure", "side": "income", "group": "benefits", "item": "universal_credit",
         "amount": 400, "quote": "q"},
    ])
    if stage != "income":
        L.apply([
            {"kind": "figure", "side": E, "group": "home_and_contents", "item": "rent",
             "amount": 700, "quote": "q"},
            {"kind": "figure", "side": E, "group": "home_and_contents", "item": "tv_licence",
             "amount": 0, "quote": "q"},
            {"kind": "figure", "side": E, "group": "food_and_housekeeping",
             "item": "groceries", "amount": 300, "quote": "q"},
            {"kind": "figure", "side": E, "group": "food_and_housekeeping",
             "item": "smoking_products", "amount": 20, "period": "weekly", "quote": "q"},
            {"kind": "alternatives", "side": E, "group": "communications_and_leisure",
             "item": "hobbies_leisure_sport", "amount": 80, "amount_high": 100, "quote": "q"},
            {"kind": "yes_to_advisor", "side": E, "group": "personal_costs",
             "item": "clothing_and_footwear", "amount": 40, "quote": "q"},
        ])
    return L


def payload(L, view="income", solutions=False, visible=True):
    return dict(P.panel_payload(L, visible, view, solutions), audio_ts=None)


def pump(n=8, ms=0):
    from PyQt6.QtCore import QEventLoop, QTimer
    for _ in range(n):
        app.processEvents()
    if ms:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
        for _ in range(n):
            app.processEvents()


@pytest.fixture
def win():
    w = m.MainWindow()
    w._stack.setCurrentWidget(w._page_main)
    w.move(100, 40)
    w.show()
    # The checklist column resizes the window on deferred timers; measure
    # only once it has settled, or its move reads as this column's.
    pump(ms=800)
    w._recording = True
    yield w
    w._recording = False
    w.hide()
    w.deleteLater()
    pump()


def texts(widget):
    return [lab.text() for lab in widget.findChildren(QLabel) if lab.text()]


# ── appearing and going ──────────────────────────────────────────────────────

def test_the_column_is_hidden_until_the_server_says_otherwise(win):
    assert not win._ie_panel.isVisible()
    width = win.width()
    win._handle_server_message(payload(P.Ledger(), visible=False))
    pump()
    assert not win._ie_panel.isVisible() and win.width() == width


def test_it_appears_to_the_right_and_the_window_grows_by_exactly_the_column(win):
    x, width = win.x(), win.width()
    card_x = win._front_card.mapToGlobal(win._front_card.rect().topLeft()).x()
    win._handle_server_message(payload(ledger()))
    pump()
    assert win._ie_panel.isVisible()
    assert win.width() == width + m.IEPanel.WIDTH + 6
    # The call card does not move.
    assert win._front_card.mapToGlobal(win._front_card.rect().topLeft()).x() == card_x
    assert win.x() == x
    assert win._ie_panel.x() > win._front_card.x()


def test_the_end_of_the_call_gives_the_width_back(win):
    x, width = win.x(), win.width()
    win._handle_server_message(payload(ledger()))
    pump()
    win._reset_ie_panel()
    pump()
    assert not win._ie_panel.isVisible()
    assert (win.x(), win.width()) == (x, width)


# A 1920px monitor, the window's real widths: 1082 with the checklist and
# alerts showing, 1428 with this column too.
@pytest.mark.parametrize("x,right,want_x,shift", [
    (300, 1920, 300, 0),     # room to the right: nothing moves
    (838, 1920, 492, 346),   # flush to the right edge: slides left by the column
    (600, 1920, 492, 108),   # partly: only as far as it must
    # A 1366px laptop, window already hanging off the LEFT edge and now too
    # wide for the screen: it must stay put, never be pushed right - the
    # first version moved it to 0 and the card moved with it (143px).
    (-50, 1366, -50, 0),
    (20, 1366, 0, 20),       # on screen but too wide: left edge to the screen's
])
def test_the_window_only_ever_slides_left_and_only_as_far_as_it_must(x, right, want_x, shift):
    nx, sh = m.MainWindow._ie_column_x(x, 1428, True, 0, 0, right)
    assert (nx, sh) == (want_x, shift)
    assert nx <= x
    assert m.MainWindow._ie_column_x(nx, 1082, False, sh, 0, right) == (x, 0)


def test_a_message_after_the_call_has_stopped_is_ignored(win):
    win._recording = False
    win._handle_server_message(payload(ledger()))
    pump()
    assert not win._ie_panel.isVisible()


def test_the_column_never_makes_the_window_taller(win):
    """The checklist resizes the window to the row's height on every message
    (twice a second on a live call). If this column asked for its content's
    height, ~70 open rows would grow the window and stretch the call card."""
    win._compliance_panel._sync_window()
    pump(ms=300)
    height = win.height()
    win._handle_server_message(payload(ledger("exp"), view="expenditure"))
    pump()
    for key in [f"exp.{g[0]}" for g in P.EXPENDITURE]:
        win._ie_panel.toggle_group(key)          # every group open: ~70 rows
    pump()
    win._compliance_panel._sync_window()         # what the next message does
    pump(ms=300)
    assert win.height() == height


# ── what it shows ───────────────────────────────────────────────────────────

def panel(view="income", solutions=False, stage=None):
    p = m.IEPanel()
    p.apply(payload(ledger(stage or view), view=view, solutions=solutions))
    p.resize(340, 900)
    p.show()
    pump()
    return p


def test_the_top_block_holds_household_vehicles_and_affordability():
    t = texts(panel())
    for want in ("Household", "1 adult, children aged 7 and 12", "Vehicles", "2",
                 "Client affordability", "£100"):
        assert want in t


def test_the_income_view_shows_only_the_sources_given():
    t = texts(panel())
    assert "Wages (take-home)" in t and "Universal Credit" in t
    assert "Housing Benefit" not in t and "State pension" not in t
    assert "Total outgoings" not in t


def test_the_expenditure_view_has_every_group_closed_and_income_one_click_away():
    p = panel("expenditure")
    t = texts(p)
    assert "Total outgoings" in t and "Income" in t
    heads = [lab for lab in p.findChildren(m._IEElide)]
    names = {lab._full for lab in heads}
    assert {g[1] for g in P.EXPENDITURE} <= names
    assert "Rent" not in names                    # closed until opened (answer 3)


def test_opening_a_group_shows_every_item_and_stays_open_through_an_update():
    p = panel("expenditure")
    p.toggle_group("exp.home_and_contents")
    pump()
    names = {lab._full for lab in p.findChildren(m._IEElide)}
    assert {"Rent", "Mortgage", "TV licence", "Other costs"} <= names
    L = ledger("exp")
    L.apply([{"kind": "figure", "side": E, "group": "water", "item": "water_supply",
              "amount": 31, "quote": "q"}])
    p.apply(payload(L, view="expenditure"))
    pump()
    assert "Rent" in {lab._full for lab in p.findChildren(m._IEElide)}


def test_a_genuine_zero_reads_zero_and_an_unmentioned_item_a_dash():
    p = panel("expenditure")
    p.toggle_group("exp.home_and_contents")
    pump()
    t = texts(p)
    assert "£0" in t and "—" in t


def test_amber_says_why_on_the_item():
    p = panel("expenditure")
    for k in ("exp.communications_and_leisure", "exp.food_and_housekeeping",
              "exp.personal_costs"):
        p.toggle_group(k)
    pump()
    t = texts(p)
    assert "Unresolved" in t and "£80 / £100" in t
    assert "Monthly not said yet" in t and "£20/wk → £87/mo" in t
    assert "Only a “yes” to the advisor’s figure" in t


def test_di_is_hidden_until_the_advisor_says_one_then_pending_while_unresolved():
    L = ledger("exp")
    p = m.IEPanel()
    p.apply(payload(L, view="expenditure"))
    assert "Disposable income" not in texts(p)
    L.apply([{"kind": "advisor_total", "which": "disposable", "amount": 200, "quote": "q"}])
    p.apply(payload(L, view="expenditure"))
    t = texts(p)
    assert "Disposable income" in t and "Pending recalculation" in t


def test_no_dots_before_solutions():
    p = panel("expenditure")
    dots = [lab for lab in p.findChildren(QLabel)
            if lab.width() == 8 and lab.height() == 8]
    assert dots == []


def test_every_guideline_dot_is_the_same_size_whatever_its_colour():
    """Bilal, 1 Oct: the green circle was bigger than the red one."""
    p = panel("expenditure", solutions=True, stage="exp")
    sheet = {lab.styleSheet() for lab in p.findChildren(QLabel)}
    dots = [lab for lab in p.findChildren(QLabel)
            if "border-radius:4px" in lab.styleSheet() and lab.pixmap().isNull()
            and not lab.text()]
    colours = {lab.styleSheet().split("background:")[1].split(";")[0] for lab in dots}
    assert len(dots) == len(P.EXPENDITURE)
    assert {(d.width(), d.height()) for d in dots} == {(8, 8)}
    assert colours <= set(m.IEPanel.DOTS.values()) and len(colours) >= 2, (colours, sheet)


# ── ref5544, 5 Oct ──────────────────────────────────────────────────────────

def test_an_unresolved_group_says_so_on_its_heading_without_being_opened():
    L = P.Ledger()
    L.apply([{"kind": "alternatives", "side": E, "group": "utilities", "item": "electricity",
              "amount": 150, "amount_high": 180, "quote": "q"}])
    p = m.IEPanel()
    p.apply(payload(L, view="expenditure"))
    p.resize(340, 900)
    p.show()
    pump()
    heads = [lab for lab in p.findChildren(QLabel) if lab.text() == "Unresolved"]
    assert heads, "the heading should read Unresolved"
    assert m.IEPanel.AMBER in heads[0].styleSheet()
    amber_dots = [lab for lab in p.findChildren(QLabel)
                  if not lab.text() and lab.width() == 6
                  and m.IEPanel.AMBER in lab.styleSheet()]
    assert amber_dots, "an amber mark on the closed heading"


def _hover(label):
    """The tooltip Windows would show for `label`, drawn; None if there is none."""
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtGui import QHelpEvent
    from PyQt6.QtWidgets import QToolTip
    QToolTip.hideText()
    pump()
    app.sendEvent(label, QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5),
                                    label.mapToGlobal(QPoint(5, 5))))
    pump()
    tips = [w for w in app.topLevelWidgets()
            if w.objectName() == "qtooltip_label" and w.isVisible()]
    if not tips:
        return None
    img = tips[0].grab().toImage()
    QToolTip.hideText()
    pump()
    return img


# ── ref134, 7 Oct ───────────────────────────────────────────────────────────

def test_a_cut_name_shows_its_full_text_on_a_solid_tooltip_not_a_black_box():
    """Bilal: hovering the panel showed a black box. The heading's
    "background:transparent" reached its tooltip, which Windows draws black."""
    p = panel("expenditure")
    cut = next(lab for lab in p.findChildren(m._IEElide)
               if lab._full == "Communications and leisure")
    assert cut.text() != cut._full, "this heading must be cut at 340px to test anything"
    assert cut.toolTip() == "Communications and leisure"
    img = _hover(cut)
    assert img is not None
    for x, y in ((img.width() // 2, 2), (2, img.height() // 2)):
        c = img.pixelColor(x, y)
        assert c.alpha() == 255 and c.lightness() > 128, c.name()


def test_a_name_shown_whole_has_no_tooltip():
    p = panel("expenditure")
    whole = next(lab for lab in p.findChildren(m._IEElide) if lab._full == "Utilities")
    assert whole.text() == "Utilities"
    assert whole.toolTip() == "" and _hover(whole) is None


def test_scoping_the_style_leaves_the_name_drawn_as_before():
    """The sheet still styles the label itself: transparent, its own colour."""
    p = panel("expenditure")
    lab = next(lab for lab in p.findChildren(m._IEElide) if lab._full == "Utilities")
    assert lab.palette().color(lab.foregroundRole()).name().lower() == m.IEPanel.INK.lower()
    assert not lab.autoFillBackground()


def _package(parts):
    L = P.Ledger()
    L.apply([{"kind": "figure", "side": E, "group": "communications_and_leisure",
              "item": "home_phone_internet_tv_package", "amount": a, "part": n, "quote": "q"}
             for n, a in parts])
    return L


def test_ref661_a_line_made_of_parts_shows_them_on_its_grey_note():
    L = _package([("Internet", 25), ("Netflix", 10), ("Xbox Live", 10.99)])
    p = m.IEPanel()
    p.apply(payload(L, view="expenditure"))
    p.toggle_group("exp.communications_and_leisure")
    p.resize(340, 900)
    p.show()
    pump()
    notes = [lab for lab in p.findChildren(QLabel)
             if lab.text() == "Internet £25 + Netflix £10 + Xbox Live £11"]
    assert notes and m.IEPanel.MUTED in notes[0].styleSheet()
    assert "£46" in texts(p)
    assert "Xbox Live" not in {lab._full for lab in p.findChildren(m._IEElide)}  # no own row


def test_a_grey_note_too_long_for_the_line_never_widens_the_window(win):
    """The widget never wraps the note; the server keeps it short - and if a
    note were ever too long, it is cut, the column does not grow."""
    import ie_panel
    short = _package([("Internet", 25), ("Netflix", 10)])
    win._handle_server_message(payload(short, view="expenditure"))
    win._ie_panel.toggle_group("exp.communications_and_leisure")
    pump(ms=300)
    width = win.width()
    keep = ie_panel.PARTS_NOTE_MAX
    ie_panel.PARTS_NOTE_MAX = 999                       # force the longest note through
    try:
        long_ = _package([("Broadband and phone", 40), ("Disney Plus", 9),
                          ("Xbox Game Pass", 13), ("Spotify Family", 17)])
        win._handle_server_message(payload(long_, view="expenditure"))
        pump(ms=300)
    finally:
        ie_panel.PARTS_NOTE_MAX = keep
    assert win.width() == width


def test_a_line_paid_from_pip_carries_a_plain_grey_note():
    L = P.Ledger()
    L.apply([{"kind": "figure", "side": E, "group": "food_and_housekeeping",
              "item": "groceries", "amount": 400, "quote": "q"},
             {"kind": "pip_funded", "side": E, "group": "food_and_housekeeping",
              "item": "groceries", "amount": 100, "whole": False, "quote": "q"}])
    p = m.IEPanel()
    p.apply(payload(L, view="expenditure"))
    p.toggle_group("exp.food_and_housekeeping")
    p.resize(340, 900)
    p.show()
    pump()
    notes = [lab for lab in p.findChildren(QLabel)
             if lab.text() == "£100 of it paid from PIP/DLA"]
    assert notes and m.IEPanel.MUTED in notes[0].styleSheet()
    assert "£300" in texts(p)
