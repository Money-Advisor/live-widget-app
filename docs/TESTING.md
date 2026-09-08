# Testing — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> System-wide testing and the cross-component UAT checklist:
> [live-widget-api/docs/TESTING.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TESTING.md)

## Running the tests

```powershell
cd "Spark Flow\live-widget-app"
python -m pytest tests\ -q      # 313 tests, about 4 seconds
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

Verified on 8 September 2026: **313 passed**, and the smoke test **all 21 pass**.

## What is covered

| File | Tests | What it protects |
| --- | --- | --- |
| `test_autoupdate.py` | 47 | Version comparison as tuples rather than strings, the trusted-host gate, the `.exe`-only rule, the HTTPS requirement for off-backend downloads, filename sanitisation against `../..`, and the updater script. This is the security-sensitive area of the app — it downloads and executes a binary. |
| `test_dialer_activate.py` | 45 | Dialer-driven pop-up, start, stop, and PCI pause and resume, including which connection is addressed. |
| `test_loopback_keepalive.py` | 44 | Speaker loopback capture, format probing, and keepalive behaviour. |
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
| `test_server_migration.py` | 4 | That a saved address naming a retired host is rewritten, and that a deliberately different address is left alone. |

Several of these are regression contracts for specific field failures rather than
ordinary unit tests — the sticky sign-out, the server migration, the mic filter, the
buffering, and most of the auto-update suite. Treat them accordingly.

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
