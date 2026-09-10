# Architecture — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> System-wide architecture: [live-widget-api/docs/ARCHITECTURE.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/ARCHITECTURE.md)

## Stack

| | |
| --- | --- |
| Language | Python 3.12 |
| UI | PyQt6 (widgets, not QML), with `QtSvg` for icons |
| Audio | `pyaudiowpatch` — a PyAudio fork with WASAPI loopback support |
| Networking | `websocket-client` for audio, `requests` for REST |
| Packaging | PyInstaller (folder build) then Inno Setup |
| Storage | `QSettings` — the Windows registry, `HKCU\Software\Spark Flow\Widget` |

Windows only. WASAPI loopback is how the customer's side of a call is captured, and
`pyaudiowpatch` is the only practical way to reach it from Python.

Everything lives in one file, `main.py`, at roughly 4,600 lines. That is unusual and
deliberate: it is packaged as a single binary, there is no import graph to reason
about at runtime, and a PyInstaller build with one module has one fewer thing to go
wrong. It has held up, but see [HANDOVER.md](HANDOVER.md) for the argument on both
sides.

## Threading model

**Qt only. No asyncio anywhere, and no `await`.** This is a hard constraint, and the
mirror image of the recording server, which is asyncio-only.

```
main thread (Qt event loop)
├── every widget, every paint, every UI state change
├── ControlConnection      (QThread)  persistent socket to the recording server
├── AudioStreamer          (thread)   capture + send, per call
├── RecordingThread        (QThread)  the recording lifecycle
├── LoginWorker            (QThread)  POST /auth/login-widget
├── RefreshWorker          (QThread)  token renewal
├── ValidateWorker         (QThread)  token check on launch
├── StartCallWorker        (QThread)  so pressing Start is instant
├── ConfigRefreshWorker    (QThread)  GET /api/widget/config
├── ForgotPasswordWorker   (QThread)
└── UpdateCheckWorker      (QThread)  GET /api/version, download, install
```

**Every UI update from a worker goes through a `pyqtSignal` or
`QTimer.singleShot(0, ...)`.** Touching a widget directly from a worker thread
crashes the process rather than raising an exception, and the crash appears far from
the cause. `_receiver_loop` reads from the socket on a worker and hands each message
to `_handle_server_message` on the main thread through exactly that route.

`StartCallWorker` exists purely so that pressing Start does not block the UI while
devices are opened. On some machines that takes a noticeable moment, and a frozen
window at the start of a call looks like a broken application.

## Audio capture

Two streams per call.

| Stream | Source | Notes |
| --- | --- | --- |
| `mic` | The selected input device | Recorded **raw** — no noise suppression |
| `speaker` | A WASAPI **loopback** of the selected output device | This is the customer's side |

`CHUNK = 4096` frames, 16-bit PCM (`paInt16`). The chunk size is part of the
protocol contract with the recording server and must not be changed on one side.

**Krisp's virtual microphone is excluded** (`_EXCLUDED_MIC_SUBSTRINGS = ("krisp",)`).
Suppression mangles fast speech, and compliance review needs to hear what was
actually said, so the widget records the physical device instead. This was verified
against a purpose-built probe.

**Device selection is remembered and matched tolerantly.** Names are normalised
before comparison, which is what makes a device survive Windows renaming it
slightly — including an AirPods entry whose name contained a curly apostrophe. There
is a rescan poll for hot-plugged devices, a format probe for loopback streams, and a
first-run gate so an agent cannot start recording before choosing a microphone.

**The customer channel is only as good as the selected speaker device.** If it is
not the device the call actually plays through — a swapped headset leaves the old
name selected — the widget records an idle output and channel 2 comes out silent.
That is the single most common audio fault reported from the field.

## The WebSocket protocol

Shared with the recording server. **Do not change one side alone.** Full reference:
[live-widget-server/docs/ARCHITECTURE.md](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/ARCHITECTURE.md#the-websocket-protocol-port-8765).

### Two kinds of connection

| Connection | Lives | Purpose |
| --- | --- | --- |
| **Control** (`ControlConnection`) | The whole time the widget runs | Registers the agent so the dialer can pop an idle widget. Reports the widget's build. |
| **Call** (`AudioStreamer`) | One per call | Audio frames, live alerts, the post-call summary |

The per-call streamer connects with `register_for_dialer=False`, because the control
connection already owns that registration. Two registrations for the same agent
would make the dialer's target ambiguous.

### Handshake, in order

```
identify → session_start (+token) → start (mic) → start (speaker)
        → binary audio frames → stop → stop → session_end
```

### Binary frames

```
struct.pack("I", len(stream_type)) + stream_type.encode() + pcm_bytes
```

Little-endian 4-byte length, then `mic` or `speaker`, then the raw PCM.

### Messages received from the server

| Type | What the widget does |
| --- | --- |
| `compliance_alert` | Renders missing items in `ComplianceAlertPanel` — amber and red chips, forbidden hits, cue hits |
| `knowledge_surface` | Shows the relevant knowledge item |
| `transcription_status` | Updates the transcription indicator |
| `session_summary` | Populates `SummaryScreen` — score, covered, missing, duration |
| `upload_complete` | Marks the recording saved |
| `dialer_activate` | Pop up and start recording |
| `dialer_stop` | Stop |
| `dialer_pause` / `dialer_resume` | PCI pause and resume |

Timeouts: `WS_CONNECT_TIMEOUT` 10s, `WS_HANDSHAKE_TIMEOUT` 30s,
`WS_STREAM_TIMEOUT` 5s. The 30-second handshake deadline is why the recording
server's database retry ladder is sized to finish well inside it.

## Configuration and state

No `.env`, no configuration file. Compile-time constants:

```python
DEFAULT_API_BASE_URL = "http://192.168.80.53:8080"
DEFAULT_RECORDING_WS = "ws://192.168.80.53:8765"
ORG = "Spark Flow";  APP = "Widget"
CHUNK = 4096
APP_VERSION = "2.9.31"
```

`QSettings("Spark Flow", "Widget")` keys:

| Key | Holds |
| --- | --- |
| `api/base_url`, `ws/url` | Server addresses — **these override the defaults above** |
| `auth/token`, `auth/refresh_token`, `auth/user` | The session, only with "Remember me" |
| `config/json`, `config/etag` | The cached compliance configuration and its ETag |
| `audio/mic_name`, `audio/spk_name` | The remembered devices |
| `update/attempts` | Auto-update retry bookkeeping |

**`QSettings` takes precedence over the compile-time defaults.** This is the most
important operational fact about the widget, and it is what
`_migrate_server_urls()` exists for.

## Technical decisions, and why

### A folder build, not one-file

`build_all.py` passes `--onedir`. A one-file build unpacks about 44 MB, including
`python312.dll`, into a fresh `%TEMP%\_MEIxxxxxx` on **every launch** and deletes it
on exit. With antivirus scanning that unpack, agents hit
`Failed to load Python DLL ...\_MEIxxxxxx\python312.dll` and end up with no widget
at all — which for a call recorder means no recording. The failure happens in the
PyInstaller bootloader, before any of our Python runs, so it cannot be handled
in-app. A folder build ships the DLLs beside the executable, unpacks nothing, and
starts noticeably faster.

### The retired-host migration

Shipping a new build with a new default address is **not enough**. `QSettings` wins,
so an agent who has ever run the widget keeps the dead address and sees a 502 at
login — the old box still runs nginx but not the API.

`_migrate_server_urls()` rewrites a saved address only if it names a host in
`RETIRED_HOSTS`, so anyone who has deliberately set a different server (a test box,
a future move) is left alone. It runs once, on launch.

The proper fix is a DNS hostname both boxes can answer to, so a future move needs no
widget change at all.

### A sticky sign-out

A revoked session used to fail silently. `_on_validate_bad` switched the stack to
the login page, but if the window was hidden in the tray — the normal state, since
it hides on both close and minimise — the agent saw nothing, carried on working, and
nothing recorded. The signal existed; it just had nowhere to appear.

So while signed out the window forces itself back on screen, stays on top and
refuses to hide, resurfacing after a minute if it gets buried. Quitting from the
tray still works, so an agent can genuinely shut down at the end of a shift.

It deliberately does **not** call `activateWindow()`. Agents type customer details
into the dialer, and stealing keyboard focus mid-call could send half a phone number
into our window. Raising without focus is unmissable and harmless.

Version 2.9.13 extended this to the manual Log Out button, which had been left out
and could therefore still be minimised away.

### PCI pause at one choke point

Pause is implemented at the single `send_audio` choke point, where the chunk is
simply dropped. That means there is exactly one place in the code where audio can be
suppressed, so the guarantee is easy to verify — and both channels pause together by
construction rather than by coordination.

The consequence downstream is that a paused stretch is **absent** from the recording
rather than silent, so the audio jumps from before the pause to after it. QA
reasonably hears that seam as a fault. See
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Local buffering and resume

If the socket dies mid-call the widget spools audio locally and replays it on
reconnect, so the finished recording has no hole. The widget's deadline is 150
seconds and the server holds the session for 180 — the server's window must stay the
larger of the two, or the widget will try to resume into a session that has already
been finalised.

Old spool files are purged after seven days.

### Auto-update that will not run arbitrary code

`/api/version` is plaintext over the LAN today, so its JSON must not be able to
point the widget at any binary it likes. `is_safe_installer_url()` accepts a
download only if:

- the path ends in `.exe`; **and**
- the host is either the backend's own host (any scheme, since the LAN deployment is HTTP) or an HTTPS host under `github.com` / `githubusercontent.com`, where releases are published.

Plain HTTP anywhere else is refused, because without TLS the real host cannot be
distinguished from someone impersonating it. `safe_installer_filename()` sanitises
the version string before it is interpolated into a temp path, so a crafted version
cannot escape the directory with `../..`.

### Native login, no web view

The login screen is plain PyQt6. An earlier design used a `QWebEngineView` loading
`assets/login.html` with a `QWebChannel` bridge; it was removed. The smoke test
asserts that neither `QWebEngineView` nor the bridge has come back, because
reintroducing them would add a browser engine — tens of megabytes and its own
update surface — to a call recorder.

### A log file, because there is no console

This is a `--windowed` build, so `print()` output is lost. Field failures — a
stalled update, an unexplained sign-out — had to be diagnosed by guesswork, and the
agent had nothing to send. Everything is now mirrored to a bounded log at
`%LOCALAPPDATA%\Spark Flow\logs\widget.log`. Ask for that file first.

### Single instance

`acquire_single_instance()` prevents two widgets running at once. Two would compete
for the same audio devices and register the same agent twice with the dialer.

## The screens

| Class | What it is |
| --- | --- |
| `MainWindow` | The whole application shell, and by far the largest class |
| `ComplianceAlertPanel` | Live alert chips: amber, red, forbidden hits, cue hits, transcription status |
| `SummaryScreen` | Post-call: score, covered, missing, duration — or a plain "recording saved" card when the live pipeline is off |
| `ToggleSwitch`, `_DraggableWidget`, `RenderKeepAlive` | Small custom UI pieces |

The window minimises to the tray rather than closing, and `hide_customer_fields`
from the widget configuration can hide the customer name and reference inputs —
cosmetic only, since the values are still captured.

## Constraints that must not change

- `CHUNK = 4096`.
- The binary frame layout.
- The handshake order.
- Qt threads only. No asyncio, no `await`.
- No UI access from a worker thread except via `pyqtSignal` or `QTimer.singleShot(0, ...)`.
- No web view in the login flow.
- WAV writing on the server side always continues in parallel — nothing the widget does may assume otherwise.

## Related documentation

- [API_INTEGRATIONS.md](API_INTEGRATIONS.md) — the endpoints and the protocol
- [SETUP.md](SETUP.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [TESTING.md](TESTING.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) · [HANDOVER.md](HANDOVER.md)
- [live-widget-server/docs/ARCHITECTURE.md](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/ARCHITECTURE.md) — the other half of the protocol
