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
    "idle": (['aria-label="Hide to the tray" data-tip="Hide to the tray">', 'aria-label="Minimise to the bar" data-tip="Minimise to the bar">', "Ready for your next call", "Start a call manually", "This shift", "84%", 'class="logo" src="../focus/logo.png"'], ["Focus layout"]),
    "idle-manual": (["Customer name", "Reference ID", "Start recording"], []),
    # Opening a dropdown must not replay the sheet's slide-up: the sheet and its
    # backdrop are still on screen, so they are redrawn "calm"; only the list animates.
    "settings-dropdown": (['class="dd open"', 'role="listbox"', "Smart Sound Technology for Digital Microphones",
                           "Jabra Evolve2 30", 'aria-selected="true"',
                           'class="scrim calm"', 'class="sheet calm"', 'class="dd-list" data-anim="dd-mic"'],
                          ["<select", 'class="dd-list calm"']),
    "settings-dropdown-picked": (['data-tip="Headset Microphone (Jabra Evolve2 30)"', 'class="sheet calm"',
                                  'class="dd shut"'], ['class="dd open"', 'role="listbox"']),
    "idle-settings": (["Your voice", "Customer voice", "Log out", "Save settings"],
                      ['class="sheet calm"', "shut", "classic layout", 'data-act="classic"']),
    "mic-gate": (["Choose your microphone", "Headset Microphone", "Use this microphone"], []),
    # "-" is locked from the moment a call starts connecting (19 Oct).
    "starting": (["Connecting", 'aria-label="Can\u2019t hide during a call"', "during a call\" disabled"],
                 ["Start a call manually", 'aria-label="Hide to the tray"']),
    "live-listening": (["Listening", "Your checklist appears"], ["Put right"]),
    "live-next": (["Say next", "Ask about every source of household income", "4 things not to say", "On track"], []),
    "live-critical": (["Put right now", "You suggested a food figure", "Say this", "1 thing to put right",
                       "Show another way to say it"], ["On track", "Customer said", 'class="quote said"']),
    "live-critical-alt": (["Or say this", "Just to check"], []),
    "live-three": (["3 things to put right", "Council tax: two amounts", "Guideline figure said aloud",
                    "Affordability steering"], []),
    # 2.9.58 I&E popups: the server's title where other cards say "Put right",
    # not repeated, no "put right" promise under it; other cards unchanged.
    "popup-front": (['class="kind ttl">Income clarification required</span>', '<h2 class="gtext">', "1 thing to clarify"],
                    ['class="eyebrow">Income clarification required', "Clears itself when it", ">Put right</span>",
                     "to put right", "Customer said", 'class="quote said"']),
    # 2.9.60: a popup says why it opened and what the customer said; a popup
    # with neither (popup-front) and a breach card with a quote (live-critical) do not.
    "popup-said": (['<p class="detail">Two figures, not settled: £1,000 or £1,500</p>',
                    '<div class="quote said"><span class="cap">Customer said</span><p>“maybe 1000 or 1500 from the business”</p></div>',
                    'class="kind ttl">Income clarification required</span>'],
                   ["Say this", "Clears itself when it", ">Put right</span>"]),
    "popup-long-title": (['class="kind ttl">Household expenditure needs confirming</span>'], []),
    "popup-queued": (['<span class="kind">Put right</span>', 'class="eyebrow">Council tax: two amounts',
                      '<span class="qt">Income clarification required</span>', ">Clarify</span>",
                      "2 things to put right"], ["to clarify"]),
    "popup-peek": (["New · Income clarification required", "Keep as count", '<span class="cap">Ask</span>', '<h2 class="gtext">'],
                   ["New · put right", '<span class="cap">Fix</span>']),
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
    # The tag sits on the same line as the label, never under it.
    "sheet-checklist": (["Still to do from earlier", "Creditor Check", "Take-home pay asked",
                         'household income</span><span class="tagnow">Say next</span></span>'], []),
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
    "summary-score": (["82%", "Worth working on", "Show all 9", "Recording saved",
                       'aria-label="Minimise to the bar"', 'aria-label="Hide to the tray"'], []),
    "summary-all": (["Show the top three", "Call closed properly", "Missed \u00b7 9"], []),
    "summary-saved": (["Call saved", "Recording saved"], ["%</div>"]),
    # 26 Oct: the bar between calls and after a call; "-" folds, "x" hides.
    "bar-idle": (['class="strip"', 'class="sb rdy"', "Ready", ">11<", "Calls", 'aria-label="Hide to the tray"',
                  'aria-label="Open the panel"', 'class="slogo"'], ['class="pad"', 'class="hd']),
    "bar-open": (["Ready for your next call", 'aria-label="Minimise to the bar"'], ['class="strip"']),
    "bar-starting": (['class="strip"', 'class="spin"', "Connect"], ['data-act="hide"', 'class="pad"']),
    "bar-call-starts": (['class="strip"', 'class="rec', 'data-act="stop"', 'data-act="pause"'], ['class="body"', 'class="sb rdy"']),
    "bar-call-ends": (['class="strip"', "24:16", "Score", 'class="spin"', 'data-act="newcall"', "Done"],
                      ['<h2>Working out your score', 'class="pad"', 'data-act="stop"']),
    "bar-summary-score": (['class="strip"', "82%", 'class="sb a"', 'data-act="newcall"', 'aria-label="Hide to the tray"'],
                          ["Worth working on"]),
    "bar-summary-high": (["93%", 'class="sb g"'], []),
    "bar-summary-low": (["55%", 'class="sb r"'], []),
    "bar-summary-saved": (["Saved", 'class="sb g"', 'data-act="newcall"'], ["%</span>"]),
    "bar-safety": (["Customer safety", "Stays until signposted"], ['class="strip"']),
    "bar-signed-out": (["Calls are NOT being recorded", "Sign in"], ['class="strip"']),
    "bar-mic-gate": (["Choose your microphone"], ['class="strip"']),
    # Folding closes Settings: opened again, the panel shows no Settings sheet.
    "bar-settings-closes": (["Ready for your next call"], ['role="dialog" aria-label="Settings"', 'class="strip"']),
    # Signed out while folded, then signed in again: the full panel, not the bar.
    "bar-signed-in-again": (["Ready for your next call"], ['class="strip"']),
    "bar-dock-left": (['class="strip"', 'm13 9 3 3-3 3'], []),
    "summary-saving": (["Saving the recording", "64%"], ["Recording saved"]),
    # The card a manager dismissed is gone, and the advisor is NOT told they put it right.
    "false-positive": (["Affordability steering", "1 thing to put right"],
                       ["Council tax: two amounts", "Put right<", "Moving to the next thing"]),
    "dock-left": (['class="dock-left"'], []),
    # Case continuity (server 25 Oct): a callback opens on the case, in full on the
    # first stage, one line after; a name that does not match is flagged above it;
    # everything done on an earlier call says which call, advisor and date.
    "case-callback": (["Continuing case REF-48213", "Call 2", "Priya Shah · dropped",
                       "done on earlier calls", "Pick up at Loans",
                       "Confirm DPA first — it is asked again on every call."],
                      ["Check the reference", 'class="casebn compact"']),
    "case-callback-name": (["Check the reference — this call is for <b>Jordan Blake</b>",
                            "the case is <b>Sam Taylor</b>", "Continuing case REF-48213"], []),
    "case-later": (['class="casebn compact"', "Continuing case · call 2", "33 done earlier"],
                   ["Confirm DPA first", "Pick up at"]),
    "case-checklist": (['data-tip="Done on Call 1 · Priya Shah · 14 Oct"', "Call 1 · Priya Shah · 14 Oct",
                        "FCA regulated statement"], []),
    "case-ie": (['<span class="il">Rent</span><span class="cchip"', "Call 1"], []),
    "case-parts": (['Child Benefit and any tax credits</span><span class="cchip"'], []),
    # A card carried from an earlier call says so; a held one says it waited.
    "case-carried-card": (['class="carried-line"', "Carried over from Call 1 · Priya Shah · 14 Oct",
                           "Council tax: two amounts"], ["held for Solutions"]),
    "case-carried-two": (["Carried over from Call 1 · Priya Shah · 14 Oct",
                          'class="qt">Non-monthly cost not captured</span><span class="cchip"',
                          'data-tip="Done on Call 2 · Tom Reid · 16 Oct"'], []),
    "case-carried-held": (["Carried over from Call 2 · Tom Reid · 16 Oct · held for Solutions"], []),
    # 2.9.64 (W2): a call whose live AI is on keeps the panel open.
    "coached-call": (['aria-label="Stays open during coached calls" data-tip="Stays open during coached calls" disabled',
                      'class="body"', 'data-act="stop"'], ['aria-label="Fold to the strip"', 'class="strip"']),
    "coached-fold-refused": (['class="body"', 'aria-label="Stays open during coached calls"'], ['class="strip"']),
    "coached-call-opens-the-bar": (['class="body"', 'aria-label="Stays open during coached calls"', 'data-act="stop"'],
                                   ['class="strip"']),
    "coached-call-ends-folds-back": (['class="strip"', 'data-act="newcall"', "Done"],
                                     ['class="body"', 'aria-label="Stays open during coached calls"']),
    "coached-call-ends-open": (['<h2>Working out your score'], ['class="strip"']),
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
        # No browser hover hint, anywhere: inside the widget Qt draws it as an
        # empty black box (15 Oct). The page's own data-tip hint replaces it.
        if ' title="' in html:
            present.append('title="..." (a browser hint - use data-tip)')
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
