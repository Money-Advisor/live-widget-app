# -*- coding: utf-8 -*-
"""Count what makes the Focus window blink when it opens.

    python focus_dev/startup_blinks.py

Starts FocusWindow the way focus_main.run() does, then plays the signed-in
start (the stored session validates -> _enter_main), and counts every time the
window is hidden, shown or its native window rebuilt (WinIdChange) in the
first seconds - each of those is a visible blink. Throwaway settings, no
network: the "session" is a stand-in token and no agent id, so no dialer
connection is opened.
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

_INI = os.path.join(tempfile.mkdtemp(prefix="sf-blink-"), "widget.ini")
main.QSettings = lambda *a, **k: QSettings(_INI, QSettings.Format.IniFormat)
# A signed-in start, as on an agent's PC: a stored token, a chosen mic.
s = QSettings(_INI, QSettings.Format.IniFormat)
s.setValue("auth/token", "stand-in")
s.setValue("audio/mic_name", "x")
s.sync()
main.ValidateWorker.start = lambda self: None          # no network: validated by hand below

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
t0 = time.time()
log = []


class Watch(QObject):
    def eventFilter(self, obj, ev):
        if isinstance(obj, focus_ui.FocusWindow) and ev.type() in (
                QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WinIdChange):
            log.append((round(time.time() - t0, 2), ev.type().name))
            if ev.type() == QEvent.Type.Hide and "--why" in sys.argv:
                import traceback
                print(f"--- Hide at {log[-1][0]}s, visible={obj.isVisible()} minimized={obj.isMinimized()}")
                traceback.print_stack(limit=12)
        return False


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


win = None
watch = Watch()
app.installEventFilter(watch)
win = focus_ui.FocusWindow()
win.show()
if win.focus_active():
    win._focus.place()
pump(1500)
# The stored session comes back valid (what ValidateWorker does on a real start).
win._user = {}
win._on_validate_ok({}, "", {}, "", "", 0)
pump(3000)
blinks = [e for e in log if e[1] in ("Hide", "WinIdChange")]
print("events:", log)
print(f"RESULT hides/rebuilds after first show: {len(blinks)}  ready={win._focus.ready}")
os._exit(0)
