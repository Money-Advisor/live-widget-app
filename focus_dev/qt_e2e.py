# -*- coding: utf-8 -*-
"""End to end in the real widget: FocusWindow + real Qt WebEngine + the page.

    python focus_dev/qt_e2e.py <out_dir>

Proves, with nothing faked between Python and the page:
  * the page loads inside the widget and the bridge connects (it says "ready")
  * what the widget sends is drawn (states, real-shaped server messages)
  * pressing the page's buttons reaches the SAME MainWindow methods
  * the window is the width of what is drawn, on the screen edge
  * switching to classic and back works, mid-call
and saves a screenshot of the real window at each step.

Safe on a working PC: QSettings point at a throwaway folder (the real signed-
in widget's registry key is never read or written), nothing signs in, nothing
connects to a server, and the "recording" is a flag - no audio is opened.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

from PyQt6.QtCore import Qt, QCoreApplication, QSettings, QEventLoop, QTimer  # noqa: E402
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

import main      # noqa: E402
import focus_ui  # noqa: E402

# MainWindow builds QSettings(ORG, APP), which ALWAYS means the real registry
# key (setDefaultFormat does not apply to that constructor). Swap the class for
# a throwaway file, or this script runs as whoever is signed in on this PC.
_INI = os.path.join(tempfile.mkdtemp(prefix="sf-focus-e2e-"), "widget.ini")
main.QSettings = lambda *a, **k: QSettings(_INI, QSettings.Format.IniFormat)
from PyQt6.QtWidgets import QApplication  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "qt_shots"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication(sys.argv)
results = []


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(cond, ms=15000, step=100):
    waited = 0
    while waited < ms:
        if cond():
            return True
        pump(step)
        waited += step
    return cond()


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def js(win, code):
    box = {}
    win._focus.view.page().runJavaScript(code, lambda r: box.setdefault("r", r))
    wait_for(lambda: "r" in box, 3000, 20)
    return box.get("r")


def shot(win, name):
    pump(350)
    img = win.grab()
    path = OUT / f"{name}.png"
    img.save(str(path))
    return path


def scenarios():
    out = subprocess.run(["node", "-e", "global.self=global; require(process.argv[1]);"
                          "console.log(JSON.stringify(global.FocusScenarios))", str(HERE / "scenarios.js")],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


SC = scenarios()


def msgs(name):
    return [s["data"] for s in SC[name]["steps"] if s["kind"] == "msg"]


win = focus_ui.FocusWindow(start=True)
if win._settings.format() != QSettings.Format.IniFormat or win._token:
    print("ABORT: the test window is not on its own throwaway settings")
    os._exit(2)
win.show()
ctl = win._focus
check("the page starts and the bridge connects", wait_for(lambda: ctl.ready, 20000), f"failed={ctl.failed}")
check("Focus is showing, classic hidden", win.focus_active() and win._stack.isHidden())
avail = win.screen().availableGeometry()
g = win.geometry()
check("the window is 360px wide, full height, on the right edge",
      (g.width(), g.height(), g.x() + g.width()) == (360, avail.height(), avail.right() + 1),
      f"{g.x()},{g.y()} {g.width()}x{g.height()} avail {avail.width()}x{avail.height()}")
check("the page shows the sign-in", wait_for(lambda: js(win, "!!document.getElementById('f-email')") is True, 5000))
shot(win, "01-login")

# --- sign-in goes through the classic sign-in (worker stubbed: no network) ---
seen = []
win._attempt_login = lambda: seen.append((win._email_edit.text(), bool(win._pw_edit.text())))
js(win, "document.getElementById('f-email').value='sam@example.co.uk';"
        "document.getElementById('f-pw').value='pw';"
        "document.querySelector('[data-act=login]').click(); true")
check("Sign in on the page calls the classic _attempt_login", wait_for(lambda: seen == [("sam@example.co.uk", True)], 3000), str(seen))

# --- signed in, between calls ---
win._user = {"name": "Sam Advisor", "email": "sam@example.co.uk"}
win._company_name = "The Insolvency Group"
win._active_department = "sfm"
win._stack.setCurrentWidget(win._page_main)
check("the page shows Ready between calls",
      wait_for(lambda: (js(win, "document.body.innerText") or "").find("Ready for your next call") >= 0, 3000))
shot(win, "02-idle")

# --- a call ---
win._reference_edit.setText("REF-48213")
win._live_pipeline = True
win._recording = True
win._elapsed = 755
ctl.push_state(force=True)
for m in msgs("live-three"):
    win.server_message.emit(m)
check("a correction card is drawn in front",
      wait_for(lambda: (js(win, "(document.querySelector('.focus.high,.focus.critical')||{}).innerText||''") or "").find("Council tax") >= 0, 3000))
check("the queue holds the other two and the next thing to say",
      js(win, "document.querySelectorAll('.qrow').length") == 3)
shot(win, "03-live-three")

paused = []
win._toggle_pause = lambda: paused.append(1)
js(win, "document.querySelector('[data-act=pause]').click(); true")
check("Pause on the page calls the classic _toggle_pause", wait_for(lambda: paused == [1], 2000))

js(win, "document.querySelector('[data-v=ie]').click(); true")
check("the I&E sheet opens", wait_for(lambda: js(win, "!!document.querySelector('.sheet')") is True, 2000))
shot(win, "04-ie-sheet")
js(win, "document.querySelector('[data-act=pin]').click(); true")
check("pinning the I&E widens the window to 720px", wait_for(lambda: win.width() == 720, 3000), str(win.width()))
shot(win, "05-pinned")
js(win, "document.querySelector('[data-act=unpin]').click(); true")
check("unpinning gives the width back", wait_for(lambda: win.width() == 360, 3000), str(win.width()))

js(win, "document.querySelector('[data-act=collapse]').click(); true")
check("folding to the strip makes the window 64px", wait_for(lambda: win.width() == 64, 3000), str(win.width()))
shot(win, "06-strip")
folded = dict(msgs("strip-peek")[0])          # a full checklist state, as the server sends
assert folded["type"] == "compliance_alert"
folded["trigger_actions"] = [{"id": "Q17.NEW", "label": "New card", "severity": "high",
                              "message": "A new card while folded.", "script": "Say this.", "occurrence": 1}]
win.server_message.emit(folded)
check("a new card slides out of the strip (window grows to 416px)", wait_for(lambda: win.width() == 416, 3000), str(win.width()))
shot(win, "07-strip-peek")
check("the slide-out goes back after 8 seconds", wait_for(lambda: win.width() == 64, 11000), str(win.width()))
js(win, "document.querySelector('.strip [data-act=expand]:last-child').click(); true")
check("opening the panel again", wait_for(lambda: win.width() == 360, 3000), str(win.width()))

# --- safety ---
win.server_message.emit({"type": "crisis_alert", "line": "Approved support wording.", "immediate": True,
                         "escalation": "IMMEDIATE RISK TO LIFE - call 999 now.",
                         "resources": [{"name": "Samaritans", "detail": "116 123"}], "evidence": ""})
check("the safety card takes the front", wait_for(lambda: js(win, "!!document.querySelector('.focus.safety')") is True, 3000))
shot(win, "08-safety")

# --- switch to classic mid-call and back ---
win.use_layout("classic")
pump(400)
check("switching to classic mid-call shows the classic window", not win.focus_active() and not win._stack.isHidden()
      and win.width() >= 460, f"{win.width()}x{win.height()}")
shot(win, "09-classic-midcall")
win.use_layout("focus")
check("and back to Focus", wait_for(lambda: win.focus_active() and win.width() == 360, 3000))
check("the page still shows the call after switching", js(win, "!!document.querySelector('.focus.safety')") is True)

# --- end of call: the classic summary path ---
win._recording = False
win._summary_card.show_pending(1456)
win._stack.setCurrentWidget(win._page_main)
win._summary_card.setVisible(True)
win._front_card.setVisible(False)
ctl.push_state(force=True)
check("the summary waits for the score", wait_for(lambda: (js(win, "document.body.innerText") or "").find("Working out your score") >= 0, 3000))
win._show_server_summary({"type": "session_summary", "duration_seconds": 1456, "recording_saved": True,
                          "score": {"covered": 41, "total": 50, "earned": 41.0, "fraction": 0.82},
                          "covered": {f"c{i}": {} for i in range(41)}, "missing": ["m1", "m2"],
                          "check_info": {"m1": {"label": "Fees explained", "section": "Fees"},
                                         "m2": {"label": "Next steps agreed", "section": "Next Steps"}}})
win._summary_card.mark_saved()
check("the score and missed checks are drawn",
      wait_for(lambda: (js(win, "document.body.innerText") or "").find("82%") >= 0, 3000))
shot(win, "10-summary")

newcall = []
orig_new = win._on_new_call
win._on_new_call = lambda: (newcall.append(1), orig_new())
js(win, "document.querySelector('[data-act=newcall]').click(); true")
check("Ready for the next call runs the classic _on_new_call", wait_for(lambda: newcall == [1], 2000))

# --- a page reload rebuilds from the replay ---
win._recording = True
ctl.push_state(force=True)
for m in msgs("live-three"):
    win.server_message.emit(m)
pump(300)
ctl.ready = False
win._focus.view.reload()
check("after a reload the page reconnects", wait_for(lambda: ctl.ready, 15000))
check("and redraws the call from the replay",
      wait_for(lambda: js(win, "document.querySelectorAll('.qrow').length") == 3, 3000))
win._recording = False

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)} of {len(results)} checks passed; screenshots in {OUT}")
win._focus._poll.stop()
os._exit(1 if failed else 0)
