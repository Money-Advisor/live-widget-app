# Spark Flow Focus — the compact widget screen

Branch `focus-ui`, started 15 Oct 2026. **Nothing here changes the classic
widget.** `main.py`, `build_all.py`, `tests/conftest.py` and every existing test
are byte-for-byte as on `main` (`tests/test_focus_ui.py` checks it).

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
build_focus.py     PyInstaller -> build/focus-dist/SparkFlowFocus/ (+ installer); build_all.py untouched
installer/installer_focus.iss   the Focus installer (installer.iss untouched)
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
* **Two exes, two widgets** (Faseeh, 15 Oct): `SparkFlowFocus.exe` is Focus only —
  no tray item, Settings button or start option leads to the classic screen;
  that is `SparkFlow.exe`. The classic screen appears here only as the
  automatic fallback above.
* Same single-instance lock as classic: the two can never run together.
* **Nothing flashes on opening** (15 Oct). The window stays fully transparent
  until the page has drawn, then appears already docked. Two classic startup
  shows are kept from the screen: the checklist panel's constructor shows it
  before it has a parent (a small window of its own for ~20 ms) - Focus builds
  it as `_QuietComplianceAlertPanel` for its own window only; and signed out,
  the classic code shows the window inside `MainWindow.__init__`, before the
  page exists, where Windows drew it solid - Focus holds that show until the
  page is in place.
* **Hover hints are the page's own** (`data-tip`, never `title=""`): inside the
  widget Qt draws a browser hint as a black box with black text.

## Run it

```powershell
# from Spark Flow\live-widget-app-focus, with the Focus venv (has PyQt6-WebEngine 6.11.0)
..\..\.venv-focus\Scripts\python.exe focus_main.py            # Focus
```

`focus_main.py` uses the real widget settings — the signed-in session on that
PC — exactly like the installed widget. Don't run it beside an installed
widget you don't want to share a session with (the lock stops a second copy).

## Give it to someone (Bilal) — one file

```powershell
..\..\.venv-focus\Scripts\python.exe build_focus.py --installer --check
```

makes `installer\Output\SparkFlowFocusSetup.exe` (~145 MB). It installs as
**"Spark Flow Focus"** beside the normal widget — own folder, Start Menu entry and
desktop icon, **no auto-start** (the normal widget keeps that), and uninstalling it
removes only its own files. `--check` installs it into a throwaway folder,
self-tests the installed exe, uninstalls it and proves the normal widget's
program, start-up entry and settings are identical before and after.

Only one Spark Flow runs at a time: quit the normal one (tray → Quit) before
opening Spark Flow Focus — it says so if you forget. Build output goes to
`build\focus-dist\` so a rebuild never fights a copy someone has open.

## Proof (15 Oct)

| What | Result |
| --- | --- |
| `node --test focus/tests/*.test.cjs` — the rules | 22 pass; **10/10** deliberate rule breaks go red |
| `pytest tests/test_focus_ui.py` — the wiring | 54 pass; deliberate breaks go red (incl. 6/6 startup rules) |
| `focus_dev/check_harness.py` — every screen rendered in Edge | **43/43**; drawing breaks go red; a browser `title` hint anywhere fails it |
| `build_focus.py --installer --check` — the installer | installs, installed exe self-test **OK**, uninstalls clean, normal widget untouched |
| `focus_dev/qt_e2e.py` — real widget + real WebEngine | **32/32** (hover hint, load, bridge, buttons → classic methods, dropdown keeps the sheet still, widths 360/720/64/416, slide-out, safety, no layout switch, summary, reload replay) |
| `build_focus.py --check` — the packaged exe | builds; self-test **OK** (page loads from the package, bridge connects) |
| `focus_dev/startup_windows.py` — what Windows shows on opening, watched from outside | signed in, signed out and the built exe: **one window, first seen already docked**; FAILs with either startup fix removed |
| `focus_dev/startup_blinks.py` — the same from inside Qt | 0 visible blinks, 0 early frames |
| `main.py` / `build_all.py` / conftest | unchanged (git diff) |

Screens to look at: `python focus_dev/shoot_harness.py <dir>` (all 40 at real size).

## Known, and owed

* **Bilal**: older correction cards wait in the "Then" queue (one tap each)
  rather than all showing at once. The newest is always in front.
* **Size**: the package is ~530 MB on disk vs ~105 MB classic — Qt WebEngine is
  195 MB of it. Trimming its language files would save ~50 MB.
* **Not proved on a real call yet**: everything above uses real message shapes
  from the server code, not a live call. Next: Faseeh's and Bilal's PCs on staging.
* **Found while testing, NOT fixed (pre-existing, outside this branch's
  remit)**: `tests/conftest.py` does not isolate the widget's settings —
  `QSettings(ORG, APP)` always uses the real registry key, so the existing
  suite runs as whoever is signed in on the PC (renews their token, opens a
  dialer connection to the server their widget points at). The Focus tests
  swap the class themselves and never touch the registry.
