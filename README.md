# Spark Flow — Desktop Widget (`live-widget-app`)

The desktop application TIG's agents run during customer calls. It signs the agent
in, pops up on its own when the dialer connects a call, records the agent's
microphone and the customer's audio to the recording server, lets the agent pause
recording while card details are read out, and shows a summary when the call ends.
It lives in the Windows system tray the rest of the time.

**Version 2.9.14** · **Owner:** Faseeh Iqbal (developer / technical owner) ·
**Business owner:** Azzam Sheikh
**Status:** in production on agents' machines across three departments.

Spark Flow is four repos. The system-wide documentation lives in
[live-widget-api](https://github.com/Money-Advisor/live-widget-api), which is the hub.

| Repo | What it is |
| --- | --- |
| [live-widget-api](https://github.com/Money-Advisor/live-widget-api) | FastAPI backend, PostgreSQL, Firebase auth, scheduled jobs — **the hub** |
| [live-widget-server](https://github.com/Money-Advisor/live-widget-server) | Recording server: audio capture, post-call audio, live AI pipeline |
| [live-widget-frontend](https://github.com/Money-Advisor/live-widget-frontend) | Next.js admin/supervisor dashboard |
| **live-widget-app** (this repo) | The PyQt6 desktop widget |

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | What the widget does, who runs it, current state |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Threading model, audio capture, the protocol, technical decisions |
| [docs/SETUP.md](docs/SETUP.md) | Local development, configuration, the QSettings keys |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Building, the installer, releasing, and repointing agents |
| [docs/DATABASE.md](docs/DATABASE.md) | No direct access — what the widget sends and where it lands |
| [docs/API_INTEGRATIONS.md](docs/API_INTEGRATIONS.md) | The backend endpoints and the recording-server protocol |
| [docs/TESTING.md](docs/TESTING.md) | Test commands, coverage, and the on-machine checklist |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Agent-reported faults and what they actually mean |
| [docs/HANDOVER.md](docs/HANDOVER.md) | Current state, priorities, known issues, required access |

## Run it locally

```powershell
pip install -r requirements.txt        # or use the shared venv one level above the repos
python main.py
```

Then open Settings (the gear icon) and point it at your own machine: API base URL
`http://localhost:8000`, recording server `ws://localhost:8765`. **The shipped
defaults point at the production server**, so this step is not optional for
development.

The backend and the recording server both have to be running.

```powershell
python -m pytest tests/ -q       # 311 tests, all offscreen — no window appears
python smoke_test.py             # 21 headless checks
```

Run both from the repo root so `import main` resolves, and scope pytest to
`tests/` — the root-level `smoke_test.py` breaks bare collection.

## Build

```powershell
python build_all.py                                              # -> dist\SparkFlow\SparkFlow.exe
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss   # -> installer\Output\SparkFlowSetup.exe
```

Windows only. It needs `pyaudiowpatch` for WASAPI loopback capture, which is how
the customer's side of the call is recorded.

## Layout

```
main.py            the entire application, one file (~4,600 lines)
build_all.py       PyInstaller build — a FOLDER build, deliberately not one-file
smoke_test.py      21 headless checks, including that no web view has crept back in
installer/         Inno Setup script, per-user install, no admin prompt
assets/            icons
scripts/           local probes and previews (gitignored output)
tests/             13 test files
```

## Requirements

```
PyQt6>=6.6
pyaudiowpatch>=0.2.12
websocket-client>=1.7
requests>=2.31
pyinstaller>=6.0
```

No `.env`. Configuration is compile-time constants plus `QSettings`, stored in the
Windows registry under `HKCU\Software\Spark Flow\Widget`.

## Two things to know before changing anything

**The protocol is shared with the recording server** and must change on both sides
together. Chunk size 4096, binary frames of
`struct.pack("I", len(stream_type)) + stream_type + pcm`, and the handshake order
`identify`, `session_start`, `start`, audio, `stop`, `session_end`. A mismatch
breaks recording in the field, silently.

**`QSettings` beats a new build.** Shipping a new default server address does not
repoint any agent who has ever opened the Settings panel. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#repointing-agents-at-a-new-server).

## Threading

Qt only. No asyncio, no `await`. Audio and network work happen in `QThread`
workers, and every UI update from a worker goes through a `pyqtSignal` or
`QTimer.singleShot(0, ...)`. Touching a widget directly from a worker thread will
crash the process, not raise an exception.

## Secrets

There are none in the repo. The agent's session token lives in `QSettings` on their
own machine. `dist/`, `build/` and `installer/Output/` are gitignored — the binaries
are published as GitHub releases, never committed.
