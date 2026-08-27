# Database — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> The schema, all 16 migrations and the full table reference:
> [live-widget-api/docs/DATABASE.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/DATABASE.md)

## The widget has no database access

No connection string, no driver, no SQL. It never talks to PostgreSQL and holds no
credential that could. Everything reaches the database through one of two services:

| Path | Carries |
| --- | --- |
| REST to the backend | Login, the compliance configuration, the current version |
| WebSocket to the recording server | The call itself, and everything about it |

That is deliberate. The widget runs on a machine we do not control, so it gets no
more trust than a browser would.

## Local storage on the agent's machine

The widget's own persistence is `QSettings` — the Windows registry under
`HKCU\Software\Spark Flow\Widget`, per Windows user. It is not a database, it does
not sync, and it does not travel to a new machine.

| Key | Holds | Sensitive? |
| --- | --- | --- |
| `api/base_url`, `ws/url` | Server addresses | No |
| `auth/token`, `auth/refresh_token` | The session, only with "Remember me" | **Yes** — these authenticate as that agent |
| `auth/user` | Cached name, email, company, role, department | Mildly |
| `config/json`, `config/etag` | The cached compliance configuration | No — company policy text, not customer data |
| `audio/mic_name`, `audio/spk_name` | Remembered devices | No |
| `update/attempts` | Update retry bookkeeping | No |

**No customer data is ever stored locally.** Audio is streamed, not written to the
agent's disk, with one bounded exception: the buffering-and-resume feature spools
audio locally while a connection is down, replays it on reconnect, and purges
anything left behind after seven days.

The log at `%LOCALAPPDATA%\Spark Flow\logs\widget.log` is bounded and is written
without customer names or references.

## What the widget sends, and where it lands

Everything the widget contributes to the database goes through the recording
server's `session_start` and the call that follows.

| Widget sends | Lands in |
| --- | --- |
| `agent_id` | `sessions.agent_id` |
| `reference_id` | `sessions.reference_id` — the Aryza case reference, the key everything groups by |
| `customer_name` | `sessions.customer_name` |
| `department` (from the dialer) | Resolves which department's checklist is loaded |
| `token` | Not stored — exchanged for identity via the backend's `GET /api/me` |
| The dialer metadata that came with the pop-up | `sessions.crm_customer_data` (JSONB) |
| `app_version`, on `identify` | `users.widget_version` |
| The audio itself | `RECORDINGS_DIR/<reference>/<session id>.mp3`, indexed by `sessions.recording_url` |

Written by the server rather than the widget, but caused by the call:
`sessions.duration_seconds`, `compliance_score`, `status`, `connection_dropped`,
`alerts_fired`, `knowledge_surfaces`, and `agent_activity` rows for login and
presence.

`client_id`, `agent_id` and `reference_id` are **required** on `session_start`.
Customer name and id are **not**, because a dialer-driven start sends them blank and
the CRM resolves the name later from the reference.

## Three facts that explain widget behaviour

**A blank widget version on the dashboard is not a bug.** `users.widget_version` is
only populated from 2.9.12 onward, so a blank cell means that agent is on an older
build — which is exactly the thing worth knowing.

**`users.extension` is why the widget pops up.** The dialer identifies an agent by
their numeric XDial id, matched against that column. If it is empty, the dialer
never reaches that widget and their calls are never recorded, and the widget itself
has no way to know. That is not a widget fault, but it is the most common reason a
widget "does nothing".

**A former-staff account cannot sign in.** `users.left_at` is checked in the backend's
auth dependency, so an agent marked as having left gets a rejection from
`/auth/login-widget` and from `GET /api/me`. An already-issued token also stops
working, because the check runs on every request rather than only at sign-in.

## Related documentation

- [live-widget-api/docs/DATABASE.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/DATABASE.md) — the full schema
- [API_INTEGRATIONS.md](API_INTEGRATIONS.md) — what the widget sends, in protocol terms
- [live-widget-server/docs/DATABASE.md](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/DATABASE.md) — the service that does the writing
