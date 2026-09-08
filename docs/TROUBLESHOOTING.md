# Troubleshooting — Desktop Widget

> **Spark Flow** · `live-widget-app` · Owner: Faseeh Iqbal · Last reviewed: 2026-08-27
> System-wide troubleshooting: [live-widget-api/docs/TROUBLESHOOTING.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TROUBLESHOOTING.md)

## A code change appears to have no effect

Before anything else, check for a stale `__pycache__`. Python decides a `.pyc`
is current from the source file's **size and mtime in whole seconds** - so a
same-size edit reverted inside the same second leaves the old bytecode in
place and running.

This is not theoretical: a script that flips a constant, runs one test and
flips it back does exactly that. `STAGE_CONFIRM = 2` -> `1` -> `2` left the
server importing `1` while `grep` and `inspect.getsource` both showed `2`, and
a passing fix looked like a failing one for several minutes.

    find . -name __pycache__ -type d -exec rm -rf {} +

and run the child process with `python -B` when a tool edits sources under it.

## The panel animation does not animate

`_refit` deliberately defers by one event-loop turn before measuring. Rows added
a moment ago have not been given a width yet, and nearly every row is a
word-wrapped label whose height depends on its width - measured synchronously
the accordion reported 52px when its real height was 358px. Anything that
measures the panel immediately after a rebuild will get the old height, decide
there is nothing to animate, and the panel will snap on the following tick.

`_sync_window` must also leave a running animation alone; it used to re-target
without animating a millisecond after the animation started, which had the same
effect.

## A cleared row is still on screen

Taking an item out of a **layout** does not detach the widget from its
**parent**, so a row removed with `layout.takeAt()` keeps painting at its last
position until `deleteLater()` is serviced. Call `hide()` before
`deleteLater()`.

Do **not** reach for `setParent(None)` instead. It fixes the painting, but it
hands ownership to Python while Qt still has the widget queued for deletion,
and the widget suite's rare teardown access violation went from a 1-in-8
background rate to 3 runs in 8 with it in. `hide()` leaves ownership alone.

Related, and still open: that background access violation at test teardown
pre-dates all of this - it reproduces on the suite with none of the 2.9.24
changes present. It has never been seen in the field, only at interpreter exit
under pytest, so it has not been chased down. If you are hunting a widget
crash, do not assume this is it.

## The widget disappears a few seconds after a call ends

Look in `%LOCALAPPDATA%\Spark Flow\logs\widget.log` for a
`===== Spark Flow x.y.z starting =====` line sitting directly underneath a
`session_summary received` line. That pairing is the signature: the widget did
not close, it was **aborted**, and the tray relaunch is what wrote the next
starting line.

The cause is always the same shape - an unhandled Python exception inside a Qt
slot. PyQt6 responds to that by calling `qFatal()`, which aborts the process
without unwinding, so **there is no traceback in the log**. Do not go looking
for one; look instead at the last message the widget handled before the restart
and at what changed on the server side of it.

The instance this was found on: the rulebook server started sending `score` as
`{"covered": 1, "total": 59, "earned": 1.0, "fraction": 0.0169}` where the old
matcher sent a bare float, and `float(dict)` raises TypeError. Fixed in 2.9.22
by `score_fraction()`, which accepts either shape and returns None rather than
raising on anything it does not recognise. Any new field the server sends the
widget should be read the same defensive way.

## Ask for the log file first

```
%LOCALAPPDATA%\Spark Flow\logs\widget.log
```

This is a windowed build with no console, so `print()` output would otherwise be
lost. Before this file existed, field failures — a stalled update, an unexplained
sign-out — had to be diagnosed by guesswork and the agent had nothing to send. It is
bounded, contains no customer names or references, and is the single most useful
thing an agent can give you.

Then check the dashboard's **Agents** page: is that agent online, and what build are
they on? Those two facts eliminate most of the possibilities immediately.

## The four questions that resolve most reports

1. **Is the widget running and online?** The Agents page says. Running but offline usually means a wrong server address.
2. **What build?** A blank version means older than 2.9.12. An old build may not contain the fix being discussed.
3. **Does the agent have an extension set?** Without `users.extension` the dialer cannot reach them at all, and the widget has no way to know anything was expected of it. In the August 2026 reconciliation, 16 agents had never captured a single call — 1,474 calls — largely for this reason.
4. **Which server does their Settings panel show?** `QSettings` overrides the shipped default, so a build alone does not repoint anyone.

---

## Sign-in problems

### 502 or "cannot reach server" at login

The saved address names a dead server. `_migrate_server_urls()` rewrites addresses
naming a host in `RETIRED_HOSTS` (currently `192.168.80.52`), but only those. Any
other stale value has to be corrected in the Settings panel.

The retired box still runs nginx but not the API, which is why this presents as a
502 rather than as a connection failure — and why it looks like a server problem
rather than a client one.

### "Authentication failed. Please log in again"

This message comes from the recording server when `session_start` fails token
validation, and it points at the wrong thing about half the time. The real causes,
in order of likelihood:

1. **The backend is down or unreachable** from the recording server. The recording server calls `GET /api/me` and rejects the session on any failure.
2. The token genuinely is stale, and refresh failed.
3. The account has been marked former staff.

### Signed out unexpectedly

Token refresh failed. The widget deliberately makes this impossible to miss: the
window forces itself back on screen, stays on top and refuses to hide.

If an agent says they were signed out **and did not notice**, they are on a build
older than 2.9.13 — the manual Log Out button was not covered by the sticky
behaviour until then, so it could still be minimised away while nothing recorded.

### "This account is no longer active"

`users.left_at` is set. Reinstate them from the dashboard's Agents page, and
remember that reinstating deliberately does **not** restore their extension — set
that separately or the dialer still will not reach them.

### The sticky sign-out window steals focus

It should not, and does not call `activateWindow()` on purpose: agents type customer
details into the dialer, and stealing focus mid-call could send half a phone number
into our window. If focus is genuinely being taken, that is a bug worth reporting.

---

## The widget never pops up for a call

This is the most consequential report, because the agent may not notice for hours.

1. **Is the control connection up?** The Agents page shows online state. An offline widget cannot be reached by the dialer, no matter what XDial does.
2. **Is the extension set?** See above.
3. **Was the campaign mapped?** An unmapped campaign is ignored by design and nothing pops up. Check `dialer_campaign_map`.
4. **Did the relay reach the recording server?** The backend's log line is the answer:
   ```
   [dialer] event=start user=409 campaign=ADVICE ref=122283 -> dept=sfm agent_matched=True widget_notified=True
   ```
   `widget_notified=False` with `agent_matched=True` means the command never reached a widget. On the server side that is usually `RECORDING_CONTROL_URL` including `/dialer/activate` when it must be a base URL — it fails silently and the webhook still returns 200.
5. **Can the agent's machine reach port 8765?** Agents are on 10.10.30.x and the server is on 192.168.80.x. A firewall rule restricted to `192.168.80.0/24` cuts off every agent.

Full detail in the [backend's troubleshooting guide](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TROUBLESHOOTING.md#a-call-was-not-recorded-at-all).

---

## Audio problems

### The customer cannot be heard on the recording

**The most common real fault in the field**, and it is fixed on the agent's machine.

The widget captures the customer from the **selected speaker device**. If that is not
the device the call actually plays through — and a swapped headset leaves the old
name selected — it records an idle output. The only trace of the customer is
acoustic bleed into the microphone, which is exactly what "both voices in one
earpiece" sounds like.

Confirmed by measuring the channels: channel 2 around −120 dB is digital silence.
Loudness normalisation targets −18 LUFS and can rescue quiet speech, but **cannot
amplify silence**, so a still-silent channel means nothing was captured.

Fix: gear icon, set Speaker to the device the call plays through, and use a wired or
USB headset. **Their existing recordings cannot be repaired.**

The measurement command is in the
[recording server's guide](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/TROUBLESHOOTING.md#one-channel-is-silent).

### The recording has gaps

Almost always **PCI pause**, not a fault. Pause drops the chunk at the widget's
single send choke point and **both channels pause together**, so the audio jumps from
before the pause to after it. QA hears the seam and reasonably reports it as broken.

Measured over three days in August 2026: **3,162 pause events against 2,600
resumes**, so roughly 562 pauses were never lifted — meaning everything after them
was never recorded. About 8% of calls involve a pause at all.

Nothing currently flags a pause that is never resumed. Until it does, the check is
manual: if a recording ends abruptly and the session stayed open, ask whether the
agent paused.

### One sentence is clipped but the other side is intact

Not a pause — a pause removes **both** sides. Either a small microphone-stream drop
or, just as likely, the audit tool's own transcriber dropping words during
overlapping speech. **Listen to the audio at that timestamp before investigating
anything.**

### The agent sounds late relative to the customer

Fixed in **2.9.14** — the customer channel was losing time. If it is still
happening, check the build number first.

### Krisp is missing from the device list

By design. The widget records the physical microphone, because suppression mangles
fast speech and compliance review needs to hear what was actually said.

### No loopback device at all

Loopback needs a real, enabled output device. A machine with nothing connected, or
with output disabled, has nothing to capture.

### Poor audio quality

Bluetooth headsets cap the quality. The rule is wired or USB, and that is an
enforcement matter rather than a bug.

---

## Recording stops or fails mid-call

### "Connection timed out" at the start of a call

Usually the recording server being **slow**, not broken. 2.9.8 changed the widget to
stop treating one for the other. On the server side, grep the loop watchdog — it
names the blocking code.

The widget's handshake deadline is 30 seconds.

### A call dropped and the recording is short

If the network was gone for under 150 seconds the widget should have buffered and
replayed, leaving no gap. Beyond that the call finalises, the session is flagged
`connection_dropped`, and the audit pollers deliberately skip it.

If a resume attempt is rejected, check that the server's `RESUME_GRACE_SECONDS`
(180) is still **above** the widget's 150-second deadline. Lower it and the widget
will try to resume into a session that has already been finalised.

### The widget froze when starting a call

`StartCallWorker` exists precisely so it should not — opening devices happens off the
UI thread. A freeze means either a very slow device enumeration or a genuine bug
worth capturing with the log.

---

## Update problems

| Symptom | Cause |
| --- | --- |
| No update offered, though a new version exists | It was not published in Settings ▸ Releases. The widget compares against `/api/version`, not against GitHub. |
| Update downloads then does nothing | Check `update/attempts` in `QSettings` and the log. Retries are bounded so a persistently failing update cannot loop forever. |
| Update refused outright | `is_safe_installer_url()` rejected it. The URL must end in `.exe` and be on the backend's own host or an HTTPS GitHub host. A plain-HTTP file server elsewhere is refused on purpose. |
| SmartScreen warns on install | The installer is not code-signed. Expected today, and on the open list — it is exactly the wrong signal to give someone installing a recording tool. |
| `Failed to load Python DLL ...\_MEIxxxxxx\python312.dll` | Someone changed the build to `--onefile`. Revert it: antivirus scanning the per-launch unpack causes this, it happens in the PyInstaller bootloader before any of our code runs, and the agent ends up with no widget at all. |

---

## Getting a machine back to a clean state

```powershell
reg delete "HKCU\Software\Spark Flow\Widget" /f
```

That clears the saved server addresses, the session, the cached configuration and
the remembered devices. The widget then starts as a fresh install: code defaults,
signed out, first-run microphone gate.

Useful when a machine's state has become unexplainable — but it does mean the agent
has to sign in and pick their devices again, so it is not a first resort.

---

## What to collect before escalating

1. `%LOCALAPPDATA%\Spark Flow\logs\widget.log`
2. The widget version, from the Agents page or the log.
3. What the Settings panel shows for both server addresses.
4. The approximate time of the call, so the server-side logs can be matched.
5. For an audio complaint: the session id or the customer reference, so the file itself can be measured.

## Escalation

| Problem | Who |
| --- | --- |
| The widget, the build, the installer | **Faseeh Iqbal** — faseeh.iqbal@theinsolvencygroup.co.uk |
| Rolling the installer out to machines, GPO, antivirus exclusions | TIG IT |
| The dialer not triggering at all | **Keith** (XDial vendor) |
| Network reachability between agent subnets and the server | **Nooh** |

## Related documentation

- [live-widget-api/docs/TROUBLESHOOTING.md](https://github.com/Money-Advisor/live-widget-api/blob/main/docs/TROUBLESHOOTING.md) — the dialer chain and the server side
- [live-widget-server/docs/TROUBLESHOOTING.md](https://github.com/Money-Advisor/live-widget-server/blob/main/docs/TROUBLESHOOTING.md) — audio measurement and merge health
- [ARCHITECTURE.md](ARCHITECTURE.md) · [SETUP.md](SETUP.md) · [DEPLOYMENT.md](DEPLOYMENT.md)
