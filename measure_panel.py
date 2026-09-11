# -*- coding: utf-8 -*-
"""Lay the advisor's left column out with the REAL font and measure it.

    python measure_panel.py

Run this after any change to the alerts panel, and read the exit code.

The pytest suite cannot do this job. It runs on the offscreen platform,
which has no fonts, so every glyph is a tofu box far wider than the real
character - it once claimed 31 prompts were clipped when the true number was
five. So tests/test_advisor_alerts_panel.py asserts BEHAVIOUR (what gives
way, and in what order) and this asserts pixels, with Plus Jakarta Sans, in
a real window shown at -3000,-3000: laid out for real, never on a screen.

Worst case on purpose: the safety card with the 999 bar, two critical
corrections carrying the longest scripts compliance wrote, four more behind
them, and every reminder underneath.

Needs the recording server checked out beside this repo - it is where the
rulebook and compliance's trigger handling live.
"""
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
SRV = APP.parent / "live-widget-server"
if not SRV.exists():
    raise SystemExit(f"expected the recording server at {SRV} - it holds the "
                     f"rulebook and the trigger handling this measures")
sys.path.insert(0, str(APP))
sys.path.insert(0, str(SRV))

from PyQt6.QtWidgets import (QApplication, QScrollArea,          # noqa: E402
                             QAbstractScrollArea)
app = QApplication.instance() or QApplication([])

import main as m                                                 # noqa: E402
import crisis                                                    # noqa: E402
import q17_handling as Q                                         # noqa: E402
import rulebook                                                  # noqa: E402
from rulebook_checker import RulebookChecker                     # noqa: E402

rb = rulebook.load(rulebook.BUNDLED / "sfm.json")
WARNINGS = RulebookChecker(rb, llm=None).warnings("AFFORDABILITY")

# The two longest scripts, so nothing shorter can surprise us later.
by_len = sorted(
    (Q.render(t, None) for t in Q.all_ids()),
    key=lambda r: -len((r["script"] or "") + r["message"]))
WORST = [dict(by_len[0], severity="critical"),
         dict(by_len[1], severity="critical")]
# ...plus every other one, to drive the "+N more to put right" line.
ACTIONS = WORST + [Q.render(t, None) for t in sorted(Q.all_ids())[:4]]

panel = m.AdvisorAlertsPanel()
panel.move(-3000, -3000)
panel.show()
for _ in range(6):
    app.processEvents()

panel.show_crisis(crisis.payload("I have been thinking about ending it", True))
panel.set_trigger_actions(ACTIONS)
panel.set_warnings(WARNINGS)
for _ in range(10):
    app.processEvents()
panel._fit()
for _ in range(6):
    app.processEvents()

print(f"column          {panel.width()} x {panel.height()}")
print(f"room on screen  {panel._room()}")
print(f"corrections     {len(ACTIONS)} sent, {panel._shown_actions} shown")
for box, name in ((panel._crisis_box, "safety"), (panel._action_box, "correction"),
                  (panel._warn_box, "reminders")):
    for i in range(box.count()):
        w = box.itemAt(i).widget()
        if w is not None:
            print(f"   {name:11} {w.objectName() or type(w).__name__:12} "
                  f"{w.height():>4}px")
print(f"reminders       {len(WARNINGS)} sent, {panel._shown_warnings} shown")
print()

bad = []
for lab in panel.findChildren(m.QLabel):
    if not lab.isVisibleTo(panel) or not lab.text().strip():
        continue
    need = (lab.heightForWidth(lab.width()) if lab.wordWrap()
            else lab.sizeHint().height())
    if need > lab.height() + 1:
        bad.append((lab.text()[:46], lab.width(), lab.height(), need))
    if lab.sizeHint().width() > lab.width() + 1 and not lab.wordWrap():
        bad.append(("TOO WIDE: " + lab.text()[:36], lab.width(),
                    lab.sizeHint().width(), 0))
print(f"clipped or squeezed labels : {len(bad)}")
for b in bad:
    print("   ", b)

sc = panel.findChildren(QScrollArea) + panel.findChildren(QAbstractScrollArea)
print(f"scroll areas               : {len(sc)}")

kids = []
for box in (panel._crisis_box, panel._action_box, panel._warn_box):
    kids += [box.itemAt(i).widget() for i in range(box.count())
             if box.itemAt(i).widget() is not None]
over = [(a.objectName(), b.objectName())
        for i, a in enumerate(kids) for b in kids[i + 1:]
        if a.geometry().intersects(b.geometry())]
print(f"overlapping cards          : {len(over)} {over}")

fits = panel.sizeHint().height() <= panel._room()
print(f"fits the screen            : {fits}")

# Visible only, here and below. deleteLater() is asynchronous, so the labels
# of a card that has already been replaced are still children of the panel
# and still answer text() - reading those made the condensed card look as if
# it had kept the full script.
showing = [l for l in panel.findChildren(m.QLabel) if l.isVisibleTo(panel)]

brackets = [l.text() for l in showing if "[" in l.text()]
print(f"unfilled placeholders      : {len(brackets)} {brackets[:2]}")

# The one thing only a real font can prove: that the trim pass actually
# reached for the condensed safety card. The pytest suite drives condensing
# directly because the offscreen platform never overflows, so whether _fit
# CALLS it under a genuine overflow is only visible here.
seen = " ".join(l.text() for l in showing)
condensed = "Thank you for telling me that" not in seen
keeps_numbers = all(n in seen for n in ("116 123", "85258", "0300 123 3393"))
print(f"safety card condensed      : {condensed}")
print(f"  ...and kept every number : {keeps_numbers}")

# ---------------------------------------------------------------- checklist
# The other column, and the one Bilal saw a scrollbar on. Worst case: the
# longest stage, every check done, each with the advisor's own words, and
# one opened out.
import rulebook as _rb                                            # noqa: E402
worst = max(rb.sections, key=lambda s_: len(s_.checks))
CHECKS = [{"id": c.id, "label": c.label, "severity": c.severity,
           "done": i > 1,
           "evidence": ("so what I have got there is about two hundred and "
                        "ten pounds a month, is that right") if i > 1 else None,
           "prompt": None if i > 1 else c.prompt,
           "missing_parts": [] if i > 1 else [e for e in c.elements[:3]],
           "parts": [{"text": e, "done": i > 1, "na": False}
                     for e in c.elements]}
          for i, c in enumerate(worst.checks)]

checklist = m.ComplianceAlertPanel()
checklist.move(-3000, -3000)
checklist.show()
for _ in range(6):
    app.processEvents()
checklist.show_live()
checklist.update_stage(worst.key, [{"key": s_.key, "label": s_.label,
                                    "done": 0, "total": len(s_.checks),
                                    "current": s_.key == worst.key}
                                   for s_ in rb.sections], CHECKS)
# The panel GROWS into its height over GROW_MS, and mid-animation it is
# legitimately shorter than its contents. Measuring during that reports a
# scrollbar that is about to go away on its own, so let it land first -
# real elapsed time, not a fixed number of event-loop turns.
import time                                                       # noqa: E402
deadline = time.monotonic() + 2.0
while time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)

print()
print(f"CHECKLIST  worst stage: {worst.key} ({len(worst.checks)} checks)")
print(f"  size                     : {checklist.width()} x {checklist.height()}")
bars = [b for b in checklist.findChildren(QScrollArea)
        if b.verticalScrollBar().isVisible()]
print(f"  visible scrollbars       : {len(bars)}")
cl_bad = []
for lab in checklist.findChildren(m.QLabel):
    if not lab.isVisibleTo(checklist) or not lab.text().strip():
        continue
    need = (lab.heightForWidth(lab.width()) if lab.wordWrap()
            else lab.sizeHint().height())
    if need > lab.height() + 1:
        cl_bad.append((lab.text()[:44], lab.height(), need))
print(f"  clipped labels           : {len(cl_bad)}")
for b in cl_bad[:4]:
    print("     ", b)
checklist.hide()

panel.hide()
ok = (not bad and not sc and not over and fits and not brackets
      and condensed and keeps_numbers and not bars and not cl_bad)
print("\n" + ("PIXEL CHECK PASSED" if ok else "PROBLEMS ABOVE"))
sys.exit(0 if ok else 1)
