#!/usr/bin/env python3
"""
Spark Flow Widget
-----------------
Desktop call-compliance widget (Phase 3).

Agent logs in (native PyQt6 login -> POST /auth/login-widget), the widget fetches
company compliance config (GET /api/widget/config), then records mic + speaker
audio to the recording server while showing live compliance alerts pushed back
over the same WebSocket. Minimizes to the Windows system tray instead of closing.

Requirements:
    pip install PyQt6 pyaudiowpatch websocket-client requests
"""

import os
import sys
import time
import wave
import datetime
import threading
import json
import struct
import subprocess
import tempfile
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    sys.exit(
        "pyaudiowpatch is not installed.\n"
        "Install it with:  pip install pyaudiowpatch"
    )

try:
    import requests
except ImportError:
    sys.exit(
        "requests is not installed.\n"
        "Install it with:  pip install requests"
    )

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton,
    QGroupBox, QSystemTrayIcon, QMenu,
    QMessageBox, QLineEdit, QSizePolicy,
    QFrame, QCheckBox, QStackedWidget, QScrollArea,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal,
    QTimer, QEvent, QSettings, QPropertyAnimation, QEasingCurve,
    QSize, QRectF, QByteArray,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QBrush, QPen, QAction, QFont,
)
from PyQt6.QtSvg import QSvgRenderer


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
CHUNK = 4096                       # Phase 3: was 1024
AUDIO_FORMAT = pyaudio.paInt16

# Virtual / processed input devices we must never record from: they carry
# noise-cancelled and accent-converted audio (e.g. Krisp), not the raw agent
# voice the audit pipeline needs. We want the physical headset mic underneath.
_EXCLUDED_MIC_SUBSTRINGS = ("krisp",)


def _is_excluded_mic(name: str) -> bool:
    """True if a mic device name belongs to an excluded virtual/processed source."""
    lowered = (name or "").lower()
    return any(sub in lowered for sub in _EXCLUDED_MIC_SUBSTRINGS)


def _pick_stream_format(is_supported, channels_list, rates_list):
    """First (channels, rate) combo the device actually supports, else None.

    Used to capture a WASAPI *loopback* stream at the render device's true mix
    format. Guessing a format the device doesn't natively support (the old
    behaviour) yields misaligned/garbled samples — distortion + noise."""
    for ch in channels_list:
        for rate in rates_list:
            if is_supported(ch, rate):
                return (ch, rate)
    return None


def _norm_dev(name: str) -> str:
    """Normalize a device name for tolerant matching: lowercase, collapse spaces,
    and fold typographic apostrophes to a plain one. Bluetooth/AirPods names vary
    by exactly these between sessions/profiles, which broke exact-string matching."""
    s = (name or "").lower().strip()
    for ch in ("’", "‘", "ʼ", "`"):   # curly/modifier apostrophes
        s = s.replace(ch, "'")
    return " ".join(s.split())


def _match_device_index(names: list[str], target: str) -> int:
    """Index of the device best matching `target`, or -1. Exact (normalized) first,
    then a substring match either direction (handles profile-renamed suffixes)."""
    if not target:
        return -1
    nt = _norm_dev(target)
    norm = [_norm_dev(n) for n in names]
    if nt in norm:
        return norm.index(nt)
    for i, n in enumerate(norm):
        if n and (nt in n or n in nt):
            return i
    return -1


def _index_for_saved_mic(names: list[str], saved_name: str) -> int:
    """Index of the agent's remembered mic in the dropdown list, else 0.

    The agent picks their device (e.g. a Bluetooth headset) once; we persist the
    name and re-select it on every launch so they never re-pick. Tolerant matching
    (see _match_device_index) handles Bluetooth/AirPods name variance. Falls back
    to 0 when nothing is saved or the saved device isn't currently connected."""
    i = _match_device_index(names, saved_name)
    return i if i >= 0 else 0


def _index_for_saved_or_default_spk(spk_names: list[str], saved_name: str,
                                    default_output_name: str) -> int:
    """Index of the speaker-loopback to capture the customer's audio.

    Priority: (1) the agent's remembered manual override, (2) the loopback of the
    Windows default output device — which follows the headset when connected, so
    the customer side auto-pairs with the chosen mic — (3) first device. WASAPI
    loopback names embed the output device name (e.g. 'Headset (PLT) [Loopback]'),
    so we match the default output name as a substring."""
    i = _match_device_index(spk_names, saved_name)
    if i >= 0:
        return i
    i = _match_device_index(spk_names, default_output_name)
    if i >= 0:
        return i
    return 0


def _needs_mic_gate(token: str, saved_mic: str) -> bool:
    """First-run mic setup gate: True when the agent is logged in but has never
    picked a microphone. Blocks recording (incl. dialer auto-start) behind a
    one-time setup overlay so we never record a silent/wrong default device.
    Not logged in -> the login screen handles it, so no gate."""
    return bool(token) and not saved_mic

# Backend API (login + config) and recording-server WebSocket.
# Point at the deployed server; both are overridable via QSettings (Settings panel).
# (Update these to the public subdomain — https:// + wss:// — once DNS/HTTPS is live.)
DEFAULT_API_BASE_URL = "http://192.168.80.52:8080"
DEFAULT_RECORDING_WS = "ws://192.168.80.52:8765"

# WebSocket budgets. These answer two DIFFERENT questions and must not share a number:
#   - connect: "is the recording server reachable?" A server that isn't listening
#     should fail fast, so this stays short.
#   - handshake: "how long may the server take to ANSWER?" Answering identify /
#     session_start / session_resume means authenticating the agent's token and
#     writing a session row, so on a busy server it is legitimately slow.
# create_connection's timeout silently governs every later read on the socket too, so
# both used to be 10s. A server queueing behind a database connection then looked
# exactly like an unreachable one: the agent got "Connection timed out" and the call
# refused to start, and a buffered call could not be resumed so it stored as dropped.
# Keep the handshake budget comfortably above the server's worst-case DB wait
# (_ACQUIRE_* in the server's persistence.py).
WS_CONNECT_TIMEOUT = 10
WS_HANDSHAKE_TIMEOUT = 30
# Socket timeout while a call is streaming. The receiver thread used to set this to
# 1.0s just so it could poll its stop flag — but websocket-client applies ONE timeout
# to the whole socket, so that 1s governed audio SENDS as well. One busy second on the
# server (its TCP buffer momentarily undrained) made a 16KB chunk time out, send_audio
# treats any send failure as "the socket died mid-call", and a perfectly healthy call
# was buffered, resumed, and — when the resume couldn't complete — stored as a dropped
# recording. At fleet scale that was most calls.
# The trade-off: the capture thread blocks on a stuck send for up to this long, and
# the audio device's buffer can overflow meanwhile, so this must stay small. A few
# seconds tolerates a server hiccup without pretending a genuinely dead link is fine.
WS_STREAM_TIMEOUT = 5

ORG = "Spark Flow"
APP = "Widget"

# This build's version. MUST be kept in step with installer/installer.iss AppVersion —
# it's what the auto-updater compares against the release registry (GET /api/version).
APP_VERSION = "2.9.8"

FF = "'Plus Jakarta Sans','DM Sans','Segoe UI',sans-serif"


def resource_path(rel: str) -> str:
    """Resolve a bundled asset path (works under PyInstaller's _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ── Lucide icon paths (rendered crisply via QSvgRenderer) ─────
_LUCIDE = {
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/>'
            '<path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
            '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "eye":  '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 '
            '1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 '
               '10.747 10.747 0 0 1-1.444 2.49"/>'
               '<path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/>'
               '<path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 '
               '10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
    # lucide "refresh-cw" — crisp vector rescan glyph (replaces the ↻ text char).
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
               '<path d="M21 3v5h-5"/>'
               '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
               '<path d="M3 21v-5h5"/>',
    # Filled glyphs for the PCI pause/resume buttons (rendered solid via fill).
    "pause": '<rect x="6" y="4" width="4.2" height="16" rx="1.4"/>'
             '<rect x="13.8" y="4" width="4.2" height="16" rx="1.4"/>',
    "play":  '<path d="M7 4.2a1 1 0 0 1 1.52-.85l11 7.8a1 1 0 0 1 0 1.7l-11 7.8A1 1 0 0 1 7 19.8z"/>',
}


def _dpr() -> float:
    """Device pixel ratio of the primary screen (for crisp hi-DPI pixmaps)."""
    app = QApplication.instance()
    try:
        if app is not None and app.primaryScreen() is not None:
            return max(1.0, float(app.primaryScreen().devicePixelRatio()))
    except Exception:
        pass
    return 1.0


def svg_icon(name: str, color: str = "#9AA0B4", size: int = 18, fill: bool = False) -> QIcon:
    """Render a lucide icon to a crisp, hi-DPI-aware QIcon. fill=True draws a
    solid glyph (for the pause/play buttons); default is an outline stroke."""
    body = _LUCIDE[name]
    fill_attr = color if fill else "none"
    stroke_w = 0 if fill else 2
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="{fill_attr}" stroke="{color}" stroke-width="{stroke_w}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    dpr = _dpr()
    pix = QPixmap(round(size * dpr), round(size * dpr))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    pix.setDevicePixelRatio(dpr)
    return QIcon(pix)


class ToggleSwitch(QCheckBox):
    """A small iOS-style pill toggle (purple when on), drawn natively."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 20)

    def sizeHint(self) -> QSize:
        return QSize(40, 20)

    def hitButton(self, pos) -> bool:
        return self.contentsRect().contains(pos)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        track = QColor("#9333EA") if self.isChecked() else QColor(255, 255, 255, 56)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 40, 20), 10, 10)
        p.setBrush(QColor("#FFFFFF"))
        x = 22.0 if self.isChecked() else 2.0
        p.drawEllipse(QRectF(x, 2, 16, 16))
        p.end()


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _make_icon(color: str, size: int = 32) -> QIcon:
    """Programmatically create a filled-circle icon in the given hex colour."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(color)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.end()
    return QIcon(pix)


ICON_IDLE: QIcon | None = None
ICON_RECORDING: QIcon | None = None


def _init_icons():
    global ICON_IDLE, ICON_RECORDING
    ICON_IDLE = _make_icon("#2196F3")    # blue – idle (source)
    ICON_RECORDING = _make_icon("#F44336")   # red    – recording


# ──────────────────────────────────────────────────────────────
# Backend API client (login + widget config)
# ──────────────────────────────────────────────────────────────
class BackendError(Exception):
    """Something went wrong talking to the backend. Treated as TRANSIENT by the startup
    path (no network yet, server restarting, 5xx) — the session is kept and retried."""
    pass


class AuthError(BackendError):
    """The backend definitively rejected our credentials (401/403, or a refresh token
    that is no longer valid). This — and only this — signs the agent out."""
    pass


def api_login(base_url: str, email: str, password: str) -> dict:
    """POST /auth/login-widget -> {token, user:{id,name,company_name,role}}."""
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}/auth/login-widget",
            json={"email": email, "password": password},
            timeout=15,
        )
    except requests.RequestException:
        raise BackendError("Could not reach the server. Check your connection.")
    if r.status_code == 200:
        return r.json()
    if r.status_code in (400, 401, 403):
        raise BackendError("Incorrect email or password.")
    raise BackendError(f"Login failed (server error {r.status_code}).")


def api_refresh(base_url: str, refresh_token: str) -> dict:
    """POST /auth/refresh-widget -> {token, refresh_token, expires_in}. Renews the
    session's id token from the long-lived refresh token (no password needed)."""
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}/auth/refresh-widget",
            json={"refresh_token": refresh_token},
            timeout=15,
        )
    except requests.RequestException:
        raise BackendError("Could not reach the server. Check your connection.")
    if r.status_code == 200:
        return r.json()
    # 400/401/403 = the refresh token itself is no longer valid (revoked, password
    # changed, account removed) -> a real sign-out. Anything else (5xx, proxy error)
    # is transient and must NOT cost the agent their session.
    if r.status_code in (400, 401, 403):
        raise AuthError("Your session is no longer valid. Please sign in again.")
    raise BackendError(f"Session refresh failed (server error {r.status_code}).")


def api_get_config(base_url: str, token: str, etag: str | None = None,
                   department: str | None = None):
    """GET /api/widget/config. Returns the requests.Response (caller inspects).

    `department` (a department key) scopes the config to shared ∪ that
    department. Omitted -> the backend falls back to the agent's home
    department, else the whole company (backward compatible)."""
    headers = {"Authorization": f"Bearer {token}"}
    if etag:
        headers["If-None-Match"] = etag
    params = {"department": department} if department else None
    try:
        return requests.get(
            f"{base_url.rstrip('/')}/api/widget/config",
            headers=headers, params=params, timeout=15,
        )
    except requests.RequestException:
        raise BackendError("Could not reach the server. Check your connection.")


def api_get_me(base_url: str, token: str) -> dict:
    """GET /api/me -> the current user's profile (id, full_name, email, role,
    company, department). Raises BackendError on any non-200."""
    try:
        r = requests.get(
            f"{base_url.rstrip('/')}/api/me",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
    except requests.RequestException:
        raise BackendError("Could not reach the server. Check your connection.")
    if r.status_code == 200:
        return r.json()
    raise BackendError(f"Could not load your profile (server error {r.status_code}).")


def _user_from_me(me: dict) -> dict:
    """Map a /api/me payload to the widget's internal _user shape
    ({id, name, email, company_name, role}), as returned by login-widget."""
    me = me or {}
    return {
        "id": me.get("id", "") or "",
        "name": me.get("full_name") or "",
        "email": me.get("email", "") or "",
        "company_name": (me.get("company") or {}).get("name", "") or "",
        "role": me.get("role", "") or "",
    }


# ──────────────────────────────────────────────────────────────
# Login worker: authenticate then load config, off the UI thread
# ──────────────────────────────────────────────────────────────
def _load_json_setting(settings, key) -> dict:
    """Read a JSON blob from QSettings, tolerating anything malformed/absent."""
    try:
        raw = settings.value(key, "") or ""
        if raw:
            val = json.loads(raw)
            if isinstance(val, dict):
                return val
    except Exception:
        pass
    return {}


def _as_expires_in(value) -> int:
    """Firebase returns expiresIn as a string of seconds; be tolerant."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 3600


def _needs_token_refresh(token, refresh_token, inflight, expiry, now=None) -> bool:
    """Pure decision (unit-testable without Qt): renew when we hold a session that's
    within 10 min of expiry (or of unknown age, expiry=0) plus a refresh token to
    renew it, and no refresh is already running."""
    now = time.time() if now is None else now
    return bool(token and refresh_token and not inflight and now >= expiry - 600)


class LoginWorker(QThread):
    # token, refresh_token, expires_in, user, config, etag
    succeeded = pyqtSignal(str, str, int, dict, dict, str)
    failed = pyqtSignal(str)

    def __init__(self, base_url, email, password, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.email = email
        self.password = password

    def run(self):
        try:
            data = api_login(self.base_url, self.email, self.password)
            token = data.get("token", "")
            refresh_token = data.get("refresh_token", "") or ""
            expires_in = _as_expires_in(data.get("expires_in"))
            user = data.get("user", {}) or {}
            if not token:
                raise BackendError("Server did not return a session token.")
            resp = api_get_config(self.base_url, token)
            if resp.status_code != 200:
                raise BackendError(
                    f"Could not load your company config ({resp.status_code}).")
            config = resp.json()
            etag = resp.headers.get("ETag", "")
            self.succeeded.emit(token, refresh_token, expires_in, user, config, etag)
        except BackendError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


class RefreshWorker(QThread):
    """Silently renews the id token from the refresh token, off the UI thread, so
    an idle widget never gets logged out mid-shift."""
    refreshed = pyqtSignal(str, str, int)   # token, refresh_token, expires_in
    failed = pyqtSignal(str)                # transient — keep the session, retry
    rejected = pyqtSignal()                 # credentials revoked — sign out

    def __init__(self, base_url, refresh_token, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.refresh_token = refresh_token

    def run(self):
        try:
            data = api_refresh(self.base_url, self.refresh_token)
            token = data.get("token", "") or ""
            if not token:
                raise BackendError("Server did not return a refreshed token.")
            refresh_token = data.get("refresh_token", "") or self.refresh_token
            self.refreshed.emit(token, refresh_token, _as_expires_in(data.get("expires_in")))
        except AuthError:
            # The refresh token itself was rejected (revoked, password changed, account
            # deleted). Must be caught BEFORE BackendError — AuthError subclasses it —
            # or a revoked agent would keep working for as long as the widget stays open.
            self.rejected.emit()
        except BackendError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


class ValidateWorker(QThread):
    """Restore a stored session at launch, off the UI thread.

    Two rules keep an agent signed in across restarts:

    1. RENEW BEFORE VALIDATING. The stored id token lives ~1 hour, so after an
       overnight restart it is almost always expired. Validating it first would come
       back 401 and look exactly like a rejected login — which is what used to sign
       agents out every morning. So if we hold a refresh token we mint a fresh id
       token first, then validate that.
    2. ONLY A DEFINITIVE REJECTION SIGNS OUT. "I couldn't reach the server" (no
       network yet — the widget auto-starts the moment Windows logs in, before the
       network is up), a 5xx, or a proxy error are OUR problem, not the agent's:
       those emit `unreachable`, the session is kept and retried. Only a genuine
       401/403 on a token we know is fresh — or a refresh token the backend rejects
       outright — emits `invalid`.
    """
    # config, etag, user, token, refresh_token, expires_in  (config={} on 304)
    valid = pyqtSignal(dict, str, dict, str, str, int)
    invalid = pyqtSignal()          # credentials really are dead -> sign out
    unreachable = pyqtSignal(str)   # transient -> keep the session, retry later

    def __init__(self, base_url, token, etag, refresh_token="", parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.token = token
        self.etag = etag
        self.refresh_token = refresh_token or ""

    def run(self):
        token = self.token
        refresh_token = self.refresh_token
        expires_in = 0
        refreshed = False

        # 1. Renew first (see rule 1 above).
        if refresh_token:
            try:
                data = api_refresh(self.base_url, refresh_token)
                token = data.get("token") or token
                refresh_token = data.get("refresh_token") or refresh_token
                expires_in = _as_expires_in(data.get("expires_in"))
                refreshed = True
            except AuthError as exc:
                # The one path that legitimately signs an agent out. Log it: an
                # unexplained sign-out is impossible to support otherwise.
                print(f"[auth] SIGN-OUT: the server rejected our refresh token ({exc})")
                self.invalid.emit()
                return
            except BackendError as exc:
                # Transient: fall through and try the stored id token as-is; it may
                # still be inside its hour.
                print(f"[widget] startup refresh deferred: {exc}")

        if not token:
            print("[auth] SIGN-OUT: no token available to validate")
            self.invalid.emit()
            return

        # 2. Validate (and pick up config changes).
        try:
            resp = api_get_config(self.base_url, token, self.etag or None)
        except BackendError as exc:
            self.unreachable.emit(str(exc))
            return

        if resp.status_code in (401, 403):
            # Only definitive when the token we just used is known-fresh (or there was
            # no refresh token to try). If the refresh failed transiently, this 401 is
            # just the stale token — keep the session and retry.
            if refreshed or not self.refresh_token:
                print(f"[auth] SIGN-OUT: config returned {resp.status_code} on a "
                      f"{'freshly renewed' if refreshed else 'stored'} token")
                self.invalid.emit()
            else:
                self.unreachable.emit("could not renew the session yet")
            return
        if resp.status_code not in (200, 304):
            self.unreachable.emit(f"server error {resp.status_code}")
            return

        # Token is good -> restore the agent's profile. Best-effort: a /api/me hiccup
        # must not fail the launch (the token is still valid).
        user = {}
        try:
            user = _user_from_me(api_get_me(self.base_url, token))
        except Exception:
            pass
        if resp.status_code == 304:
            self.valid.emit({}, self.etag, user, token, refresh_token, expires_in)
        else:
            self.valid.emit(resp.json(), resp.headers.get("ETag", ""), user,
                            token, refresh_token, expires_in)


class StartCallWorker(QThread):
    """Runs AudioStreamer.connect() (WebSocket + identify + session_start, which
    includes server-side token validation) OFF the UI thread, so pressing Start
    never freezes the widget for the handshake."""
    connected = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, streamer, parent=None):
        super().__init__(parent)
        self.streamer = streamer

    def run(self):
        try:
            self.streamer.connect()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.connected.emit()


class ControlConnection(QThread):
    """Persistent login-time WebSocket. It `identify`s the agent so the dialer can
    reach an IDLE widget (registers in the server's agent index) and forwards
    inbound control messages (dialer_activate / dialer_stop) to the widget. It
    does NO recording/session — that's the per-call AudioStreamer. Reconnects with
    a short backoff so the widget stays reachable across drops/server restarts."""
    message = pyqtSignal(dict)

    _BACKOFF_SECONDS = 3.0

    def __init__(self, server_url, client_id, agent_id, agent_email, parent=None):
        super().__init__(parent)
        self.server_url = server_url
        self.client_id = client_id
        self.agent_id = agent_id
        self.agent_email = agent_email
        self._stop = threading.Event()
        self._ws = None

    def _serve_once(self):
        """One connect → identify → receive-until-error pass (no reconnect)."""
        ws = _websocket.create_connection(
            self.server_url, timeout=WS_CONNECT_TIMEOUT, enable_multithread=True)
        # Let the server take its time to answer identify; a 10s read budget made a
        # busy server drop every widget out of the dialer index for a 3s backoff,
        # adding reconnect churn to the very load that caused it.
        ws.settimeout(WS_HANDSHAKE_TIMEOUT)
        self._ws = ws
        try:
            ws.send(json.dumps({
                "command": "identify",
                "client_id": self.client_id,
                "client_name": "SparkFlowWidget-control",
                "agent_email": self.agent_email,
                "agent_id": self.agent_id,
            }))
            if json.loads(ws.recv()).get("status") != "identified":
                return   # server didn't accept us — let run() back off + retry
            ws.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    raw = ws.recv()
                except _websocket.WebSocketTimeoutException:
                    continue                 # idle tick — re-check stop flag
                except Exception:
                    break                    # dropped — reconnect
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if isinstance(msg, dict):
                    self.message.emit(msg)
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def run(self):
        while not self._stop.is_set():
            try:
                self._serve_once()
            except Exception:
                pass                         # connect failed — back off + retry
            if not self._stop.is_set():
                self._stop.wait(self._BACKOFF_SECONDS)

    def stop(self):
        self._stop.set()
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass


class ConfigRefreshWorker(QThread):
    """Re-fetch the widget config scoped to a department (dialer leg switch).
    Best-effort: on any failure we keep the current config."""
    loaded = pyqtSignal(dict, str)   # config, etag

    def __init__(self, base_url, token, department, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.token = token
        self.department = department

    def run(self):
        try:
            resp = api_get_config(self.base_url, self.token, department=self.department)
            if resp.status_code == 200:
                self.loaded.emit(resp.json(), resp.headers.get("ETag", ""))
        except Exception:
            pass   # keep existing config


# ──────────────────────────────────────────────────────────────
# Recording thread  (UNCHANGED audio capture logic)
# ──────────────────────────────────────────────────────────────
class RecordingThread(QThread):
    """Captures audio from one PyAudio device and writes it to a WAV file."""

    error_occurred = pyqtSignal(str)
    stream_ready = pyqtSignal(str, int, int)   # stream_type, channels, sample_rate

    def __init__(
        self,
        device_index: int,
        stream_type: str,
        sample_rate: int,
        channels: int,
        send_callback,
        is_loopback: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.device_index = device_index
        self.stream_type = stream_type
        self.sample_rate = sample_rate
        self.channels = channels
        self.send_callback = send_callback
        self.is_loopback = is_loopback
        self._stop_event = threading.Event()
        self._start_ack = threading.Event()

    @staticmethod
    def _try_open_stream(p, channels: int, rate: int, device_index: int):
        try:
            return p.open(
                format=AUDIO_FORMAT,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK,
            )
        except Exception:
            return None

    def run(self):
        p = pyaudio.PyAudio()
        stream = None
        try:
            if self.is_loopback:
                # Capture the customer side at the render device's TRUE mix format.
                # Probe device-supported (channels, rate) — guessing a wrong format
                # (the old blind open) produced misaligned/garbled audio. Candidates
                # lead with the device's reported values; 16000 covers Bluetooth HFP.
                def _supported(ch, rate, _p=p, _idx=self.device_index):
                    try:
                        return bool(_p.is_format_supported(
                            rate, input_device=_idx, input_channels=ch,
                            input_format=AUDIO_FORMAT))
                    except Exception:
                        return False

                ch_candidates = list(dict.fromkeys([max(1, self.channels), 2, 1]))
                reported = self.sample_rate if self.sample_rate > 0 else 48000
                rate_candidates = list(dict.fromkeys([reported, 48000, 44100, 16000]))
                chosen = _pick_stream_format(_supported, ch_candidates, rate_candidates)

                if chosen is not None:
                    actual_channels, actual_rate = chosen
                else:
                    # Nothing reported supported — fall back to the device's values
                    # so we still record (better degraded than nothing).
                    actual_channels = max(1, self.channels)
                    actual_rate = reported
                stream = p.open(
                    format=AUDIO_FORMAT,
                    channels=actual_channels,
                    rate=actual_rate,
                    input=True,
                    input_device_index=self.device_index,
                    frames_per_buffer=CHUNK,
                )
            else:
                candidate_channels = list(dict.fromkeys([
                    max(1, min(self.channels, 2)),
                    1,
                    2,
                ]))
                reported_rate = self.sample_rate if self.sample_rate > 0 else 48000
                candidate_rates = list(dict.fromkeys([
                    reported_rate,
                    48000,
                    44100,
                ]))

                actual_channels = None
                actual_rate = None

                for ch in candidate_channels:
                    for rate in candidate_rates:
                        stream = self._try_open_stream(
                            p, ch, rate, self.device_index)
                        if stream is not None:
                            actual_channels = ch
                            actual_rate = rate
                            break
                    if stream is not None:
                        break

                if stream is None:
                    self.error_occurred.emit(
                        "Microphone: could not open audio stream with any format combination."
                    )
                    return

            self.stream_ready.emit(
                self.stream_type, actual_channels, actual_rate)
            if not self._start_ack.wait(timeout=10):
                self.error_occurred.emit(
                    f"Timeout waiting for server to acknowledge {self.stream_type} stream."
                )
                return

            while not self._stop_event.is_set():
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    self.send_callback(self.stream_type, data)
                except OSError as exc:
                    self.error_occurred.emit(f"Stream read error: {exc}")
                    break

        except Exception as exc:
            self.error_occurred.emit(str(exc))
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            p.terminate()

    def stop(self):
        self._stop_event.set()


# ──────────────────────────────────────────────────────────────
# Audio streamer (WebSocket client)
# ──────────────────────────────────────────────────────────────
try:
    import websocket as _websocket  # websocket-client package
except ImportError:
    sys.exit(
        "websocket-client is not installed.\n"
        "Install it with:  pip install websocket-client"
    )


# ──────────────────────────────────────────────────────────────
# Auto-update
# ──────────────────────────────────────────────────────────────
def _version_tuple(v: str) -> tuple:
    """'2.4.10' -> (2, 4, 10) for correct ordering (10 > 9, unlike string compare).
    Unparseable pieces sort as 0 rather than blowing up."""
    parts = []
    for chunk in str(v or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer_version(latest: str, current: str) -> bool:
    """True only when `latest` is strictly newer, comparing numerically and padding
    so '2.5' > '2.4.9' and '2.4' == '2.4.0'."""
    if not latest:
        return False
    a, b = _version_tuple(latest), _version_tuple(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _url_origin(url: str):
    """(scheme, host, port) for a URL, or None if it isn't plain http(s)."""
    try:
        p = urlparse((url or "").strip())
    except Exception:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    return (p.scheme, p.hostname.lower(), p.port or (443 if p.scheme == "https" else 80))


# Hosts we accept a release from over HTTPS, in addition to the backend's own host.
# Releases are published to GitHub, and GitHub redirects asset downloads to its CDN.
# HTTPS is what makes these safe: the host is authenticated and the bytes can't be
# tampered with in flight, so a spoofed /api/version can't redirect us to an attacker.
TRUSTED_UPDATE_HOSTS = ("github.com", "githubusercontent.com")


def _host_is_trusted(host: str, api_base: str = "") -> bool:
    host = (host or "").lower()
    if api_base:
        base = _url_origin(api_base)
        if base is not None and host == base[1]:
            return True          # our own backend, http or https
    return any(host == h or host.endswith("." + h) for h in TRUSTED_UPDATE_HOSTS)


def is_safe_installer_url(url: str, api_base: str = "") -> bool:
    """Gate on what we're about to DOWNLOAD AND EXECUTE.

    /api/version is plaintext today, so its JSON must not be able to point us at an
    arbitrary binary. Accepted sources are only:
      * the backend's own host (any scheme — the LAN deployment is http), or
      * an HTTPS release host we trust (GitHub, where releases are published).
    Plain http anywhere else is refused: without TLS we cannot tell the real host from
    someone impersonating it.
    """
    origin = _url_origin(url)
    if origin is None:
        return False
    scheme, host, _port = origin
    path = (url or "").split("?", 1)[0].split("#", 1)[0]
    if not path.lower().endswith(".exe"):
        return False
    if not _host_is_trusted(host, api_base):
        return False
    # Off-backend downloads must be TLS; only our own host may be reached over http.
    base = _url_origin(api_base) if api_base else None
    if scheme != "https" and not (base is not None and host == base[1]):
        return False
    return True


def safe_installer_filename(version: str) -> str:
    """Build the temp filename from a SANITISED version. The version string comes from
    the network, and interpolating it raw would let '../..' escape the temp directory."""
    clean = "".join(ch for ch in str(version or "") if ch.isalnum() or ch in "._-")[:32]
    return f"SparkFlowSetup-{clean or 'update'}.exe"


def api_get_version(base_url: str) -> dict:
    """GET /api/version -> {version, windows_url, mac_url}. Public (no auth)."""
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/version", timeout=10)
    except requests.RequestException as exc:
        raise BackendError(f"version check unreachable: {exc}")
    if r.status_code != 200:
        raise BackendError(f"version check failed ({r.status_code})")
    return r.json() or {}


class UpdateCheckWorker(QThread):
    """Ask the backend for the current release and, if it's newer than us, download
    the installer to a temp file. Entirely best-effort: any failure just means no
    update this time — it must never interrupt an agent."""
    update_ready = pyqtSignal(str, str)   # installer_path, version
    no_update = pyqtSignal()

    MAX_BYTES = 300 * 1024 * 1024        # sanity cap on the download

    def __init__(self, base_url: str, current_version: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.current_version = current_version

    def run(self):
        try:
            info = api_get_version(self.base_url)
            latest = str(info.get("version") or "")
            url = str(info.get("windows_url") or "")
            if not is_newer_version(latest, self.current_version):
                self.no_update.emit()
                return
            if not is_safe_installer_url(url, self.base_url):
                print(f"[update] {latest} available but the download URL is not trusted: {url!r}")
                self.no_update.emit()
                return
            print(f"[update] {self.current_version} -> {latest}; downloading installer")
            dest = Path(tempfile.gettempdir()) / safe_installer_filename(latest)
            # Redirects are followed (GitHub bounces release assets to its CDN) but the
            # host we ACTUALLY downloaded from is re-checked below — a redirect must not
            # be able to smuggle us off a trusted host onto an attacker's.
            with requests.get(url, stream=True, timeout=60) as r:
                if r.status_code != 200:
                    raise BackendError(f"download failed ({r.status_code})")
                final = _url_origin(str(r.url))
                if final is None or not _host_is_trusted(final[1], self.base_url):
                    raise BackendError(f"download redirected to an untrusted host: {r.url}")
                written = 0
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=262144):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > self.MAX_BYTES:
                            raise BackendError("installer larger than expected — aborting")
                        fh.write(chunk)
            # A truncated download or an HTML error page would brick the update, so
            # only accept something that really is a Windows executable.
            with open(dest, "rb") as fh:
                if fh.read(2) != b"MZ":
                    raise BackendError("downloaded file is not a Windows installer")
            print(f"[update] installer ready at {dest} ({written} bytes)")
            self.update_ready.emit(str(dest), latest)
        except Exception as exc:  # noqa: BLE001 — never let an update check surface
            print(f"[update] check skipped: {exc}")
            self.no_update.emit()


def build_updater_script(installer: str, exe: str, minimized: bool) -> str:
    """The batch a detached cmd runs after we quit.

    A running exe can't overwrite itself, so the sequence has to happen from
    outside the process: wait for us to exit, run the installer silently, relaunch.
    The install is per-user (Inno PrivilegesRequired=lowest), so there's no UAC
    prompt. Finally it deletes the installer and itself.
    """
    args = " --minimized" if minimized else ""
    exe_name = os.path.basename(exe) or "SparkFlow.exe"
    return (
        "@echo off\r\n"
        "ping 127.0.0.1 -n 4 >nul\r\n"                     # ~3s: let the widget exit
        f'"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS\r\n'
        # Let the installer settle and antivirus finish scanning the new exe before
        # launching it — starting too eagerly is how the relaunch gets swallowed.
        "ping 127.0.0.1 -n 4 >nul\r\n"
        f'start "" "{exe}"{args}\r\n'
        # Verify it actually came up; AV can silently block the first attempt.
        "ping 127.0.0.1 -n 8 >nul\r\n"
        f'tasklist /FI "IMAGENAME eq {exe_name}" 2>nul | find /I "{exe_name}" >nul\r\n'
        f'if errorlevel 1 start "" "{exe}"{args}\r\n'
        f'del "{installer}" >nul 2>&1\r\n'
        'del "%~f0" >nul 2>&1\r\n'
    )


def _spool_dir() -> Path:
    """Where interrupted-call audio is buffered. Per-user app data (survives a reboot,
    unlike %TEMP% cleaners); falls back to the temp dir if that isn't writable."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = Path(base) / "Spark Flow" / "spool"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path(tempfile.gettempdir()) / "SparkFlowSpool"
        d.mkdir(parents=True, exist_ok=True)
        return d


def purge_old_spools(max_age_days: int = 7) -> int:
    """Delete spool files we could never deliver, once they're older than
    `max_age_days`. Undelivered call audio is kept for a while so it isn't silently
    lost, but it is PII, so retention is bounded. Returns how many were removed."""
    removed = 0
    try:
        cutoff = time.time() - max_age_days * 86400
        for f in _spool_dir().glob("*.spool"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    except Exception:
        pass
    return removed


class AudioStreamer:
    """Manages a single WebSocket connection to the recording server.

    Survives a mid-call disconnect. If the socket dies while recording, audio is
    spooled to a local file instead of being thrown away, a background thread
    reconnects and RESUMES the same server-side session, the spool is replayed in
    order, and only then does live streaming continue. Net effect: the stored
    recording has no gap, and the local copy is deleted as soon as it is delivered.
    """

    _CONNECT_TIMEOUT = WS_CONNECT_TIMEOUT
    _HANDSHAKE_TIMEOUT = WS_HANDSHAKE_TIMEOUT
    # Reconnect backoff (seconds) — quick at first, then easy on a struggling network.
    _RECONNECT_BACKOFF = (1, 2, 4, 8, 15, 30)
    # Give up resuming after this long. Must stay UNDER the server's resume grace
    # window (RESUME_GRACE_SECONDS there), or we'd reconnect to a finalized session.
    _RESUME_DEADLINE_SECS = 150

    def __init__(
        self,
        server_url: str,
        client_id: str,
        session_id: str,
        agent_id: str,
        customer_name: str,
        customer_id: str,
        reference_id: str,
        token: str = "",
        agent_email: str = "",
        department: str = "",
        dialer_metadata: dict | None = None,
        register_for_dialer: bool = True,
        token_provider=None,
    ):
        # When False, the identify message omits agent_email/agent_id so this
        # connection does NOT register in the server's dialer index. The per-call
        # recording connection uses False so it won't clobber the persistent
        # ControlConnection's registration.
        self.register_for_dialer = register_for_dialer
        self.department = department  # call-leg department key (scopes the checklist)
        # Dialer call metadata (lead id, campaign, direction, transfer flag) for a
        # dialer-originated call; the server stores it on the session. None = manual.
        self.dialer_metadata = dialer_metadata
        self.server_url = server_url
        self.client_id = client_id
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_email = agent_email
        self.customer_name = customer_name
        self.customer_id = customer_id
        self.reference_id = reference_id
        self.token = token  # Phase 4: server validates this at session_start
        # Optional callable returning the CURRENT id token. The one above is a snapshot
        # from call start; on a long call it will have expired (~1h) by the time a
        # resume needs it, and the server would refuse. Set by MainWindow.
        self.token_provider = token_provider
        self._ws = None
        # Whether the server runs the live transcription/compliance pipeline for
        # this session (from the session_started ack). Default True = behave as
        # before (show compliance summary) for older servers that don't send it.
        self.live_pipeline = True
        self._lock = threading.Lock()
        self._receiver_stop = threading.Event()
        self._receiver_thread: threading.Thread | None = None
        # PCI pause: when set, send_audio drops chunks so nothing is recorded
        # during card capture. A STATE (not a toggle) so the manual button and a
        # future dialer pause/resume trigger can both drive it without fighting.
        self._pause_event = threading.Event()
        # Phase 3: set by MainWindow to receive inbound server messages.
        self.on_message = None

        # ── Interrupted-call buffering ──────────────────────────────────────
        # Set while the socket is down: send_audio spools to disk instead of
        # dropping chunks, and a reconnect thread works on resuming the session.
        self._degraded = threading.Event()
        self._closing = threading.Event()
        self._spool_path: Path | None = None
        self._spool_w = None            # append handle
        self._spool_r = None            # read handle (opened when draining)
        self._spool_lock = threading.Lock()   # guards the spool handles only
        self._reconnect_thread: threading.Thread | None = None
        # Streams we've started, so a resumed connection can be closed down
        # properly (stop per stream, then session_end) if the call already ended.
        self._started_streams: list = []
        # 'start' frames that never reached the server because the socket was already
        # down; replayed immediately after a resume so the streams exist again.
        self._deferred_starts: list = []
        self._final_stop = threading.Event()  # user ended the call while degraded
        # Set once we stop trying to resume. Audio after this point can never reach
        # the server, so it is dropped rather than spooled forever.
        self._gave_up = threading.Event()
        # Only set once the server has accepted session_start. Until then there is
        # no session to resume, so a failure must surface to connect() as an error
        # rather than kicking off a pointless reconnect loop.
        self._session_live = threading.Event()

    def set_paused(self, paused: bool):
        """Set the pause state (idempotent). Paused = audio chunks dropped."""
        if paused:
            self._pause_event.set()
        else:
            self._pause_event.clear()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def connect(self):
        """Open WebSocket, identify the client, and start a session."""
        self._ws = _websocket.create_connection(
            self.server_url, timeout=self._CONNECT_TIMEOUT, enable_multithread=True
        )
        # The connect timeout also governs every later read on this socket, and the
        # two handshake replies below wait on the server, not on the network.
        self._ws.settimeout(self._HANDSHAKE_TIMEOUT)

        identify_msg = {
            "command":     "identify",
            "client_id":   self.client_id,
            "client_name": "SparkFlowWidget",
        }
        # Only register this connection for dialer targeting when asked. The
        # persistent ControlConnection registers; the per-call recording
        # connection does NOT (so it can't clobber that registration).
        if self.register_for_dialer:
            identify_msg["agent_email"] = self.agent_email
            identify_msg["agent_id"] = self.agent_id
        self._send_json(identify_msg)
        resp = json.loads(self._ws.recv())
        if resp.get("status") != "identified":
            raise RuntimeError(f"Server identification failed: {resp}")

        session_payload = {
            "command":       "session_start",
            "client_id":     self.client_id,
            "session_id":    self.session_id,
            "agent_id":      self.agent_id,
            "customer_name": self.customer_name,
            "customer_id":   self.customer_id,
            "reference_id":  self.reference_id,
            "token":         self.token,
            "timestamp":     datetime.datetime.now().isoformat(),
        }
        # Scope the server-side compliance checklist to this call's department
        # (omitted -> server uses the agent's home department / company-wide).
        if self.department:
            session_payload["department"] = self.department
        # Forward dialer call metadata so the server can label the stored session
        # (omitted for manual calls -> backward compatible).
        if self.dialer_metadata:
            session_payload["dialer_metadata"] = self.dialer_metadata
        self._send_json(session_payload)
        resp = json.loads(self._ws.recv())
        if resp.get("status") != "session_started":
            raise RuntimeError(f"Server session_start failed: {resp}")
        self.live_pipeline = bool(resp.get("live_pipeline", True))
        # From here on a socket failure is recoverable: the server holds the session
        # open for a grace period, so we buffer locally and resume.
        self._session_live.set()

        self._receiver_stop.clear()
        self._receiver_thread = threading.Thread(
            target=self._receiver_loop, args=(self._ws,),
            daemon=True, name="ws-receiver"
        )
        self._receiver_thread.start()

    def _receiver_loop(self, ws=None):
        """Drain inbound frames: keep pings answered AND dispatch JSON messages.

        websocket-client auto-sends a pong when recv() reads a ping frame.
        We use a 1 s timeout so _receiver_stop is checked promptly, parse JSON
        messages, and forward dict payloads to on_message (set by MainWindow).
        Non-JSON frames (pongs etc.) are ignored.

        `ws` is bound for the life of this thread. After a resume there is briefly an
        old thread still unwinding on the previous socket; binding it here lets that
        thread recognise it is stale and stay quiet instead of reporting the NEW,
        healthy connection as broken.
        """
        ws = ws if ws is not None else self._ws
        try:
            # NOT a poll interval: this is the whole socket's timeout, sends included
            # (see WS_STREAM_TIMEOUT). The loop doesn't need a short tick to shut down —
            # close() closes the socket, which makes a blocked recv raise at once.
            ws.settimeout(WS_STREAM_TIMEOUT)
        except Exception:
            pass
        print("[recv] receiver loop started")
        while not self._receiver_stop.is_set():
            try:
                raw = ws.recv()
            except _websocket.WebSocketTimeoutException:
                continue                      # idle tick – re-check stop flag
            except Exception as exc:
                print(f"[recv] loop EXIT on {type(exc).__name__}: {exc}")
                # A dead socket usually shows up here first (the server closed it,
                # or the link died). If the call is still running ON THIS socket,
                # start buffering rather than waiting for the next chunk to fail.
                # `ws is self._ws` keeps a stale post-resume thread from wrongly
                # declaring the new connection dead.
                if (self._session_live.is_set() and not self._receiver_stop.is_set()
                        and not self._closing.is_set() and ws is self._ws):
                    self._enter_degraded(f"receiver: {type(exc).__name__}")
                break                         # socket closed / error – exit
            if not raw:
                continue
            print(f"[recv] {str(raw)[:90]}")
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue                      # not JSON – ignore
            if self.on_message and isinstance(msg, dict):
                try:
                    self.on_message(msg)
                except Exception:
                    pass
        print("[recv] receiver loop ended")

    def start_stream(self, stream_type: str, channels: int, sample_rate: int):
        if stream_type not in self._started_streams:
            self._started_streams.append(stream_type)
        self._send_json({
            "command":     "start",
            "client_id":  self.client_id,
            "stream_type": stream_type,
            "channels":    channels,
            "sample_rate": sample_rate,
        })

    def send_audio(self, stream_type: str, audio_data: bytes):
        """Send a raw PCM chunk with the binary framing the server expects.

        If the socket is down the chunk is written to the local spool instead of
        being discarded, and a reconnect is kicked off. Nothing is ever lost to a
        dropped connection — the spool is replayed once the session resumes.
        """
        # PCI pause: drop the chunk while paused so card audio is never sent or
        # written. Both mic and speaker flow through here, so both pause together.
        if self._pause_event.is_set():
            return
        # Resume already timed out: the server finalized this call, so nothing more can
        # be delivered. Drop rather than spool — otherwise the file grows for the rest
        # of the call for audio that can never be sent.
        if self._gave_up.is_set():
            return
        type_bytes = stream_type.encode("utf-8")
        packet = struct.pack("I", len(type_bytes)) + type_bytes + audio_data

        # Already buffering -> straight to disk, preserving order. The check and the
        # write happen under the SAME lock the drain uses to flip back to live, so a
        # chunk can't slip through the check and then recreate a spool file the drain
        # has just deleted (which would strand it, out of order, forever).
        with self._spool_lock:
            if self._degraded.is_set():
                self._spool_write_locked(packet)
                return
        try:
            with self._lock:
                self._ws.send_binary(packet)
        except Exception as exc:
            # The socket just died mid-call. Keep this chunk and start recovering.
            self._enter_degraded(f"send failed: {type(exc).__name__}")
            self._spool_write(packet)

    # ── interrupted-call buffering ─────────────────────────────────────────
    def _spool_write(self, packet: bytes) -> None:
        """Append one length-prefixed frame to the local spool file."""
        with self._spool_lock:
            self._spool_write_locked(packet)

    def _spool_write_locked(self, packet: bytes) -> None:
        """_spool_write for callers that already hold _spool_lock."""
        try:
            if self._spool_w is None:
                if self._spool_path is None:
                    self._spool_path = _spool_dir() / f"{self.session_id}.spool"
                self._spool_w = open(self._spool_path, "ab")
            self._spool_w.write(struct.pack("<I", len(packet)) + packet)
            self._spool_w.flush()
        except Exception as exc:
            print(f"[buffer] spool write failed: {exc}")

    def _spool_next(self):
        """Read the next spooled frame, or None at end-of-spool."""
        with self._spool_lock:
            return self._spool_next_locked()

    def _spool_next_locked(self):
        """_spool_next for callers that already hold _spool_lock."""
        try:
            if self._spool_r is None:
                if self._spool_path is None or not self._spool_path.exists():
                    return None
                self._spool_r = open(self._spool_path, "rb")
            header = self._spool_r.read(4)
            if len(header) < 4:
                # Partial header (writer mid-flush). Rewind so the next read starts
                # on the frame boundary — otherwise the whole spool desyncs.
                if header:
                    self._spool_r.seek(-len(header), os.SEEK_CUR)
                return None
            (n,) = struct.unpack("<I", header)
            payload = self._spool_r.read(n)
            if len(payload) < n:              # torn tail (writer mid-flush) — retry later
                self._spool_r.seek(-len(header) - len(payload), os.SEEK_CUR)
                return None
            return payload
        except Exception as exc:
            print(f"[buffer] spool read failed: {exc}")
            return None

    def _spool_discard(self) -> None:
        """Delete the local copy — called once everything has reached the server."""
        with self._spool_lock:
            self._spool_discard_locked()

    def _spool_discard_locked(self) -> None:
        """_spool_discard for callers that already hold _spool_lock."""
        for h in ("_spool_r", "_spool_w"):
            try:
                handle = getattr(self, h)
                if handle is not None:
                    handle.close()
            except Exception:
                pass
            setattr(self, h, None)
        try:
            if self._spool_path is not None and self._spool_path.exists():
                self._spool_path.unlink()
        except OSError as exc:
            print(f"[buffer] could not delete spool: {exc}")

    def _enter_degraded(self, reason: str) -> None:
        """Switch to local buffering and start trying to resume the session."""
        if self._degraded.is_set() or self._closing.is_set() or self._gave_up.is_set():
            return
        self._degraded.set()
        print(f"[buffer] connection lost ({reason}) — buffering locally and reconnecting")
        self._notify({"type": "connection_status", "state": "buffering", "reason": reason})
        # The old receiver is looping on a dead socket; let it exit.
        self._receiver_stop.set()
        if self._reconnect_thread is None or not self._reconnect_thread.is_alive():
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop, daemon=True, name="ws-reconnect")
            self._reconnect_thread.start()

    def _notify(self, msg: dict) -> None:
        """Surface a locally-generated status message on the same path as server
        messages, so the UI can show 'reconnecting' without a second mechanism."""
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception:
                pass

    def _reconnect_loop(self) -> None:
        deadline = time.time() + self._RESUME_DEADLINE_SECS
        attempt = 0
        while self._degraded.is_set() and not self._closing.is_set():
            if time.time() > deadline:
                # Stop spooling. The server has finalized this session by now, so
                # nothing more can ever be delivered — continuing would just grow the
                # file on the agent's disk at ~10 MB/min for the rest of the call.
                self._gave_up.set()
                self._degraded.clear()
                with self._spool_lock:
                    try:
                        if self._spool_w is not None:
                            self._spool_w.close()
                    except Exception:
                        pass
                    self._spool_w = None
                print(f"[buffer] gave up resuming after {self._RESUME_DEADLINE_SECS}s; "
                      f"audio captured up to that point kept at {self._spool_path}")
                self._notify({"type": "connection_status", "state": "failed"})
                return
            delay = self._RECONNECT_BACKOFF[min(attempt, len(self._RECONNECT_BACKOFF) - 1)]
            attempt += 1
            if self._closing.wait(timeout=delay):
                return
            try:
                if self._reconnect_once():
                    print("[buffer] session resumed — buffered audio delivered")
                    self._notify({"type": "connection_status", "state": "resumed"})
                    if self._final_stop.is_set():
                        self._finish_after_resume()
                    return
            except Exception as exc:
                print(f"[buffer] resume attempt {attempt} failed: {exc}")

    def _reconnect_once(self) -> bool:
        """One resume attempt: reopen, re-identify, resume the SAME session, then
        replay the spool. Returns True only when the spool is fully delivered."""
        ws = _websocket.create_connection(
            self.server_url, timeout=self._CONNECT_TIMEOUT, enable_multithread=True)
        # Same reasoning as connect(): the resume handshake waits on the server. A
        # 10s read budget here meant a busy server could not be resumed at all, so a
        # recording that WAS safely buffered still got stored as a dropped call.
        ws.settimeout(self._HANDSHAKE_TIMEOUT)
        try:
            ws.send(json.dumps({
                "command": "identify",
                "client_id": self.client_id,       # same id -> same server-side streams
                "client_name": "SparkFlowWidget",
            }))
            if json.loads(ws.recv()).get("status") != "identified":
                ws.close()
                return False
            # Use the freshest token we can get: on a long call the one captured at
            # session_start has already expired.
            token = self.token
            if self.token_provider is not None:
                try:
                    token = self.token_provider() or token
                except Exception:
                    pass
            ws.send(json.dumps({
                "command": "session_resume",
                "client_id": self.client_id,
                "session_id": self.session_id,
                "token": token,
            }))
            resp = json.loads(ws.recv())
            if resp.get("status") != "session_resumed":
                print(f"[buffer] server refused resume: {resp}")
                ws.close()
                return False
        except Exception:
            try:
                ws.close()
            except Exception:
                pass
            raise

        # Swap in the live socket and restart the receiver.
        with self._lock:
            old, self._ws = self._ws, ws
        try:
            if old is not None:
                old.close()
        except Exception:
            pass
        self._receiver_stop.clear()
        self._receiver_thread = threading.Thread(
            target=self._receiver_loop, args=(ws,), daemon=True, name="ws-receiver")
        self._receiver_thread.start()

        # Re-open any stream whose 'start' was lost to the outage, BEFORE replaying —
        # otherwise the server has nowhere to write the frames we're about to send.
        if self._deferred_starts:
            pending, self._deferred_starts = self._deferred_starts, []
            for frame_ in pending:
                try:
                    with self._lock:
                        self._ws.send(json.dumps(frame_))
                    print(f"[buffer] re-opened '{frame_.get('stream_type')}' after resume")
                except Exception as exc:
                    self._deferred_starts = pending      # try again next attempt
                    print(f"[buffer] could not re-open streams: {exc}")
                    return False

        return self._drain_spool()

    def _drain_spool(self) -> bool:
        """Replay buffered frames in order, then hand back to live streaming.

        Capture keeps appending while we drain, so we only flip back to live when
        the spool is genuinely empty — under the same lock the writer uses, so no
        chunk can slip in behind us and arrive out of order.
        """
        while not self._closing.is_set():
            packet = self._spool_next()
            if packet is None:
                # Looks empty. Re-check holding BOTH locks: _spool_lock is the one
                # send_audio uses to decide "buffer or send", so taking it here makes
                # the emptiness check and the flip back to live atomic against a
                # capture thread — otherwise a chunk could pass that check and then
                # recreate the spool file we are about to delete.
                with self._lock:
                    with self._spool_lock:
                        packet = self._spool_next_locked()
                        if packet is None:
                            self._degraded.clear()
                            self._spool_discard_locked()
                            return True
                    # A chunk landed in that window. We've already consumed it from
                    # the spool, so it MUST be sent here — dropping it would lose
                    # ~93ms of the call.
                    try:
                        self._ws.send_binary(packet)
                        continue
                    except Exception as exc:
                        self._rewind_spool(packet)
                        print(f"[buffer] replay interrupted: {exc}")
                        return False
            try:
                with self._lock:
                    self._ws.send_binary(packet)
            except Exception as exc:
                # Dropped again mid-replay: put this frame back so the next attempt
                # re-sends it instead of losing it.
                self._rewind_spool(packet)
                print(f"[buffer] replay interrupted: {exc}")
                return False
        return False

    def _rewind_spool(self, packet: bytes) -> None:
        """Un-consume the frame we just read, so a failed send doesn't lose it.
        The record on disk is 4 length bytes + the frame."""
        with self._spool_lock:
            try:
                if self._spool_r is not None:
                    self._spool_r.seek(-(len(packet) + 4), os.SEEK_CUR)
            except Exception as exc:
                print(f"[buffer] rewind failed: {exc}")

    def _finish_after_resume(self) -> None:
        """The agent ended the call while we were offline: now that the buffered
        audio has landed, close the call down properly so the server finalizes a
        COMPLETE recording instead of timing the session out as dropped."""
        try:
            for stream_type in list(self._started_streams):
                self.stop_stream(stream_type)
            self.end_session()
            print("[buffer] deferred session_end delivered after resume")
        except Exception as exc:
            print(f"[buffer] deferred session_end failed: {exc}")

    def stop_stream(self, stream_type: str):
        self._send_json({
            "command":     "stop",
            "client_id":  self.client_id,
            "stream_type": stream_type,
        })

    def end_session(self):
        """Send session_end but KEEP the socket open — the Phase 4 server
        sends session_summary / upload_complete after this. Call close()
        once those arrive (or on timeout)."""
        if self._degraded.is_set():
            # The call is over but we're still offline. Record that NOW: the resume
            # thread may reconnect before close()'s 15s timer runs, and without this
            # it would deliver the audio and then just stop — never telling the server
            # the call ended, so a complete recording would time out as "dropped".
            self._final_stop.set()
            print("[buffer] call ended while offline — session_end deferred to the resume")
            return
        self._send_json({
            "command":    "session_end",
            "client_id":  self.client_id,
            "session_id": self.session_id,
        })

    def close(self):
        """Release the connection after post-call messages have arrived.

        If we're still buffering, the reconnect thread is deliberately left running
        (as a daemon) so it can finish delivering this call's audio — closing here
        would throw away recording we already captured. It stops itself on success
        or at its own deadline.
        """
        if self._degraded.is_set():
            print("[buffer] call closed while offline — resume still in progress")
            self._final_stop.set()
            return
        self._closing.set()
        self._receiver_stop.set()
        try:
            self._ws.close()
        except Exception:
            pass
        if self._receiver_thread is not None:
            self._receiver_thread.join(timeout=3)
            self._receiver_thread = None
        self._spool_discard()

    def _send_json(self, data: dict):
        """Send a control frame. While the socket is down these are dropped on
        purpose: replaying stale control frames after a resume would confuse the
        server, and _finish_after_resume re-sends the ones that still matter."""
        if self._degraded.is_set():
            if data.get("command") == "start":
                # A 'start' that never reached the server means that stream does not
                # exist there — the replayed audio would be written nowhere. Queue it
                # and open the stream first thing after the resume.
                self._deferred_starts.append(data)
            print(f"[buffer] control frame '{data.get('command')}' deferred (offline)")
            return
        try:
            with self._lock:
                self._ws.send(json.dumps(data))
        except Exception as exc:
            # Before the session exists there is nothing to resume — let connect()
            # see the failure and fail the call cleanly, as it always has.
            if not self._session_live.is_set():
                raise
            # A control frame failing is the same signal as audio failing: the
            # socket is gone. Start buffering so the call keeps recording.
            self._enter_degraded(f"control send failed: {type(exc).__name__}")


def _smooth_fonts(root: "QWidget"):
    """Antialias + full hinting on root and every descendant widget.

    Needed wherever widgets are created dynamically (e.g. live compliance
    chips) — they miss the startup smoothing pass and render soft otherwise.
    """
    widgets = [root] + root.findChildren(QWidget)
    for w in widgets:
        f = w.font()
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        w.setFont(f)


# ──────────────────────────────────────────────────────────────
# Compliance alert panel  (live checklist during a call)
# ──────────────────────────────────────────────────────────────
class ComplianceAlertPanel(QFrame):
    """Live compliance checklist. update_missing() must be called on the UI thread."""

    # severity palette: (accent, soft tint bg) on the white panel
    _LEVELS = {
        "red":   ("#DC2626", "#FEE2E2"),
        "amber": ("#D97706", "#FEF3C7"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setObjectName("compliancePanel")
        self.setStyleSheet("QFrame#compliancePanel { background:white; border-radius:18px; }")
        self.setFixedWidth(300)   # own floating column beside the call card
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(16, 14, 16, 16)
        self._lay.setSpacing(10)

        # ── heading row: title + count pill ──
        head = QHBoxLayout()
        head.setSpacing(8)
        self._heading = QLabel("COMPLIANCE")
        self._heading.setStyleSheet(
            f"background:transparent; font-size:11px; font-family:{FF};"
            " font-weight:800; color:#1A1A2E; letter-spacing:1.5px;")
        head.addWidget(self._heading)
        head.addStretch(1)
        self._count = QLabel("0")
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count.setStyleSheet(
            f"font-size:10px; font-family:{FF}; font-weight:800; color:white;"
            " background:#6B4EFF; border-radius:8px; padding:1px 8px;")
        head.addWidget(self._count)
        self._lay.addLayout(head)

        # ── transcription status notice (R2): shown when live checking is
        # degraded / down so the agent knows the safety net dropped. ──
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        self._status_label.setStyleSheet(
            f"QLabel {{ font-size:12px; font-family:{FF}; font-weight:700;"
            " color:white; background:#D97706; border-radius:8px; padding:7px 11px; }}")
        self._lay.addWidget(self._status_label)

        # ── forbidden-phrase violations (persistent red banners; a breach the
        # agent already committed, surfaced live). Survives checklist updates. ──
        self._forbidden_box = QVBoxLayout()
        self._forbidden_box.setSpacing(7)
        self._lay.addLayout(self._forbidden_box)

        # ── customer cues (R4): amber banners surfaced when the customer says
        # something noteworthy (e.g. discloses vulnerability). Not agent tasks. ──
        self._cue_box = QVBoxLayout()
        self._cue_box.setSpacing(7)
        self._lay.addLayout(self._cue_box)
        self._cue_seen: set = set()
        self._forbidden_seen: set = set()

        self._items_box = QVBoxLayout()
        self._items_box.setSpacing(7)
        self._lay.addLayout(self._items_box)

        # ── suggestion hint card ──
        self._suggestion = QLabel("")
        self._suggestion.setWordWrap(True)
        self._suggestion.setStyleSheet(
            f"QLabel {{ font-size:13px; font-family:{FF}; font-weight:600;"
            " color:#B91C1C; background:#FEF2F2; border-radius:8px;"
            " padding:9px 12px; }}")
        self._suggestion.setVisible(False)
        self._lay.addWidget(self._suggestion)

    def _clear_items(self):
        while self._items_box.count():
            it = self._items_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _forbidden_banner(self, item: dict) -> QFrame:
        label = item.get("label", "Forbidden phrase used")
        banner = QFrame()
        banner.setObjectName("forbidden")
        banner.setMinimumHeight(40)
        banner.setStyleSheet(
            "QFrame#forbidden { background:#DC2626; border-radius:10px; }")
        row = QHBoxLayout(banner)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(11)
        text = QLabel(f"⚠  Said: {label}")
        text.setWordWrap(True)
        text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text.setStyleSheet(
            f"background:transparent; border:none; color:white;"
            f" font-size:14px; font-family:{FF}; font-weight:700;")
        row.addWidget(text, 1)
        return banner

    def add_forbidden(self, forbidden_hits: list):
        """Surface forbidden-phrase breaches as persistent red banners. Called on
        the UI thread. De-duplicated per call; never cleared by checklist updates."""
        new = [f for f in forbidden_hits if f.get("id") not in self._forbidden_seen]
        if not new:
            return
        for f in new:
            self._forbidden_seen.add(f.get("id"))
            self._forbidden_box.addWidget(self._forbidden_banner(f))
        _smooth_fonts(self)
        self.setVisible(True)
        self.updateGeometry()
        QTimer.singleShot(0, self._sync_window)

    def clear_forbidden(self):
        """Reset forbidden banners (call at the start of a new call)."""
        self._forbidden_seen.clear()
        while self._forbidden_box.count():
            it = self._forbidden_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _cue_banner(self, item: dict) -> QFrame:
        label = item.get("label", "Customer cue")
        suggestion = item.get("suggestion_text") or ""
        banner = QFrame()
        banner.setObjectName("cue")
        banner.setStyleSheet("QFrame#cue { background:#FEF3C7; border-radius:10px; }")
        col = QVBoxLayout(banner)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(3)
        title = QLabel(f"👤  {label}")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"background:transparent; border:none; color:#1A1A2E;"
            f" font-size:14px; font-family:{FF}; font-weight:700;")
        col.addWidget(title)
        if suggestion:
            hint = QLabel(suggestion)
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"background:transparent; border:none; color:#92400E;"
                f" font-size:12px; font-family:{FF}; font-weight:600;")
            col.addWidget(hint)
        return banner

    def add_cues(self, cue_hits: list):
        """Surface just-fired customer cues (amber, deduped per call)."""
        new = [c for c in cue_hits if c.get("id") not in self._cue_seen]
        if not new:
            return
        for c in new:
            self._cue_seen.add(c.get("id"))
            self._cue_box.addWidget(self._cue_banner(c))
        _smooth_fonts(self)
        self.setVisible(True)
        self.updateGeometry()
        QTimer.singleShot(0, self._sync_window)

    def clear_cues(self):
        self._cue_seen.clear()
        while self._cue_box.count():
            it = self._cue_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def set_transcription_status(self, state: str):
        """R2: show/clear a notice when live transcription drops or recovers."""
        if state == "recovered":
            self._status_label.setVisible(False)
        else:
            msg = ("⚠  Live checking unavailable — transcription stopped."
                   if state == "failed"
                   else "⚠  Live checking interrupted — reconnecting…")
            self._status_label.setText(msg)
            self._status_label.setStyleSheet(
                f"QLabel {{ font-size:12px; font-family:{FF}; font-weight:700;"
                " color:white; background:"
                + ("#DC2626" if state == "failed" else "#D97706")
                + "; border-radius:8px; padding:7px 11px; }}")
            self._status_label.setVisible(True)
            self.setVisible(True)
        QTimer.singleShot(0, self._sync_window)

    def _chip(self, item: dict) -> QFrame:
        level = (item.get("level") or "amber").lower()
        accent, bg = self._LEVELS.get(level, self._LEVELS["amber"])
        label = item.get("label", "Requirement")

        chip = QFrame()
        chip.setObjectName("chip")
        chip.setMinimumHeight(40)
        chip.setStyleSheet(
            f"QFrame#chip {{ background:{bg}; border-radius:10px; }}")
        row = QHBoxLayout(chip)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(11)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background:{accent}; border-radius:5px;")
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QLabel(label)
        text.setWordWrap(True)
        text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text.setStyleSheet(
            f"background:transparent; border:none; color:#1A1A2E;"
            f" font-size:14px; font-family:{FF}; font-weight:600;")
        row.addWidget(text, 1)
        return chip

    def _sync_window(self):
        """Grow/shrink the (frameless, translucent) window leftward so the
        panel slides in beside the card without shifting it on screen."""
        win = self.window()
        if win is None or not win.isVisible():
            return
        old_w = win.width()
        new_w = max(win.sizeHint().width(), win.minimumWidth())
        if new_w != old_w:
            win.move(win.x() - (new_w - old_w), win.y())
            win.resize(new_w, win.height())

    def update_missing(self, missing_items: list):
        """Render missing requirements. Empty list -> hide the panel."""
        self._clear_items()
        if not missing_items:
            self._suggestion.setVisible(False)
            # keep the panel visible if forbidden breaches, cues, or a status
            # notice are showing
            self.setVisible(self._forbidden_box.count() > 0
                            or self._cue_box.count() > 0
                            or self._status_label.isVisible())
            QTimer.singleShot(0, self._sync_window)
            return

        self._count.setText(str(len(missing_items)))
        for item in missing_items:
            self._items_box.addWidget(self._chip(item))

        # Surface the first red item's suggestion text, if any.
        suggestion = ""
        for item in missing_items:
            if (item.get("level") or "").lower() == "red" and item.get("suggestion_text"):
                suggestion = "💡  " + item["suggestion_text"]
                break
        if suggestion:
            self._suggestion.setText(suggestion)
            self._suggestion.setVisible(True)
        else:
            self._suggestion.setVisible(False)

        # size to content — no height clamp (clamping mid-layout collapsed the
        # word-wrap cards into thin lines and cut the suggestion text off)
        _smooth_fonts(self)   # chips are dynamic; they miss the startup pass
        self.setVisible(True)
        self.updateGeometry()
        QTimer.singleShot(0, self._sync_window)


# ──────────────────────────────────────────────────────────────
# Post-call summary screen
# ──────────────────────────────────────────────────────────────
class SummaryScreen(QFrame):
    """Shown after a call: compliance score + covered / missed lists."""

    new_call_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(340)
        self.setObjectName("summaryCard")
        # scope to this frame only — bare "QFrame" cascades to every child
        # (QLabel inherits QFrame, so labels would get white boxes)
        self.setStyleSheet("QFrame#summaryCard { background:white; border-radius:18px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)

        title = QLabel("Call Summary")
        title.setStyleSheet(
            f"font-size:17px; font-weight:700; font-family:{FF}; color:#1A1A2E;")
        lay.addWidget(title)

        self._score = QLabel("—")
        self._score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._score)

        self._duration = QLabel("")
        self._duration.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._duration.setStyleSheet(
            f"font-size:12px; font-family:{FF}; color:#8888A8;")
        lay.addWidget(self._duration)

        self._covered_lbl = QLabel("")
        self._covered_lbl.setWordWrap(True)
        self._covered_lbl.setStyleSheet(
            f"font-size:12px; font-family:{FF}; color:#16A34A;")
        lay.addWidget(self._covered_lbl)

        self._missed_lbl = QLabel("")
        self._missed_lbl.setWordWrap(True)
        self._missed_lbl.setStyleSheet(
            f"font-size:12px; font-family:{FF}; color:#DC2626;")
        lay.addWidget(self._missed_lbl)

        self._saved_lbl = QLabel("Saving recording…")
        self._saved_lbl.setStyleSheet(
            f"font-size:11px; font-family:{FF}; color:#8888A8;")
        lay.addWidget(self._saved_lbl)

        lay.addStretch()

        new_btn = QPushButton("New Call")
        new_btn.setFixedHeight(46)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(
            "QPushButton {"
            f"  background:#6B4EFF; color:white; border:none;"
            f"  border-radius:12px; font-size:14px; font-family:{FF}; font-weight:700;"
            "}"
            "QPushButton:hover { background:#5438D6; }")
        new_btn.clicked.connect(self.new_call_requested.emit)
        lay.addWidget(new_btn)

    def show_summary(self, score: float, covered: list, missed: list, duration_seconds: int):
        pct = int(round(score * 100))
        if pct >= 90:
            color = "#16A34A"
        elif pct >= 70:
            color = "#D97706"
        else:
            color = "#DC2626"
        self._score.setStyleSheet(
            f"font-size:44px; font-weight:800; font-family:{FF}; color:{color};")
        self._score.setText(f"{pct}%")

        m, s = divmod(int(duration_seconds or 0), 60)
        self._duration.setText(f"Duration  {m:02d}:{s:02d}")

        self._covered_lbl.setText(
            "✓ Covered: " + (", ".join(covered) if covered else "none"))
        self._missed_lbl.setText(
            "✗ Missed: " + (", ".join(missed) if missed else "none"))
        self._saved_lbl.setText("Saving recording…")

    def show_saved_only(self, duration_seconds: int):
        """Recording-only confirmation — no compliance score (pipeline is off)."""
        self._score.setStyleSheet(
            f"font-size:44px; font-weight:800; font-family:{FF}; color:#16A34A;")
        self._score.setText("✓")
        m, s = divmod(int(duration_seconds or 0), 60)
        self._duration.setText(f"Duration  {m:02d}:{s:02d}")
        self._covered_lbl.setText("")
        self._missed_lbl.setText("")
        self._saved_lbl.setText("Saving recording…")

    def mark_saved(self):
        self._saved_lbl.setText("✓ Recording saved")


# ──────────────────────────────────────────────────────────────
# Frameless drag helper
# ──────────────────────────────────────────────────────────────
class _DraggableWidget(QWidget):
    """A widget that lets the user drag the frameless window."""

    def __init__(self, window: QMainWindow, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint()
                - self._window.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self._window.move(
                event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


# ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    # Cross-thread bridge: the ws receiver thread emits this; Qt delivers it
    # on the GUI thread (QueuedConnection). QTimer can't be used from a worker
    # thread — it has no event loop, so the callback would never fire.
    server_message = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.server_message.connect(self._handle_server_message)
        self.setWindowTitle("Spark Flow")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(460, 600)
        self._settings = QSettings(ORG, APP)

        _init_icons()

        # Auth / config state
        self._token: str = self._settings.value("auth/token", "") or ""
        # Long-lived refresh token + when the id token expires, for silent renewal
        # so an idle widget never gets logged out mid-shift.
        self._refresh_token: str = self._settings.value("auth/refresh_token", "") or ""
        self._token_expiry: float = 0.0        # epoch secs; 0 = unknown -> refresh soon
        self._refresh_inflight: bool = False
        self._refresh_worker: "RefreshWorker | None" = None
        # Cached agent identity. Persisted so a restart with no network still knows who
        # is signed in (name + agent id for the dialer control connection) instead of
        # waiting on /api/me.
        self._user: dict = _load_json_setting(self._settings, "auth/user")
        # Backoff for retrying a startup validation that failed transiently.
        self._validate_retry_secs: int = 0
        # Auto-update state: checked once per run; an update found mid-call is held
        # here and applied as soon as the agent is off the phone.
        self._update_checked: bool = False
        self._update_worker = None
        self._pending_update: tuple | None = None
        self._update_attempts: dict = {}
        self._config: dict = {}
        # Active department key for this widget (from the loaded config; the
        # dialer can switch it per call leg, e.g. on a transfer).
        self._active_department: str = ""
        # Dialer call metadata stashed by _handle_dialer_activate and consumed
        # (one-shot) by the next _start_recording. None for manual calls.
        self._pending_dialer_meta: dict | None = None
        # First-run mic-setup gate: dims the widget + shows a setup card until the
        # agent picks a microphone. Blocks recording (incl. dialer auto-start).
        self._mic_gate_active: bool = False
        self._mic_gate_overlay = None   # lazily built QFrame overlay
        # Whether the current call's server runs live transcription/compliance.
        # Set from the session_started ack; gates the post-call compliance summary.
        self._live_pipeline: bool = True
        # Connecting-to-server state: connect() runs on a worker thread so Start
        # never freezes the UI. _pending_streamer holds it until the worker reports.
        self._starting: bool = False
        self._pending_streamer = None
        self._start_worker = None
        # Persistent control connection (Option A): identifies the agent at login
        # so the dialer can reach an idle widget. Stable client id per widget run.
        self._control = None
        self._control_client_id = str(uuid.uuid4())
        self._company_name: str = ""
        self._api_base = self._settings.value("api/base_url", DEFAULT_API_BASE_URL)
        self._ws_url = self._settings.value("ws/url", DEFAULT_RECORDING_WS)

        # Recording state
        self._recording = False
        self._paused = False        # PCI pause: True = audio dropped (card capture)
        self._elapsed = 0
        self._mic_thread: RecordingThread | None = None
        self._spk_thread: RecordingThread | None = None
        self._streamer:   AudioStreamer | None = None
        self._streams_started = 0

        # Live compliance state for this call
        self._all_criteria_labels: dict = {}   # id -> label
        self._missing_ids: set = set()

        self._login_worker: LoginWorker | None = None
        self._validate_worker: ValidateWorker | None = None

        self._pa = pyaudio.PyAudio()
        self._mic_devices: list[dict] = []
        self._spk_devices: list[dict] = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        # Polls for hot-plugged audio devices (e.g. a Bluetooth headset connected
        # after launch). Runs only while the setup gate or Settings panel is open
        # — never during a call. See _start_rescan_poll / _stop_rescan_poll.
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setInterval(2000)
        self._rescan_timer.timeout.connect(self._rescan_devices)

        # Silently renew the auth token before it expires so an idle widget never
        # gets logged out mid-shift. Checks every few minutes and refreshes when the
        # token is within ~10 min of its ~1-hour expiry. Harmless before login
        # (no-op until there's a token + refresh token).
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(240000)   # 4 minutes
        self._refresh_timer.timeout.connect(self._maybe_refresh_token)
        self._refresh_timer.start()

        # Bound how long undeliverable call audio lingers on the agent's machine.
        purged = purge_old_spools()
        if purged:
            print(f"[buffer] purged {purged} stale spool file(s)")

        self._build_ui()
        self._build_tray()
        self._enumerate_devices()
        # Apply after the event loop starts so it runs AFTER Qt's stylesheet
        # polish (which rebuilds widget fonts and would otherwise drop it).
        QTimer.singleShot(0, self._apply_font_smoothing)

        # Decide which page to show first.
        if self._token:
            self._stack.setCurrentWidget(self._page_main)
            self._validate_stored_token()
        else:
            self._stack.setCurrentWidget(self._page_login)

    def showEvent(self, event):
        super().showEvent(event)
        # Per-monitor DPI: when the window is dragged to a screen with a
        # different scale factor, stale geometry mangles the frameless layout
        # and text renders soft. Re-sync after Qt finishes the DPI switch.
        wh = self.windowHandle()
        if wh is not None and not getattr(self, "_screen_hook_installed", False):
            self._screen_hook_installed = True
            wh.screenChanged.connect(self._on_screen_changed)

    def _on_screen_changed(self, _screen):
        QTimer.singleShot(0, self._refit_after_screen_change)

    def _refit_after_screen_change(self):
        self._apply_font_smoothing()
        lay = self.centralWidget().layout() if self.centralWidget() else None
        if lay is not None:
            lay.activate()
        # re-fit width to the (possibly rescaled) layout, keep height behavior
        hint = self.sizeHint()
        self.resize(max(hint.width(), self.minimumWidth()),
                    max(hint.height(), self.minimumHeight()))

    def _apply_font_smoothing(self):
        """Force antialiased / fully-hinted text on every label & button.

        Qt builds fresh QFonts from stylesheet `font-*` rules, which can drop
        the smoothing strategy set on the application font — this re-applies it
        per widget while preserving each one's size/weight/family.
        """
        _smooth_fonts(self)

    # ── Top-level layout: stacked login / main ────────────────
    def _build_ui(self):
        root = QWidget(self)
        root.setStyleSheet("background:transparent;")
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self._stack = QStackedWidget()
        root_lay.addWidget(self._stack)

        self._page_login = self._build_login_page()
        self._page_main = self._build_main_page()
        self._stack.addWidget(self._page_login)
        self._stack.addWidget(self._page_main)

    # ── Login page (web view) ─────────────────────────────────
    def _build_login_page(self) -> QWidget:
        # Transparent page so the dark card floats on the desktop (matches the
        # main widget's floating cards). The DARK comes from the card (a QFrame,
        # which paints its background reliably) — not the page.
        page = _DraggableWidget(self)
        page.setStyleSheet("background:transparent;")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Centre the dark card.
        center = QHBoxLayout()
        center.setContentsMargins(16, 16, 16, 16)
        center.addStretch()

        card = QFrame()
        card.setObjectName("loginCard")
        card.setFixedWidth(360)
        # Dark, slightly transparent panel.
        card.setStyleSheet(
            "QFrame#loginCard { background: rgba(13,9,20,0.92);"
            " border:1px solid rgba(255,255,255,0.10); border-radius:18px; }")
        c = QVBoxLayout(card)
        c.setContentsMargins(30, 24, 30, 30)
        c.setSpacing(0)

        # Slim window-control row (minimise / close) inside the card.
        bar_lay = QHBoxLayout()
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.setSpacing(2)
        bar_lay.addStretch()
        for sym, slot in (("—", self.showMinimized), ("✕", self.close)):
            b = QPushButton(sym)
            b.setFixedSize(26, 22)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton { background:transparent; color:#B9B9D6; border:none;"
                f" font-size:12px; font-family:{FF}; border-radius:6px; }}"
                "QPushButton:hover { background: rgba(255,255,255,0.10); color:#FFFFFF; }")
            b.clicked.connect(slot)
            bar_lay.addWidget(b)
        c.addLayout(bar_lay)
        c.addSpacing(4)

        # ── Header: logo + title + subtitle ───────────────────
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(resource_path("assets/icon.png"))
        if not pix.isNull():
            dpr = _dpr()
            pix = pix.scaledToHeight(
                round(72 * dpr), Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            logo.setPixmap(pix)
        c.addWidget(logo)
        c.addSpacing(14)

        title = QLabel("Spark Flow")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color:#FFFFFF; font-size:27px; font-weight:700; font-family:{FF};")
        c.addWidget(title)
        c.addSpacing(6)

        subtitle = QLabel("Sign in to start compliance-coached calls")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: rgba(255,255,255,0.72); font-size:13px; font-family:{FF};")
        c.addWidget(subtitle)
        c.addSpacing(28)

        # Dark translucent inputs with a blue boundary.
        field_qss = (
            "QLineEdit { background: rgba(255,255,255,0.05);"
            " border:1px solid rgba(79,141,255,0.55); border-radius:10px;"
            f" color:#FFFFFF; padding:12px 14px; font-size:14px; font-family:{FF}; }}"
            "QLineEdit:focus { border:1px solid #4F8DFF; }"
        )

        # ── Email ─────────────────────────────────────────────
        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText("Email address")
        self._email_edit.setStyleSheet(field_qss)
        self._email_edit.addAction(
            svg_icon("mail", "#AEB4C6"), QLineEdit.ActionPosition.LeadingPosition)
        self._style_placeholder(self._email_edit)
        c.addWidget(self._email_edit)
        c.addSpacing(14)

        # ── Password (+ show/hide eye) ────────────────────────
        self._pw_edit = QLineEdit()
        self._pw_edit.setPlaceholderText("Password")
        self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_edit.setStyleSheet(field_qss)
        self._pw_edit.addAction(
            svg_icon("lock", "#AEB4C6"), QLineEdit.ActionPosition.LeadingPosition)
        self._style_placeholder(self._pw_edit)
        self._pw_action = self._pw_edit.addAction(
            svg_icon("eye", "#AEB4C6"), QLineEdit.ActionPosition.TrailingPosition)
        self._pw_action.triggered.connect(self._toggle_password_echo)
        self._pw_edit.returnPressed.connect(self._attempt_login)
        c.addWidget(self._pw_edit)
        c.addSpacing(22)

        # ── Sign In button ────────────────────────────────────
        self._signin_btn = QPushButton("Sign In")
        self._signin_btn.setObjectName("signin")
        self._signin_btn.setFixedHeight(46)
        self._signin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._signin_btn.setStyleSheet(
            "QPushButton#signin { background:#2563EB; color:#FFFFFF; border:none;"
            f" border-radius:12px; font-size:14px; font-weight:700; font-family:{FF}; }}"
            "QPushButton#signin:hover { background:#1D4ED8; }"
            "QPushButton#signin:disabled { background:#2C4A86; color: rgba(255,255,255,0.65); }")
        self._signin_btn.clicked.connect(self._attempt_login)
        c.addWidget(self._signin_btn)

        # ── Error line ────────────────────────────────────────
        self._login_error = QLabel("")
        self._login_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._login_error.setWordWrap(True)
        self._login_error.setStyleSheet(
            f"color:#FCA5A5; font-size:13px; font-family:{FF};")
        c.addSpacing(12)
        c.addWidget(self._login_error)

        center.addWidget(card)
        center.addStretch()
        v.addStretch()
        v.addLayout(center)
        v.addStretch()
        return page

    def _style_placeholder(self, edit: QLineEdit):
        pal = edit.palette()
        pal.setColor(pal.ColorRole.PlaceholderText, QColor(255, 255, 255, 140))
        pal.setColor(pal.ColorRole.Text, QColor("#FFFFFF"))
        edit.setPalette(pal)

    def _toggle_password_echo(self):
        if self._pw_edit.echoMode() == QLineEdit.EchoMode.Password:
            self._pw_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._pw_action.setIcon(svg_icon("eye_off", "#AEB4C6"))
        else:
            self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._pw_action.setIcon(svg_icon("eye", "#AEB4C6"))

    def _attempt_login(self):
        email = self._email_edit.text().strip()
        password = self._pw_edit.text()
        if not email or not password:
            self._login_error.setText("Enter your email and password.")
            return
        self._set_login_busy(True)
        # No "remember me" control any more — always persist the session token.
        self._on_login_requested(email, password, True)

    def _set_login_busy(self, busy: bool):
        self._signin_btn.setDisabled(busy)
        self._signin_btn.setText("Signing in…" if busy else "Sign In")
        if busy:
            self._login_error.setText("")

    # ── Main page (front card + summary + settings + pill) ────
    def _build_main_page(self) -> QWidget:
        INPUT_STYLE = (
            "QLineEdit, QComboBox {"
            f"  height:40px; border-radius:10px;"
            "  border:1px solid #E8E8F0;"
            f"  padding:0 12px; font-size:13px; font-family:{FF};"
            "  background:#F7F7FB; color:#1A1A2E;"
            "}"
            "QLineEdit:disabled, QComboBox:disabled {"
            "  background:#EBEBF0; color:#AAAACC;"
            "}"
            "QComboBox QAbstractItemView {"
            "  background:#FFFFFF; color:#1A1A2E;"
            "  selection-background-color:#6B4EFF; selection-color:#FFFFFF;"
            "  border:1px solid #E8E8F0; border-radius:8px;"
            f"  font-size:13px; font-family:{FF};"
            "}"
        )
        LABEL_STYLE = f"font-size:12px; font-family:{FF}; color:#1A1A2E;"
        SECTION_STYLE = (
            f"font-size:10px; font-family:{FF}; text-transform:uppercase;"
            " color:#8888A8; letter-spacing:1px;"
        )

        page = _DraggableWidget(self)
        page.setStyleSheet("background:transparent;")
        outer = QHBoxLayout(page)
        outer.setSpacing(6)
        outer.setContentsMargins(16, 16, 16, 16)

        # ── FRONT CARD ────────────────────────────────────────
        self._front_card = QFrame()
        self._front_card.setFixedWidth(340)
        self._front_card.setObjectName("frontCard")
        self._front_card.setStyleSheet(
            "QFrame#frontCard { background:white; border-radius:18px; }")
        front_lay = QVBoxLayout(self._front_card)
        front_lay.setSpacing(10)
        front_lay.setContentsMargins(24, 24, 24, 24)

        self._company_lbl = QLabel("Spark Flow")
        self._company_lbl.setStyleSheet(
            f"font-size:17px; font-weight:700; font-family:{FF}; color:#1A1A2E;")
        front_lay.addWidget(self._company_lbl)

        subtitle_lbl = QLabel("Securely capturing your call")
        subtitle_lbl.setStyleSheet(f"font-size:12px; font-family:{FF}; color:#8888A8;")
        front_lay.addWidget(subtitle_lbl)

        agent_row = QHBoxLayout()
        logged_lbl = QLabel("Logged in as:")
        logged_lbl.setStyleSheet(f"font-size:11px; font-family:{FF}; color:#8888A8;")
        self._agent_display_lbl = QLabel("Not Set")
        self._agent_display_lbl.setStyleSheet(
            f"font-size:12px; font-family:{FF}; font-weight:500; color:#1A1A2E;")
        agent_row.addWidget(logged_lbl)
        agent_row.addSpacing(4)
        agent_row.addWidget(self._agent_display_lbl)
        agent_row.addStretch()
        front_lay.addLayout(agent_row)

        self._status_chip = QLabel("● Ready to Record")
        self._status_chip.setStyleSheet(
            "background:#F0FDF4; color:#22C55E; border-radius:12px;"
            f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")
        self._status_chip.setFixedHeight(28)
        front_lay.addWidget(self._status_chip)

        hr1 = QFrame()
        hr1.setFrameShape(QFrame.Shape.HLine)
        hr1.setStyleSheet("background:#E8E8F0; border:none; max-height:1px;")
        front_lay.addWidget(hr1)

        sec_lbl = QLabel("SESSION DETAILS")
        sec_lbl.setStyleSheet(SECTION_STYLE)
        front_lay.addWidget(sec_lbl)

        self._cust_lbl = QLabel("Customer Name")
        self._cust_lbl.setStyleSheet(LABEL_STYLE)
        front_lay.addWidget(self._cust_lbl)
        self._customer_name_edit = QLineEdit()
        self._customer_name_edit.setPlaceholderText("e.g. John Smith")
        self._customer_name_edit.setStyleSheet(INPUT_STYLE)
        front_lay.addWidget(self._customer_name_edit)

        self._ref_lbl = QLabel("Reference ID")
        self._ref_lbl.setStyleSheet(LABEL_STYLE)
        front_lay.addWidget(self._ref_lbl)
        self._reference_edit = QLineEdit()
        self._reference_edit.setPlaceholderText("e.g. REF-12345")
        self._reference_edit.setStyleSheet(INPUT_STYLE)
        front_lay.addWidget(self._reference_edit)

        self._timer_lbl = QLabel("")
        self._timer_lbl.setStyleSheet("font-size:12px; color:#8888A8;")
        front_lay.addWidget(self._timer_lbl)

        front_lay.addStretch()

        self._rec_btn = QPushButton("Start Call Recording")
        self._rec_btn.setFixedHeight(46)
        self._rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rec_btn.setStyleSheet(
            "QPushButton {"
            f"  background:#6B4EFF; color:white; border:none;"
            f"  border-radius:12px; font-size:14px; font-family:{FF}; font-weight:700;"
            "}"
            "QPushButton:hover { background:#5438D6; }")
        self._rec_btn.clicked.connect(self._toggle_recording)
        front_lay.addWidget(self._rec_btn)

        # ── PCI PAUSE — drop audio while the customer reads card details ──
        # Hidden until recording starts. State-driven (see _set_paused) so a
        # future dialer pause/resume trigger drives the same machine.
        self._pause_btn = QPushButton("Pause for Card Payment")
        self._pause_btn.setFixedHeight(44)
        self._pause_btn.setIconSize(QSize(19, 19))
        self._pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pause_btn.setVisible(False)
        self._pause_btn.clicked.connect(self._toggle_pause)
        front_lay.addWidget(self._pause_btn)
        self._style_pause_btn()

        # ── LIVE COMPLIANCE PANEL — own floating column, left of the card ──
        # (inside the card it fought the form for vertical space and the
        #  chips collapsed once 2+ alerts were showing)
        self._compliance_panel = ComplianceAlertPanel()
        outer.addWidget(self._compliance_panel, 0, Qt.AlignmentFlag.AlignTop)

        outer.addWidget(self._front_card)

        # ── SUMMARY CARD (hidden until a call ends) ───────────
        self._summary_card = SummaryScreen()
        self._summary_card.setVisible(False)
        self._summary_card.new_call_requested.connect(self._on_new_call)
        outer.addWidget(self._summary_card)

        # ── SETTINGS CARD (audio + advanced only) ─────────────
        self._settings_card = QFrame()
        self._settings_card.setFixedWidth(340)
        self._settings_card.setObjectName("settingsCard")
        self._settings_card.setStyleSheet(
            "QFrame#settingsCard { background:white; border-radius:18px; }")
        self._settings_card.setVisible(False)
        settings_lay = QVBoxLayout(self._settings_card)
        settings_lay.setSpacing(10)
        settings_lay.setContentsMargins(24, 24, 24, 24)

        s_title = QLabel("Settings")
        s_title.setStyleSheet(
            f"font-size:17px; font-weight:700; font-family:{FF}; color:#1A1A2E;")
        settings_lay.addWidget(s_title)

        audio_sec = QLabel("AUDIO")
        audio_sec.setStyleSheet(SECTION_STYLE)
        settings_lay.addWidget(audio_sec)

        mic_lbl = QLabel("Your Voice")
        mic_lbl.setStyleSheet(LABEL_STYLE)
        settings_lay.addWidget(mic_lbl)
        self._mic_combo = QComboBox()
        self._mic_combo.setStyleSheet(INPUT_STYLE)
        # Remember the agent's manual mic pick. `activated` fires only on a real
        # user selection (not programmatic setCurrentIndex), so re-selecting the
        # saved device on launch won't loop back and overwrite it.
        self._mic_combo.activated.connect(self._on_mic_selected)
        settings_lay.addWidget(self._mic_combo)

        spk_lbl = QLabel("Customer Voice")
        spk_lbl.setStyleSheet(LABEL_STYLE)
        settings_lay.addWidget(spk_lbl)
        self._spk_combo = QComboBox()
        self._spk_combo.setStyleSheet(INPUT_STYLE)
        # Remember the agent's manual speaker pick (same one-shot rule as the mic).
        self._spk_combo.activated.connect(self._on_spk_selected)
        settings_lay.addWidget(self._spk_combo)

        rescan_btn = QPushButton("  Rescan devices")
        rescan_btn.setIcon(svg_icon("refresh", "#6B4EFF", 16))
        rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#6B4EFF; border:none;"
            " font-size:12px; font-weight:600; text-align:left; }"
            " QPushButton:hover { color:#5438D6; }")
        rescan_btn.clicked.connect(self._rescan_devices)
        settings_lay.addWidget(rescan_btn)

        hr2 = QFrame()
        hr2.setFrameShape(QFrame.Shape.HLine)
        hr2.setStyleSheet("background:#E8E8F0; border:none; max-height:1px;")
        settings_lay.addWidget(hr2)

        adv_sec = QLabel("ADVANCED")
        adv_sec.setStyleSheet(SECTION_STYLE)
        settings_lay.addWidget(adv_sec)

        api_lbl = QLabel("API base URL")
        api_lbl.setStyleSheet(LABEL_STYLE)
        settings_lay.addWidget(api_lbl)
        self._api_edit = QLineEdit(self._api_base)
        self._api_edit.setStyleSheet(INPUT_STYLE)
        settings_lay.addWidget(self._api_edit)

        ws_lbl = QLabel("Recording server URL")
        ws_lbl.setStyleSheet(LABEL_STYLE)
        settings_lay.addWidget(ws_lbl)
        self._ws_edit = QLineEdit(self._ws_url)
        self._ws_edit.setStyleSheet(INPUT_STYLE)
        settings_lay.addWidget(self._ws_edit)

        settings_lay.addStretch()

        save_btn = QPushButton("Save Settings")
        save_btn.setFixedHeight(46)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton {"
            f"  background:#6B4EFF; color:white; border:none;"
            f"  border-radius:12px; font-size:14px; font-family:{FF}; font-weight:700;"
            "}"
            "QPushButton:hover { background:#5438D6; }")
        save_btn.clicked.connect(self._save_settings)
        settings_lay.addWidget(save_btn)

        logout_btn = QPushButton("Log Out")
        logout_btn.setFixedHeight(38)
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.setStyleSheet(
            "QPushButton {"
            "  background:transparent; color:#DC2626; border:1px solid #F0C0C0;"
            f"  border-radius:10px; font-size:13px; font-family:{FF}; font-weight:700;"
            "}"
            "QPushButton:hover { background:#FFF5F5; }")
        logout_btn.clicked.connect(self._logout)
        settings_lay.addWidget(logout_btn)

        outer.addWidget(self._settings_card)

        # ── PILL SIDEBAR ──────────────────────────────────────
        pill = QFrame()
        pill.setFixedWidth(52)
        pill.setObjectName("sidebarPill")
        pill.setStyleSheet("QFrame#sidebarPill { background:#1C1C2E; border-radius:26px; }")
        pill_lay = QVBoxLayout(pill)
        pill_lay.setContentsMargins(6, 16, 6, 16)
        pill_lay.setSpacing(10)
        pill_lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._pill_rec_btn = QPushButton("⏺")
        self._pill_rec_btn.setFixedSize(40, 40)
        self._pill_rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill_rec_btn.setStyleSheet(
            "QPushButton { background:transparent; color:white; border:none;"
            " font-size:16px; border-radius:20px; }"
            "QPushButton:hover { background:#2D2D45; }")
        self._pill_rec_btn.clicked.connect(self._toggle_recording)
        pill_lay.addWidget(self._pill_rec_btn)

        self._pill_settings_btn = QPushButton("⚙")
        self._pill_settings_btn.setFixedSize(40, 40)
        self._pill_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill_settings_btn.setStyleSheet(
            "QPushButton { background:transparent; color:white; border:none;"
            " font-size:16px; border-radius:20px; }"
            "QPushButton:hover { background:#2D2D45; }")
        self._pill_settings_btn.clicked.connect(self._toggle_settings)
        pill_lay.addWidget(self._pill_settings_btn)

        pill_lay.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(40, 40)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#8888A8; border:none;"
            " font-size:14px; border-radius:20px; }"
            "QPushButton:hover { background:#2D2D45; color:white; }")
        close_btn.clicked.connect(self.close)
        pill_lay.addWidget(close_btn)

        outer.addWidget(pill)
        return page

    # ── Login handling ────────────────────────────────────────
    def _on_login_requested(self, email: str, password: str, remember: bool = True):
        # `remember` is vestigial — the session is ALWAYS persisted now (sign in once).
        base = self._api_edit.text().strip() or self._api_base
        self._api_base = base
        self._login_worker = LoginWorker(base, email, password)
        self._login_worker.succeeded.connect(self._on_login_succeeded)
        self._login_worker.failed.connect(self._on_login_failed)
        self._login_worker.start()

    def _on_login_succeeded(self, token: str, refresh_token: str, expires_in: int,
                            user: dict, config: dict, etag: str):
        self._set_auth_tokens(token, refresh_token, expires_in)
        self._set_user(user or {})
        self._apply_config(config, etag)
        self._settings.setValue("api/base_url", self._api_base)
        self._set_login_busy(False)
        self._pw_edit.clear()
        self._enter_main()

    def _set_user(self, user: dict) -> None:
        """Cache the agent's identity in memory AND on disk, so the next launch knows
        who is signed in even before (or without) reaching the backend."""
        self._user = user or {}
        try:
            self._settings.setValue("auth/user", json.dumps(self._user))
        except Exception:
            pass

    def _set_auth_tokens(self, token: str, refresh_token: str, expires_in) -> None:
        """Store the id token, refresh token, and id-token expiry.

        Always persisted: the agent signs in once and stays signed in. The id token
        lives ~1 hour, so it is the long-lived refresh token that actually keeps the
        session alive — renewed by the background timer and again at every launch."""
        self._token = token or ""
        if refresh_token:
            self._refresh_token = refresh_token
        self._token_expiry = time.time() + _as_expires_in(expires_in)
        if self._token:
            self._settings.setValue("auth/token", self._token)
            if self._refresh_token:
                self._settings.setValue("auth/refresh_token", self._refresh_token)

    def _token_needs_refresh(self) -> bool:
        return _needs_token_refresh(self._token, self._refresh_token,
                                    self._refresh_inflight, self._token_expiry)

    def _maybe_refresh_token(self) -> None:
        """Timer hook: renew the token in the background if it's near expiry."""
        if not self._token_needs_refresh():
            return
        self._refresh_inflight = True
        self._refresh_worker = RefreshWorker(self._api_base, self._refresh_token)
        self._refresh_worker.refreshed.connect(self._on_token_refreshed)
        self._refresh_worker.failed.connect(self._on_token_refresh_failed)
        self._refresh_worker.rejected.connect(self._on_token_rejected)
        self._refresh_worker.start()

    def _on_token_rejected(self):
        """The backend revoked this session (password changed, account removed). Unlike
        a transient refresh failure, this must sign the agent out — otherwise a revoked
        account keeps working for as long as the widget stays open. Never mid-call."""
        self._refresh_inflight = False
        if self._recording:
            print("[widget] session revoked — signing out after this call")
            return
        print("[widget] session revoked by the server — signing out")
        self._on_validate_bad()

    def _on_token_refreshed(self, token: str, refresh_token: str, expires_in: int):
        self._refresh_inflight = False
        self._set_auth_tokens(token, refresh_token, expires_in)
        print("[widget] session token refreshed")

    def _on_token_refresh_failed(self, message: str):
        # Transient (network/backend) — keep the current token and retry next tick.
        # We don't force a logout: the refresh token is long-lived.
        self._refresh_inflight = False
        print(f"[widget] token refresh failed (will retry): {message}")

    def _on_login_failed(self, message: str):
        self._set_login_busy(False)
        self._login_error.setText(message)

    def _on_forgot_password(self):
        webbrowser.open(self._api_base.rstrip("/") + "/login")

    def _validate_stored_token(self):
        etag = self._settings.value("config/etag", "") or ""
        cached = self._settings.value("config/json", "") or ""
        if cached:
            try:
                self._apply_config(json.loads(cached), etag, persist=False)
            except Exception:
                pass
        self._validate_worker = ValidateWorker(
            self._api_base, self._token, etag, self._refresh_token)
        self._validate_worker.valid.connect(self._on_validate_ok)
        self._validate_worker.invalid.connect(self._on_validate_bad)
        self._validate_worker.unreachable.connect(self._on_validate_unreachable)
        self._validate_worker.start()

    def _on_validate_ok(self, config: dict, etag: str, user: dict,
                        token: str, refresh_token: str, expires_in: int):
        self._validate_retry_secs = 0
        # The worker renews the id token before validating, so store what it got back.
        if token:
            self._set_auth_tokens(token, refresh_token, expires_in)
        # Restore the agent's identity from /api/me so the session shows the name and
        # sends a real agent_id (not 'unknown'). Empty user (e.g. an /api/me hiccup)
        # -> keep the cached one rather than wiping it.
        if user and user.get("id"):
            self._set_user(user)
        if config:   # 200 with fresh config; {} means 304 -> keep cache
            self._apply_config(config, etag)
        self._enter_main()

    # ── Auto-update ───────────────────────────────────────────
    def _maybe_check_for_update(self):
        """Look for a newer release and, if there is one, fetch it in the background.

        Only from a packaged build (a dev checkout has nothing to install over), only
        once per run, and never while a call is in progress."""
        if self._update_checked or self._recording or self._starting:
            return
        if not getattr(sys, "frozen", False):
            print("[update] dev run — skipping update check")
            return
        self._update_checked = True
        # Loop guard: if the registry ever advertises a version the installer doesn't
        # actually produce (a mis-tagged release), we would reinstall and relaunch on
        # every start — across the whole fleet. Try a given version twice, then stop.
        self._update_attempts = _load_json_setting(self._settings, "update/attempts")
        self._update_worker = UpdateCheckWorker(self._api_base, APP_VERSION)
        self._update_worker.update_ready.connect(self._on_update_ready)
        self._update_worker.no_update.connect(
            lambda: print(f"[update] up to date ({APP_VERSION})"))
        self._update_worker.start()

    def _on_update_ready(self, installer_path: str, version: str):
        """Installer downloaded. Install it once the agent isn't on a call."""
        tried = int((self._update_attempts or {}).get(version, 0))
        if tried >= 2:
            print(f"[update] {version} already attempted {tried}x and we're still on "
                  f"{APP_VERSION} — not retrying (check the release registry)")
            return
        attempts = dict(self._update_attempts or {})
        attempts[version] = tried + 1
        # Keep only this version's counter; older ones are irrelevant once we move on.
        self._update_attempts = {version: attempts[version]}
        try:
            self._settings.setValue("update/attempts", json.dumps(self._update_attempts))
            self._settings.sync()      # must survive the imminent restart
        except Exception:
            pass
        self._pending_update = (installer_path, version)
        self._apply_pending_update()

    def _apply_pending_update(self):
        """Hand off to a detached helper and quit so the installer can replace us.

        Deferred while recording — an update must never cut off a live call. The
        deferral is retried from _stop_recording, so it lands right after the call.
        """
        if not self._pending_update:
            return
        if self._recording or self._starting:
            print("[update] on a call — update deferred until it ends")
            return
        installer, version = self._pending_update
        self._pending_update = None
        try:
            exe = sys.executable
            minimized = "--minimized" in sys.argv
            script = Path(tempfile.gettempdir()) / "sparkflow_update.cmd"
            script.write_text(build_updater_script(installer, exe, minimized),
                              encoding="utf-8")
            # CREATE_NO_WINDOW ONLY. Windows explicitly IGNORES CREATE_NO_WINDOW when
            # it is combined with DETACHED_PROCESS — which is why the helper's console
            # kept flashing up at the agent despite "hiding" it. CREATE_NO_WINDOW on its
            # own gives the console app no window and still outlives us.
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags,
                             close_fds=True)
            print(f"[update] installing {version} — restarting")
            self._quit()
        except Exception as exc:  # noqa: BLE001 — a failed update must not kill the widget
            print(f"[update] could not start the installer: {exc}")

    def _on_validate_unreachable(self, reason: str):
        """Transient failure — the backend was unreachable / erroring, which says
        nothing about whether this agent is allowed in. Keep the session, carry on with
        the cached config + identity, and retry with backoff. This is the common case at
        Windows login, when the widget auto-starts before the network is ready."""
        print(f"[widget] session check deferred ({reason}) — keeping the stored session")
        # Only enter the main page on the FIRST deferral. _enter_main calls _show_front,
        # which would otherwise yank the agent off the settings panel or the post-call
        # summary every time a retry fires in the background.
        if not self._validate_retry_secs:
            self._enter_main()
        # 30s, 60s, 2m, 4m … capped at 5m.
        self._validate_retry_secs = min(300, (self._validate_retry_secs or 15) * 2)
        QTimer.singleShot(self._validate_retry_secs * 1000, self._retry_validate)

    def _retry_validate(self):
        # Only still relevant if we're signed in and no other check is running.
        if not self._token:
            return
        if self._validate_worker is not None and self._validate_worker.isRunning():
            return
        self._validate_stored_token()

    def _on_validate_bad(self):
        print("[auth] clearing the stored session; the agent must sign in again")
        self._settings.remove("auth/token")
        self._settings.remove("auth/refresh_token")
        self._settings.remove("auth/user")
        self._token = ""
        self._refresh_token = ""
        self._user = {}
        self._stack.setCurrentWidget(self._page_login)
        # If we auto-started minimized but the stored session turned out invalid,
        # reveal the window so the agent can log in (otherwise it'd hide the login).
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _apply_config(self, config: dict, etag: str, persist: bool = True):
        self._config = config or {}
        # The backend echoes which department this config was scoped to (None =
        # company-wide). Track it so session_start tells the server the same.
        self._active_department = self._config.get("department") or ""
        self._company_name = self._config.get("company_name", "") or \
            self._user.get("company_name", "")
        # Build id -> label map across criteria + railguards for summaries.
        labels: dict = {}
        crit = self._config.get("criteria", {}) or {}
        for level in ("green", "amber", "red"):
            for item in crit.get(level, []) or []:
                if item.get("id"):
                    labels[item["id"]] = item.get("label", "Requirement")
        rg = self._config.get("railguards", {}) or {}
        for kind in ("forbidden", "required"):
            for item in rg.get(kind, []) or []:
                if item.get("id"):
                    labels[item["id"]] = item.get("label", "Railguard")
        self._all_criteria_labels = labels
        if persist and config:
            self._settings.setValue("config/json", json.dumps(config))
            if etag:
                self._settings.setValue("config/etag", etag)
        self._refresh_identity_labels()
        self._apply_customer_field_visibility()

    def _apply_customer_field_visibility(self):
        """Show/hide the Customer Name + Reference ID fields per the backend's
        superadmin toggle (config['hide_customer_fields']). Cosmetic only — the
        values are still captured from the dialer and sent with the recording."""
        hide = bool(self._config.get("hide_customer_fields", False))
        for w in (
            getattr(self, "_cust_lbl", None),
            getattr(self, "_customer_name_edit", None),
            getattr(self, "_ref_lbl", None),
            getattr(self, "_reference_edit", None),
        ):
            if w is not None:
                w.setVisible(not hide)

    def _refresh_identity_labels(self):
        company = self._company_name or "Spark Flow"
        self.setWindowTitle(
            f"Spark Flow — {company}" if self._company_name else "Spark Flow")
        if hasattr(self, "_company_lbl"):
            self._company_lbl.setText(company)
        # full_name may be None (invited agents) -> fall back to email.
        name = (self._user.get("name") or self._user.get("email") or "").strip()
        if hasattr(self, "_agent_display_lbl"):
            self._agent_display_lbl.setText(name if name else "Not Set")

    def _enter_main(self):
        self._refresh_identity_labels()
        self._show_front()
        self._stack.setCurrentWidget(self._page_main)
        # Re-scan + re-apply the saved device selection on login, so a headset
        # connected before login (or that enumerated late at startup) is used —
        # the selection isn't otherwise refreshed between logout and login.
        self._rescan_devices()
        # Open the persistent control connection so the dialer can reach this
        # widget while it sits idle (auto-start from XDial).
        self._start_control_connection()
        # First-run: block use behind the mic-setup gate until a mic is chosen.
        self._maybe_show_mic_gate()
        # Pick up a new release in the background (once per run, never mid-call).
        self._maybe_check_for_update()

    def _start_control_connection(self):
        """Open the persistent dialer-reachable control connection (idempotent).

        Requires a known agent id: the dialer finds an idle widget by that id, so
        registering with an empty one makes the agent silently unreachable. On an
        offline start (upgrading agents have a stored token but no cached profile yet)
        we skip and let the next successful validation open it.
        """
        if self._control is not None or not self._token:
            return
        if not (self._user.get("id") or self._user.get("email")):
            print("[widget] agent identity not known yet — deferring the dialer connection")
            return
        self._control = ControlConnection(
            self._ws_url, self._control_client_id,
            self._user.get("id", "") or "", self._user.get("email", "") or "")
        self._control.message.connect(self._on_inbound_message)
        self._control.start()

    def _stop_control_connection(self):
        if self._control is not None:
            try:
                self._control.stop()
                self._control.wait(2000)
            except Exception:
                pass
            self._control = None

    def _logout(self):
        if self._recording:
            self._stop_recording()
        self._stop_control_connection()
        # Clear the WHOLE session. The refresh token is long-lived, so leaving it on
        # disk after an explicit sign-out would let the session be resumed.
        self._settings.remove("auth/token")
        self._settings.remove("auth/refresh_token")
        self._settings.remove("auth/user")
        self._token = ""
        self._refresh_token = ""
        self._token_expiry = 0.0
        self._user = {}
        self._settings_card.setVisible(False)
        self._front_card.setVisible(True)
        # Reset the login form fields.
        self._email_edit.clear()
        self._pw_edit.clear()
        self._login_error.setText("")
        self._set_login_busy(False)
        self._stack.setCurrentWidget(self._page_login)

    # ── Settings helpers ──────────────────────────────────────
    def _show_front(self):
        self._front_card.setVisible(True)
        self._settings_card.setVisible(False)
        self._summary_card.setVisible(False)

    def _toggle_settings(self):
        showing_settings = self._settings_card.isVisible()
        self._settings_card.setVisible(not showing_settings)
        self._front_card.setVisible(showing_settings)
        if not showing_settings:
            self._summary_card.setVisible(False)
            self._rescan_devices()      # refresh list on open
            self._start_rescan_poll()   # keep catching hot-plugged devices
        else:
            self._stop_rescan_poll()

    def _save_settings(self):
        self._api_base = self._api_edit.text().strip() or DEFAULT_API_BASE_URL
        self._ws_url = self._ws_edit.text().strip() or DEFAULT_RECORDING_WS
        self._settings.setValue("api/base_url", self._api_base)
        self._settings.setValue("ws/url", self._ws_url)
        self._stop_rescan_poll()
        self._show_front()

    # ── Tray ──────────────────────────────────────────────────
    def _build_tray(self):
        self._tray = QSystemTrayIcon(ICON_IDLE, self)
        self._tray.setToolTip("Spark Flow – idle")
        self._tray.activated.connect(self._tray_activated)

        menu = QMenu()
        show_act = QAction("Show Window", self)
        show_act.triggered.connect(self._show_window)
        menu.addAction(show_act)
        menu.addSeparator()
        self._tray_rec_act = QAction("⏺  Start Recording", self)
        self._tray_rec_act.triggered.connect(self._toggle_recording)
        menu.addAction(self._tray_rec_act)
        menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self._quit)
        menu.addAction(quit_act)
        self._tray.setContextMenu(menu)
        self._tray.show()

    # ── Device enumeration ────────────────────────────────────
    def _enumerate_devices(self):
        self._mic_devices.clear()
        self._spk_devices.clear()
        self._mic_combo.clear()
        self._spk_combo.clear()

        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            QMessageBox.critical(
                self, "Error",
                "WASAPI host API is not available on this system.\n"
                "Spark Flow requires Windows + WASAPI.",
            )
            return

        for i in range(int(wasapi_info["deviceCount"])):
            dev = self._pa.get_device_info_by_host_api_device_index(
                int(wasapi_info["index"]), i)
            if dev.get("isLoopbackDevice", False):
                self._spk_devices.append(dev)
                self._spk_combo.addItem(dev["name"])
            elif int(dev.get("maxInputChannels", 0)) > 0:
                # Skip Krisp's virtual mic (and similar) so we record the raw
                # physical headset, not the accent-converted / denoised feed.
                if _is_excluded_mic(dev.get("name", "")):
                    continue
                self._mic_devices.append(dev)
                self._mic_combo.addItem(dev["name"])

        if not self._spk_devices:
            self._spk_combo.addItem("⚠  No WASAPI loopback devices found")
        if not self._mic_devices:
            self._mic_combo.addItem("⚠  No microphone devices found")

        # Re-select the agent's remembered mic (saved on a previous manual pick)
        # so a connected headset is used automatically — no re-picking each launch.
        if self._mic_devices:
            saved = self._settings.value("audio/mic_name", "") or ""
            names = [d["name"] for d in self._mic_devices]
            self._mic_combo.setCurrentIndex(_index_for_saved_mic(names, saved))

        # Auto-select the customer-audio loopback: saved override -> loopback of
        # the Windows default output (follows the headset) -> first.
        if self._spk_devices:
            saved_spk = self._settings.value("audio/spk_name", "") or ""
            default_out = ""
            try:
                out_idx = int(wasapi_info.get("defaultOutputDevice", -1))
                if out_idx >= 0:
                    default_out = self._pa.get_device_info_by_index(out_idx).get("name", "")
            except Exception:
                default_out = ""
            spk_names = [d["name"] for d in self._spk_devices]
            self._spk_combo.setCurrentIndex(
                _index_for_saved_or_default_spk(spk_names, saved_spk, default_out))

    def _on_mic_selected(self, index: int):
        """Persist the agent's manual mic choice (by name) for future launches."""
        if 0 <= index < len(self._mic_devices):
            self._settings.setValue("audio/mic_name", self._mic_devices[index]["name"])
            # Setup complete -> release the first-run gate if it was up.
            self._clear_mic_gate()

    def _on_spk_selected(self, index: int):
        """Persist the agent's manual speaker (customer-audio) choice by name."""
        if 0 <= index < len(self._spk_devices):
            self._settings.setValue("audio/spk_name", self._spk_devices[index]["name"])

    def _start_rescan_poll(self):
        """Begin polling for hot-plugged devices (gate/Settings open, idle only)."""
        if not self._recording:
            self._rescan_timer.start()

    def _stop_rescan_poll(self):
        self._rescan_timer.stop()

    def _rescan_devices(self):
        """Re-detect audio devices so a hot-plugged headset appears without a
        restart. PortAudio caches its device list at init, so we recreate the
        PyAudio instance. NEVER while recording — that would break live streams."""
        if self._recording:
            return
        try:
            self._pa.terminate()
        except Exception:
            pass
        self._pa = pyaudio.PyAudio()
        self._enumerate_devices()   # preserves selection via saved names
        # Keep the gate's picker in sync if the gate is currently up.
        if self._mic_gate_active and self._mic_gate_overlay is not None:
            cur = self._gate_combo.currentText()
            self._gate_combo.clear()
            for d in self._mic_devices:
                self._gate_combo.addItem(d["name"])
            i = self._gate_combo.findText(cur)
            if i >= 0:
                self._gate_combo.setCurrentIndex(i)

    # ── First-run mic-setup gate (dim overlay) ────────────────
    def _build_mic_gate_overlay(self):
        """Lazily build the dim overlay + centered setup card (mic picker)."""
        overlay = QFrame(self._page_main)
        overlay.setObjectName("micGate")
        # Dim, semi-opaque scrim (reliable on the translucent window — true blur
        # renders unpredictably with WA_TranslucentBackground).
        overlay.setStyleSheet(
            "QFrame#micGate { background: rgba(10,12,20,0.78); }"
            "QFrame#micGateCard { background:white; border-radius:18px; }"
            "QLabel#micGateTitle { color:#0B1220; font-size:18px; font-weight:700; }"
            "QLabel#micGateBody  { color:#5B6577; font-size:13px; }"
        )
        outer = QVBoxLayout(overlay)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        card = QFrame(overlay)
        card.setObjectName("micGateCard")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 20)
        cl.setSpacing(12)

        title = QLabel("Choose your microphone")
        title.setObjectName("micGateTitle")
        body = QLabel("Select your headset so we record your voice clearly. "
                      "You only need to do this once.")
        body.setObjectName("micGateBody")
        body.setWordWrap(True)
        self._gate_combo = QComboBox()
        # Self-contained style (INPUT_STYLE is local to _build_main_page).
        self._gate_combo.setStyleSheet(
            "QComboBox { height:40px; border-radius:10px; border:1px solid #E8E8F0;"
            " padding:0 12px; font-size:13px; background:#F7F7FB; color:#1A1A2E; }"
            "QComboBox QAbstractItemView { background:#FFFFFF; color:#1A1A2E; }")
        confirm = QPushButton("Confirm microphone")
        confirm.setStyleSheet(
            "QPushButton { background:#6B4EFF; color:#FFFFFF; border:none;"
            " border-radius:12px; padding:10px 16px; font-weight:600; }"
            "QPushButton:hover { background:#5438D6; }")
        confirm.clicked.connect(self._confirm_gate_mic)

        rescan = QPushButton("  Don't see your headset? Rescan")
        rescan.setIcon(svg_icon("refresh", "#6B4EFF", 15))
        rescan.setStyleSheet(
            "QPushButton { background:transparent; color:#6B4EFF; border:none;"
            " font-size:12px; font-weight:600; } QPushButton:hover { color:#5438D6; }")
        rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan.clicked.connect(self._rescan_devices)

        cl.addWidget(title)
        cl.addWidget(body)
        cl.addWidget(self._gate_combo)
        cl.addWidget(confirm)
        cl.addWidget(rescan)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(card, 3)
        wrap.addStretch(1)
        outer.addLayout(wrap)
        outer.addStretch(1)

        self._mic_gate_overlay = overlay
        # Dynamically-built widgets miss the startup smoothing pass and render
        # soft — apply antialias + full hinting so the card text/buttons are crisp.
        _smooth_fonts(overlay)

    def _show_mic_gate(self):
        """Dim the widget and present the one-time mic-setup card."""
        self._mic_gate_active = True
        if self._mic_gate_overlay is None:
            self._build_mic_gate_overlay()
        self._gate_combo.clear()
        for d in self._mic_devices:
            self._gate_combo.addItem(d["name"])
        self._mic_gate_overlay.setGeometry(self._page_main.rect())
        self._mic_gate_overlay.raise_()
        self._mic_gate_overlay.setVisible(True)
        _smooth_fonts(self._mic_gate_overlay)   # keep card text/buttons crisp
        self._start_rescan_poll()   # catch a headset connected after this opens

    def _confirm_gate_mic(self):
        """Save the mic chosen in the gate card; this also clears the gate."""
        i = self._gate_combo.currentIndex()
        if 0 <= i < len(self._mic_devices):
            self._mic_combo.setCurrentIndex(i)   # keep Settings in sync
            self._on_mic_selected(i)             # persists + clears the gate

    def _clear_mic_gate(self):
        """Release the gate and hide the overlay (safe if never shown)."""
        self._mic_gate_active = False
        self._stop_rescan_poll()
        if self._mic_gate_overlay is not None:
            self._mic_gate_overlay.setVisible(False)

    def _maybe_show_mic_gate(self):
        """Show the setup gate after login if the agent hasn't picked a mic yet."""
        if _needs_mic_gate(self._token, self._settings.value("audio/mic_name", "") or ""):
            self._show_mic_gate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._mic_gate_active and self._mic_gate_overlay is not None:
            self._mic_gate_overlay.setGeometry(self._page_main.rect())

    # ── Recording control ─────────────────────────────────────
    def _toggle_recording(self):
        if self._starting:
            return   # a connection is already in flight — ignore extra presses
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()
        # The record button + status chip get restyled above, which rebuilds
        # their fonts — re-apply text smoothing so they stay crisp.
        self._apply_font_smoothing()

    # ── PCI pause (card capture) ──────────────────────────────
    def _style_pause_btn(self):
        """Clean filled-yellow buttons with crisp vector icons. Amber while
        recording (pause), brighter yellow while paused (resume)."""
        if self._paused:
            # Paused → bright yellow "resume" affordance, dark ink + play glyph.
            self._pause_btn.setIcon(svg_icon("play", "#7C2D12", 19, fill=True))
            self._pause_btn.setStyleSheet(
                "QPushButton {"
                "  background:#FBBF24; color:#7C2D12; border:none;"
                f"  border-radius:12px; font-size:14px; font-family:{FF}; font-weight:800;"
                "}"
                "QPushButton:hover { background:#F59E0B; }")
        else:
            # Recording → amber "pause for card" button, white ink + pause glyph.
            self._pause_btn.setIcon(svg_icon("pause", "#FFFFFF", 19, fill=True))
            self._pause_btn.setStyleSheet(
                "QPushButton {"
                "  background:#F59E0B; color:white; border:none;"
                f"  border-radius:12px; font-size:14px; font-family:{FF}; font-weight:700;"
                "}"
                "QPushButton:hover { background:#E08C07; }")

    def _toggle_pause(self):
        """Manual Pause/Resume button — flips the pause state."""
        self._set_paused(not self._paused)

    def _set_paused(self, paused: bool):
        """Pause/resume recording as a STATE (idempotent). While paused, audio is
        dropped at the streamer so nothing is captured — for PCI card capture.
        The manual button AND a future dialer pause/resume trigger both call this,
        so the two paths converge and never fight."""
        if not self._recording or self._streamer is None:
            return
        paused = bool(paused)
        if paused == self._paused:
            return                      # already in this state — no-op
        self._paused = paused
        self._streamer.set_paused(paused)
        self._update_pause_ui()
        self._apply_font_smoothing()

    def _update_pause_ui(self):
        """Reflect the pause state on the button, status chip and timer."""
        if self._paused:
            self._pause_btn.setText("Resume Recording")
            self._status_chip.setText("❚❚ Paused — not recording")
            self._status_chip.setStyleSheet(
                "background:#FFF7ED; color:#D97706; border-radius:12px;"
                f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")
            self._tray.setToolTip("Spark Flow – PAUSED (not recording)")
        else:
            self._pause_btn.setText("Pause for Card Payment")
            self._status_chip.setText("● Recording Live")
            self._status_chip.setStyleSheet(
                "background:#FFF5F5; color:#EF4444; border-radius:12px;"
                f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")
            self._tray.setToolTip("Spark Flow – RECORDING")
        self._style_pause_btn()

    def _start_recording(self, require_name: bool = True):
        # require_name=True for the manual Start button (agent must type a name);
        # the dialer auto-start passes False (name is blank, resolved via CRM).
        if not self._token:
            self._stack.setCurrentWidget(self._page_login)
            return
        if not self._mic_devices or not self._spk_devices:
            QMessageBox.warning(
                self, "No Devices",
                "At least one required audio device was not found.\n"
                "Make sure WASAPI loopback and a microphone are available.",
            )
            return

        server_url = self._ws_url
        agent_id = self._user.get("id", "") or "unknown"
        customer_name = self._customer_name_edit.text().strip()
        reference_id = self._reference_edit.text().strip()

        # When the superadmin hides the customer fields, the agent has nothing to type,
        # so demanding a Customer Name would make manual Start impossible. A reference
        # is still required though — the server rejects session_start without one — and
        # in that setup it arrives from the dialer, so say so plainly rather than
        # starting a call the server will refuse.
        fields_hidden = bool(self._config.get("hide_customer_fields", False))
        if fields_hidden:
            if not reference_id:
                QMessageBox.information(
                    self, "Start from the dialer",
                    "Customer details are managed by the dialer for your team.\n"
                    "Start the call in the dialer and this widget will record it "
                    "automatically.",
                )
                return
            require_name = False          # name is resolved from the CRM

        missing = (not all([customer_name, reference_id]) if require_name
                   else not reference_id)
        # Reference ID is always required. Customer Name is required for the
        # manual flow, but optional for dialer auto-start (resolved via CRM).
        if missing:
            QMessageBox.warning(
                self, "Missing Info",
                "Please fill in Customer Name and Reference ID before starting a recording."
                if require_name else
                "Please fill in the Reference ID before starting a recording.",
            )
            return

        # Guard against double-launch while a connection is already in flight.
        if self._starting:
            return

        # Never re-enumerate/recreate PyAudio during a live recording.
        self._stop_rescan_poll()

        client_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        streamer = AudioStreamer(
            server_url=server_url,
            client_id=client_id,
            session_id=session_id,
            agent_id=agent_id,
            customer_name=customer_name,
            customer_id=customer_name,
            reference_id=reference_id,
            token=self._token,
            agent_email=self._user.get("email", ""),
            department=self._active_department,
            dialer_metadata=self._pending_dialer_meta,
            # The persistent ControlConnection holds the dialer registration; this
            # per-call connection must not register (it would clobber it on close).
            register_for_dialer=False,
            # Lets a mid-call resume authenticate with the CURRENT token rather than
            # the one captured here, which expires ~1h into a long call.
            token_provider=lambda: self._token,
        )
        # One-shot: a later manual call must not inherit this dialer metadata.
        self._pending_dialer_meta = None
        # Phase 3: receive inbound server messages (compliance alerts etc.)
        streamer.on_message = self._on_inbound_message

        # Connect on a worker thread so the UI stays responsive ("Starting…").
        self._pending_streamer = streamer
        self._starting = True
        self._set_starting_ui()
        self._start_worker = StartCallWorker(streamer)
        self._start_worker.connected.connect(self._on_call_connected)
        self._start_worker.failed.connect(self._on_call_failed)
        self._start_worker.start()

    def _set_starting_ui(self):
        """Show an immediate 'connecting' state while the worker handshakes."""
        self._rec_btn.setText("Starting…")
        self._rec_btn.setEnabled(False)
        self._status_chip.setText("● Connecting…")
        self._status_chip.setStyleSheet(
            "background:#FFF7ED; color:#D97706; border-radius:12px;"
            f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")

    def _on_call_failed(self, detail: str):
        """Worker could not connect — surface the error and return to idle."""
        self._starting = False
        self._pending_streamer = None
        self._rec_btn.setEnabled(True)
        self._rec_btn.setText("Start Call Recording")
        self._status_chip.setText("● Ready to Record")
        self._status_chip.setStyleSheet(
            "background:#F0FDF4; color:#22C55E; border-radius:12px;"
            f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")
        self._tray.showMessage(
            "Spark Flow",
            "Connection issue – could not reach the server. Please check your connection.",
            QSystemTrayIcon.MessageIcon.Warning, 3000)
        QMessageBox.critical(
            self, "Connection Issue",
            f"Could not connect to the recording server.\n"
            f"Please check your connection and try again.\n\nDetail: {detail}")

    def _on_call_connected(self):
        """Worker connected — start the audio streams and enter recording state."""
        streamer = self._pending_streamer
        self._pending_streamer = None
        self._starting = False
        self._rec_btn.setEnabled(True)
        if streamer is None:
            return
        # The server told us whether live compliance runs (gates the summary).
        self._live_pipeline = getattr(streamer, "live_pipeline", True)

        self._streamer = streamer
        self._streams_started = 0

        # Reset live compliance state for this call.
        self._missing_ids = set()
        self._server_summary_shown = False  # server summary is authoritative
        self._compliance_panel.clear_forbidden()
        self._compliance_panel.clear_cues()
        self._compliance_panel.set_transcription_status("recovered")  # hide any stale notice
        self._compliance_panel.update_missing([])

        mic_dev = self._mic_devices[self._mic_combo.currentIndex()]
        spk_dev = self._spk_devices[self._spk_combo.currentIndex()]
        mic_ch = min(int(mic_dev["maxInputChannels"]), 2)
        spk_ch = min(int(spk_dev["maxInputChannels"]), 2)
        mic_rate = int(mic_dev["defaultSampleRate"])
        spk_rate = int(spk_dev["defaultSampleRate"])

        self._mic_thread = RecordingThread(
            device_index=int(mic_dev["index"]), stream_type="mic",
            sample_rate=mic_rate, channels=mic_ch,
            send_callback=self._streamer.send_audio)
        self._spk_thread = RecordingThread(
            device_index=int(spk_dev["index"]), stream_type="speaker",
            sample_rate=spk_rate, channels=spk_ch,
            send_callback=self._streamer.send_audio, is_loopback=True)
        for t in (self._mic_thread, self._spk_thread):
            t.error_occurred.connect(self._on_error)
            t.stream_ready.connect(self._on_stream_ready)

        self._mic_thread.start()
        self._spk_thread.start()

        self._recording = True
        self._paused = False           # every call starts actively recording
        self._elapsed = 0
        self._timer.start(1000)

        self._show_front()
        # PCI pause control becomes available once recording.
        self._pause_btn.setVisible(True)
        self._update_pause_ui()
        self._customer_name_edit.setEnabled(False)
        self._reference_edit.setEnabled(False)
        self._rec_btn.setText("Stop Recording")
        self._rec_btn.setStyleSheet(
            "QPushButton {"
            "  background:#EF4444; color:white; border:none;"
            f"  border-radius:12px; font-size:14px; font-family:{FF}; font-weight:700;"
            "}"
            "QPushButton:hover { background:#DC2626; }")
        self._status_chip.setText("● Recording Live")
        self._status_chip.setStyleSheet(
            "background:#FFF5F5; color:#EF4444; border-radius:12px;"
            f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")
        self._timer_lbl.setText("00:00")
        self._tray_rec_act.setText("⏹  Stop Recording")
        self._tray.setIcon(ICON_RECORDING)
        self._tray.setToolTip("Spark Flow – RECORDING")
        # No tray toast on start/stop: its Windows notification ding is captured
        # by the customer-side loopback. The status chip already shows state.

    def _on_stream_ready(self, stream_type: str, channels: int, sample_rate: int):
        if self._streamer is None:
            return
        self._streamer.start_stream(stream_type, channels, sample_rate)
        self._streams_started += 1
        if stream_type == "mic" and self._mic_thread is not None:
            self._mic_thread._start_ack.set()
        elif stream_type == "speaker" and self._spk_thread is not None:
            self._spk_thread._start_ack.set()

    def _stop_recording(self):
        for t in (self._mic_thread, self._spk_thread):
            if t is not None:
                t.stop()
                t.wait(1500)   # daemon threads; don't freeze the GUI waiting

        if self._streamer is not None:
            try:
                self._streamer.stop_stream("mic")
                self._streamer.stop_stream("speaker")
                self._streamer.end_session()
            except Exception:
                pass
            # Phase 4: hold the socket open so session_summary /
            # upload_complete can arrive; close on upload_complete or timeout.
            self._closing_streamer = self._streamer
            QTimer.singleShot(15000, self._close_finished_streamer)
            self._streamer = None

        self._mic_thread = None
        self._spk_thread = None
        was_recording = self._recording
        duration = self._elapsed
        self._recording = False
        self._paused = False
        self._timer.stop()

        self._pause_btn.setVisible(False)
        self._customer_name_edit.setEnabled(True)
        self._reference_edit.setEnabled(True)
        self._rec_btn.setText("Start Call Recording")
        self._rec_btn.setStyleSheet(
            "QPushButton {"
            "  background:#6B4EFF; color:white; border:none;"
            f"  border-radius:12px; font-size:14px; font-family:{FF}; font-weight:700;"
            "}"
            "QPushButton:hover { background:#5438D6; }")
        self._status_chip.setText("● Ready to Record")
        self._status_chip.setStyleSheet(
            "background:#F0FDF4; color:#22C55E; border-radius:12px;"
            f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")
        self._timer_lbl.setText("")
        self._compliance_panel.update_missing([])
        self._tray_rec_act.setText("⏺  Start Recording")
        self._tray.setIcon(ICON_IDLE)
        self._tray.setToolTip("Spark Flow – idle")
        # No "Recording stopped" toast — its ding can be caught by the loopback tail.

        if was_recording:
            if self._live_pipeline:
                self._show_local_summary(duration)
            else:
                # Recording-only: no compliance to summarise — just confirm the save.
                self._show_saved_confirmation(duration)

        # An update that arrived mid-call was deferred; the agent is free now.
        if self._pending_update:
            QTimer.singleShot(2000, self._apply_pending_update)

    def _show_connection_status(self, state: str):
        """Reflect a mid-call connection drop in the status chip.

        The recording does NOT stop — audio is buffered locally and sent when the link
        comes back — so the wording tells the agent to carry on rather than hang up.
        """
        if not self._recording:
            return
        styles = {
            "buffering": ("● Reconnecting — still recording", "#FEF3C7", "#B45309"),
            "resumed":   ("● Recording Live", "#FEE2E2", "#EF4444"),
            "failed":    ("● Saved locally — will not upload", "#FEE2E2", "#EF4444"),
        }
        if state not in styles:
            return
        text, bg, fg = styles[state]
        self._status_chip.setText(text)
        self._status_chip.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:12px;"
            f"padding:4px 12px; font-size:12px; font-family:{FF}; font-weight:700;")

    # ── Inbound server messages (Phase 3) ─────────────────────
    def _on_inbound_message(self, msg: dict):
        """Called from the receiver thread – marshal to the UI thread via a
        queued signal (QTimer would not fire on this thread)."""
        self.server_message.emit(msg)

    def _handle_server_message(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "compliance_alert":
            forbidden = msg.get("forbidden_hits") or []
            if forbidden:
                # forbidden-only message: show the red breach banner without
                # disturbing the live checklist (missing_items is empty here).
                self._compliance_panel.add_forbidden(forbidden)
                return
            cues = msg.get("cue_hits") or []
            if cues:
                # customer-cue message (R4): amber, doesn't touch the checklist.
                self._compliance_panel.add_cues(cues)
                return
            items = msg.get("missing_items", []) or []
            self._missing_ids = {i.get("id") for i in items if i.get("id")}
            self._compliance_panel.update_missing(items)
        elif mtype == "connection_status":
            # Locally generated by AudioStreamer while the socket is down. The call
            # keeps recording to disk, so this reassures rather than alarms.
            self._show_connection_status(msg.get("state", ""))
        elif mtype == "transcription_status":
            self._compliance_panel.set_transcription_status(msg.get("state", ""))
        elif mtype == "session_summary":
            print(f"[widget] session_summary received: score={msg.get('score')} "
                  f"covered={msg.get('covered')} missing={msg.get('missing')} "
                  f"recording_saved={msg.get('recording_saved')}")
            self._show_server_summary(msg)
            # Fix 2: the server confirms the audio is safely captured right here
            # in session_summary. Mark saved and release the socket NOW — don't
            # wait on upload_complete, which is the background merge and can be
            # minutes away on a long call (that wait was the "Saving…" freeze).
            if msg.get("recording_saved"):
                self._summary_card.mark_saved()
            QTimer.singleShot(500, self._close_finished_streamer)
        elif mtype == "upload_complete":
            # Background merge finished. The socket is usually already closed;
            # if it's still open this just reaffirms the saved state.
            self._summary_card.mark_saved()
            QTimer.singleShot(500, self._close_finished_streamer)
        elif mtype == "dialer_activate":
            self._handle_dialer_activate(msg)
        elif mtype == "dialer_stop":
            # Mirror the Stop button. Ignore if not on a call.
            if self._recording:
                self._stop_recording()
        elif mtype == "dialer_pause":
            # Future: dialer-driven PCI pause. Same state machine as the manual
            # button, so manual and dialer control never fight.
            self._set_paused(True)
        elif mtype == "dialer_resume":
            self._set_paused(False)
        # Unknown types are ignored quietly.

    def _handle_dialer_activate(self, msg: dict):
        """Dialer-driven auto-start — behaves exactly like clicking Start."""
        # Guard against double-start: never start a second call.
        if self._recording:
            return
        # First-run gate: if the agent hasn't picked a mic yet, do NOT record on
        # a default/wrong device — surface the setup overlay and bail. The dialer
        # re-fires on the next call once setup is done.
        if _needs_mic_gate(self._token, self._settings.value("audio/mic_name", "") or ""):
            self._show_window()
            self._show_mic_gate()
            return
        # Stash the call metadata so the upcoming session_start can store it on
        # the session (one-shot; cleared after _start_recording consumes it).
        self._pending_dialer_meta = {
            "customer_reference": msg.get("customer_reference"),
            "lead_id": msg.get("lead_id"),
            "campaign_id": msg.get("campaign_id"),
            "call_direction": msg.get("call_direction"),
            "is_transfer": msg.get("is_transfer"),
            "department": msg.get("department"),
        }
        # Prefill the reference (fall back to lead_id) and the customer name when the
        # dialer resolved it (via the CRM phone->client lookup). If no name came
        # through, leave the field blank rather than showing a stale value.
        ref = msg.get("customer_reference") or msg.get("lead_id") or ""
        if ref:
            self._reference_edit.setText(str(ref))
        name = (msg.get("customer_name") or "").strip()
        if name:
            self._customer_name_edit.setText(name)
        else:
            self._customer_name_edit.clear()
        # Honor the call leg's department (e.g. a transfer routes to Advisor).
        # Set it now so session_start scopes the server checklist correctly, and
        # refresh the on-screen config to match (best-effort, non-blocking).
        dept = (msg.get("department") or "").strip()
        if dept and dept != self._active_department:
            self._active_department = dept
            if self._token:
                self._cfg_refresh_worker = ConfigRefreshWorker(self._api_base, self._token, dept)
                self._cfg_refresh_worker.loaded.connect(
                    lambda cfg, etag: self._apply_config(cfg, etag))
                self._cfg_refresh_worker.start()
        # Bring the widget to the foreground for the agent.
        self._show_window()
        # Reuse the SAME start path as the manual button — no parallel logic. The
        # name may be blank (if the CRM lookup found nothing), so don't require it.
        self._start_recording(require_name=False)

    def _close_finished_streamer(self):
        s = getattr(self, "_closing_streamer", None)
        if s is not None:
            self._closing_streamer = None
            try:
                s.close()
            except Exception:
                pass

    def _show_saved_confirmation(self, duration: int):
        """Recording-only: show a simple 'recording saved' card (no compliance)."""
        self._server_summary_shown = True   # block any stale compliance summary
        self._summary_card.show_saved_only(duration)
        self._front_card.setVisible(False)
        self._settings_card.setVisible(False)
        self._summary_card.setVisible(True)

    def _show_local_summary(self, duration: int):
        """Provisional summary from the last live state. The server sends an
        authoritative session_summary that overrides this; once that arrives,
        this must never clobber it."""
        if getattr(self, "_server_summary_shown", False):
            return
        print("[widget] showing LOCAL summary (provisional)")
        total = self._all_criteria_labels
        missing = {i for i in self._missing_ids if i in total}
        covered_ids = [i for i in total if i not in missing]
        covered = [total[i] for i in covered_ids]
        missed = [total[i] for i in missing]
        score = (len(covered_ids) / len(total)) if total else 1.0
        self._summary_card.show_summary(score, covered, missed, duration)
        self._front_card.setVisible(False)
        self._settings_card.setVisible(False)
        self._summary_card.setVisible(True)

    def _show_server_summary(self, msg: dict):
        self._server_summary_shown = True  # authoritative — wins over local
        # Recording-only: ignore any compliance numbers, just confirm the save.
        if not self._live_pipeline:
            self._summary_card.show_saved_only(
                int(msg.get("duration_seconds", self._elapsed) or 0))
            self._front_card.setVisible(False)
            self._settings_card.setVisible(False)
            self._summary_card.setVisible(True)
            return
        print("[widget] showing SERVER summary (authoritative)")
        score = float(msg.get("score", 0.0) or 0.0)
        covered = msg.get("covered", []) or []
        missed = msg.get("missing", []) or []
        duration = int(msg.get("duration_seconds", self._elapsed) or 0)
        covered = [self._all_criteria_labels.get(x, x) for x in covered]
        missed = [self._all_criteria_labels.get(x, x) for x in missed]
        self._summary_card.show_summary(score, covered, missed, duration)
        self._front_card.setVisible(False)
        self._settings_card.setVisible(False)
        self._summary_card.setVisible(True)

    def _on_new_call(self):
        self._customer_name_edit.clear()
        self._reference_edit.clear()
        self._show_front()

    def _tick(self):
        self._elapsed += 1
        m, s = divmod(self._elapsed, 60)
        self._timer_lbl.setText(f"{m:02d}:{s:02d}")

    def _on_error(self, message: str):
        self._stop_recording()
        self._tray.showMessage(
            "Spark Flow",
            "Connection issue – recording stopped. Please reconnect.",
            QSystemTrayIcon.MessageIcon.Warning, 4000)
        QMessageBox.critical(
            self, "Connection Issue",
            f"{message}\n\nPlease check your connection and start a new recording.")

    # ── Tray interaction ──────────────────────────────────────
    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "Spark Flow",
            "Running in the system tray.  Right-click the icon to quit.",
            QSystemTrayIcon.MessageIcon.Information, 2500)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            event.ignore()
            self.hide()
            return
        super().changeEvent(event)

    def _quit(self):
        if self._recording:
            self._stop_recording()
        self._stop_control_connection()
        self._pa.terminate()
        QApplication.quit()


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────
class _Tee:
    """Write to the console (when there is one) AND the log file."""

    def __init__(self, stream, fh):
        self._stream = stream
        self._fh = fh

    def write(self, text):
        for target in (self._stream, self._fh):
            try:
                if target is not None:
                    target.write(text)
            except Exception:
                pass

    def flush(self):
        for target in (self._stream, self._fh):
            try:
                if target is not None:
                    target.flush()
            except Exception:
                pass


def log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "Spark Flow" / "logs" / "widget.log"


def setup_logging() -> Path | None:
    """Mirror everything the widget prints into a log file.

    This is a --windowed build: there is no console, so print() output is simply lost.
    That is why field failures (a stalled update, an unexplained sign-out) have had to be
    diagnosed by guesswork — an agent had nothing to send us. Keep a bounded log under
    %LOCALAPPDATA%\\Spark Flow\\logs so support can just ask for the file.
    """
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Roll at ~2MB so it can never grow without bound on an agent's machine.
        if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
            path.replace(path.with_name("widget.prev.log"))
        fh = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
        sys.stdout = _Tee(sys.__stdout__, fh)
        sys.stderr = _Tee(sys.__stderr__, fh)
        print(f"\n===== Spark Flow {APP_VERSION} starting "
              f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====")
        return path
    except Exception:
        return None      # logging must never stop the widget starting


_INSTANCE_LOCK = None


def acquire_single_instance(key: str = "SparkFlowWidget-singleton") -> bool:
    """True if we are the only running copy; False means one is already up.

    Two copies must never run. Beyond the obvious duplication, this build is a
    PyInstaller ONE-FILE exe: every instance unpacks ~44MB (including python312.dll)
    into its own %TEMP%\\_MEIxxxxxx and deletes it on exit. Two of them starting at once
    — which is exactly what the updater's relaunch-and-retry could cause — race over
    that temp state while antivirus scans it, and the loser dies with
    "Failed to load Python DLL ... python312.dll".

    The lock is a named shared-memory segment; Windows frees it automatically when the
    last process detaches, so a crash can't leave it stuck.
    """
    global _INSTANCE_LOCK
    try:
        from PyQt6.QtCore import QSharedMemory
        _INSTANCE_LOCK = QSharedMemory(key)
        return bool(_INSTANCE_LOCK.create(1))
    except Exception as exc:  # noqa: BLE001 — never block startup on the guard itself
        print(f"[startup] single-instance check unavailable: {exc}")
        return True


def main():
    lp = setup_logging()
    print(f">>> Spark Flow widget {APP_VERSION} <<<")
    if lp:
        print(f"[startup] logging to {lp}")
    # Crisp text on fractional-DPI displays (must be set before QApplication).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    if not acquire_single_instance():
        print("[startup] Spark Flow is already running — exiting this copy")
        return 0
    app.setApplicationName("Spark Flow")
    app.setOrganizationName(ORG)
    app.setQuitOnLastWindowClosed(False)
    _icon_path = resource_path("assets/icon.png")
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    _app_font = QFont("Plus Jakarta Sans")
    if not _app_font.exactMatch():
        _app_font = QFont("Segoe UI")
    _app_font.setPointSizeF(10)
    _app_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    _app_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(_app_font)

    win = MainWindow()
    # Auto-start on login: the installer adds a "--minimized" Run entry so the widget
    # comes up quietly in the system tray instead of popping a window. The control
    # connection still opens via the remembered session, so the dialer can reach it.
    # With no remembered session we show the window so the agent can log in.
    if "--minimized" in sys.argv and win._token:
        pass
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
