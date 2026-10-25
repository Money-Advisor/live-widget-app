# -*- coding: utf-8 -*-
"""The bar between calls and the tray, in the REAL widget (26 Oct, 2.9.62).

    python focus_dev/minimise_e2e.py <out_dir>

FocusWindow + real Qt WebEngine + the page, driven the way an agent and the
dialer drive it: "-" folds to the bar between calls, "x" hides to the tray, a
call brings the widget back in the shape it was left, it stays a bar when a
call starts and ends, the score opens the summary, Done gets ready for the next
call, a safety card and signing in always open the panel. Checks the window's
real size and place at each step and saves a screenshot of each.

Throwaway settings with dead server addresses, the dialer connection stubbed
out, nothing recorded: the "call" is the widget's own flags and its classic
summary path, as in qt_e2e.py.
"""
import os
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from PyQt6.QtCore import Qt, QCoreApplication, QSettings, QEventLoop, QTimer  # noqa: E402
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

import main      # noqa: E402
import focus_ui  # noqa: E402

# Never the real widget's registry, never a real server: a blank INI would fall
# back to the built-in PRODUCTION addresses, so point both at a dead port.
_INI = os.path.join(tempfile.mkdtemp(prefix="sf-minbar-"), "widget.ini")
_s = QSettings(_INI, QSettings.Format.IniFormat)
_s.setValue("ws/url", "ws://127.0.0.1:9")
_s.setValue("api/base_url", "http://127.0.0.1:9")
_s.sync()
main.QSettings = lambda *a, **k: QSettings(_INI, QSettings.Format.IniFormat)
main.MainWindow._start_control_connection = lambda self: None

from PyQt6.QtWidgets import QApplication  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "minbar_shots"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication(sys.argv)
results = []


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(cond, ms=5000, step=50):
    waited = 0
    while waited < ms:
        if cond():
            return True
        pump(step)
        waited += step
    return cond()


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def js(code):
    box = {}
    win._focus.view.page().runJavaScript(code, lambda r: box.setdefault("r", r))
    wait_for(lambda: "r" in box, 3000, 20)
    return box.get("r")


def click(sel):
    return js("(function(){var e=document.querySelector(%r);if(!e)return 'missing';if(e.disabled)return 'disabled';e.click();return 'ok'})()" % sel)


def shot(name):
    pump(400)
    win.grab().save(str(OUT / f"{name}.png"))


def docked(width):
    """The window is `width` wide, full height, flush to the right edge."""
    g, avail = win.geometry(), win.screen().availableGeometry()
    return (g.width(), g.height(), g.x() + g.width(), g.y()) == (width, avail.height(), avail.right() + 1, avail.top())


def geo():
    g = win.geometry()
    return f"{g.x()},{g.y()} {g.width()}x{g.height()} visible={win.isVisible()}"


def text():
    return js("document.body.innerText") or ""


win = focus_ui.FocusWindow(start=True)
assert win._settings.format() == QSettings.Format.IniFormat and not win._token
win.show()
ctl = win._focus
check("the page starts", wait_for(lambda: ctl.ready, 20000))
# Signed in, between calls.
win._user = {"name": "Sam Advisor", "email": "sam@example.co.uk"}
win._company_name = "The Insolvency Group"
win._active_department = "sfm"
win._logged_out_sticky = False
win._stack.setCurrentWidget(win._page_main)
check("waiting: the full panel", wait_for(lambda: "Ready for your next call" in text(), 4000) and wait_for(lambda: docked(360)), geo())
check("the header has Settings, minimise and x",
      js("[...document.querySelectorAll('.hd [data-act]')].map(e=>e.getAttribute('data-act')).join(',')") == "settings,collapse,hide")
check("the company name stays on one line",
      js("(function(){var n=document.querySelector('.hd .name');return n.scrollWidth<=n.clientWidth && n.getBoundingClientRect().height<24})()") is True)
shot("01-waiting-panel")

# "-" between calls
click(".hd [data-act=collapse]")
check("- folds it to the 64px bar, full height, on the edge", wait_for(lambda: docked(64)), geo())
check("the bar says Ready", wait_for(lambda: js("!!document.querySelector('.strip .sb.rdy')") is True, 2000))
shot("02-waiting-bar")

# "x" on the bar
click(".strip [data-act=hide]")
check("x on the bar hides it to the tray", wait_for(lambda: not win.isVisible(), 3000), geo())

# The dialer starts a call: _handle_dialer_activate shows the window, then records.
win._show_window()
check("a call brings it back from the tray as the bar", wait_for(lambda: win.isVisible() and docked(64), 3000), geo())
win._starting = True
ctl.push_state(force=True)
check("while connecting: still the bar, with no x",
      wait_for(lambda: js("!!document.querySelector('.strip .spin') && !document.querySelector('[data-act=hide]')") is True, 3000))
win._starting = False
win._recording = True
win._live_pipeline = True
ctl.push_state(force=True)
check("the call starts and it stays the bar", wait_for(lambda: js("!!document.querySelector('.strip [data-act=stop]')") is True, 3000)
      and docked(64), geo())
ctl.on_action("hide", "{}")
pump(300)
check("hiding is refused during the call", win.isVisible(), geo())
shot("03-call-bar")

# The call ends while it is a bar.
win._recording = False
win._summary_card.show_pending(1456)
win._summary_card.setVisible(True)
win._front_card.setVisible(False)
ctl.push_state(force=True)
check("the call ends and it stays the bar", wait_for(lambda: js("!!document.querySelector('.strip [data-act=newcall]')") is True, 3000)
      and docked(64), geo())
shot("04-ended-bar-pending")
win._show_server_summary({"type": "session_summary", "duration_seconds": 1456, "recording_saved": True,
                          "score": {"covered": 41, "total": 50, "earned": 41.0, "fraction": 0.82},
                          "covered": {f"c{i}": {} for i in range(41)}, "missing": ["m1", "m2"],
                          "check_info": {"m1": {"label": "Fees explained", "section": "Fees"},
                                         "m2": {"label": "Next steps agreed", "section": "Next Steps"}}})
win._summary_card.mark_saved()
check("the bar shows the score", wait_for(lambda: "82%" in text(), 3000) and docked(64))
shot("05-ended-bar-score")

click(".strip .sb.a")
check("tapping the score opens the summary panel", wait_for(lambda: docked(360) and "Call ended" in text(), 3000), geo())
check("the summary has minimise and x",
      js("[...document.querySelectorAll('.hd [data-act]')].map(e=>e.getAttribute('data-act')).join(',')") == "collapse,hide")
shot("06-summary-panel")
click(".hd [data-act=collapse]")
check("- on the summary folds it to the bar", wait_for(lambda: docked(64), 3000), geo())

newcall = []
orig_new = win._on_new_call
win._on_new_call = lambda: (newcall.append(1), orig_new())
click(".strip [data-act=newcall]")
check("Done on the bar runs the classic Ready-for-the-next-call", wait_for(lambda: newcall == [1], 2000))
check("and it is ready for the next call, still the bar",
      wait_for(lambda: js("!!document.querySelector('.strip .sb.rdy')") is True, 3000) and docked(64), geo())
win._on_new_call = orig_new

# Open, then "x" from the header: the next call brings back the panel.
click(".strip [data-act=expand]")
check("open from the bar: the full panel", wait_for(lambda: docked(360), 3000), geo())
click(".hd [data-act=hide]")
check("x on the header hides it to the tray", wait_for(lambda: not win.isVisible(), 3000))
win._show_window()
win._recording = True
ctl.push_state(force=True)
check("the next call brings it back as the panel", wait_for(lambda: win.isVisible() and docked(360), 3000)
      and wait_for(lambda: js("!!document.querySelector('.panel [data-act=stop]')") is True, 3000), geo())
shot("07-call-panel")

# A safety card while folded opens the panel (unchanged).
click("[data-act=collapse]")
check("folded during the call", wait_for(lambda: docked(64), 3000), geo())
win.server_message.emit({"type": "crisis_alert", "line": "Approved support wording.", "immediate": True,
                         "escalation": "IMMEDIATE RISK TO LIFE - call 999 now.",
                         "resources": [{"name": "Samaritans", "detail": "116 123"}], "evidence": ""})
check("a safety card opens the full panel", wait_for(lambda: docked(360), 3000)
      and wait_for(lambda: js("!!document.querySelector('.focus.safety')") is True, 3000), geo())
win._recording = False
win._summary_card.setVisible(False)
win._front_card.setVisible(True)
ctl.push_state(force=True)

# Signed out while folded: the panel, and it stays the panel after signing in.
wait_for(lambda: "Ready for your next call" in text(), 3000)
click(".hd [data-act=collapse]")
check("folded between calls again", wait_for(lambda: docked(64), 3000), geo())
win._stack.setCurrentWidget(win._page_login)
check("signed out: the full panel", wait_for(lambda: docked(360) and "Sign in" in text(), 3000), geo())
win._stack.setCurrentWidget(win._page_main)
check("signed in again: the full panel, not the bar", wait_for(lambda: "Ready for your next call" in text(), 3000) and docked(360), geo())

print(f"\n{sum(results)} of {len(results)} checks passed; screenshots in {OUT}")
win._focus._poll.stop()
os._exit(0 if all(results) else 1)
