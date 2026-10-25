# The panel ("Focus") — Spark Flow's screen since 2.9.59

Built on branch `focus-ui` from 15 Oct 2026 as a separate preview ("Spark Flow
Focus"). **The company approved it on 19 Oct and it REPLACED the old screen:**
since 2.9.59 `SparkFlow.exe` is `focus_main.py`, installed by the same
installer over the old widget, and there is no separate Focus exe any more.
`main.py` is unchanged apart from its version (`tests/test_focus_ui.py` checks
it); the old screen survives only as the automatic fallback.

## What it is

The manager's complaint: four columns take ~1,428px — 74% of a 1920px monitor.
Focus is **one 360px panel** docked to a screen edge at full height (19%), or a
**64px strip** when folded (3%). It shows **the one thing that matters most
right now** in a big card, queues the rest underneath, and keeps the checklist
and the I&E one tap away as slide-up sheets (the I&E can be pinned beside the
panel, 720px).

Order of the main card: customer safety → corrections ("put right", newest
first, as Bilal ruled 1 Oct) → questions a disclosure made due → critical
checks missed earlier → the next thing to say. Every rule is the classic
widget's, ported and named in `focus/model.js`.

## How it is built — and why it cannot lose a call

```
focus_main.py      entry point: the SAME widget started as FocusWindow
focus_ui.py        FocusWindow(main.MainWindow) + FocusController + the bridge
focus/             the page: index.html, app.js (drawing), model.js (rules), app.css, fonts/ (OFL)
focus_dev/         harness.html + scenarios.js (40 states), screenshot + check scripts, qt_e2e.py
build_all.py       PyInstaller: focus_main.py -> dist/SparkFlow/SparkFlow.exe (--check self-tests it)
installer/installer.iss   the one installer - same AppId/folder/exe/Run entry as every earlier Spark Flow
```

* `FocusWindow` **is** the classic `MainWindow`. Every worker, the recording,
  the dialer connection, sign-in, tray and auto-update run unchanged; the
  classic panels are still built and fed every message, just hidden.
* The page is drawn by Qt WebEngine and talks to Python over QWebChannel.
  **Every button ends in the same `MainWindow` method the classic button
  calls** (`_toggle_recording`, `_toggle_pause`, `_attempt_login`, …). Focus
  has no recording, sign-in or network code of its own.
* Only window-placement methods are overridden (`sizeHint`, `set_compliance_on_top`,
  `_fit_ie_column`, `_refit_after_screen_change`, `moveEvent`), and each defers
  to the classic method whenever Focus is not showing.
* **Falls back to classic by itself** if WebEngine is missing, the page fails to
  load, or it does not say "ready" within 10 s — with a tray message.
* **One widget** (19 Oct): no tray item, Settings button or start option leads
  to the old screen; it appears only as the automatic fallback above.
* Same single-instance lock as before, and a second copy exits silently as the
  old widget did.
* **Minimise and tray** (2.9.62, 26 Oct, agents' feedback that the panel sat
  on screen while idle): between calls and on the summary, **"-"** folds to the
  bar and **"x"** hides to the tray; the next call brings it back in the shape
  it was left. Folded stays folded through a call's start and end (the bar shows
  Ready / the call / the score + Done). Safety card, mic choice and sign-in open
  the panel. Proof: 15 `bar-*` screens + 9 rules each seen red when broken;
  `focus_dev/minimise_e2e.py` 26/26 in the real window.
* **"x" is locked during a call** (19 Oct, after an advisor hid a call by
  mistake): greyed out from the moment a call starts connecting until it stops,
  refused in Python whatever the page sends, and the old screen's "-" is locked
  the same way.
* **Nothing flashes on opening** (15 Oct). The window stays fully transparent
  until the page has drawn, then appears already docked. Two classic startup
  shows are kept from the screen: the checklist panel's constructor shows it
  before it has a parent (a small window of its own for ~20 ms) - Focus builds
  it as `_QuietComplianceAlertPanel` for its own window only; and signed out,
  the classic code shows the window inside `MainWindow.__init__`, before the
  page exists, where Windows drew it solid - Focus holds that show until the
  page is in place.
* **I&E clarification popups (2.9.58).** A card the server sends with a
  `title` ("Income clarification required" …) shows that title where other
  cards say "Put right" — in the card, the queue ("Clarify"), the slide-out
  and the folded strip ("Ask") — with its message as plain text and no
  "put right" promise under it. When only popups are showing, the line above
  reads "N things to clarify". Every other card is unchanged.
* **Hover hints are the page's own** (`data-tip`, never `title=""`): inside the
  widget Qt draws a browser hint as a black box with black text.

## Run it / build it

```powershell
# a Python with PyQt6-WebEngine (requirements.txt) - on this PC <root>\.venv-focus
python focus_main.py                 # uses the real widget settings, like the installed widget
python build_all.py --check          # dist\SparkFlow\SparkFlow.exe + its self-test
ISCC installer\installer.iss         # installer\Output\SparkFlowSetup.exe (~145 MB)
python focus_dev\upgrade_test.py <old dist\SparkFlow> <old installer.iss>
```

The upgrade test installs an old widget and runs the new installer over it with
the auto-updater's own command line, under a throwaway identity (the real
install on the PC is never touched), then uninstalls. 19 Oct, 2.9.58 -> 2.9.59:
**16/16** - same folder, exactly the new file set, nothing old left behind,
auto-start kept, one install entry at 2.9.59, installed exe self-test OK, clean
uninstall; with the installer's clean-runtime step removed it fails 2.

The old preview, "Spark Flow Focus" (own AppId, no auto-start), is not removed
by the new installer: uninstall it by hand on the two PCs that have it.

## Proof (15-19 Oct)

| What | Result |
| --- | --- |
| `node --test focus/tests/*.test.cjs` — the rules | 23 pass; **10/10** deliberate rule breaks go red |
| `pytest tests/test_focus_ui.py` — the wiring | 59 pass; deliberate breaks go red (incl. 6/6 startup rules); "-" locked in a call; installer identity |
| `focus_dev/check_harness.py` — every screen rendered in Edge | **47/47** (4 popup screens); drawing breaks go red (3/3 popup rules); every non-popup screen pixel-identical to before except the animated ring, which differs run to run; a browser `title` hint anywhere fails it |
| `focus_dev/upgrade_test.py` — old widget upgraded in place | **16/16** (above) |
| the existing suite (`pytest tests`) on throwaway settings | 549 pass; 2 fail, neither from this work: one fails on `main` too (I&E income view), one reads the sibling `live-widget-app` checkout's installer from inside this worktree |
| `smoke_test.py` | ALL PASS |
| `focus_dev/qt_e2e.py` — real widget + real WebEngine | **32/32** (hover hint, load, bridge, buttons → classic methods, dropdown keeps the sheet still, widths 360/720/64/416, slide-out, safety, no layout switch, summary, reload replay) |
| `build_all.py --check` — the packaged exe | builds; self-test **OK** (version 2.9.59, page loads from the package, bridge connects, shown once drawn) |
| `focus_dev/startup_windows.py` — what Windows shows on opening, watched from outside | signed in, signed out and the built exe: **one window, first seen already docked**; FAILs with either startup fix removed |
| `focus_dev/startup_blinks.py` — the same from inside Qt | 0 visible blinks, 0 early frames |
| `main.py` | identical to `main` except `APP_VERSION` (test) |

Screens to look at: `python focus_dev/shoot_harness.py <dir>` (all 40 at real size).

## Known, and owed

* **Bilal**: older correction cards wait in the "Then" queue (one tap each)
  rather than all showing at once. The newest is always in front.
* **Size**: the package is ~530 MB on disk vs ~105 MB before — Qt WebEngine is
  195 MB of it. Trimming its language files would save ~50 MB. The installer
  (~145 MB) is under the updater's 300 MB cap, which every widget since the
  updater was added (3 Aug) has.
* **Not proved on a real call yet**: everything above uses real message shapes
  from the server code, not a live call. Next: Faseeh's and Bilal's PCs on staging.
* **Found while testing, NOT fixed (pre-existing, outside this branch's
  remit)**: `tests/conftest.py` does not isolate the widget's settings —
  `QSettings(ORG, APP)` always uses the real registry key, so the existing
  suite runs as whoever is signed in on the PC (renews their token, opens a
  dialer connection to the server their widget points at). The Focus tests
  swap the class themselves and never touch the registry.
