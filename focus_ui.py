# -*- coding: utf-8 -*-
"""Spark Flow Focus - the new screen, laid over the unchanged widget.

Faseeh, 15 Oct 2026: "DON'T TOUCH ANYTHING FROM THE CURRENT SETUP OR BREAK
ANYTHING - IMPLEMENT EVERYTHING IN ISOLATION". So this file changes nothing in
main.py. FocusWindow IS the classic MainWindow - every worker, the recording,
the dialer connection, sign-in, the tray, the auto-update - with one more
thing laid over it: a web page (focus/index.html) drawn by Qt WebEngine.

The classic screens are still built, still fed every message, and simply
hidden while Focus is showing. That is what makes switching back instant and
safe in the middle of a call: nothing has to be rebuilt, the classic panels are
already up to date.

Every button on the Focus page ends in a call to the SAME MainWindow method the
classic button calls (`_toggle_recording`, `_toggle_pause`, `_attempt_login`,
...). Focus has no recording, sign-in or network code of its own, so it cannot
lose a call; the worst a fault here can do is draw something wrong. If the page
cannot start at all - WebEngine missing, the page failing to load, the page
never saying it is ready - the window drops back to the classic screen by
itself and says so in the tray.
"""
import json
import os
import sys

from PyQt6.QtCore import QObject, QSize, QTimer, Qt, QUrl, pyqtSignal, pyqtSlot, QEvent
from PyQt6.QtGui import QGuiApplication, QColor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

import main

try:   # WebEngine is the one new dependency, and it is optional: without it, classic.
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineScript, QWebEnginePage, QWebEngineSettings
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtCore import QFile, QIODevice
    WEBENGINE_ERROR = None
except Exception as exc:          # noqa: BLE001 - any import failure means "no Focus"
    QWebEngineView = None
    WEBENGINE_ERROR = f"{type(exc).__name__}: {exc}"


DOCK_KEY = "ui/focus_dock"        # "right" | "left"

PANEL_W = 360                     # the panel, as drawn by focus/app.css
PIN_W = 360                       # the I&E pinned beside it
STRIP_W = 64                      # folded
PEEK_W = 352                      # a card sliding out of the strip (340 + 12 gap)
READY_TIMEOUT_MS = 10_000         # the page must say "ready" within this, or classic
MESSAGES_KEPT = 600               # this call's messages, replayed if the page reloads


def focus_dir() -> str:
    return main.resource_path("focus")


def _norm_items(items):
    """Summary rows arrive as {label, section} (rulebook) or plain strings (old matcher)."""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append({"label": str(it.get("label") or ""), "section": str(it.get("section") or "")})
        else:
            out.append({"label": str(it), "section": ""})
    return out


class FocusBridge(QObject):
    """The one object the page can reach. Two ways in, one way out."""

    push = pyqtSignal(str)

    def __init__(self, ctl):
        super().__init__()
        self._ctl = ctl

    @pyqtSlot(str, str)
    def call(self, action, payload):
        # An exception escaping a slot makes PyQt6 call qFatal - the whole
        # widget, and the call it is recording, gone. Never let one out.
        try:
            self._ctl.on_action(action, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[focus] action {action!r} failed: {type(exc).__name__}: {exc}")

    @pyqtSlot()
    def ready(self):
        try:
            self._ctl.on_ready()
        except Exception as exc:  # noqa: BLE001
            print(f"[focus] ready failed: {type(exc).__name__}: {exc}")


class FocusController:
    """Everything between the widget and the Focus page.

    `view_factory` exists for the tests: they drive the controller with a
    stand-in view and so prove the wiring without WebEngine or a screen.
    """

    def __init__(self, win, view_factory=None):
        self.win = win
        self.active = False
        self.ready = False
        self.failed = None
        self.dock = (win._settings.value(DOCK_KEY, "right") or "right")
        if self.dock not in ("left", "right"):
            self.dock = "right"
        self.layout = {"mode": "panel", "pin": False, "peek": False}
        self.summary = None
        self.call_seq = 0
        self._was_recording = bool(win._recording)
        self._had_token = bool(win._token)
        self._seen_main = False
        self._messages = []
        self._last_state = None
        self._placing = False
        self.view = None
        self.bridge = FocusBridge(self)
        self._view_factory = view_factory or self._make_web_view
        # Only a real page says "drawn" (FocusWindow._unveil); a stand-in view
        # (the tests) has nothing to wait for.
        self._waits_for_drawn = view_factory is None

        # The page can be told nothing before it says it is ready; anything
        # sent earlier would be lost, so the first push is a full replay.
        self._poll = QTimer(win)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._tick)
        self._ready_timer = QTimer(win)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.timeout.connect(self._ready_timed_out)
        self._snap = QTimer(win)
        self._snap.setSingleShot(True)
        self._snap.setInterval(300)
        self._snap.timeout.connect(self._snap_to_edge)

        win.server_message.connect(self._on_server_message)
        self._wrap_summary(win._summary_card)

    # ------------------------------------------------------------------ view
    def _make_web_view(self):
        if QWebEngineView is None:
            raise RuntimeError(f"Qt WebEngine is not available ({WEBENGINE_ERROR})")
        index = os.path.join(focus_dir(), "index.html")
        if not os.path.exists(index):
            raise RuntimeError(f"the Focus page is missing ({index})")
        view = QWebEngineView(self.win)
        page = view.page()
        # Transparent behind the panel: when a card slides out of the strip,
        # the space around it must show the advisor's desktop, not a block.
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        s = page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        channel = QWebChannel(page)
        channel.registerObject("bridge", self.bridge)
        page.setWebChannel(channel)
        self._channel = channel
        script = QWebEngineScript()
        script.setName("spark-flow-bridge")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(_qwebchannel_js() + "\n" +
                             "new QWebChannel(qt.webChannelTransport, function (ch) {"
                             " window.FocusApp.connect(ch.objects.bridge); });")
        page.scripts().insert(script)
        view.loadFinished.connect(self._on_load_finished)
        view.setUrl(QUrl.fromLocalFile(index))
        return view

    def start(self):
        """Build the page and show it. Any failure leaves the classic screen up."""
        try:
            self.view = self._view_factory()
            lay = self.win.centralWidget().layout()
            lay.addWidget(self.view)
            self.view.hide()
            self._ready_timer.start(READY_TIMEOUT_MS)
            self._poll.start()
            self.activate()
            if not self._waits_for_drawn:
                self.win._unveil()
            return True
        except Exception as exc:  # noqa: BLE001
            self._fail(f"could not start ({type(exc).__name__}: {exc})")
            return False

    def _on_load_finished(self, ok):
        if not ok:
            self._fail("the page did not load")

    def _ready_timed_out(self):
        if not self.ready:
            self._fail(f"the page did not start within {READY_TIMEOUT_MS // 1000}s")

    def _fail(self, why):
        self.failed = why
        print(f"[focus] falling back to the classic layout: {why}")
        self.deactivate()
        # Whatever else happens, the window must not stay invisible.
        unveil = getattr(self.win, "_unveil", None)
        if callable(unveil):
            unveil()
        tray = getattr(self.win, "_tray", None)
        if tray is not None:
            tray.showMessage("Spark Flow", "The new layout could not start, so the classic "
                             "layout is showing. Recording is not affected.",
                             QSystemTrayIcon.MessageIcon.Warning, 6000)

    # ------------------------------------------------------- on and off
    def activate(self):
        if self.view is None or self.failed:
            return False
        self.active = True
        self.win._stack.hide()
        self.view.show()
        self.win.setMinimumSize(0, 0)
        self.place()
        self._apply_on_top()
        self.push_state(force=True)
        return True

    def deactivate(self):
        was = self.active
        self.active = False
        if self.view is not None:
            self.view.hide()
        self.win._stack.show()
        self.win.setMinimumSize(460, 600)
        if was or self.failed:
            self._restore_classic_geometry()

    def _restore_classic_geometry(self):
        """Hand the window back to the classic layout, on the same edge."""
        win = self.win
        lay = win.centralWidget().layout() if win.centralWidget() else None
        if lay is not None:
            lay.activate()
        hint = win.sizeHint()
        scr = win.screen() or QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr is not None else None
        w = max(hint.width(), win.minimumWidth())
        h = max(hint.height(), win.minimumHeight())
        if avail is not None:
            h = min(h, avail.height())
            x = avail.right() - w + 1 - 16 if self.dock == "right" else avail.left() + 16
            y = max(avail.top(), min(win.y(), avail.bottom() - h))
            win.setGeometry(x, y, w, h)
        else:
            win.resize(w, h)
        # The classic panel keeps itself on top while it is showing; let it decide.
        try:
            main.MainWindow.set_compliance_on_top(win, win._compliance_panel.isVisible())
        except Exception:  # noqa: BLE001
            pass
        QTimer.singleShot(0, win._compliance_panel._sync_window)

    def _apply_on_top(self):
        # Exactly the classic rule: once signed in the panel is always visible,
        # and a visible panel keeps the widget above Aryza and the browser.
        # Sign-out's sticky mode owns the flag itself (set_compliance_on_top
        # returns early then).
        if not self.active:
            return
        on = self.win._stack.currentWidget() is not self.win._page_login
        main.MainWindow.set_compliance_on_top(self.win, on)

    # ------------------------------------------------------------- geometry
    def width(self):
        lay = self.layout
        if lay.get("mode") == "strip":
            return STRIP_W + (PEEK_W if lay.get("peek") else 0)
        return PANEL_W + (PIN_W if lay.get("pin") else 0)

    def place(self):
        """Full height, flush to the chosen edge of the screen the window is on."""
        win = self.win
        scr = win.screen() or QApplication.primaryScreen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        w = self.width()
        x = avail.right() - w + 1 if self.dock == "right" else avail.left()
        self._placing = True
        try:
            win.setGeometry(x, avail.top(), w, avail.height())
        finally:
            self._placing = False

    def size_hint(self):
        return QSize(self.width(), self.win.height() or 800)

    def on_moved(self):
        if self.active and not self._placing:
            self._snap.start()

    def _snap_to_edge(self):
        if not self.active:
            return
        if _left_button_down():
            self._snap.start()           # still being dragged; look again shortly
            return
        win = self.win
        centre = win.frameGeometry().center()
        scr = QGuiApplication.screenAt(centre) or win.screen() or QApplication.primaryScreen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        self.dock = "left" if centre.x() < avail.center().x() else "right"
        win._settings.setValue(DOCK_KEY, self.dock)
        if win.windowHandle() is not None and win.windowHandle().screen() is not scr:
            win.windowHandle().setScreen(scr)
        self.place()
        self.push_state(force=True)

    # ---------------------------------------------------------------- state
    def phase(self):
        win = self.win
        if win._stack.currentWidget() is win._page_login:
            return "login"
        self._seen_main = True
        if win._recording:
            return "live"
        if win._starting:
            return "starting"
        if not win._summary_card.isHidden():
            return "summary"
        return "idle"

    def snapshot(self):
        win = self.win
        phase = self.phase()
        rec = bool(win._recording)
        if rec and not self._was_recording:
            # A new call. The page clears its call state on a new number,
            # exactly as the classic panels are cleared in _on_call_connected.
            self.call_seq += 1
            self._messages = []
            self._latest = {}
            self._last_card_keys = ()
            self._resolved_kept = False
            self.summary = None
        self._was_recording = rec
        panel = win._compliance_panel
        scores = list(getattr(panel, "_shift_scores", []) or [])
        user = win._user or {}
        err_css = win._login_error.styleSheet() or ""
        err_text = (win._login_error.text() or "").strip()
        is_info = "#86EFAC" in err_css.upper()
        mic_names = [d.get("name", "") for d in (win._mic_devices or [])]
        spk_names = [d.get("name", "") for d in (win._spk_devices or [])]
        return {
            "phase": phase,
            "signedOut": phase == "login" and (self._seen_main or self._had_token),
            "login": {
                "busy": not win._signin_btn.isEnabled(),
                "error": "" if is_info else err_text,
                "info": err_text if is_info else "",
                "forgotBusy": not win._forgot_btn.isEnabled(),
            },
            "user": {"name": (user.get("name") or user.get("email") or "").strip(),
                     "email": user.get("email") or "",
                     "dept": (win._active_department or "").upper() if len(win._active_department or "") <= 4
                     else (win._active_department or "").replace("-", " ").title()},
            "company": win._company_name or "Spark Flow",
            "recording": rec,
            "hideLocked": win.call_in_progress(),
            "paused": bool(win._paused),
            "elapsed": int(win._elapsed or 0),
            "callSeq": self.call_seq,
            "ref": win._reference_edit.text().strip(),
            "livePipeline": bool(win._live_pipeline),
            "hideFields": bool((win._config or {}).get("hide_customer_fields", False)),
            "shift": {
                "calls": getattr(panel, "_shift_calls", 0) or "",
                "avg": f"{round(100 * sum(scores) / len(scores))}%" if scores else "",
                "flags": getattr(panel, "_shift_flags", 0) or "",
            },
            "micGate": bool(win._mic_gate_active),
            "mics": mic_names,
            "micIndex": win._mic_combo.currentIndex() if mic_names else -1,
            "spks": spk_names,
            "spkIndex": win._spk_combo.currentIndex() if spk_names else -1,
            "apiBase": win._api_base or "",
            "wsUrl": win._ws_url or "",
            "version": main.APP_VERSION,
            "dock": self.dock,
        }

    def _send(self, payload):
        if self.ready:
            self.bridge.push.emit(json.dumps(payload))

    def push_state(self, force=False):
        state = self.snapshot()
        text = json.dumps(state, sort_keys=True)
        if force or text != self._last_state:
            self._last_state = text
            self._send({"kind": "state", "data": state})
            self._apply_on_top()

    def _tick(self):
        try:
            self.push_state()
        except Exception as exc:  # noqa: BLE001
            print(f"[focus] state not sent ({type(exc).__name__}: {exc})")

    def on_ready(self):
        """The page is up: give it everything, in order, in one go."""
        self.ready = True
        self._ready_timer.stop()
        state = self.snapshot()
        self._last_state = json.dumps(state, sort_keys=True)
        items = [{"kind": "state", "data": state}]
        replay = self.replay()
        items += [{"kind": "msg", "data": m} for m in replay]
        if self.summary is not None:
            items.append({"kind": "summary", "data": self.summary})
        self.bridge.push.emit(json.dumps({"kind": "batch", "items": items}))
        print(f"[focus] page ready ({len(replay)} messages replayed)")

    # -------------------------------------------------------------- messages
    FORWARD_ALWAYS = ("crisis_alert", "transcription_status", "connection_status")
    FORWARD_WHEN_RECORDING = ("compliance_alert", "ie_panel")

    def _on_server_message(self, msg):
        try:
            if not isinstance(msg, dict):
                return
            t = msg.get("type")
            if t in self.FORWARD_WHEN_RECORDING:
                # The classic rule (_handle_server_message): the server's last
                # fragments land after the call has stopped, and nothing about a
                # call that has ended is worth acting on.
                if not self.win._recording:
                    return
            elif t not in self.FORWARD_ALWAYS:
                return
            # The state first, so the page knows which call this belongs to.
            self.push_state()
            self._remember(msg)
            self._send({"kind": "msg", "data": msg})
        except Exception as exc:  # noqa: BLE001
            print(f"[focus] message not forwarded ({type(exc).__name__}: {exc})")

    @staticmethod
    def _card_keys(msg):
        return tuple(sorted(f"{r.get('id') or r.get('message')}#{r.get('occurrence')}"
                            for r in (msg.get("trigger_actions") or []) if isinstance(r, dict)))

    def _remember(self, msg):
        """Keep what a reloaded page needs to draw this call exactly as it was.

        Not every message: the server sends the full state every few seconds,
        and a 90-minute call is thousands of them. Kept for good are the ones
        that changed something lasting - the safety card, its resolution, a
        forbidden phrase, every change in WHICH correction cards are up (their
        order on screen is the order they arrived) - plus the newest of each
        other kind. Replayed in arrival order, that rebuilds the same screen.
        """
        t = msg.get("type")
        lasting = (t == "crisis_alert"
                   or (t == "compliance_alert" and (msg.get("forbidden_hits") or msg.get("cue_hits"))))
        # crisis_resolved stays true on every message after it - only the first counts,
        # or a long call's list would fill with them and push the safety card itself out.
        if t == "compliance_alert" and msg.get("crisis_resolved") and not getattr(self, "_resolved_kept", False):
            self._resolved_kept = True
            lasting = True
        # Track the card set on EVERY full state - also one already kept for
        # another reason - or the next message is wrongly seen as a change.
        if t == "compliance_alert" and (msg.get("sections") or msg.get("section_checks") or msg.get("stage")):
            keys = self._card_keys(msg)
            if keys != getattr(self, "_last_card_keys", ()):
                self._last_card_keys = keys
                lasting = True
        self._seq = getattr(self, "_seq", 0) + 1
        if lasting:
            self._messages.append((self._seq, msg))
            if len(self._messages) > MESSAGES_KEPT:
                # Trim the oldest card changes, never the safety card.
                crisis = [m for m in self._messages if m[1].get("type") == "crisis_alert"]
                rest = [m for m in self._messages if m[1].get("type") != "crisis_alert"]
                self._messages = sorted(crisis + rest[-MESSAGES_KEPT:], key=lambda x: x[0])
        else:
            kind = t if t != "compliance_alert" else ("state" if (msg.get("sections") or msg.get("stage")) else "praise")
            if kind != "praise":
                self._latest = getattr(self, "_latest", {})
                self._latest[kind] = (self._seq, msg)

    def replay(self):
        latest = list(getattr(self, "_latest", {}).values())
        return [m for _, m in sorted(self._messages + latest, key=lambda x: x[0])]

    def _wrap_summary(self, card):
        """Watch the classic summary card, which MainWindow already drives.

        The decisions - wait for the server, show a score, show "saved" only,
        give up after 25 seconds - stay in MainWindow, made once. Focus only
        draws the outcome.
        """
        ctl = self

        def wrap(name, make):
            original = getattr(card, name)

            def wrapped(*a, **k):
                result = original(*a, **k)
                try:
                    make(*a, **k)
                    ctl._send({"kind": "summary", "data": ctl.summary})
                    ctl.push_state()
                except Exception as exc:  # noqa: BLE001
                    print(f"[focus] summary not sent ({type(exc).__name__}: {exc})")
                return result
            setattr(card, name, wrapped)

        def on_summary(score, covered, missed, duration_seconds):
            self.summary = {"mode": "score", "score": main.score_fraction(score),
                            "covered": _norm_items(covered), "missed": _norm_items(missed),
                            "duration": int(duration_seconds or 0), "saved": False}

        def on_pending(duration_seconds):
            self.summary = {"mode": "pending", "duration": int(duration_seconds or 0)}

        def on_saved_only(duration_seconds):
            self.summary = {"mode": "saved_only", "duration": int(duration_seconds or 0), "saved": False}

        def on_mark_saved():
            if self.summary is None:
                self.summary = {"mode": "saved_only", "duration": int(self.win._elapsed or 0)}
            self.summary["saved"] = True

        wrap("show_summary", on_summary)
        wrap("show_pending", on_pending)
        wrap("show_saved_only", on_saved_only)
        wrap("mark_saved", on_mark_saved)

    # --------------------------------------------------------------- actions
    def on_action(self, action, payload):
        win = self.win
        try:
            p = json.loads(payload or "{}")
        except ValueError:
            p = {}
        if action == "layout":
            self.layout = {"mode": "strip" if p.get("mode") == "strip" else "panel",
                           "pin": bool(p.get("pin")), "peek": bool(p.get("peek"))}
            if self.active:
                self.place()
            return
        if action == "drawn":
            # The page has painted its first real screen: show the window now,
            # already at its edge, so the first frame anyone sees is the panel.
            win._unveil()
            return
        if action == "move":
            handle = win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            return
        if action == "login":
            win._email_edit.setText(str(p.get("email") or ""))
            win._pw_edit.setText(str(p.get("password") or ""))
            win._attempt_login()
        elif action == "forgot":
            win._email_edit.setText(str(p.get("email") or ""))
            win._attempt_forgot_password()
        elif action == "start":
            if not win._recording and not win._starting:
                win._customer_name_edit.setText(str(p.get("name") or ""))
                win._reference_edit.setText(str(p.get("ref") or ""))
                win._toggle_recording()
        elif action == "pause":
            if win._recording:
                win._toggle_pause()
        elif action == "stop":
            if win._recording:
                win._toggle_recording()
        elif action == "newcall":
            self.summary = None
            win._on_new_call()
        elif action == "mic":
            i = int(p.get("index", -1))
            if 0 <= i < len(win._mic_devices):
                win._mic_combo.setCurrentIndex(i)
                win._on_mic_selected(i)
        elif action == "spk":
            i = int(p.get("index", -1))
            if 0 <= i < len(win._spk_devices):
                win._spk_combo.setCurrentIndex(i)
                win._on_spk_selected(i)
        elif action == "rescan":
            win._rescan_devices()
        elif action == "gateMic":
            i = int(p.get("index", 0))
            gate = getattr(win, "_gate_combo", None)
            if gate is not None and 0 <= i < gate.count():
                gate.setCurrentIndex(i)
                win._confirm_gate_mic()
        elif action == "saveServers":
            win._api_edit.setText(str(p.get("api") or ""))
            win._ws_edit.setText(str(p.get("ws") or ""))
            win._save_settings()
        elif action == "logout":
            win._logout()
        elif action == "hide":
            # Never during a call (19 Oct: an advisor pressed "-" mid-call by
            # mistake). The page greys the button out; this is the second lock.
            if win.call_in_progress():
                print("[focus] hide refused - a call is in progress")
            else:
                win.close()
        else:
            print(f"[focus] unknown action {action!r}")
            return
        self.push_state(force=True)


def _qwebchannel_js():
    """The channel's client script, as Qt ships it inside WebEngine."""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("qwebchannel.js is not available")
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


def _left_button_down():
    """Is the mouse still held? The OS runs the drag, so Qt may not know."""
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:  # noqa: BLE001
            pass
    return bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton)


class _QuietComplianceAlertPanel(main.ComplianceAlertPanel):
    """The classic checklist panel, minus a flash at startup.

    Its constructor ends with show_idle(), which shows the panel while it has
    no parent yet - so for ~20ms it is a small window of its own (356x317) on
    the desktop, before MainWindow adds it to its layout. The classic widget
    covers it straight away; Focus opens transparent, so it was the square
    seen on every double-click (Faseeh, 15 Oct; measured from outside the
    process with focus_dev/startup_windows.py). Here that parentless show is
    kept - the same visible/hidden state as classic - but never reaches the
    screen; the attribute is dropped the moment the panel gets its parent.
    """

    def setVisible(self, visible):
        if visible and self.parentWidget() is None:
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        super().setVisible(visible)

    def event(self, ev):
        if ev.type() == QEvent.Type.ParentChange and self.parentWidget() is not None:
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
        return super().event(ev)


class FocusWindow(main.MainWindow):
    """The classic widget with the Focus screen over it.

    Only the methods that move or pin the WINDOW are overridden, and each one
    defers to the classic method whenever Focus is not showing - so with Focus
    off, this window behaves exactly as MainWindow does.
    """

    _focus = None    # class default: the overrides below run during MainWindow.__init__
    # Veiled (fully transparent) from the window's first show until the page has
    # drawn. Without it, opening the widget flashed an empty square for a split
    # second - the window at the classic default size and place, before the
    # page loaded and docked it (Faseeh, 15 Oct). A class default because the
    # classic sign-out code can show the window from INSIDE MainWindow.__init__.
    _veiled = True
    _building = False         # True only while MainWindow.__init__ runs
    _show_after_build = False

    def __init__(self, view_factory=None, start=True):
        # The panel ONLY (2.9.59: it replaced the old screen in SparkFlow.exe).
        # There is no tray item, button or start option to switch back.
        # The one way the classic screen still appears here is the automatic
        # fallback (FocusController._fail) when the page cannot start at all -
        # a widget that records with the old screen beats one that shows nothing.
        # `start=False` exists for the tests only.
        # MainWindow.__init__ builds its panel by the name in main's globals;
        # point that name at the quiet panel for this one construction only, so
        # nothing else that imports main (the classic widget, its tests) sees it.
        classic_panel = main.ComplianceAlertPanel
        main.ComplianceAlertPanel = _QuietComplianceAlertPanel
        self._building = True
        try:
            super().__init__()
        finally:
            main.ComplianceAlertPanel = classic_panel
            self._building = False
        self._focus = FocusController(self, view_factory=view_factory)
        # Belt and braces: whatever happens to the page, the window is never
        # left invisible past the ready timeout (plus a margin for the fallback).
        self._veil_guard = QTimer(self)
        self._veil_guard.setSingleShot(True)
        self._veil_guard.timeout.connect(self._unveil)
        if start:
            self._veil_guard.start(READY_TIMEOUT_MS + 2000)
            self._focus.start()
        else:
            self._unveil()
        if self._show_after_build and not self.isVisible():
            self.setVisible(True)           # the show the classic code asked for
        # The old screen's own "-" (shown only if the panel cannot start): locked
        # during a call exactly like the panel's. Checked twice a second - cheap,
        # and it cannot miss a start or stop whichever path made it.
        self._classic_minimise = next(
            (b for b in self.findChildren(main.QPushButton) if b.text() == "\u2014"), None)
        self._hide_lock_timer = QTimer(self)
        self._hide_lock_timer.timeout.connect(self._sync_hide_lock)
        self._hide_lock_timer.start(500)
        self._sync_hide_lock()

    def call_in_progress(self):
        """True from the moment a call starts connecting until it has stopped."""
        return bool(self._recording or self._starting)

    def _sync_hide_lock(self):
        btn = getattr(self, "_classic_minimise", None)
        if btn is None:
            return
        locked = self.call_in_progress()
        if btn.isEnabled() == locked:
            btn.setEnabled(not locked)
            btn.setToolTip("Can't hide during a call" if locked else "")

    def setVisible(self, visible):
        # Every show - show(), showNormal(), the sign-out resurfacing - comes
        # through here; while veiled it shows at zero opacity, so the page can
        # load and draw (a hidden window would not) without being seen.
        if self._building:
            # Signed out, the classic code shows the window from inside
            # MainWindow.__init__ - before the page exists. A window shown then
            # is a plain one, and Windows drew it SOLID at its classic size for
            # ~180ms whatever opacity Qt was given (layered, but no alpha set;
            # measured from outside the process, 15 Oct). So the request is
            # held and carried out once the page is in place (see __init__).
            self._show_after_build = visible
            return
        if visible and self._veiled:
            self.setWindowOpacity(0.0)
        super().setVisible(visible)

    def _unveil(self):
        """Show what has been drawn: dock it, then make it visible. Once only."""
        if not self._veiled:
            return
        self._veiled = False
        guard = getattr(self, "_veil_guard", None)
        if guard is not None:
            guard.stop()
        if self.focus_active():
            self._focus.place()
        self.setWindowOpacity(1.0)
        print("[focus] first frame drawn - window shown")

    def focus_active(self):
        return self._focus is not None and self._focus.active

    def _exit_logged_out_mode(self):
        """Signed in: as the classic method, but without dropping "on top".

        The classic one removes WindowStaysOnTopHint, and Focus puts it straight
        back (a signed-in Focus panel is always on top, as the classic panel
        is). Changing that flag destroys and rebuilds the native window on
        Windows, so the two changes were two visible blinks a third of a
        second apart every time the widget opened (Faseeh, 15 Oct; measured
        with focus_dev/startup_blinks.py). Leaving the flag alone is the same
        end state with no rebuild.
        """
        if not self.focus_active():
            return super()._exit_logged_out_mode()
        self._logged_out_sticky = False
        if getattr(self, "_resurface_timer", None):
            self._resurface_timer.stop()
        if getattr(self, "_tray", None):
            self._tray.setToolTip("Spark Flow – idle")

    # ---- the window, while Focus shows ----
    def set_compliance_on_top(self, on):
        if self.focus_active():
            return              # Focus decides (FocusController._apply_on_top)
        super().set_compliance_on_top(on)

    def _fit_ie_column(self, showing):
        if self.focus_active():
            return              # the I&E is inside the Focus panel; the window does not grow
        super()._fit_ie_column(showing)

    def _refit_after_screen_change(self):
        if self.focus_active():
            self._apply_font_smoothing()
            self._focus.place()
            return
        super()._refit_after_screen_change()

    def sizeHint(self):
        # The classic panels resize the window to their sizeHint as they
        # change. While Focus is showing they are hidden, and the window must
        # stay the Focus size - so the hint IS the Focus size, and their
        # resizes become no-ops.
        if self.focus_active():
            return self._focus.size_hint()
        return super().sizeHint()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.focus_active():
            self._focus.on_moved()

    def _on_call_connected(self):
        super()._on_call_connected()
        if self._focus is not None:
            self._focus.push_state(force=True)

    def _stop_recording(self):
        super()._stop_recording()
        if self._focus is not None:
            self._focus.push_state(force=True)
