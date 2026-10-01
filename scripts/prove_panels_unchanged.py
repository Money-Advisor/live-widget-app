# -*- coding: utf-8 -*-
"""Prove a change left the widget's existing columns pixel-identical.

    python scripts/prove_panels_unchanged.py            # against HEAD
    python scripts/prove_panels_unchanged.py <commit>

Written for the live I&E column (1 Oct 2026). Faseeh's instruction was that
the alerts column, the checklist and the call card must not change "even a
slight one", and that is a claim only pixels can settle. So: the same live
call state - a real rulebook stage, real checks, a correction card built by
the server's own code - is drawn by the committed main.py and by the working
tree's, each in a fresh process, offscreen, with the system's real fonts, and
every column is compared pixel for pixel.

Each build is drawn TWICE first. The alerts column moves on timers, and a
build that does not match itself proves nothing about a change; this run
reports that rather than calling it a difference.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
SRV = APP.parent / "live-widget-server"
PANELS = ("alerts.png", "checklist.png", "card.png")

SHOOT = r'''
import importlib.util, os, sys, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
main_path, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
from PyQt6.QtCore import QSettings, QEventLoop, QTimer
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
sys.path.insert(0, sys.argv[3]); sys.path.insert(0, sys.argv[4])
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
app = QApplication.instance() or QApplication([])
app.setFont(QFont("Plus Jakarta Sans"))
spec = importlib.util.spec_from_file_location("widget_main", str(main_path))
m = importlib.util.module_from_spec(spec); sys.modules["widget_main"] = m
spec.loader.exec_module(m)
def pump(ms=1500):
    for _ in range(20): app.processEvents()
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
    for _ in range(20): app.processEvents()
w = m.MainWindow(); w._stack.setCurrentWidget(w._page_main); w.move(200, 50); w.show(); pump()
w._recording = True; w._compliance_panel.show_live()
import rulebook, cat_integration as C
rb = rulebook.load(rulebook.BUNDLED / "sfm.json")
cw = C.CatWatch("REF-W", client=None)
cw.case = C.CatCase("complete", {"food": C.CatItem("food", "Food and housekeeping", 180.0)})
cw.observe([{"category": "food", "amount": 320.0, "amount_high": None, "period": "monthly",
             "approximate": False, "put_forward_by": "advisor", "quote": "put 320 for food"}], [])
sections = [{"key": s.key, "label": s.label, "current": s.key == "AFFORDABILITY",
             "done": i < 11, "count": 3, "total": 4} for i, s in enumerate(rb.sections)]
checks = [{"id": c.id, "label": c.label, "covered": i % 2 == 0, "severity": c.severity,
           "prompt": c.prompt}
          for i, c in enumerate([c for c in rb.checks if c.section == "AFFORDABILITY"][:6])]
w._handle_server_message({"type": "compliance_alert", "missing_items": [], "covered_ids": [],
    "stage": "AFFORDABILITY", "sections": sections, "section_checks": checks,
    "still_to_do": [], "open_criticals": [], "warnings": [], "trigger_actions": cw.cards()})
pump()
# The alerts column measures its wrapped card while the window is still
# resizing, and on a busy machine lands a few pixels out (both builds alike:
# the committed one did not match its own first screenshot). Its own refit -
# what its tests call - settles it, the same for both builds.
w._alerts_panel._fit()
pump()
w._alerts_panel.grab().save(str(out / "alerts.png"))
w._compliance_panel.grab().save(str(out / "checklist.png"))
w._front_card.grab().save(str(out / "card.png"))
print(w.width(), w.height())
'''


def shoot(main_py, out, script):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               QT_QPA_FONTDIR=os.environ.get("QT_QPA_FONTDIR", r"C:\Windows\Fonts"))
    r = subprocess.run([sys.executable, str(script), str(main_py), str(out), str(APP), str(SRV)],
                       capture_output=True, text=True, env=env, cwd=APP)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit("a build failed to draw - not a result")
    return r.stdout.strip().splitlines()[-1]


def same(a, b):
    from PyQt6.QtGui import QImage
    x, y = QImage(str(a)), QImage(str(b))
    return not x.isNull() and x == y


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    tmp = Path(tempfile.mkdtemp(prefix="panels-"))
    script = tmp / "shoot.py"
    script.write_text(SHOOT, encoding="utf-8")
    old = tmp / "main_ref.py"
    old.write_bytes(subprocess.run(["git", "show", f"{ref}:main.py"], cwd=APP,
                                   capture_output=True, check=True).stdout)
    sizes = {}
    for tag, src in (("ref1", old), ("ref2", old), ("new1", APP / "main.py"),
                     ("new2", APP / "main.py")):
        sizes[tag] = shoot(src, tmp / tag, script)
    ok = True
    for name in PANELS:
        stable = same(tmp / "ref1" / name, tmp / "ref2" / name) and \
                 same(tmp / "new1" / name, tmp / "new2" / name)
        if not stable:
            print(f"UNSTABLE   {name}: a build does not match itself - not a result")
            ok = False
            continue
        if same(tmp / "ref1" / name, tmp / "new1" / name):
            print(f"IDENTICAL  {name}")
        else:
            print(f"DIFFERENT  {name}")
            ok = False
    print(f"window ({ref} / working tree): {sizes['ref1']} / {sizes['new1']}")
    print("ALL COLUMNS PIXEL-IDENTICAL" if ok else "NOT PROVEN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
