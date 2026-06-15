#!/usr/bin/env python3
"""
build_all.py
------------
Builds the Spark Flow desktop widget (main.py) into a standalone app with
PyInstaller. Produces a Windows .exe or a macOS .app + .dmg depending on the
host OS. The login web page (assets/login.html) is bundled alongside the binary.

Usage:
    python build_all.py

Output (Windows):  dist/SparkFlow.exe
Output (macOS):    dist/SparkFlow.app  +  dist/SparkFlow.dmg
"""

import subprocess
import sys
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
IS_MAC = sys.platform == "darwin"

APP_NAME = "SparkFlow"

# Bundle the assets folder (icon.png). --add-data uses os.pathsep as the
# SRC{sep}DEST separator (';' on Windows, ':' elsewhere).
ADD_DATA = [f"{os.path.join(HERE, 'assets')}{os.pathsep}assets"]

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
]

COLLECT_ALL = ["pyaudiowpatch"]


def run_build() -> bool:
    print(f"\n{'=' * 60}")
    print(f"  Building: {APP_NAME}  <-  main.py  ({'macOS' if IS_MAC else 'Windows'})")
    print(f"{'=' * 60}")

    cmd = [
        PYTHON, "-m", "PyInstaller",
        "--onefile",
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

    cmd.append(os.path.join(HERE, "main.py"))

    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f"\nx  FAILED: {APP_NAME}  (exit code {result.returncode})")
        return False
    return True


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
        print(f"\nOK  Done: dist/{APP_NAME}.exe")

    print(f"\nArtifacts are in:  {dist_dir}")


if __name__ == "__main__":
    main()
