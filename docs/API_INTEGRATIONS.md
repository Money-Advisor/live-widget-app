# APIs and Integrations — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> The backend's full endpoint reference: [live-widget-api/docs/API_INTEGRATIONS.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/API_INTEGRATIONS.md)

The widget talks to exactly two things: the **backend** over REST, and the
**recording server** over WebSocket. It reaches nothing else — no Firebase SDK, no
third-party service, no telemetry.

---

## The backend (REST)

Base URL is `api/base_url` from `QSettings`, falling back to
`DEFAULT_API_BASE_URL`. All calls use `requests`, on worker threads.

| Endpoint | When | Notes |
| --- | --- | --- |
| `POST /auth/login-widget` | The login screen | Email and password in, an ID token, a refresh token, `expires_in`, and the user's name, company, role and department out. Rate-limited to 10 a minute. |
| `POST /auth/refresh-widget` | Before the one-hour expiry | Exchanges the refresh token for a fresh ID token, so an agent signs in once and not again. Rate-limited to 60 a minute. |
| `POST /auth/forgot-password` | The "Forgot password?" link | Sends a reset link. Always succeeds from the widget's point of view, so it cannot be used to discover which addresses exist. |
| `GET /api/widget/config` | After login, and on refresh | The department-scoped compliance configuration: script steps, criteria by level, knowledge bank, railguards, company name, and `hide_customer_fields`. |
| `GET /api/me` | On launch, to validate a stored token | Also how the widget confirms the account is still active. |
| `GET /api/version` | The update check | The current release per platform and its download URL. |

### Authentication

`Authorization: Bearer <token>` on everything except login and forgot-password. The
token is a Firebase ID token — but **the widget contains no Firebase SDK**. It posts
credentials to the backend, which signs in through Firebase's REST API on its behalf.
That keeps Firebase confined to one file in one repo.

Tokens last an hour. `_needs_token_refresh()` decides when to renew, and
`RefreshWorker` does it on a worker thread. A refresh that fails puts the widget into
sticky sign-out rather than letting it fail quietly.

### Configuration caching, with ETags

`GET /api/widget/config` returns an `ETag`. The widget stores it as `config/etag`
alongside the body in `config/json`, and sends `If-None-Match` on the next request.
Unchanged configuration comes back as `304 Not Modified` with no body.

The ETag is a hash of the whole configuration, so any change to a criterion, a
railguard, the company name or the `hide_customer_fields` toggle changes it and
every widget picks the new version up on its next refresh.

### The update check

`UpdateCheckWorker` compares `/api/version` against `APP_VERSION` using
`is_newer_version()`, which does a proper tuple comparison rather than a string one.

Before anything is downloaded, `is_safe_installer_url()` gates it. `/api/version` is
plaintext over the LAN today, so its JSON must not be able to point the widget at any
binary at all. A URL is accepted only if:

- the path ends in `.exe`; **and**
- the host is the backend's own host (any scheme, since the LAN deployment is HTTP), or an HTTPS host under `github.com` / `githubusercontent.com`.

Plain HTTP anywhere else is refused, because without TLS the real host cannot be
told apart from an impersonator. `safe_installer_filename()` sanitises the
network-supplied version string before it is interpolated into a temp path, so a
crafted version cannot escape the directory with `../..`.

`build_updater_script()` then writes a small script that waits for the widget to
exit, runs the installer, and relaunches. `update/attempts` bounds the retries.

---

## The recording server (WebSocket)

URL is `ws/url` from `QSettings`, falling back to `DEFAULT_RECORDING_WS`.
`websocket-client`, on worker threads.

**This protocol is a hard contract shared with the recording server. Do not change
one side alone.** Full reference:
[live-widget-server/docs/ARCHITECTURE.md](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/ARCHITECTURE.md#the-websocket-protocol-port-8765).

### Two connections

| Connection | Class | Lives | Purpose |
| --- | --- | --- | --- |
| Control | `ControlConnection` (QThread) | The whole time the widget runs | Registers the agent so the dialer can pop an idle widget; reports the widget's build |
| Call | `AudioStreamer` | One per call | Audio, alerts, the summary |

The per-call connection identifies with `register_for_dialer=False`, because the
control connection already owns that registration. Two registrations for one agent
would make the dialer's target ambiguous.

### What the widget sends

| Message | Fields |
| --- | --- |
| `identify` | `client_id`, `client_name`, `agent_id`, `agent_email`, `app_version` |
| `session_start` | `client_id`, `session_id`, `agent_id`, `reference_id`, `token`, and optionally `customer_name`, `customer_id`, `department`, `timestamp` |
| `session_resume` | After a mid-call disconnect, to continue the same recording |
| `start` | `client_id`, `stream_type` (`mic` or `speaker`), `channels`, `sample_rate` — once per stream |
| `stop` | Per stream |
| `session_end` | End of the call |

Then binary audio frames:

```
struct.pack("I", len(stream_type)) + stream_type.encode() + pcm_bytes
```

`CHUNK = 4096` frames, 16-bit PCM. **The chunk size and the frame layout are part of
the contract.**

The server will refuse `start` unless `session_start` produced a token-validated
session. No validated session means no WAV and no audio accepted — that is enforced
on the server, and it removed an earlier path where an unauthenticated peer could
write arbitrary files.

### What the widget receives

| Type | Handled by |
| --- | --- |
| `compliance_alert` | `ComplianceAlertPanel` — amber and red chips, forbidden hits, cue hits |
| `knowledge_surface` | The knowledge display |
| `transcription_status` | The transcription indicator |
| `session_summary` | `SummaryScreen` — score, covered, missing, duration |
| `upload_complete` | Marks the recording saved |
| `dialer_activate` | Pop up and start recording |
| `dialer_stop` | Stop |
| `dialer_pause` / `dialer_resume` | PCI pause and resume |

`_receiver_loop` reads on a worker thread and hands every message to
`_handle_server_message` **on the main thread** via `QTimer.singleShot(0, ...)`.
Touching a widget from the reader thread would crash the process.

### Timeouts and resilience

| Constant | Value | Meaning |
| --- | --- | --- |
| `WS_CONNECT_TIMEOUT` | 10s | Opening the socket |
| `WS_HANDSHAKE_TIMEOUT` | 30s | Waiting for `session_start` to be accepted. This is why the server's database retry ladder is sized to finish inside it. |
| `WS_STREAM_TIMEOUT` | 5s | Per-send |

If the socket dies mid-call the widget spools audio locally and replays it on
reconnect, so the recording has no gap. Its own resume deadline is **150 seconds**
and the server holds the session for **180** — the server's window must stay the
larger of the two, or the widget will try to resume into a session that has already
been finalised.

A slow recording server is not the same as a broken one, and the widget was changed
(in 2.9.8) to stop treating it as such.

---

## The dialer, indirectly

The widget never talks to XDial. The chain is:

```
XDial → POST /api/dialer/call-event (backend)
      → POST /dialer/activate (recording server control API)
      → dialer_activate down this agent's control connection
      → the widget pops up and records
```

Two things about that chain are worth knowing here:

1. **The widget must be identified on its control connection** for the dialer to reach it. That is what `identify` with an `agent_id` does.
2. **`users.extension` must be set** for the backend to know which agent the dialer means. If it is empty, nothing reaches the widget and the widget has no way to know that anything was expected of it.

`dialer_pause` and `dialer_resume` exist because the team asked for them, but the
XDial trigger turned out to be an agent action too, so it offers no compliance
advantage over the manual button. The manual button is what is used.

---

## What the widget deliberately does not do

- **No Firebase SDK.** Credentials go to the backend, which handles Firebase.
- **No database access.** No connection string exists here.
- **No direct contact with Speechmatics, Aryza, the audit tool or Sentry.** Everything server-side stays server-side.
- **No telemetry.** The only thing it reports about itself is its build number, on the presence snapshot.
- **No web view.** The login screen is native PyQt6, and the smoke test enforces that.

## Related documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — threading, audio capture, the protocol in context
- [SETUP.md](SETUP.md) — the constants and `QSettings` keys named above
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — what a failing integration looks like to an agent
- [live-widget-server/docs/API_INTEGRATIONS.md](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/API_INTEGRATIONS.md) — the other side of the socket
