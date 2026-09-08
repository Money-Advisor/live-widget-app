# Project Overview — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> System-wide overview: [live-widget-api/docs/PROJECT_OVERVIEW.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/PROJECT_OVERVIEW.md)

## What this is

The only part of Spark Flow that agents ever see, and the only part that runs on
their machines. A small PyQt6 application, installed per-user on Windows, that sits
in the system tray all day and records customer calls.

It matters more than its size suggests: **if the widget is not running, or is
pointing at the wrong server, that agent's calls are simply not recorded** and
nothing else in the system can compensate. Most capture gaps trace back to this
application's state on one person's PC.

## What it does

**Signs the agent in.** Native PyQt6 login against `POST /auth/login-widget`. With
"Remember me" the token and refresh token are stored in `QSettings`, and the widget
silently renews before the one-hour expiry, so agents sign in once and not again.
There is a "Forgot password?" link on the login screen.

**Records the call, on both sides.** The agent's microphone and the customer's
audio, the latter captured as a WASAPI loopback of the selected speaker device.
Both stream to the recording server over one WebSocket as raw PCM.

**Starts and stops itself.** A persistent control connection to the recording server
registers the agent, so when XDial connects a call the widget pops up and begins
recording with no action from the agent at all. It stops the same way.

**Pauses for card details.** A PCI pause button drops audio at the single send
choke point, so nothing is captured while a customer reads out a card number. Both
channels pause together. The dialer can also drive pause and resume.

**Survives a network blip.** If the connection dies mid-call the widget buffers
audio locally and replays it on reconnect, so the recording has no gap. The server
holds the session open for 180 seconds; the widget's own deadline is 150.

**Shows compliance coaching** — amber and red alert chips, forbidden-phrase hits,
customer cues, and transcription status — when the live AI pipeline is switched on.
That is currently off, so agents see a recording indicator and a post-call "saved"
card instead.

**Keeps itself up to date.** It checks `GET /api/version` and offers to download
and install a newer release, refusing any URL that is not the backend's own host or
an HTTPS GitHub release.

**Makes a sign-out impossible to miss.** While signed out the window forces itself
back on screen and refuses to hide, because a revoked session used to fail silently
in the tray while the agent carried on working and nothing recorded.

## Who runs it

Every agent in Drafters, SFM Advisors and Lead Generation. They do not use the web
dashboard — signing in there redirects them straight to the download page.

Installation is per-user with no administrator prompt, and by default it starts
minimised when the agent signs in to Windows.

## Configuration

There is no `.env` and no configuration file. Two layers:

1. **Compile-time defaults** in `main.py` — the production API and recording-server addresses.
2. **`QSettings`**, per Windows user, in the registry under `HKCU\Software\Spark Flow\Widget`.

`QSettings` wins. That single fact is the source of most deployment friction here:
a new build with new defaults does **not** repoint an agent who has ever opened the
Settings panel, and `QSettings` does not travel to a new machine, so a fresh install
always starts signed out.

## Current state (27 August 2026)

| | |
| --- | --- |
| Version | **2.9.28** |
| Platform | Windows only — `pyaudiowpatch` is required for WASAPI loopback |
| Distribution | `SparkFlowSetup.exe`, built with PyInstaller and Inno Setup, published as a GitHub release |
| Build type | A **folder** build, not one-file (see [ARCHITECTURE.md](ARCHITECTURE.md#a-folder-build-not-one-file)) |
| Server | Points at 192.168.80.53 by default, with a one-time migration off the retired 192.168.80.52 |
| Live AI | On for SFM only, in a silent trial - scored and shown on the panel, never interrupting |
| Tests | 318 passing, plus 21 smoke checks |
| Logs | `%LOCALAPPDATA%\Spark Flow\logs\widget.log` |

## Recent history worth knowing

Versions 2.9.9 through 2.9.14 were largely about the August 2026 server move and
about making failures visible; 2.9.15 onward is the live compliance panel:

- **2.9.9** repointed installs at the new server, including rewriting a saved address that still named the retired one.
- **2.9.10 / "Forgot password?"** self-service reset from the login screen.
- **2.9.12** reports its own build to the server, so the dashboard can show who is out of date. Anything older shows blank, which is itself the signal.
- **2.9.13** made the manual Log Out sticky too — it was only wired to expired and revoked sessions.
- **2.9.14** stopped the customer channel losing time, which had left the agent sounding late relative to the customer.
- **2.9.15 - 2.9.28, the live compliance panel.** Shipped together and only worth reading as one change. The panel is on screen for the whole of a call and between calls: a stage bar showing where the call has got to, the current stage opened out with every requirement ticked or outstanding, and the advisor's own words underneath each tick. A check made of several parts opens on a dropdown to show which parts are proved and which are still to ask.
  - **2.9.17** kept the panel on screen instead of hiding it whenever nothing was wrong, which read as the feature being broken.
  - **2.9.19** fixed rows that rendered blank, and an alert that named the wrong stage.
  - **2.9.20** added the per-check dropdown.
  - **2.9.21** made the checklist legible. Every outstanding check had been given the full red card with its own guidance, which on a 340px panel ran into itself; now exactly one item is marked due and the rest are quiet rows under a caption.
  - **2.9.22** fixed a crash that had been killing the widget after every scored call, and stopped the panel being squashed. The crash: the rulebook server sends the score as a breakdown dict, the widget did `float()` on it, and PyQt6 answers an unhandled exception in a slot by aborting the process - so the widget vanished a second after the summary appeared, leaving no traceback. The squashing: the window only ever resized sideways, so the panel took whatever height the call card left it and every row was squeezed below its natural size. The panel scrolls now, and the window grows to fit up to the screen edge.
  - **2.9.23** made the end-of-call summary readable. It listed raw check ids at the advisor - "onb.dpa_dob, cc.aryza_loaded, ff.duration" - because the widget's id -> label map is built from the backend's `criteria` config, which is the old matcher's list and holds none of the rulebook's ids. The server now sends the label and the stage with the verdict (the same reasoning as migration 017 storing the label on the row), and the summary draws the same bullets the advisor read during the call, with the misses grouped under their stage.
  - **2.9.24** stopped the widget flashing a green **100%** for two seconds at every hang-up. It filled the gap before the server answered with a summary of its own, computed from the OLD matcher's criteria list; on a rulebook call none of the check ids are in that list, so nothing counted as missing and everything counted as covered. A rulebook call now waits, saying "working out your score", with a 25-second backstop to the plain saved confirmation if the summary never lands. The old matcher keeps its instant summary, which is genuinely right for it.
  - **2.9.25** made the panel move smoothly. Three things were fighting each other: the checklist rebuilt every row on every server message - about twice a second, whether anything had changed or not, which is what read as flickering; a rebuild painted itself part-built at least once; and every height change was a hard jump. Identical messages are now free, a rebuild never paints half-done, and the panel glides to its new height. Measured at 60fps (16ms median frame, no dropped frames) on all four transitions: a stage appearing, a dropdown opening, a dropdown closing, and a check going green.
  - **2.9.26** removed a scrollbar from a panel that fits. A word-wrapped label's plain size hint is one line, so a ten-row Onboarding stage measured about 15px shorter than it really is; the panel was sized to that and the content overflowed by exactly that much. It now asks the layout how tall it is *at the viewport width* rather than taking its size hint.
  - **2.9.27** stopped the checklist vanishing mid-call. The server sends a "good job" message the instant a check goes green - no stage fields on it at all - and the widget read that as "there is no checklist any more", hid the panel, and then skipped the very next (identical) state message as a no-op rebuild. So the panel dropped to a bare heading and only recovered when some check finally changed. Seen on a 22-minute call.
  - **2.9.28** added the customer-safety card. When the server judges that a caller may be at risk of self-harm, a red card appears above everything else on the panel with the wording to use and the numbers to read out - Samaritans, SHOUT and 999. It is the only message the panel shows during a silent trial, and it does not depend on scoring being switched on. The wording, and what happens after it appears, are compliance decisions still outstanding.

## Owners and contacts

| Area | Person |
| --- | --- |
| This app, and all four repos | **Faseeh Iqbal** — faseeh.iqbal@theinsolvencygroup.co.uk |
| Business owner | **Azzam Sheikh** |
| XDial dialer (vendor) — what triggers a pop-up | **Keith** |
| Rolling the installer out to agents' machines | TIG IT |

## Related documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — threading, audio capture, the protocol
- [SETUP.md](SETUP.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [TESTING.md](TESTING.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) · [HANDOVER.md](HANDOVER.md)
- System-wide: [live-widget-api/docs/](https://github.com/Money-Advisor/live-widget-api/tree/main/docs)
