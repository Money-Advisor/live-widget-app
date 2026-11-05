# Testing — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> System-wide testing and the cross-component UAT checklist:
> [live-widget-api/docs/TESTING.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TESTING.md)

## Running the tests

```powershell
cd "Spark Flow\live-widget-app"
python -m pytest tests\ -q      # 430 tests, about 7 seconds
python smoke_test.py            # 21 headless checks
python -m pytest tests\test_dialer_activate.py -v
python -m pytest -k "mic or loopback" tests\ -q
```

Two rules:

- **Run from the repo root**, so `import main` resolves. There is no root `conftest.py` or `pytest.ini` doing it for you.
- **Scope pytest to `tests/`.** Bare collection picks up the root-level `smoke_test.py` and breaks.

All Qt runs offscreen, so nothing appears on screen and no display is needed. No
database, no backend and no audio hardware are required — devices, sockets and HTTP
are all faked.

Verified on 21 September 2026: **430 passed**, and the smoke test **all 21 pass**.

## What is covered

| File | Tests | What it protects |
| --- | --- | --- |
| `test_autoupdate.py` | 47 | Version comparison as tuples rather than strings, the trusted-host gate, the `.exe`-only rule, the HTTPS requirement for off-backend downloads, filename sanitisation against `../..`, and the updater script. This is the security-sensitive area of the app — it downloads and executes a binary. |
| `test_update_handoff.py` | 26 | Updates that land (2.9.64): the helper waits for the widget's own processes before installing - checked in the script and RUN for real against a stand-in process in a temp folder (the installer starts only after it has gone; without the wait it started while it was there; gives up after its limit; another folder's copy is not waited for; an apostrophe and % in the folder; the folder given by its 8.3 name, and a process started by it), the widget hands the installer its log beside `widget.log`, twice a day not twice ever (the old count no longer blocks), and what the next start says about the last update. |
| `test_keep_open.py` | 15 | A coached call keeps the panel open (2.9.64): only on a connected call whose live AI is on; the page is told; a fold to the bar refused (and a bar from before the call opened), allowed with live AI off and between calls; "x", Windows' minimise and Alt+F4 refused, unchanged otherwise; folded and hidden again after the call. |
| `test_dept_question.py` | 35 | "Which department was this call for?" (2.9.65, MD2), through the real connect and stop: the choices (the main department and those filing by code, main first; none while the main one is off or with one choice); the answer's request and its refusals; the call's row from the server's ack; asked on a call of 30 s or more, loaded once when it connects and off the UI thread, still asked when the departments arrive after the end, back on screen from the tray; until answered the next-call button, a fold, "x", Windows' minimise and Alt+F4 are refused and a bar opens; a coached call's end goes straight to it; the answer off the UI thread, one at a time, only a choice, changeable, a failed save frees the agent, a manager's move stands; a new call (starting, connecting, the dialer's next) drops it, so do a sign-out and a quit. |
| `test_dialer_activate.py` | 45 | Dialer-driven pop-up, start, stop, and PCI pause and resume, including which connection is addressed. |
| `test_dialer_switch.py` | 11 | A dialer start during a call (26 Oct): a new call ends the old one (stop and `session_end` on its socket) before it starts, never two at once; the old call's late messages and 25 s fallback cannot reach the new call; its socket is still closed; the same call's start again is ignored (lead, else a real reference, within 120 s); a start while connecting is queued, newest wins. |
| `test_loopback_keepalive.py` | 48 | Speaker loopback capture, format probing, and keepalive behaviour. Its fake device holds only what Windows holds (two chunks and a little - measured 0.174-0.185 s at 48 kHz, 5 Nov 2026); it used to hold everything, which is how a test claiming "our own slow send never fabricates time" passed while the field lost minutes of sound to slow sends. Now: a held-up capture loses what Windows cannot hold, keeps the clock, and is put down to the widget, never the device; a real dead device is still called one; a hold-up inside the buffer costs nothing and colours nothing. |
| `test_send_queue.py` | 10 | GF1's ordered send queue: order kept across memory, the backlog file and back, with two producers and the sender at full speed; the file deleted once sent; a disk that refuses writes keeps frames in memory without reordering; status frames first; an unreadable file reported, not spun on; the file covered by the spool purge. |
| `test_send_queue_streamer.py` | 20 | A live call on the queue: `send_audio` never waits on a 0.3 s-per-send socket; mic and speaker keep capture order; `stop`/`session_end`/`close` wait behind the audio; quit flushes; PCI pause decided at capture; the link dying mid-backlog spools the rest in order; a long backlog goes to disk and back; queued audio dropped after giving up; the slow link logged and reported (`link_status`, ahead of the backlog), nothing reported on a healthy call or a dead link; `connect()` turns the queue on; the sender survives a failed queue read and a failed report, and an unopenable backlog file never wedges it; the never-connected and after-resume paths unchanged. |
| `test_capture_never_waits.py` | 3 | In real time: a device holding 0.175 s, a 1.5 s slow spell at 0.3 s a send - the old synchronous send loses the sound and inserts silence (blamed on the widget, not the device); through the queue nothing is lost, nothing inserted, every frame arrives in order. |
| `test_call_buffering.py` | 28 | Local buffering and replay across a mid-call disconnect, so the recording has no gap. |
| `test_mic_filter.py` | 26 | That Krisp's virtual microphone is excluded, and that tolerant device-name matching survives Windows renaming a device (including the curly-apostrophe case). |
| `test_session_persistence.py` | 25 | Session state across restarts. |
| `test_sticky_signout.py` | 15 | That a sign-out cannot be minimised away — including the manual Log Out button, which was missing until 2.9.13. |
| `test_stage_tracker.py` | 18 | The compliance panel: that it stays hidden when the old matcher is on the other end and sends none of the new fields, that a check opens to show its individual parts and stays open across the next transcript fragment, that exactly **one** outstanding check is marked due, and that a full stage does not inflate the panel — the last two are regression contracts for a checklist that was unreadable on a real screen. |
| `test_panel_on_top.py` | 4 | That the panel is on screen for the whole call and stays visible between calls, rather than hiding whenever nothing is wrong. |
| `test_handshake_timeout.py` | 9 | The 30-second handshake deadline. |
| `test_forgot_password.py` | 8 | The reset flow on the login screen. |
| `test_token_refresh.py` | 7 | Silent renewal before the one-hour expiry. |
| `test_hidden_fields.py` | 6 | The `hide_customer_fields` toggle. |
| `test_user_restore.py` | 4 | Restoring the signed-in user from `QSettings`. |
| `test_advisor_alerts_panel.py` | 58 | The left column's three kinds of card competing for one column (the safety card condenses, a correction trims to one, reminders go first), and since 2.9.58 a card with its own title - the I&E clarification popups - drawn with that title and its message alone, a card without one unchanged. |
| `test_alerts_card_drawn_whole.py` | 5 | A correction card is drawn whole the first time - what the column shows at rest equals a fresh repaint, four times over - and the column still fades in, with the effect off once it has. The old code drew the card cut off on most runs. |
| `test_ie_panel_widget.py` | 34 | The live I&E column, drawn from messages built by the server's own code: hidden until sent, the window grows by exactly the column and the card does not move, the width comes back at the end of the call, it only ever slides left, it never makes the window taller, the income view shows only what was given, groups closed until opened and staying open through an update, £0 and "—", amber saying why, DI hidden until said, every guideline dot the same size, and (ref134) a cut name's hover text drawn on a solid tooltip, not a black box, with none on a name shown whole. Every guard was removed and its test seen red. ; a line of several amounts opens to its parts (closed and drawn as before until opened; never for one amount, whatever the message says; never widens the window) |
| `test_server_migration.py` | 4 | That a saved address naming a retired host is rewritten, and that a deliberately different address is left alone. |

Several of these are regression contracts for specific field failures rather than
ordinary unit tests — the sticky sign-out, the server migration, the mic filter, the
buffering, and most of the auto-update suite. Treat them accordingly.

## The panel (2.9.59+)

| What | Run |
| --- | --- |
| The page's rules (card order, auto-clear, safety, popups, the continuing-case banner and carried text; the CAT flags section) | `node --test focus/tests/*.test.cjs` - the file pattern, Node 22 does not take the folder (30 tests in `model.test.cjs` - the 30th, 2.9.67: the silent-client warning raised and cleared by the server only, client side only; 21 in `cat.test.cjs`, 2.9.66: cards marked `in_cat_section` hidden only beside a `cat_section`, the bar's count and summary, the sheet's group order, each flag announced once per id and occurrence, the pop's shape) |
| How the page talks to MainWindow, window placement, "x" locked in a call | `python -m pytest tests/test_focus_ui.py` |
| Every screen state rendered in Edge and checked | `python focus_dev/check_harness.py` (screenshots: `shoot_harness.py <dir>`); 57 checks on 25 Oct, including the `case-*` scenarios (banner full and compact, name mismatch, carried rows, parts, I&E figures, carried cards and a carried held card); 77 on 30 Oct with the five `coached-*` screens (2.9.64: the fold greyed out, a bar opened by a coached call and given back when it ends); 93 on 3 Nov with the 16 `dept-*` screens (2.9.65: the question on each kind of summary, saving, answered, Change, a failed save, a manager's move, a long name, the bar opened and given back); 129 on 5 Nov with the 36 `cat-*` screens (2.9.66, CAT flags: the bar at 0, waiting and with a count; each kind of pop, several at once, one restarted, one a flag leaves, one emptied, one landing by "Move it now" and one by itself after 6 s; the sheet with all four groups, payments, candidates, back from CAT, waiting, done open and closed, empty, new flags while open; no pop while paused, folded, with live AI off or after a new call; a CAT card in `trigger_actions` hidden only beside a section), and on every other screen no CAT bar or pop; 135 with the six `live-silent-*` screens (2.9.67, TG1: the client's side silent - the banner, the foot and the folded bar; cleared; none while paused, on the panel or the bar; shown on a recording-only call), and on every other screen no silent-client warning. The page's sends are in a hidden `#sent` element, so a check can prove a tap sent the answer and a locked button sent nothing. `check_harness.py <scenario ...>` checks only those; a third list in an entry is strings that must appear in that order; a scenario's optional `budget` (after its size) gives the page more than 3 s before it is read |
| The real window + real WebEngine, buttons -> MainWindow methods | `python focus_dev/qt_e2e.py <out_dir>` |
| The bar between calls and the tray in the real window (2.9.62): "-", "x", a call bringing it back in its shape, staying a bar through a call's start and end, score -> summary, Done, safety and sign-in opening the panel - with the window's real width and place at each step. 2.9.64: those calls have live AI off; a coached call opens the panel from the bar, greys the fold, refuses a fold, "x", Windows' minimise and Alt+F4, and gives the bar back when it ends. 2.9.65: the department question through the REAL connect and stop - back from the tray as the panel, everything locked, a tap files the call and gives the bar back, Change, under 30 s not asked, a failed save frees the agent, a coached call goes straight into it, the dialer's next call drops it | `python focus_dev/minimise_e2e.py <out_dir>` (64 checks; print is buffered - run with `python -u`) |
| Nothing flashes on opening (inside Qt / as Windows sees it) | `focus_dev/startup_blinks.py`, `focus_dev/startup_windows.py [--exe dist/SparkFlow/SparkFlow.exe]` |
| The built exe | `python build_all.py --check` |
| The installer upgrades an old widget in place - nothing running; the OLD widget OPEN with the update helper every widget up to 2.9.63 runs; the old widget open with the new helper (2.9.64). "Open" = the old exe's own `--selftest` (real window and WebEngine, throwaway settings) plus a stand-in Qt WebEngine process in its `_internal` that outlives it; checked from the installer's log that it waited and that Windows' Restart Manager found nothing of the widget's still running when files were replaced; the real widget's settings unchanged (a running real widget's own token and config refreshes aside) | `python focus_dev/upgrade_test.py <old dist> <old installer.iss>` (`--no-installer-wait`: without the installer's wait; `UPGRADE_ONLY=B`; `UPGRADE_SHORT_PATHS=1`: from part-8.3 `%TEMP%` paths) |

All of these use throwaway settings. The existing suite does not (see the
warning at the top of `tests/test_focus_ui.py`): `conftest.py`'s
`setDefaultFormat` does not reach `QSettings(ORG, APP)`, so run it on a PC where
nobody is signed in, or swap `main.QSettings` for a temp INI first.

## The smoke test

`smoke_test.py` runs 21 assertions in a headless Qt application: icons render,
custom widgets are what they claim to be, and — importantly — **that no
`QWebEngineView` and no login bridge exist**. The login screen used to be a web view
loading `assets/login.html`; reintroducing one would add a browser engine and its
own update surface to a call recorder, so the smoke test guards against it coming
back.

It is fast and worth running on every change.

## What is not covered

The tests deliberately fake audio devices, sockets and HTTP, which means:

- **Real audio capture is untested.** Whether a specific headset actually produces two healthy channels can only be checked on a real machine.
- **The packaged executable is untested.** PyInstaller problems — a missing hidden import, a bundled asset that does not resolve through `resource_path()` — appear only in the built binary.
- **The installer is untested.** Per-user install, the auto-start registry entry, and shortcuts.
- **Real UI behaviour is untested.** Offscreen Qt will not tell you that a panel is unreadable or that a button is off-screen at 125% scaling.

Everything in the next section exists to cover those gaps.

## On-machine checklist

Run this on a real Windows machine, with the built executable, before releasing.
Marked **(core)** where a regression means calls are not recorded.

### The build itself
- [ ] `python build_all.py` produces `dist\SparkFlow\SparkFlow.exe` as a **folder** build.
- [ ] Launch the built exe, not `main.py`. It starts with no missing-DLL or missing-module error. **(core)**
- [ ] The tray icon appears; closing and minimising both hide to the tray rather than exiting.
- [ ] Only one instance can run — launching again brings the existing one forward.
- [ ] `APP_VERSION` and the installer's `AppVersion` match, and the About or title shows the right number.

### Sign-in
- [ ] Sign in with a real account. The company name appears. **(core)**
- [ ] Restart — with "Remember me" it goes straight to the ready screen without asking for a password. **(core)**
- [ ] "Forgot password?" sends a reset email.
- [ ] Sign in as an account marked former staff — it is refused with a clear message.
- [ ] Leave it running past an hour — the token renews silently and the widget stays usable. **(core)**

### Devices
- [ ] Both device lists populate, and **Krisp does not appear** in the microphone list.
- [ ] Choose a microphone and a speaker, restart, and they are remembered.
- [ ] Unplug and replug a USB headset while the panel is open — the list refreshes.
- [ ] On a fresh install, Start is gated until a microphone is chosen.

### Recording a call
- [ ] Press Start manually. Recording begins and the UI does not freeze. **(core)**
- [ ] Speak, and have someone speak on the other side, for at least 30 seconds.
- [ ] Press Stop. The summary screen appears, then "recording saved". **(core)**
- [ ] On the server, the file exists at `recordings/<reference>/<session id>.mp3`. **(core)**
- [ ] **Both channels have audio** — check per-channel levels, roughly −20 to −40 dB RMS. Channel 1 is the agent, channel 2 the customer. **(core)**
- [ ] The two channels are in sync: the agent does not sound late relative to the customer (this was the 2.9.14 fix).

### Dialer-driven recording (the real test)
- [ ] With the widget idle in the tray, trigger a call event as XDial would (see the [UAT checklist](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TESTING.md#uat-checklist)).
- [ ] The widget pops up on its own and records. **(core)**
- [ ] Sending `event=end` stops it. **(core)**
- [ ] The webhook response says `widget_notified:true`. A 200 on its own proves nothing.

### PCI pause
- [ ] Pause mid-call, speak, resume.
- [ ] The finished recording jumps from before the pause to after it, on **both** channels.
- [ ] The UI clearly shows it is paused — an agent must never think they are recording when they are not. **(core)**

### Reconnection
- [ ] Disconnect the network for about 20 seconds mid-call, then restore it.
- [ ] The widget recovers and the finished recording has **no gap**. **(core)**
- [ ] Disconnect for longer than 150 seconds — the call finalises rather than hanging, and the agent is told.
- [ ] Slow the network mid-call (2.9.68): `widget.log` shows `[send] the connection to the server is slow …` then `[send] caught up …`, NO `[gapfill] … device stopped producing`, and the finished recording has no silent stretches. **(core)**

### Sticky sign-out
- [ ] Revoke the session server-side while the widget is hidden in the tray.
- [ ] The window forces itself back on screen and refuses to hide. **(core)**
- [ ] It does **not** steal keyboard focus — type into another window while it appears and no characters are lost.
- [ ] The manual Log Out button behaves the same way.
- [ ] Quit from the tray still works.

### Auto-update
- [ ] With a newer version published in Settings ▸ Releases, the widget offers the update.
- [ ] Accepting it downloads, installs and relaunches, and `QSettings` survives — no re-sign-in.
- [ ] A malformed or non-HTTPS download URL is refused rather than executed.

### The installer
- [ ] `SparkFlowSetup.exe` installs with **no administrator prompt**.
- [ ] The desktop icon and auto-start options work; after a Windows sign-in it starts minimised.
- [ ] Installing over an existing version preserves settings and the session.
- [ ] Uninstall removes the shortcuts.

### Presentation
- [ ] At 100%, 125% and 150% Windows scaling, nothing is clipped or unreadable.
- [ ] The alert panel is legible at whatever size agents actually leave the window.

## Before you push

1. `python -m pytest tests/ -q` and `python smoke_test.py` — both green.
2. **Build and run the packaged executable.** Passing tests against `main.py` says nothing about the binary.
3. If you touched the protocol — the chunk size, the framing, the handshake, or a message type — run the **recording server's** suite as well. Both sides have to change together, and a mismatch fails silently in the field.
4. If you touched audio capture, do the two-channel level check on a real machine.
5. If a document in `docs/` is now wrong, fix it in the same commit.

## Related documentation

- [live-widget-api/docs/TESTING.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TESTING.md) — the end-to-end UAT checklist
- [ARCHITECTURE.md](ARCHITECTURE.md) — what the tests are protecting
- [DEPLOYMENT.md](DEPLOYMENT.md) — building and releasing
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — what agents report
