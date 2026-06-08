# Nexcall Desktop Widget

PyQt6 desktop call-compliance widget. The agent logs in, the widget
loads the company's compliance config, records mic + speaker audio to the
recording server, and shows live compliance alerts pushed back over the same
WebSocket. Closes to the Windows system tray.

## Run

```bash
pip install -r requirements.txt
python main.py
```

## Configuration

No server addresses are hardcoded into the UI flow. Defaults (overridable in the
in-app **Settings ▸ Advanced** panel, persisted in `QSettings("Nexcall","Widget")`):

| Setting               | Default                 | Used for                          |
| --------------------- | ----------------------- | --------------------------------- |
| API base URL          | `http://localhost:8000` | `POST /auth/login-widget`, config |
| Recording server URL  | `ws://localhost:8765`   | audio streaming WebSocket         |

The session token is stored under the `auth/token` key (only when "Remember me"
is checked). The widget config is cached under `config/json` + `config/etag`
(ETag / `If-None-Match` → `304 Not Modified`).

## Auth flow

1. Launch → if a stored token validates against `GET /api/widget/config`, go
   straight to the ready screen; otherwise show the login web view.
2. Login web view (`assets/login.html`) collects email + password and calls the
   Python `QWebChannel` bridge, which runs `POST /auth/login-widget` off the UI
   thread, stores the token, fetches config, and shows the company name.

## Live compliance

The recording server pushes JSON over the existing WebSocket; the widget handles:

- `compliance_alert` → `{missing_items:[{id,label,level,suggestion_text}]}` →
  rendered in `ComplianceAlertPanel` (amber banner / red alert).
- `session_summary` → `{score,covered,missing,duration_seconds}` → summary screen.
- `upload_complete` → marks "Recording saved" on the summary screen.

> The server-side transcription + compliance matching that emits these messages
> is Phase 4. Until then the widget derives a local summary from the last live
> compliance state when a call stops.

## Build

```bash
python build_all.py
```

- Windows → `dist/Nexcall.exe`
- macOS  → `dist/Nexcall.app` + `dist/Nexcall.dmg`

`assets/` (the login page) is bundled with the binary; `main.py` resolves it via
`resource_path()` (PyInstaller `_MEIPASS`-aware).

