# Handover — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> The system-wide handover, with the full priority list and access matrix:
> [live-widget-api/docs/HANDOVER.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/HANDOVER.md)

## Current state

**Version 2.9.21**, in production on agents' machines across Drafters, SFM Advisors
and Lead Generation.

| | |
| --- | --- |
| Platform | Windows only — `pyaudiowpatch` for WASAPI loopback |
| Distribution | `SparkFlowSetup.exe` (Inno Setup, per-user, no admin prompt), published as a GitHub release |
| Build | PyInstaller **folder** build, not one-file |
| Default servers | `http://192.168.80.53:8080` and `ws://192.168.80.53:8765`, with a one-time migration off the retired `192.168.80.52` |
| Live AI | On for SFM only, in a silent trial - the server scores the call and the panel shows it, but nothing interrupts the advisor |
| Tests | 294 passing, plus 21 smoke checks |
| Code | One file, `main.py`, about 4,600 lines |
| Signed | **No.** SmartScreen warns on first run. |

## What was most recently shipped

Versions 2.9.8 through 2.9.21. The earlier ones were driven by the August 2026
server move and by making silent failures visible; everything from 2.9.15 is
the live compliance panel:

- **2.9.8** stopped mistaking a busy recording server for a broken one.
- **2.9.9** repointed installs at the new server, including rewriting any saved address that still named the retired one — because a new build alone does not repoint anyone.
- **2.9.10** and the "Forgot password?" link — self-service reset from the login screen.
- **2.9.12** reports its own build on the control connection, which is what makes the dashboard's widget-version column and "update needed" badge possible.
- **2.9.13** made the manual Log Out sticky too. It had only been wired to expired and revoked sessions, so an agent could minimise it away and carry on while nothing recorded.
- **2.9.14** stopped the customer channel losing time, which had left the agent sounding late relative to the customer.
- **2.9.15 - 2.9.21, the live compliance panel.** Shipped together and only worth reading as one change. The panel is on screen for the whole of a call and between calls: a stage bar showing where the call has got to, the current stage opened out with every requirement ticked or outstanding, and the advisor's own words underneath each tick. A check made of several parts opens on a dropdown to show which parts are proved and which are still to ask.
  - **2.9.17** kept the panel on screen instead of hiding it whenever nothing was wrong, which read as the feature being broken.
  - **2.9.19** fixed rows that rendered blank, and an alert that named the wrong stage.
  - **2.9.20** added the per-check dropdown.
  - **2.9.21** made the checklist legible. Every outstanding check had been given the full red card with its own guidance, which on a 340px panel ran into itself; now exactly one item is marked due and the rest are quiet rows under a caption.

## Priorities

**1. Code-sign the installer.** SmartScreen warns on every first run today, which is
exactly the wrong signal to give someone installing a call recorder — and it makes
the "just install this" conversation harder than it needs to be. Signing would also
allow a machine-wide install rather than per-user.

**2. A DNS hostname instead of an IP.** The compile-time defaults name a specific
box. That means every server move needs a widget release plus a `RETIRED_HOSTS`
entry, and every agent who has opened Settings needs handling separately. A hostname
both boxes could answer to would make a future move need no widget change at all.
This is the highest-leverage fix in this repo.

**3. Flag a PCI pause that is never resumed.** About 562 of 3,162 pauses over three
days were never lifted, meaning everything after them was not recorded, and nothing
tells anybody. Two possible shapes: a visual reminder in the widget after some
period paused, and a server-side alert. The widget half is the cheaper one.

**4. Surface paused time on the call page.** Roughly 8% of calls contain a pause, and
QA reasonably reports the seam as a broken recording. A "3 minutes paused" note
would end a recurring stream of false reports. Needs a small backend addition too,
so it is a cross-repo change.

**5. A pre-roll buffer for dialer-driven starts.** There is a short window between
the dialer connecting the call and the widget beginning to capture, so the first
moment can be clipped. Keeping a rolling buffer and prepending it would close that.
Parked, deliberately — it adds complexity to the capture path, which is the one path
that must not break.

**6. Consider splitting `main.py`.** 4,600 lines in one file. It was deliberate —
one module, one binary, nothing to go wrong at import time in a PyInstaller build —
and it has held up. But it is now the main obstacle to anyone else working on this
app confidently. If it is split, split by boundary (audio, networking, UI, update)
rather than by size, and keep the smoke test's guarantees intact.

## Known issues

| Issue | Impact | Notes |
| --- | --- | --- |
| Installer not code-signed | Medium | Priority 1. |
| Server address is compile-time plus per-machine `QSettings` | Medium | Priority 2. The single biggest source of deployment friction. |
| Pauses never resumed are invisible | Medium | Priority 3. Real recording loss, silently. |
| First moment of a dialer-started call can be clipped | Low | Priority 5, parked. |
| Bluetooth headsets cap audio quality | Low | A rule to enforce, not a bug: wired or USB. |
| No remote kill switch or forced downgrade | Inherent | A bad build has to be replaced by publishing a good one and reinstalling. |
| `main.py` is one very large file | Medium | Priority 6. |
| macOS path exists in `build_all.py` but is untested | Low | Nothing here works without WASAPI loopback anyway. |
| Agent has no visibility of "the dialer tried to reach me and failed" | Low | The widget cannot know. The alert belongs server-side. |

## Access needed

| System | What | Who |
| --- | --- | --- |
| GitHub | Write access to `Money-Advisor/live-widget-app`, and permission to publish releases | Faseeh |
| A Windows machine | With a real microphone and speaker. Development on any other platform is not possible for this repo. | — |
| Inno Setup 6 | To build the installer | Free download |
| Dashboard account | Admin, plus their email in the backend's `SUPERADMIN_EMAILS`, to publish a release in Settings ▸ Releases | Faseeh |
| Backend and recording server | Running, local or production, for anything beyond unit tests | Faseeh |
| Agents' machines | For a field diagnosis: their `widget.log`, and occasionally a remote session | TIG IT |
| Code-signing certificate | Does not exist yet — priority 1 | TIG IT / procurement |

## Key technical knowledge

The things that are not obvious from reading the code, each of which has cost real
time.

**`QSettings` beats a new build.** The most important operational fact here. Saved
server addresses override the compile-time defaults, so shipping a new default
repoints nobody who has ever opened the Settings panel. `_migrate_server_urls()`
handles only hosts listed in `RETIRED_HOSTS` — **add the old host there before every
server move** or the migration does nothing. `QSettings` also does not travel to a
new machine, so a fresh install always starts signed out.

**The protocol is a shared contract.** `CHUNK = 4096`, the binary frame layout
(`struct.pack("I", len(stream_type)) + stream_type + pcm`), and the handshake order.
Change one side without the other and recording breaks in the field, silently.
Always run the recording server's test suite alongside this one when touching it.

**Qt threads only.** No asyncio, no `await`. Every UI update from a worker goes
through a `pyqtSignal` or `QTimer.singleShot(0, ...)`. Touching a widget from a
worker thread crashes the process rather than raising, and the crash appears far
from the cause.

**A folder build, never one-file.** A one-file build unpacks 44 MB into `%TEMP%` on
every launch; with antivirus scanning it, agents get
`Failed to load Python DLL ...python312.dll` and end up with **no widget at all**.
The failure is in the PyInstaller bootloader, before any of our code runs, so it
cannot be handled in-app.

**The updater downloads and executes a binary,** so `is_safe_installer_url()` and
`safe_installer_filename()` are security code. `.exe` paths only, the backend's own
host or HTTPS GitHub only, and the version string is sanitised before it touches a
path. 47 tests cover this; treat them as contracts.

**Silence must never be silent.** Two of the worst faults in this app's history were
things that failed without telling anyone: a revoked session while the window was in
the tray, and a widget pointing at a dead server. Both now announce themselves. Any
new failure path should be held to the same standard — an agent who cannot tell that
recording has stopped will keep working, and the calls are simply gone.

**The customer channel depends entirely on the selected speaker device.** If it is
not the device the call plays through, the widget records an idle output. This is the
most common real fault reported from the field, and it cannot be fixed in code.

**Bump the version in two places** — `main.py` and `installer/installer.iss`. Two
binaries once shipped under one version number, which made it impossible to tell
what an agent was running.

**Test the packaged executable, not just `main.py`.** Missing hidden imports and
unresolved bundled assets only appear in the built binary.

**No customer data on the agent's disk.** Audio is streamed, the log carries no
names or references, and the only local persistence is `QSettings`. The one
exception is the resume spool, which holds audio while a connection is down and is
purged after seven days.

## If you are picking this up cold

1. Read [ARCHITECTURE.md](ARCHITECTURE.md), especially the threading model and the protocol section. Then read the [recording server's ARCHITECTURE.md](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/ARCHITECTURE.md) — half the contract lives there.
2. Get it running with [SETUP.md](SETUP.md) and **immediately** repoint it at localhost, or you will be testing against production.
3. Run both test suites so you know what green looks like, then read `test_autoupdate.py` and `test_dialer_activate.py` — between them they describe most of what this app actually does.
4. Record one real call end to end and check both channels have audio. That single exercise teaches more about this system than any amount of reading.
5. Read [TROUBLESHOOTING.md](TROUBLESHOOTING.md) before the first agent report reaches you — most of them are one of five things.

## Related documentation

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [SETUP.md](SETUP.md) · [DEPLOYMENT.md](DEPLOYMENT.md)
- [DATABASE.md](DATABASE.md) · [API_INTEGRATIONS.md](API_INTEGRATIONS.md) · [TESTING.md](TESTING.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- System-wide: [live-widget-api/docs/](https://github.com/Money-Advisor/live-widget-api/tree/main/docs)
