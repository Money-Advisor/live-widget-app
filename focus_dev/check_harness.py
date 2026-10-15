# -*- coding: utf-8 -*-
"""Render every Focus scenario in headless Edge and check what it says.

    python focus_dev/check_harness.py

The screenshots (shoot_harness.py) are for a person to look at; this is the
same rendering checked by machine, so a later change that drops a card, a
button or a warning goes red without anyone having to notice.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

# scenario: (must contain, must NOT contain)
EXPECT = {
    "login": (["Sign in", "Forgot password?", "Work email", 'class="bigLogo" src="../focus/logo.png"'],
              ["Calls are NOT being recorded"]),
    "login-busy": (["Signing in"], []),
    "login-error": (["Incorrect email or password."], []),
    "login-forgot": (["reset link is on its way"], ["msg red"]),
    "signed-out": (["Calls are NOT being recorded", "Sign in"], []),
    "idle": (["Ready for your next call", "Start a call manually", "This shift", "84%", 'class="logo" src="../focus/logo.png"'], []),
    "idle-manual": (["Customer name", "Reference ID", "Start recording"], []),
    # Opening a dropdown must not replay the sheet's slide-up: the sheet and its
    # backdrop are still on screen, so they are redrawn "calm"; only the list animates.
    "settings-dropdown": (['class="dd open"', 'role="listbox"', "Smart Sound Technology for Digital Microphones",
                           "Jabra Evolve2 30", 'aria-selected="true"',
                           'class="scrim calm"', 'class="sheet calm"', 'class="dd-list" data-anim="dd-mic"'],
                          ["<select", 'class="dd-list calm"']),
    "settings-dropdown-picked": (['title="Headset Microphone (Jabra Evolve2 30)"', 'class="sheet calm"',
                                  'class="dd shut"'], ['class="dd open"', 'role="listbox"']),
    "idle-settings": (["Your voice", "Customer voice", "Log out", "Save settings"],
                      ['class="sheet calm"', "shut", "classic layout", 'data-act="classic"']),
    "mic-gate": (["Choose your microphone", "Headset Microphone", "Use this microphone"], []),
    "starting": (["Connecting"], ["Start a call manually"]),
    "live-listening": (["Listening", "Your checklist appears"], ["Put right"]),
    "live-next": (["Say next", "Ask about every source of household income", "4 things not to say", "On track"], []),
    "live-critical": (["Put right now", "You suggested a food figure", "Say this", "1 thing to put right",
                       "Show another way to say it"], ["On track"]),
    "live-critical-alt": (["Or say this", "Just to check"], []),
    "live-three": (["3 things to put right", "Council tax: two amounts", "Guideline figure said aloud",
                    "Affordability steering"], []),
    "live-queue-pick": (["Back to the most urgent"], []),
    "live-safety": (["Customer safety", "116 123", "IMMEDIATE RISK", "Questions to ask now"], []),
    "live-urgent": (["Ask these now", "Ask whether anyone is supporting them", "Questions to ask now"],
                    ["On track", "Ask whether they feel safe right now"]),
    "live-missed": (["Missed", "Data protection check", "Date of birth", "critical check missed earlier"], ["On track"]),
    "live-missed-pick": (["Back to the most urgent"], []),
    "live-paused": (["Paused for card payment", "Resume recording", "Paused \u2014 not recording"], []),
    "live-buffering": (["Reconnecting \u2014 still recording"], []),
    "live-transcript-failed": (["Live checking unavailable", "still being recorded"], ["On track"]),
    "live-recording-only": (["Live checking is off for this call"], ["Checklist"]),
    "live-all-clear": (["Everything in Income is done", "\u00a3412", "nothing to put right"], ["1 thing to put right", "things to put right"]),
    "sheet-checklist": (["Still to do from earlier", "Creditor Check", "SAY NEXT", "Take-home pay asked"], []),
    "sheet-ie-income": (["Child Benefit", "Universal Credit", "\u00a31,840"], []),
    "sheet-ie-exp": (["Son\u2019s phone", "Hide the parts", "Unresolved", "\u00a3412", "Communications and leisure"],
                     ["UNRESOLVED</span>"]),
    "sheet-dont": (["Said once, these cannot be undone", "Don\u2019t quote guideline amounts"], []),
    "sheet-newcard": (["New: Council tax: two amounts"], []),
    "pinned": (['class="pin"', "Income &amp; expenditure"], []),
    "strip": (['class="strip"', "Fix"], ['class="body"']),
    "strip-peek": (["New \u00b7 put right", "Keep as count"], []),
    "legacy": (["You said: guaranteed write-off", "Explain the fees"], []),
    "summary-pending": (["Working out your score", "Ready for the next call"], []),
    "summary-score": (["82%", "Worth working on", "Show all 9", "Recording saved"], []),
    "summary-all": (["Show the top three", "Call closed properly", "Missed \u00b7 9"], []),
    "summary-saved": (["Call saved", "Recording saved"], ["%</div>"]),
    "summary-saving": (["Saving the recording", "64%"], ["Recording saved"]),
    "dock-left": (['class="dock-left"'], []),
}


def dom(name):
    url = (HERE / "harness.html").as_uri() + "?s=" + name
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--window-size=800,900",
           "--virtual-time-budget=3000", "--allow-file-access-from-files", "--dump-dom", url]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace")


def main():
    bad = 0
    for name, (must, never) in EXPECT.items():
        html = dom(name)
        missing = [m for m in must if m not in html]
        present = [n for n in never if n in html]
        if "ready:" + name not in html:
            missing.append("(scenario did not finish)")
        ok = not missing and not present
        bad += 0 if ok else 1
        print(("PASS " if ok else "FAIL ") + name
              + (f"  missing={missing}" if missing else "") + (f"  unexpected={present}" if present else ""))
    print(f"\n{len(EXPECT) - bad} of {len(EXPECT)} scenarios as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
