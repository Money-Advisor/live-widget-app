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
build_focus.py     PyInstaller recipe -> dist/SparkFlowFocus/ (build_all.py untouched)
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
* **Switch any time, mid-call included**: tray menu → "Use the classic layout",
  or Settings on the Focus page. Remembered per PC (`ui/layout`).
* Same single-instance lock as classic: the two can never run together.

## Run it

```powershell
# from Spark Flow\live-widget-app-focus, with the Focus venv (has PyQt6-WebEngine 6.11.0)
..\..\.venv-focus\Scripts\python.exe focus_main.py            # Focus
..\..\.venv-focus\Scripts\python.exe focus_main.py --classic  # start on classic
```

`focus_main.py` uses the real widget settings — the signed-in session on that
PC — exactly like the installed widget. Don't run it beside an installed
widget you don't want to share a session with (the lock stops a second copy).

## Proof (15 Oct)

| What | Result |
| --- | --- |
| `node --test focus/tests/*.test.cjs` — the rules | 22 pass; **10/10** deliberate rule breaks go red |
| `pytest tests/test_focus_ui.py` — the wiring | 43 pass; **10/10** deliberate breaks go red |
| `focus_dev/check_harness.py` — every screen rendered in Edge | **40/40**; 4/4 drawing breaks go red |
| `focus_dev/qt_e2e.py` — real widget + real WebEngine | **25/25** (load, bridge, buttons → classic methods, widths 360/720/64/416, slide-out, safety, classic↔Focus mid-call, summary, reload replay) |
| `build_focus.py --check` — the packaged exe | builds; self-test **OK** (page loads from the package, bridge connects) |
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
