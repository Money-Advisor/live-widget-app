# -*- coding: utf-8 -*-
"""Measure what someone sees when the Focus widget opens.

    python focus_dev/startup_blinks.py [signed-in|signed-out]

Starts FocusWindow the way focus_main.run() does and samples the window every
5ms: shown or not, its opacity, where it is. Also counts hides and native
window rebuilds. Two faults have been fixed here and both are checked:

  * blinks - the window hidden and rebuilt after it first appeared (sign-in
    dropping and Focus re-adding "on top": twice per start)
  * the empty square - the window visible before the page had drawn, at the
    classic default size and place, for a split second

PASS needs: no hide/rebuild after the first show, and every sample in which
the window is actually visible (shown AND opacity > 0) at its final docked
rectangle with the page drawn. Throwaway settings, no network.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from PyQt6.QtCore import Qt, QCoreApplication, QSettings, QEventLoop, QTimer, QObject, QEvent  # noqa: E402
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

import main      # noqa: E402
import focus_ui  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "signed-in"
_INI = os.path.join(tempfile.mkdtemp(prefix="sf-blink-"), "widget.ini")
main.QSettings = lambda *a, **k: QSettings(_INI, QSettings.Format.IniFormat)
s = QSettings(_INI, QSettings.Format.IniFormat)
s.setValue("audio/mic_name", "x")
if mode == "signed-in":
    s.setValue("auth/token", "stand-in")                 # a stored session, as on an agent's PC
s.sync()
main.ValidateWorker.start = lambda self: None          # no network: validated by hand below

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
t0 = time.time()
events, samples = [], []
state = {"win": None}


class Watch(QObject):
    def eventFilter(self, obj, ev):
        if isinstance(obj, focus_ui.FocusWindow) and ev.type() in (
                QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WinIdChange):
            events.append((round(time.time() - t0, 3), ev.type().name, round(obj.windowOpacity(), 2)))
        return False


def sample():
    w = state["win"]
    if w is None:
        return
    g = w.geometry()
    drawn = bool(w._focus and w._focus.ready and not w._veiled)
    samples.append((round(time.time() - t0, 3), w.isVisible(), round(w.windowOpacity(), 2),
                    (g.x(), g.y(), g.width(), g.height()), drawn))


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


watch = Watch()
app.installEventFilter(watch)
sampler = QTimer()
sampler.timeout.connect(sample)
sampler.start(5)

win = focus_ui.FocusWindow()           # (signed out: the classic code shows it from in here)
state["win"] = win
win.show()
if win.focus_active():
    win._focus.place()
pump(1500)
if mode == "signed-in":
    win._user = {}
    win._on_validate_ok({}, "", {}, "", "", 0)        # the stored session comes back valid
pump(2500)
sampler.stop()

# The monitor the window is actually on (a PC with two screens may open it on
# either), and its right edge - where Focus docks.
from PyQt6.QtGui import QGuiApplication  # noqa: E402
scr = QGuiApplication.screenAt(win.geometry().center()) or win.screen()
avail = scr.availableGeometry()
final = (avail.right() - 360 + 1, avail.top(), 360, avail.height())
first_show = next((i for i, e in enumerate(events) if e[1] == "Show" and e[2] > 0), None)
# Only a hide or rebuild while the window could be seen is a blink; while it is
# still veiled (opacity 0) nobody sees anything.
after = events[first_show + 1:] if first_show is not None else []
blinks = [e for e in after if e[1] in ("Hide", "WinIdChange")]
hidden_rebuilds = [e for e in events if e[1] in ("Hide", "WinIdChange") and e[2] == 0]
seen = [x for x in samples if x[1] and x[2] > 0]
wrong = [x for x in seen if x[3] != final or not x[4]]
first_seen = seen[0][0] if seen else None
print("events:", events)
print(f"first visible at {first_seen}s; visible samples {len(seen)}; at final rect & drawn: {len(seen) - len(wrong)}")
if wrong:
    print("visible but NOT final/drawn:", wrong[:5])
ok = not blinks and seen and not wrong and win.windowOpacity() == 1.0
print(f"RESULT {mode}: visible_blinks={len(blinks)} (invisible rebuilds while veiled: {len(hidden_rebuilds)}) "
      f"early_or_misplaced_frames={len(wrong)} screen={scr.name()} -> {'PASS' if ok else 'FAIL'}")
os._exit(0 if ok else 1)
