# -*- coding: utf-8 -*-
"""Spark Flow with the Focus screen.

    python focus_main.py                 # the Focus widget
    python focus_main.py --minimized     # quietly into the tray (if signed in)

The SAME widget as main.py - same sign-in, recording, dialer, tray and update
code, imported unchanged - started as FocusWindow, which lays the Focus page
over it. Focus only: this exe offers no way to the classic screen (that is
SparkFlow.exe, built from main.py, which is not touched).
"""
import os
import sys

from PyQt6.QtCore import Qt, QCoreApplication

# Qt WebEngine has to be loaded before the QApplication exists, or created
# with shared GL contexts. Both, belt and braces.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

import main            # noqa: E402 - the widget, unchanged
import focus_ui        # noqa: E402 - imports QtWebEngineWidgets (optional)

from PyQt6.QtGui import QFont, QIcon          # noqa: E402
from PyQt6.QtWidgets import QApplication      # noqa: E402


def run():
    lp = main.setup_logging()
    print(f">>> Spark Flow widget {main.APP_VERSION} (Focus) <<<")
    if lp:
        print(f"[startup] logging to {lp}")
    if focus_ui.WEBENGINE_ERROR:
        print(f"[focus] WebEngine unavailable - classic only: {focus_ui.WEBENGINE_ERROR}")
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    # The SAME single-instance key as main.py: the classic and Focus builds
    # must never both run, or one call would be recorded twice.
    if not main.acquire_single_instance():
        print("[startup] Spark Flow is already running - exiting this copy")
        # Classic exits silently here (a second copy at login is normal). For
        # Focus the usual cause is the normal widget still running, and a
        # double-click that does nothing reads as "it's broken" - so say why.
        if "--minimized" not in sys.argv:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                None, "Spark Flow is already running",
                "Spark Flow is already open on this PC.\n\n"
                "To use Spark Flow Focus, right-click the Spark Flow icon near the "
                "clock, choose Quit, then open Spark Flow Focus again.")
        return 0
    app.setApplicationName("Spark Flow")
    app.setOrganizationName(main.ORG)
    app.setQuitOnLastWindowClosed(False)
    icon = main.resource_path("assets/icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    font = QFont("Plus Jakarta Sans")
    if not font.exactMatch():
        font = QFont("Segoe UI")
    font.setPointSizeF(10)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    win = focus_ui.FocusWindow()
    if "--minimized" in sys.argv and win._token:
        pass
    else:
        win.show()
        if win.focus_active():
            win._focus.place()
    return app.exec()


def selftest(result_path):
    """Prove a build works without touching the PC it runs on.

    Throwaway settings (so nobody is signed in and no server is called), no
    widget.log, no single-instance lock - then the real FocusWindow starts,
    the page must load and connect, and the outcome is written to
    `result_path` (a --windowed build has no console to print to).
    """
    import tempfile
    from PyQt6.QtCore import QSettings, QTimer, QEventLoop
    ini = os.path.join(tempfile.mkdtemp(prefix="sf-focus-selftest-"), "widget.ini")
    main.QSettings = lambda *a, **k: QSettings(ini, QSettings.Format.IniFormat)
    app = QApplication(sys.argv)
    lines = [f"version={main.APP_VERSION}", f"webengine_error={focus_ui.WEBENGINE_ERROR}",
             f"focus_dir={focus_ui.focus_dir()}"]
    win = focus_ui.FocusWindow(start=True)
    lines.append(f"settings_isolated={win._settings.format() == QSettings.Format.IniFormat and not win._token}")
    win.show()
    waited = 0
    while waited < 30000 and not (win._focus.ready or win._focus.failed):
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()
        waited += 200
    drawn = {}
    if win._focus.ready:
        # The page draws a moment after it connects; ask until it has (3s at most).
        for _ in range(30):
            box = {}
            win._focus.view.page().runJavaScript("!!document.getElementById('f-email')",
                                                 lambda r: box.setdefault("r", r))
            loop = QEventLoop()
            QTimer.singleShot(100, loop.quit)
            loop.exec()
            if box.get("r") is True:
                drawn["login"] = True
                break
    ok = bool(win._focus.ready and drawn.get("login") and win.focus_active())
    lines += [f"ready={win._focus.ready}", f"failed={win._focus.failed}",
              f"sign_in_drawn={drawn.get('login')}", f"width={win.width()}",
              f"waited_ms={waited}", "RESULT=" + ("OK" if ok else "FAIL")]
    with open(result_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        if arg.startswith("--selftest="):
            selftest(arg.split("=", 1)[1])
    sys.exit(run())
