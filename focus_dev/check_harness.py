# -*- coding: utf-8 -*-
"""Render every Focus scenario in headless Edge and check what it says.

    python focus_dev/check_harness.py [scenario ...]

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
    # 2.9.65 (MD2): "which department was this call for?" on the summary. Until it is
    # answered the next-call button, the fold and the x wait; nothing is sent for them.
    "dept-question": (['<fieldset class="dq" data-anim="dq"><legend class="cap">Needed before the next call</legend>',
                       '<span class="dq-t" id="dq-t">Which department was this call for?</span>',
                       "Pick one. It files the call under the right team.",
                       '<div class="dq-opts" role="radiogroup" aria-labelledby="dq-t">',
                       '<button class="opt" role="radio" aria-checked="false" data-act="deptAnswer" data-v="d-cs"><span class="radio"></span>'
                       '<span class="nm">Customer Service DMP</span><span class="main">Main</span></button>',
                       '<span class="nm">Annual Review</span></button>', '<span class="nm">Case Assessment</span></button>',
                       '<span class="dq-hint">Recording never waits on this: if a new call starts first, this one is filed by the dialer’s code or confirmed by your manager.</span>',
                       '<button class="cta" data-act="newcall" disabled="">Pick the call’s department first</button>',
                       'aria-label="Answer the department question first" data-tip="Answer the department question first" disabled=""><svg',
                       "<h2>Call saved</h2>", "Recording saved"],
                      ["Ready for the next call</button>", 'aria-label="Hide to the tray"', 'aria-label="Minimise to the bar"',
                       'aria-checked="true"']),
    "dept-question-score": (["82%", "Worth working on", '<fieldset class="dq"', "Pick the call’s department first"], []),
    "dept-question-pending": (["Working out your score", '<fieldset class="dq"', "Pick the call’s department first"], []),
    "dept-question-tap": (['["deptAnswer",{"id":"d-ar"}]', '<fieldset class="dq"'], []),
    "dept-next-refused": (['<fieldset class="dq"', "<h2>Call saved</h2>"],
                          ['["newcall"', '"mode":"strip"', 'class="strip"']),
    "dept-saving": (['<button class="opt on" role="radio" aria-checked="true" data-act="deptAnswer" data-v="d-ar" disabled="">'
                     '<span class="spin"></span><span class="nm">Annual Review</span>',
                     'data-v="d-cs" disabled=""><span class="radio"></span>',
                     '<button class="cta" data-act="newcall" disabled="">Saving your answer…</button>'], []),
    "dept-answered": (['<div class="dq-done" role="status" data-anim="dq-done"><svg', "<b>Filed under Annual Review</b>",
                       "<span>Your answer files this call.</span>", '<button class="dq-chg" data-act="deptChange">Change</button>',
                       '<button class="cta" data-act="newcall">Ready for the next call</button>',
                       'aria-label="Hide to the tray"', 'aria-label="Minimise to the bar"'],
                      ['<fieldset class="dq"', "dq-hint", "Answer the department question first"]),
    "dept-change": (['<legend class="cap">Change the department</legend>',
                     '<button class="opt on" role="radio" aria-checked="true" data-act="deptAnswer" data-v="d-ar">',
                     '<button class="cta" data-act="newcall">Ready for the next call</button>'],
                    ['class="dq-done"', "dq-hint"]),
    "dept-change-same": (['class="dq-done"', "Filed under Annual Review"], ['"deptAnswer"', '<fieldset class="dq"']),
    "dept-changed": (["<b>Filed under Customer Service DMP</b>"], ['<fieldset class="dq"']),
    "dept-failed": (['<div class="msg red" role="alert">',
                     "<b>Not saved.</b> Could not reach the server. Check your connection. Pick again to try once more.",
                     "Needed before the next call", '<button class="cta" data-act="newcall">Ready for the next call</button>',
                     'aria-label="Hide to the tray"'],
                    ["dq-hint", "department first", 'disabled=""']),
    "dept-kept": (["<b>Already filed by your manager</b>", "Customer Service DMP: moved there by hand, so it stays."],
                  ['data-act="deptChange"', '<fieldset class="dq"']),
    "dept-long-name": (["Customer Service Debt Management Plan Arrears and Variations"], []),
    "dept-opens-the-bar": (['<fieldset class="dq"', 'class="panel"'], ['class="strip"']),
    "dept-answered-folds-back": (['class="strip"', 'data-act="newcall"'], ['class="panel"', '<fieldset class="dq"']),
    "dept-failed-stays-open": (["<b>Not saved.</b>", '<fieldset class="dq"'], ['class="strip"']),
    # 2.9.66: the CAT flags section (the server's cat_section). The bar sits on top of
    # the dock; a new flag pops above it, is not counted until it lands, and lands
    # with a bump; the sheet groups the cards in a fixed order. A third list here is
    # strings that must appear IN THAT ORDER.
    "cat-bar-zero": (['<button class="dk catbar" data-act="sheet" data-v="cat" aria-label="Open CAT flags">',
                      '<span class="dt"><span>CAT flags</span><span class="z">Nothing to act on</span></span>',
                      '<button class="dk" data-act="sheet" data-v="list"'],
                     ['class="cbadge', 'class="catpop', "catbar has"]),
    "cat-bar-waiting": (['<span class="z">1 waiting for CAT</span>'], ['class="cbadge', "catbar has"]),
    # Flags that arrived while paused wait in the count: no pop, no bump.
    "cat-bar-count": (['<button class="dk catbar has"', "<span>2 to ask · 1 to check</span>",
                       '<span class="cbadge" data-anim="cbadge-0" aria-label="3 CAT flags to act on">3</span>'],
                      ['class="catpop', "cbadge b1", "cbadge b2"]),
    "cat-bar-all-kinds": (["<span>3 to act on</span>", 'aria-label="3 CAT flags to act on">3</span>'], ["to confirm"]),
    "cat-paused": (["Paused for card payment"], ['class="catpop', "catbar"]),
    "cat-pop-one": (['<div class="catpop high" role="alert" data-anim="catpop-1"><div class="focus high"><div class="f-top">'
                     '<span class="kind ttl">New · CAT needs an answer</span><span class="when">just now</span></div>'
                     '<h2 class="gtext">Proof of Address: Can the customer send proof of their current address, dated in the last three months?</h2>',
                     '<div class="pa"><button class="go" data-act="sheet" data-v="cat">Open CAT flags</button>'
                     '<button class="kp" data-act="catNow">Move it now</button></div>',
                     '<span class="catmv">Moves into CAT flags in a few seconds</span></div><div class="pb"><i></i></div></div>',
                     '<span class="z">Nothing to act on</span>'],
                    ['class="cbadge', "catbar has"]),
    "cat-pop-check": (['<div class="catpop critical"', '<div class="focus critical"><div class="f-top"><span class="kind ttl">New · Check your action</span>'], []),
    "cat-pop-unsure": (['<div class="catpop next"', '<div class="focus next"><div class="f-top"><span class="kind ttl">New · Not sure which one</span>'], []),
    "cat-pop-many": (['<div class="catpop high" role="alert" data-anim="catpop-1">', '<span class="kind ttl">2 new CAT flags</span>',
                      '<div class="parts"><div class="part"><span class="o"></span><span>Unexplained Inflow</span><span class="secchip">I&amp;E</span></div>'
                      '<div class="part"><span class="o"></span><span>Family &amp; Friends</span><span class="secchip">I&amp;E</span></div></div>',
                      '<span class="z">Nothing to act on</span>'],
                     ['<h2 class="gtext">Unexplained', 'class="cbadge']),
    # More while a pop is up: it starts again (a new pop, bar full) with both.
    "cat-pop-restart": (['data-anim="catpop-2"', "2 new CAT flags", "<span>Unexplained Inflow</span>",
                         "<span>Family &amp; Friends</span>", '<div class="pb"><i></i></div>'],
                        ['data-anim="catpop-1"', 'class="cbadge']),
    # A flag that went leaves the pop, which carries on (same pop, its bar where it was).
    "cat-pop-leaves": (['data-anim="catpop-1"', "New · CAT needs an answer", "Family &amp; Friends: Who are these payments to",
                        '<div class="pb"><i style="animation-delay:-'],
                       ["2 new CAT flags", "Unexplained Inflow", 'data-anim="catpop-2"']),
    "cat-pop-empties": (['<span class="z">Nothing to act on</span>'], ['class="catpop', 'class="cbadge']),
    "cat-pop-lands": (['<button class="dk catbar has"', "<span>2 to ask</span>",
                       '<span class="cbadge b1" data-anim="cbadge-1" aria-label="2 CAT flags to act on">2</span>'],
                      ['class="catpop']),
    "cat-pop-open": (['role="dialog" aria-label="CAT flags"',
                      '<h3>CAT flags<span class="cbadge" style="margin-left:8px;vertical-align:2px">1</span></h3>',
                      '<div class="focus high catc enter" data-anim="cat-cat.flag.poa#1"><div class="f-top">'
                      '<span class="kind ttl">New · CAT needs an answer</span><span class="when">Personal Details</span></div>'],
                     ['class="catpop', "cbadge b1"]),
    # Another sheet takes the pop away; its flag is counted, with no bump and no "New".
    "cat-pop-other-sheet": (['aria-label="Checklist"', '<span class="cbadge" data-anim="cbadge-0" aria-label="1 CAT flag to act on">1</span>'],
                            ['class="catpop', "New · ", "cbadge b1"]),
    "cat-pop-over-checklist": (['aria-label="Checklist"', '<div class="catpop high"'], []),
    "cat-sheet": (['<div class="st-h">Check your action<span style="margin-left:auto;color:var(--red)">2</span></div>',
                   '<div class="st-h">To ask<span style="margin-left:auto;color:var(--amb)">3</span></div>',
                   '<div class="st-h">Not sure which one<span style="margin-left:auto;color:var(--brand)">1</span></div>',
                   '<div class="st-h">Waiting for CAT<span style="margin-left:auto;color:var(--mute)">1</span></div>',
                   '<h3>CAT flags<span class="cbadge" style="margin-left:8px;vertical-align:2px">6</span></h3>',
                   '<div class="focus critical catc', '<div class="focus high catc', '<div class="focus next catc', '<div class="focus sent catc',
                   '<span class="kind ttl">Back from CAT</span><span class="when">I&amp;E</span></div><div class="backline"><svg',
                   "<span>CAT didn’t accept the answer · ask again</span></div><h2 class=\"gtext\">Unexplained Inflow: What was this payment into the account for?</h2>"
                   '<p class="detail">Why CAT raised it: a large payment in with no reference.</p>'
                   '<p class="detail">Sent: Customer says the £250 was a birthday present from their brother.</p>'
                   '<div class="pays"><span class="cap">The payment</span><div class="pay"><span class="d">14 Oct</span><span class="p">J SMITH</span><span class="a">+£250.00</span></div></div>',
                   '<div class="pays"><span class="cap">3 payments · £115.00</span><div class="pay"><span class="d">03 Oct</span><span class="p">A JONES</span><span class="a">',
                   '<div class="pays cands"><span class="cap">Which one?</span><div class="cand"><span class="o"></span><span class="ct">'
                   '<span class="pay"><span class="d">02 Oct</span><span class="p">AVIVA</span><span class="a">£60.00</span></span>'
                   '<span class="cc">In CAT as Car insurance</span></span></div>',
                   '<div class="quote said"><span class="cap">Customer said</span><p>“the Aviva one, that’s my life insurance, not the car”</p></div>',
                   '<span class="kind ttl">Sent to CAT</span>',
                   '<div class="catst"><svg', "<span>Answer sent to CAT · waiting for CAT’s reply</span></div></div>",
                   '<div class="listen"><span class="eq"><i></i><i></i><i></i><i></i></span>Clears itself if it comes up on the call</div>',
                   '<button class="catdone" data-act="catDone" aria-expanded="true">', '<span style="flex:1">Done on this call · 4</span>',
                   '<span class="tx"><span>Proof of Address</span><span class="miss">Answered · CAT accepted</span></span></div>',
                   '<span class="cathelp">The widget can hear a document being asked for or promised. It can’t check that the document arrived.</span>'],
                  ["New · ", 'class="catpop', "Nothing to act on. A CAT flag"],
                  [">Check your action<span", "You closed ‘Partner awareness’", "You dismissed ‘Right to remain’",
                   ">To ask<span", "Back from CAT", "Family &amp; Friends: Who", "Universal Credit: the bank",
                   ">Not sure which one<span", ">Waiting for CAT<span", "Sent to CAT", 'class="catdone"', 'class="cathelp"']),
    "cat-sheet-tall": (["Done on this call · 4", "In CAT as Pet insurance"], []),
    "cat-sheet-done-closed": (['<button class="catdone" data-act="catDone" aria-expanded="false">', "Done on this call · 4"],
                              ['<span class="miss">Answered · CAT accepted</span>']),
    "cat-sheet-empty": (["<h3>CAT flags</h3>",
                         '<div class="msg plain">Nothing to act on. A CAT flag appears here when the call reaches its section.</div><span class="cathelp">'],
                        ['class="catdone"', 'class="st-h"']),
    # The section open: a new flag appears in it, marked New, with no pop.
    "cat-sheet-new": (['<div class="focus critical catc enter" data-anim="cat-cat.flag.rtr#1"><div class="f-top"><span class="kind ttl">New · Check your action</span>'],
                      ['class="catpop']),
    "cat-sheet-closed-not-new": (['<div class="focus high catc" data-anim="cat-cat.flag.poa#1"><div class="f-top"><span class="kind ttl">CAT needs an answer</span>'],
                                 ["New · "]),
    "cat-collapsed": (['class="strip"'], ['class="catpop', "catbar"]),
    "cat-fold-drops-pop": (['<span class="cbadge" data-anim="cbadge-0" aria-label="1 CAT flag to act on">1</span>'],
                           ['class="catpop', 'class="strip"', "cbadge b1"]),
    "cat-recording-only": (["Live checking is off for this call"], ['class="catpop', "catbar"]),
    "cat-new-call": (['<span class="z">Nothing to act on</span>'], ['class="catpop', 'class="cbadge', "Proof of Address"]),
    "cat-new-call-pops-again": (['<div class="catpop high" role="alert" data-anim="catpop-2">', "New · CAT needs an answer"],
                                ["2 new CAT flags", 'class="cbadge']),
    "cat-pop-times-out": (['<span class="cbadge b1" data-anim="cbadge-1" aria-label="1 CAT flag to act on">1</span>', "<span>1 to ask</span>"],
                          ['class="catpop']),
    "cat-pop-empties-no-bump": (['<span class="cbadge" data-anim="cbadge-0" aria-label="1 CAT flag to act on">1</span>'],
                                ['class="catpop', "cbadge b1", "cbadge-1"]),
    "cat-pause-drops-pop": (['<span class="cbadge" data-anim="cbadge-0" aria-label="1 CAT flag to act on">1</span>'],
                            ['class="catpop', "cbadge b1"]),
    "cat-folded-no-pop": (['class="body"', '<span class="cbadge" data-anim="cbadge-0" aria-label="1 CAT flag to act on">1</span>'],
                          ['class="catpop', 'class="strip"']),
    "cat-section-goes": (['class="body"', 'data-v="list" aria-label="Open the checklist"'], ["catbar", 'aria-label="CAT flags"']),
    # Today's CAT card in trigger_actions, marked in_cat_section: not a correction
    # beside a cat_section (body, state line, strip), drawn as before without one.
    "cat-hides-its-cards": (["1 thing to put right", "You suggested a food figure", "<span>1 to ask</span>"],
                            ["Ask the customer for proof of their current address.", ">Clarify</span>"]),
    "cat-old-card-without-section": (["2 things to put right", "Ask the customer for proof of their current address."], ["catbar"]),
    "cat-hides-its-cards-strip": (['class="strip"', 'aria-label="1 to put right"'], ['aria-label="2 to put right"']),
    "cat-old-card-strip": (['class="strip"', 'aria-label="2 to put right"'], []),
}


def budgets():
    """A scenario's `budget` (ms of page time before the page is read; default
    3000), given right after its size in scenarios.js - shoot_harness.py reads the
    same. A CAT flag's pop lands by itself only after 6.5 s (2.9.66)."""
    import re
    text = (HERE / "scenarios.js").read_text(encoding="utf-8")
    return {m.group(1): int(m.group(2)) for m in re.finditer(
        r"S\['([a-z0-9-]+)'\]\s*=\s*\{\s*size:\s*\[\d+,\s*\d+\],\s*budget:\s*(\d+)", text)}


def dom(name, budget=3000):
    url = (HERE / "harness.html").as_uri() + "?s=" + name
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--window-size=800,900",
           f"--virtual-time-budget={budget}", "--allow-file-access-from-files", "--dump-dom", url]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace")


def main():
    bad = 0
    wanted = set(sys.argv[1:])
    budget = budgets()
    for name, (must, never, *order) in EXPECT.items():
        if wanted and name not in wanted:
            continue
        html = dom(name, budget.get(name, 3000))
        missing = [m for m in must if m not in html]
        present = [n for n in never if n in html]
        # In this order (the CAT sheet's groups): each after the one before it.
        at = -1
        for s in (order[0] if order else []):
            i = html.find(s, at + 1)
            if i < 0:
                missing.append(f"(in order) {s}")
                break
            at = i
        # A server that sends no cat_section gets the 2.9.65 panel: no CAT bar, no pop.
        if not name.startswith("cat-") and ("catbar" in html or 'class="catpop' in html):
            present.append("a CAT bar or pop on a screen with no cat_section")
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
    n = len(wanted & set(EXPECT)) if wanted else len(EXPECT)
    print(f"\n{n - bad} of {n} scenarios as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
