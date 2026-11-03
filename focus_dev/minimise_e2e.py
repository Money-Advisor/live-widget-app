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

2.9.64 (W2, 30 Oct): those calls are ones with live AI OFF; a call whose live AI
is on opens the panel and keeps it open - the fold greyed out, a fold, a hide,
Windows' minimise and Alt+F4 all refused - and the agent's own bar comes back
when it ends.
"""
import json
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

# A call with live AI OFF (a recording-only team): as in 2.9.62, folded stays
# folded through the call. The dialer shows the window, then records.
win._show_window()
check("a call brings it back from the tray as the bar", wait_for(lambda: win.isVisible() and docked(64), 3000), geo())
win._starting = True
ctl.push_state(force=True)
check("while connecting: still the bar, with no x",
      wait_for(lambda: js("!!document.querySelector('.strip .spin') && !document.querySelector('[data-act=hide]')") is True, 3000))
win._starting = False
win._recording = True
win._live_pipeline = False
ctl.push_state(force=True)
check("a call with live AI off starts and it stays the bar",
      wait_for(lambda: js("!!document.querySelector('.strip [data-act=stop]')") is True, 3000) and docked(64), geo())
ctl.on_action("hide", "{}")
pump(300)
check("hiding is refused during the call", win.isVisible(), geo())
shot("03-call-bar")
win._recording = False
win._summary_card.show_pending(1456)
win._summary_card.setVisible(True)
win._front_card.setVisible(False)
ctl.push_state(force=True)
check("the call ends and it stays the bar", wait_for(lambda: js("!!document.querySelector('.strip [data-act=newcall]')") is True, 3000)
      and docked(64), geo())
win._show_server_summary({"type": "session_summary", "duration_seconds": 1456, "recording_saved": True})
win._summary_card.mark_saved()
check("with live AI off the bar shows Saved, no score", wait_for(lambda: js("!!document.querySelector('.strip .sb.g')") is True, 3000)
      and "%" not in (js("document.querySelector('.strip').innerText") or "") and docked(64), geo())
click(".strip [data-act=newcall]")
check("Done: ready for the next call, still the bar",
      wait_for(lambda: js("!!document.querySelector('.strip .sb.rdy')") is True, 3000) and docked(64), geo())

# A call whose live AI is ON (2.9.64, W2): the panel opens and stays open; the
# agent's bar comes back when the call ends.
win._starting = True
ctl.push_state(force=True)
check("a coached call connecting: still the bar", wait_for(lambda: js("!!document.querySelector('.strip .spin')") is True, 3000)
      and docked(64), geo())
win._starting = False
win._recording = True
win._live_pipeline = True
ctl.push_state(force=True)
check("a coached call opens the full panel", wait_for(lambda: docked(360), 3000)
      and wait_for(lambda: js("!!document.querySelector('.panel [data-act=stop]')") is True, 3000), geo())
check("its fold is greyed out",
      js("(function(){var b=document.querySelector('.hd [data-act=collapse]');"
         "return b && b.disabled ? b.getAttribute('aria-label') : 'enabled'})()") == "Stays open during coached calls")
shot("04-coached-call")
ctl.on_action("layout", json.dumps({"mode": "strip", "pin": False, "peek": False}))
pump(400)
check("a fold sent anyway is refused", docked(360), geo())
ctl.on_action("hide", "{}")
pump(300)
check("hiding is refused", win.isVisible() and docked(360), geo())
win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)      # a taskbar click, Win+M
check("Windows minimising it brings it straight back",
      wait_for(lambda: win.isVisible() and not win.isMinimized() and docked(360), 3000), geo())
win.close()                                                                  # Alt+F4
check("closing it is refused", wait_for(lambda: win.isVisible() and docked(360), 3000), geo())

win._recording = False
win._summary_card.show_pending(1456)
win._summary_card.setVisible(True)
win._front_card.setVisible(False)
ctl.push_state(force=True)
check("the call ends: back to the bar the agent chose", wait_for(lambda: js("!!document.querySelector('.strip [data-act=newcall]')") is True, 3000)
      and docked(64), geo())
shot("05-ended-bar-pending")
win._show_server_summary({"type": "session_summary", "duration_seconds": 1456, "recording_saved": True,
                          "score": {"covered": 41, "total": 50, "earned": 41.0, "fraction": 0.82},
                          "covered": {f"c{i}": {} for i in range(41)}, "missing": ["m1", "m2"],
                          "check_info": {"m1": {"label": "Fees explained", "section": "Fees"},
                                         "m2": {"label": "Next steps agreed", "section": "Next Steps"}}})
win._summary_card.mark_saved()
check("the bar shows the score", wait_for(lambda: "82%" in text(), 3000) and docked(64))
shot("06-ended-bar-score")

click(".strip .sb.a")
check("tapping the score opens the summary panel", wait_for(lambda: docked(360) and "Call ended" in text(), 3000), geo())
check("the summary has minimise and x",
      js("[...document.querySelectorAll('.hd [data-act]')].map(e=>e.getAttribute('data-act')).join(',')") == "collapse,hide")
shot("07-summary-panel")
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
shot("08-call-panel")
win.server_message.emit({"type": "crisis_alert", "line": "Approved support wording.", "immediate": True,
                         "escalation": "IMMEDIATE RISK TO LIFE - call 999 now.",
                         "resources": [{"name": "Samaritans", "detail": "116 123"}], "evidence": ""})
check("a safety card shows in the open panel", wait_for(lambda: js("!!document.querySelector('.focus.safety')") is True, 3000)
      and docked(360), geo())
win._recording = False
win._summary_card.setVisible(False)
win._front_card.setVisible(True)
ctl.push_state(force=True)

# A call with live AI off from the panel: it can be folded during the call.
check("between calls again: the panel", wait_for(lambda: "Ready for your next call" in text(), 3000) and docked(360), geo())
win._recording = True
win._live_pipeline = False
ctl.push_state(force=True)
wait_for(lambda: js("!!document.querySelector('.panel [data-act=stop]')") is True, 3000)
click("[data-act=collapse]")
check("folded during a call with live AI off", wait_for(lambda: docked(64), 3000), geo())
win._recording = False
ctl.push_state(force=True)
click(".strip [data-act=expand]")
check("and it opens again as before", wait_for(lambda: docked(360), 3000), geo())

# Signed out while folded: the panel, and it stays the panel after signing in.
wait_for(lambda: "Ready for your next call" in text(), 3000)
click(".hd [data-act=collapse]")
check("folded between calls again", wait_for(lambda: docked(64), 3000), geo())
win._stack.setCurrentWidget(win._page_login)
check("signed out: the full panel", wait_for(lambda: docked(360) and "Sign in" in text(), 3000), geo())
win._stack.setCurrentWidget(win._page_main)
check("signed in again: the full panel, not the bar", wait_for(lambda: "Ready for your next call" in text(), 3000) and docked(360), geo())

# 2.9.65 (MD2): "which department was this call for?" Through the REAL connect and
# stop this time, so the widget itself decides when to ask. Stand-ins: the audio
# threads (nothing is recorded), the call's connection, and the backend's two calls -
# nothing leaves this PC.
import types  # noqa: E402


class _Sig:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a):
        for fn in list(self._slots):
            fn(*a)


class _NoAudio:
    def __init__(self, **k):
        self.error_occurred, self.stream_ready = _Sig(), _Sig()

    def start(self):
        pass

    def stop(self):
        pass

    def wait(self, *_a):
        return True


class _NoConnect:
    def __init__(self, streamer):
        self.connected, self.failed = _Sig(), _Sig()

    def start(self):
        pass


ME = {"departments": [
    {"id": "d-cs", "name": "Customer Service DMP", "main": True, "file_by_code": True},
    {"id": "d-ar", "name": "Annual Review", "main": False, "file_by_code": True}]}
answers, fail = [], {"why": None}


def _answer(base, token, row, dept):
    answers.append((row, dept))
    if fail["why"]:
        raise main.BackendError(fail["why"])
    return {"department_id": dept, "result": "filed"}


main.api_get_me = lambda base, token: ME
main.api_answer_department = _answer
main.RecordingThread = _NoAudio
main.StartCallWorker = _NoConnect
win._token = "tok"
win._settings.setValue("audio/mic_name", "mic")
win._rescan_devices = lambda: None
win._mic_devices = [{"index": 1, "name": "mic", "maxInputChannels": 1, "defaultSampleRate": 16000}]
win._spk_devices = [{"index": 2, "name": "spk", "maxInputChannels": 2, "defaultSampleRate": 48000}]
win._mic_combo.clear()
win._mic_combo.addItem("mic")
win._spk_combo.clear()
win._spk_combo.addItem("spk")


def call(row, live=False):
    win._pending_streamer = types.SimpleNamespace(
        live_pipeline=live, db_session_id=row, on_message=None, send_audio=lambda *a: None,
        stop_stream=lambda *a: None, end_session=lambda: None, close=lambda: None)
    win._starting = True
    win._on_call_connected()
    return wait_for(lambda: win._dept_call is not None and win._dept_call["choices"] is not None, 3000)


def end(secs):
    win._elapsed = secs
    win._stop_recording()


def asked():
    return js("!!document.querySelector('fieldset.dq')") is True


def label(sel):
    return js("(function(){var b=document.querySelector(%r);return b && b.disabled ? b.getAttribute('aria-label') : 'enabled'})()" % sel)


click(".hd [data-act=collapse]")
check("folded to the bar before the call", wait_for(lambda: docked(64), 3000), geo())
check("a call with live AI off connects: still the bar, its departments loaded",
      call("row-1") and wait_for(lambda: js("!!document.querySelector('.strip [data-act=stop]')") is True, 3000) and docked(64), geo())
win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)
check("minimised mid-call: the classic widget hides it to the tray", wait_for(lambda: not win.isVisible(), 3000), geo())
end(45)
check("the call ends: the question brings it back as the full panel",
      wait_for(lambda: win.isVisible() and docked(360) and asked(), 3000), geo())
check("it asks which department, the main one first",
      "Which department was this call for?" in text()
      and js("Array.from(document.querySelectorAll('.dq .opt .nm')).map(function(e){return e.textContent}).join('|')")
      == "Customer Service DMP|Annual Review")
shot("07-dept-question")
check("Ready for the next call is greyed out", click(".cta[data-act=newcall]") == "disabled")
check("the fold and the x are greyed out",
      label(".hd [data-act=collapse]") == "Answer the department question first"
      and label(".hd [data-act=hide]") == "Answer the department question first")
ctl.on_action("newcall", "{}")
ctl.on_action("layout", json.dumps({"mode": "strip", "pin": False, "peek": False}))
ctl.on_action("hide", "{}")
pump(400)
check("a next call, a fold and a hide sent anyway are all refused", asked() and docked(360) and win.isVisible(), geo())
win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)
check("Windows minimising it brings it straight back",
      wait_for(lambda: win.isVisible() and not win.isMinimized() and docked(360), 3000), geo())
win.close()
check("closing it is refused", wait_for(lambda: win.isVisible() and docked(360) and asked(), 3000), geo())
check("tapping Annual Review files the call", click('.dq [data-v="d-ar"]') == "ok"
      and wait_for(lambda: answers == [("row-1", "d-ar")], 3000), str(answers))
check("answered: back to the bar the agent chose", wait_for(lambda: docked(64), 3000)
      and js("!!document.querySelector('.strip [data-act=newcall]:not([disabled])')") is True, geo())
shot("08-dept-answered-bar")
click(".strip [data-act=expand]")
check("opened again, it says where the call is filed",
      wait_for(lambda: docked(360) and "Filed under Annual Review" in text(), 3000), geo())
shot("09-dept-filed")
click(".dq-chg")
check("Change shows the departments again, the answer ticked",
      wait_for(lambda: js("(document.querySelector('.dq .opt.on .nm')||{}).textContent") == "Annual Review", 3000))
click('.dq [data-v="d-cs"]')
check("picking another changes it", wait_for(lambda: answers[-1:] == [("row-1", "d-cs")]
                                             and "Filed under Customer Service DMP" in text(), 3000), str(answers))
click(".cta[data-act=newcall]")
check("Ready for the next call", wait_for(lambda: "Ready for your next call" in text(), 3000) and not asked(), geo())

call("row-2")
end(12)
check("a call under 30 seconds is not asked", wait_for(lambda: "Call saved" in text(), 3000) and not asked()
      and click(".cta[data-act=newcall]") == "ok", geo())
wait_for(lambda: "Ready for your next call" in text(), 3000)

fail["why"] = "Could not reach the server. Check your connection."
call("row-3")
end(60)
wait_for(asked, 3000)
click('.dq [data-v="d-ar"]')
check("a save that fails says so and frees the agent",
      wait_for(lambda: "Not saved." in text(), 3000)
      and js("!document.querySelector('.cta[data-act=newcall]').disabled") is True
      and label(".hd [data-act=hide]") == "enabled", geo())
shot("10-dept-not-saved")
fail["why"] = None
click('.dq [data-v="d-ar"]')
check("and picking again saves it", wait_for(lambda: "Filed under Annual Review" in text(), 3000)
      and answers[-1:] == [("row-3", "d-ar")], str(answers))
click(".cta[data-act=newcall]")
wait_for(lambda: "Ready for your next call" in text(), 3000)

click(".hd [data-act=collapse]")
wait_for(lambda: docked(64), 3000)
call("row-4", live=True)
check("a coached call from the bar opens the panel", wait_for(lambda: docked(360), 3000), geo())
end(45)
pump(600)
trail = json.loads(js("JSON.stringify(FocusApp.debug().trail)") or "[]")
this_call = trail[len(trail) - 1 - trail[::-1].index("phase:idle>live"):] if "phase:idle>live" in trail else []
check("its end goes straight to the question, the panel never folding in between",
      asked() and docked(360) and "phase:live>summary" in this_call and "keepOpen:false" not in this_call, str(this_call))
click('.dq [data-v="d-cs"]')
check("answered: the bar comes back", wait_for(lambda: docked(64), 3000), geo())
click(".strip [data-act=newcall]")
wait_for(lambda: js("!!document.querySelector('.strip .sb.rdy')") is True, 3000)
click(".strip [data-act=expand]")
wait_for(lambda: docked(360), 3000)

call("row-5")
end(45)
wait_for(asked, 3000)
win._handle_dialer_activate({"customer_reference": "REF-77", "lead_id": "L-77", "campaign_id": "ADVICE"})
check("the dialer's next call drops the question at once - recording never waits on it",
      win._starting and wait_for(lambda: "Connecting" in text() and not asked(), 3000), geo())
check("the next call is not held back by it", call("row-6") and win._recording, geo())
end(5)
check("and its question never comes back", wait_for(lambda: "Call saved" in text(), 3000) and not asked())
check("nothing was sent for the dropped question", [a for a in answers if a[0] in ("row-5", "row-6")] == [], str(answers))

print(f"\n{sum(results)} of {len(results)} checks passed; screenshots in {OUT}")
win._focus._poll.stop()
os._exit(0 if all(results) else 1)
