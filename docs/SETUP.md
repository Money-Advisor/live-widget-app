# Setup — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> Full-system setup: [live-widget-api/docs/SETUP.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/SETUP.md)

## Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Windows | 10 or 11 | **Windows only.** `pyaudiowpatch` provides WASAPI loopback capture, which is how the customer's audio is recorded. There is no macOS or Linux equivalent in this codebase. |
| Python | 3.12 | The other three repos share the same virtual environment. |
| The backend | running | Login and configuration. |
| The recording server | running | Anything involving audio. |
| A microphone and a speaker | real ones | Loopback capture needs an actual output device. |
| Inno Setup 6 | optional | Only to build the installer. |

## Install

```powershell
cd "<project root>\Spark Flow\live-widget-app"

# either the shared venv one level above the four repos
..\..\.venv\Scripts\python.exe -m pip install -r requirements.txt

# or a local one
pip install -r requirements.txt
```

Dependencies are deliberately few:

```
PyQt6>=6.6              the UI
pyaudiowpatch>=0.2.12   WASAPI loopback capture
websocket-client>=1.7   the audio socket
requests>=2.31          REST
pyinstaller>=6.0        packaging
```

## Run

```powershell
python main.py
```

**Then point it at your own machine.** Open Settings (the gear icon) and set:

| Field | Local value |
| --- | --- |
| API base URL | `http://localhost:8000` |
| Recording server URL | `ws://localhost:8765` |

Save. The compile-time defaults point at the **production** server
(`http://192.168.80.53:8080` and `ws://192.168.80.53:8765`), so skipping this step
means a development widget talking to production.

Those values are stored in `QSettings` and persist, so you only do it once per
Windows user account per machine.

## Configuration

There is no `.env` and no configuration file. Two layers, and the second wins.

### 1. Compile-time constants (`main.py`, around lines 226–260)

```python
DEFAULT_API_BASE_URL = "http://192.168.80.53:8080"
DEFAULT_RECORDING_WS = "ws://192.168.80.53:8765"
ORG = "Spark Flow";  APP = "Widget"
CHUNK = 4096
APP_VERSION = "2.9.23"
WS_CONNECT_TIMEOUT = 10
WS_HANDSHAKE_TIMEOUT = 30
WS_STREAM_TIMEOUT = 5
```

`APP_VERSION` must match `AppVersion` in `installer/installer.iss`. Two binaries
briefly shipped under one version number during the August 2026 move, which made it
impossible to tell what an agent was actually running.

### 2. `QSettings` — per Windows user

`QSettings("Spark Flow", "Widget")`, stored in the registry at
`HKCU\Software\Spark Flow\Widget`.

| Key | Holds | Set by |
| --- | --- | --- |
| `api/base_url` | Backend URL | Settings panel |
| `ws/url` | Recording server URL | Settings panel |
| `auth/token` | The Firebase ID token | Login, with "Remember me" |
| `auth/refresh_token` | The refresh token | Login |
| `auth/user` | The cached user record | Login |
| `config/json` | The cached compliance configuration | Config fetch |
| `config/etag` | Its ETag, for `If-None-Match` | Config fetch |
| `audio/mic_name` | The remembered input device | Device selection |
| `audio/spk_name` | The remembered output device | Device selection |
| `update/attempts` | Auto-update retry bookkeeping | Update check |

**`QSettings` overrides the compile-time defaults.** That is the single most
important operational fact about this application, and it has two consequences worth
stating plainly:

- **A new build does not repoint an agent** who has ever opened the Settings panel. `_migrate_server_urls()` handles the one specific case of a retired host; everything else needs the panel, a registry push, or the agent.
- **`QSettings` does not travel to a new machine.** A fresh install always starts signed out, with the code defaults and the first-run microphone gate.

To reset a development machine to a clean state, delete
`HKCU\Software\Spark Flow\Widget` with `regedit`, or:

```powershell
reg delete "HKCU\Software\Spark Flow\Widget" /f
```

## Testing

```powershell
python -m pytest tests\ -q      # 302 tests, ~4 seconds
python smoke_test.py            # 21 headless checks
```

Run both **from the repo root** so `import main` resolves — there is no `conftest.py`
or `pytest.ini` at the root doing that for you. Scope pytest to `tests/`, because
bare collection picks up the root-level `smoke_test.py` and breaks.

All Qt runs offscreen, so no window appears and nothing needs a display.

## Building

```powershell
python build_all.py
```

Output is `dist\SparkFlow\SparkFlow.exe` — a **folder** build, deliberately not
one-file. See [ARCHITECTURE.md](ARCHITECTURE.md#a-folder-build-not-one-file) for why
that matters.

```powershell
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss
```

Output is `installer\Output\SparkFlowSetup.exe`. Per-user install, no administrator
prompt, with a desktop-icon option and auto-start-on-sign-in both checked by
default.

`dist/`, `build/`, `installer/Output/`, `*.spec` and the probe build folders are all
gitignored. The binaries are published as GitHub releases, never committed.

Full release procedure: [DEPLOYMENT.md](DEPLOYMENT.md).

## Setup problems people actually hit

**`pyaudiowpatch` will not install.** It is Windows-only. On another platform there
is no path forward for this repo — develop the other three there instead.

**No loopback device appears.** Loopback needs a real output device present and
enabled. A machine with no speakers or headphones connected, or with the output
disabled, has nothing to capture.

**The widget starts but cannot log in.** It is almost certainly still pointing at
production while the local backend is what is running. Check the Settings panel
first, before anything else.

**A 502 at login.** The address in `QSettings` names a retired server. The migration
handles `192.168.80.52`; anything else needs the panel.

**The first-run microphone gate blocks Start.** By design — an agent must not be
able to start recording before choosing a device. Pick one in Settings.

**Krisp does not appear in the microphone list.** Also by design. The widget records
the physical device, because suppression mangles fast speech and compliance review
needs to hear what was said.

**Recording starts but the customer is silent.** The selected **speaker** device is
not the one the call plays through. This is the most common real fault in the field
and it is fixed on the agent's machine, not in code.

**Tests fail on import.** You are not in the repo root, or you ran bare `pytest`
instead of `pytest tests/`.

**Behind a TLS-inspecting corporate proxy**, `pip install` fails on certificate
validation until pip is pointed at the corporate CA bundle. See the
[system-wide setup notes](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/SETUP.md#setup-problems-people-actually-hit).

## Where the log is

```
%LOCALAPPDATA%\Spark Flow\logs\widget.log
```

This is a `--windowed` build with no console, so that file is the only record of
what the widget did. It is the first thing to ask an agent for.

## Related documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — threading, audio, the protocol
- [DEPLOYMENT.md](DEPLOYMENT.md) — building, releasing, repointing agents
- [TESTING.md](TESTING.md) — the suites and the on-machine checklist
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — agent-reported faults
