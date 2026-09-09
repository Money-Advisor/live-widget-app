# Deployment — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> The server-side deploy procedure: [live-widget-api/docs/DEPLOYMENT.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/DEPLOYMENT.md)

## This one is different

The other three components are deployed to a server that we control. This one is
installed on **each agent's Windows PC**, and its configuration lives in their own
registry. That changes everything about how a release works:

- There is no single place to flip a setting.
- A build can reach an agent's machine and still not change their behaviour, because `QSettings` overrides the compile-time defaults.
- Rollout depends on people — the agent, or IT — not on a command.
- An agent still on an old build is invisible unless it reports itself, which is why versions from 2.9.12 onward do.

Environments: there is only one binary. It points at production by default, and a
developer redirects their own copy through the Settings panel.

## Building a release

```powershell
cd "Spark Flow\live-widget-app"

# 1. Bump the version in BOTH places — they must match
#    main.py            APP_VERSION = "x.y.z"
#    installer\installer.iss   #define AppVersion "x.y.z"

# 2. Test
python -m pytest tests\ -q
python smoke_test.py

# 3. Build the executable
python build_all.py                    # -> dist\SparkFlow\SparkFlow.exe

# 4. Build the installer
# Inno Setup is installed USER-SCOPE on this machine - no administrator
# rights - so it is NOT under Program Files. That path is the one the
# Inno docs give, and it fails here with "No such file or directory".
"$env:USERPROFILE\tools\InnoSetup6\ISCC.exe" installer\installer.iss
                                       # -> installer\Output\SparkFlowSetup.exe

# 5. Commit and tag
git add -A && git commit -m "x.y.z: <what changed>"
git push origin main
```

**Bump the version in both files.** During the August 2026 move two different
binaries briefly shipped under one version number, which made it impossible to tell
what an agent was actually running. The dashboard's widget-version column exists
partly because of that.

### The build is a folder, not one file

`build_all.py` passes `--onedir` deliberately. A one-file build unpacks about 44 MB,
including `python312.dll`, into a fresh `%TEMP%\_MEIxxxxxx` on every launch. With
antivirus scanning that unpack, agents hit
`Failed to load Python DLL ...\_MEIxxxxxx\python312.dll` and end up with no widget
at all — which for a call recorder means no recording. The failure is in the
PyInstaller bootloader, before any of our code runs, so it cannot be handled
in-app. Do not "simplify" this to `--onefile`.

### The installer

Inno Setup, from `installer/installer.iss`:

- **Per-user install, `PrivilegesRequired=lowest`** — no administrator prompt, which is what makes it installable by an agent without IT.
- Licence page, desktop-icon option (checked), and **auto-start on Windows sign-in (checked, `--minimized`)**.
- Installs to the per-user program files location, with Start Menu and optional desktop shortcuts.
- x64 only, LZMA2 compression.
- It is **not code-signed.** Windows SmartScreen will warn on first run. Signing it, and switching to a machine-wide install, is on the open list.

## Publishing

Two steps, and the second is easy to forget.

**1. Upload the installer as a GitHub release** on `Money-Advisor/live-widget-app`.
Binaries are never committed — `dist/`, `build/` and `installer/Output/` are
gitignored.

**2. Publish it in the dashboard**, under Settings ▸ Releases (super-admin only).
That writes the row in `app_versions` that `GET /api/version` serves.

Until step 2 is done:

- Agents' widgets will not offer the update, because the auto-updater compares against `/api/version`.
- The dashboard's "update needed" badge judges every agent against an **older** "current", so it is misleading rather than merely absent.

The download URL must be one the widget will accept. `is_safe_installer_url()`
requires a `.exe` path on either the backend's own host or an **HTTPS** host under
`github.com` / `githubusercontent.com`. A release asset URL satisfies this; a
plain-HTTP file server elsewhere does not, and the widget will silently refuse it.

## How an agent gets the update

Three routes, in descending order of reliability:

1. **The in-app updater.** `UpdateCheckWorker` polls `GET /api/version`, compares against `APP_VERSION`, and offers to download and install. It writes a small updater script that waits for the widget to exit, runs the installer, and relaunches. `update/attempts` in `QSettings` bounds the retries so a persistently failing update cannot loop forever.
2. **The `/download` page** on the dashboard, which serves the same installer.
3. **IT pushing the installer** to machines.

## Repointing agents at a new server

This is the part that has caused the most trouble, so it is worth being explicit.

**A new build with new defaults is not enough.** `QSettings` takes precedence over
`DEFAULT_API_BASE_URL` and `DEFAULT_RECORDING_WS`, so any agent who has ever opened
the Settings panel keeps their saved address. During the August 2026 move that
meant a 502 at login — the retired box still ran nginx but not the API — and no
recording at all.

`_migrate_server_urls()` handles exactly this case, and only for hosts it knows are
dead:

```python
RETIRED_HOSTS = ("192.168.80.52",)
```

On launch, a saved address naming one of those is rewritten to the current default.
Anyone who has deliberately set something else — a test box, a future move — is left
alone. **Add the old host to `RETIRED_HOSTS` before every server move**, or the
migration does nothing.

The other options, in order of preference:

| Approach | Verdict |
| --- | --- |
| **A DNS hostname both boxes can answer to** | The right answer. A future move then needs no widget change at all. Not yet done. |
| A new build plus `RETIRED_HOSTS` | What we did in August. Works, but requires everyone to update. |
| IT pushing `HKCU\Software\Spark Flow\Widget` by GPO | Reliable, needs IT, and is per-user. |
| Asking agents to change it themselves | Last resort. |

## Verifying a rollout

After publishing, watch the **Agents page** on the dashboard:

- The **widget build** column shows what each agent is actually running.
- The **"update needed"** badge shows who is behind the published release.
- A **blank** version means that agent is on a build older than 2.9.12, which does not report itself. That blank is the signal.

Cross-check that calls are still being captured — see the UAT checklist in
[live-widget-api/docs/TESTING.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TESTING.md#uat-checklist).
A widget that launches but records nothing looks identical to a healthy one from the
agent's side.

## Rollback

Publish the previous release in Settings ▸ Releases and, if the bad build is already
installed somewhere, hand out the previous installer. Agents can install over the
top; `QSettings` survives, so they will not have to sign in again.

There is no remote kill switch and no way to force a downgrade. That is a real
limitation of shipping a desktop application.

## Branch strategy

Directly on `main`, no CI. Before pushing:

1. `python -m pytest tests/ -q` and `python smoke_test.py` — both green.
2. If you touched the protocol, run the **recording server's** suite too. Both sides must change together.
3. Build and run the actual executable, not just `main.py` — PyInstaller problems (a missing hidden import, a bundled asset) only appear in the packaged build.
4. If a document in `docs/` is now wrong, fix it in the same commit.

Commit messages here conventionally lead with the version when one is being cut,
e.g. `2.9.14: stop the customer channel losing time`.

## Open items

- **Code-sign the installer.** SmartScreen warns on every first run today, which is exactly the wrong signal to give an agent installing a recording tool.
- **A DNS hostname** instead of an IP, so the next server move needs no widget release.
- **A pre-roll buffer** for dialer-driven starts, to catch the first second of a call. Parked.
- **Agents should use wired or USB headsets.** Bluetooth caps audio quality, and this is a rule to enforce rather than a bug to fix.

## Related documentation

- [SETUP.md](SETUP.md) — the version constants and the `QSettings` keys
- [ARCHITECTURE.md](ARCHITECTURE.md) — why the build and the updater work the way they do
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — what agents report after a rollout
- [live-widget-api/docs/DEPLOYMENT.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/DEPLOYMENT.md) — the server side
