#!/usr/bin/env python3
"""
build_all.py
------------
Builds the Spark Flow desktop widget into a standalone app with PyInstaller.
Produces a Windows .exe or a macOS .app + .dmg depending on the host OS.

Since 2.9.59 the widget is focus_main.py: the one-panel screen (focus/, drawn
by Qt WebEngine) over the unchanged MainWindow in main.py. The exe keeps its
name, so the installer and the auto-updater replace the old widget in place.
The build Python needs PyQt6-WebEngine (requirements.txt).

Usage:
    python build_all.py            # build
    python build_all.py --check    # build, then self-test the built exe

Output (Windows):  dist/SparkFlow/SparkFlow.exe  (folder build)
Output (macOS):    dist/SparkFlow.app  +  dist/SparkFlow.dmg
"""

import subprocess
import sys
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
IS_MAC = sys.platform == "darwin"

APP_NAME = "SparkFlow"

# Bundle the assets folder (icon.png) and the panel's page (focus/). --add-data
# uses os.pathsep as the SRC{sep}DEST separator (';' on Windows, ':' elsewhere).
ADD_DATA = [
    f"{os.path.join(HERE, 'assets')}{os.pathsep}assets",
    f"{os.path.join(HERE, 'focus')}{os.pathsep}focus",
]

HIDDEN_IMPORTS = [
    "pyaudiowpatch",
    "websocket",
    "websocket._abnf",
    "websocket._core",
    "websocket._exceptions",
    "websocket._http",
    "websocket._logging",
    "websocket._socket",
    "websocket._ssl_compat",
    "websocket._utils",
    "requests",
    "urllib3",
    "certifi",
    "charset_normalizer",
    "idna",
    "PyQt6.QtSvg",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebChannel",
]

COLLECT_ALL = ["pyaudiowpatch"]


def run_build() -> bool:
    print(f"\n{'=' * 60}")
    print(f"  Building: {APP_NAME}  <-  focus_main.py  ({'macOS' if IS_MAC else 'Windows'})")
    print(f"{'=' * 60}")

    cmd = [
        PYTHON, "-m", "PyInstaller",
        # ONEDIR, not onefile. A one-file build unpacks ~44MB (including python312.dll)
        # into a fresh %TEMP%\_MEIxxxxxx on EVERY launch and deletes it on exit. With
        # antivirus scanning that unpack, agents hit
        #   "Failed to load Python DLL ...\_MEIxxxxxx\python312.dll"
        # and end up with no widget at all — which for a call recorder means no
        # recording. The failure happens in the PyInstaller bootloader, before any of
        # our Python runs, so it cannot be handled in-app. A folder build ships the DLLs
        # next to the exe, unpacks nothing, and also starts noticeably faster.
        "--onedir",
        "--windowed",                       # no console window (GUI app)
        "--name", APP_NAME,
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build", APP_NAME),
        "--specpath", os.path.join(HERE, "build", APP_NAME),
        "--noconfirm",
        "--clean",
    ]

    # App/exe icon (Windows .ico / macOS .icns).
    icon = os.path.join(HERE, "assets", "icon.icns" if IS_MAC else "icon.ico")
    if os.path.exists(icon):
        cmd += ["--icon", icon]

    for data in ADD_DATA:
        cmd += ["--add-data", data]
    for hi in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", hi]
    for pkg in COLLECT_ALL:
        cmd += ["--collect-all", pkg]

    cmd.append(os.path.join(HERE, "focus_main.py"))

    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f"\nx  FAILED: {APP_NAME}  (exit code {result.returncode})")
        return False
    return True


def check() -> bool:
    """Run the BUILT exe's self-test: throwaway settings (nobody signed in, no
    server called), no widget.log, no single-instance lock - so it proves the
    package on any PC without touching the widget installed there."""
    exe = os.path.join(HERE, "dist", APP_NAME, f"{APP_NAME}.exe")
    result = os.path.join(tempfile.mkdtemp(prefix="sf-build-"), "selftest.txt")
    code = subprocess.run([exe, f"--selftest={result}"], timeout=120).returncode
    text = open(result, encoding="utf-8").read() if os.path.exists(result) else "(no result written)"
    print(text)
    return code == 0 and "RESULT=OK" in text


def make_dmg() -> bool:
    """Package dist/SparkFlow.app into dist/SparkFlow.dmg (macOS only)."""
    app_path = os.path.join(HERE, "dist", f"{APP_NAME}.app")
    dmg_path = os.path.join(HERE, "dist", f"{APP_NAME}.dmg")
    if not os.path.isdir(app_path):
        print(f"x  {app_path} not found - cannot build .dmg")
        return False
    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    print(f"\n  Creating {APP_NAME}.dmg ...")
    cmd = [
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", app_path,
        "-ov", "-format", "UDZO",
        dmg_path,
    ]
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f"x  hdiutil failed (exit code {result.returncode})")
        return False
    print(f"OK  Done: dist/{APP_NAME}.dmg")
    return True


def main():
    dist_dir = os.path.join(HERE, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    ok = run_build()
    if not ok:
        print("\nBuild failed - check the output above for details.")
        sys.exit(1)

    if IS_MAC:
        print(f"\nOK  Done: dist/{APP_NAME}.app")
        if not make_dmg():
            sys.exit(1)
    else:
        print(f"\nOK  Done: dist/{APP_NAME}/{APP_NAME}.exe  (folder build)")
        if "--check" in sys.argv:
            if not check():
                print("\nSELF-TEST FAILED - do not ship this build.")
                sys.exit(1)
            print("SELF-TEST PASSED")

    print(f"\nArtifacts are in:  {dist_dir}")


if __name__ == "__main__":
    main()
