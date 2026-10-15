#!/usr/bin/env python3
"""
build_focus.py
--------------
Builds the Focus widget (focus_main.py) into dist/SparkFlowFocus/ with
PyInstaller - the same recipe as build_all.py (which is left untouched and
still builds the classic widget), plus the Focus page and Qt WebEngine.

    python build_focus.py            # build
    python build_focus.py --check    # build, then run the built exe's self-test

The self-test runs the BUILT exe on throwaway settings: nobody signed in, no
server called, no widget.log written, no single-instance lock taken - so it
proves the package on any PC without touching the widget installed there.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
APP_NAME = "SparkFlowFocus"

ADD_DATA = [
    f"{os.path.join(HERE, 'assets')}{os.pathsep}assets",
    f"{os.path.join(HERE, 'focus')}{os.pathsep}focus",
]

HIDDEN_IMPORTS = [
    "pyaudiowpatch", "websocket", "websocket._abnf", "websocket._core", "websocket._exceptions",
    "websocket._http", "websocket._logging", "websocket._socket", "websocket._ssl_compat",
    "websocket._utils", "requests", "urllib3", "certifi", "charset_normalizer", "idna",
    "PyQt6.QtSvg", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineCore", "PyQt6.QtWebChannel",
]

COLLECT_ALL = ["pyaudiowpatch"]


def build() -> bool:
    cmd = [
        PYTHON, "-m", "PyInstaller",
        "--onedir",                 # never one-file: see build_all.py (python312.dll + antivirus)
        "--windowed",
        "--name", APP_NAME,
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build", APP_NAME),
        "--specpath", os.path.join(HERE, "build", APP_NAME),
        "--noconfirm", "--clean",
    ]
    icon = os.path.join(HERE, "assets", "icon.ico")
    if os.path.exists(icon):
        cmd += ["--icon", icon]
    for data in ADD_DATA:
        cmd += ["--add-data", data]
    for hi in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", hi]
    for pkg in COLLECT_ALL:
        cmd += ["--collect-all", pkg]
    cmd.append(os.path.join(HERE, "focus_main.py"))
    return subprocess.run(cmd, cwd=HERE).returncode == 0


def check() -> bool:
    exe = os.path.join(HERE, "dist", APP_NAME, f"{APP_NAME}.exe")
    result = os.path.join(tempfile.mkdtemp(prefix="sf-focus-build-"), "selftest.txt")
    code = subprocess.run([exe, f"--selftest={result}"], timeout=120).returncode
    text = open(result, encoding="utf-8").read() if os.path.exists(result) else "(no result written)"
    print(text)
    return code == 0 and "RESULT=OK" in text


def main():
    if not build():
        print("\nBuild failed - check the output above.")
        sys.exit(1)
    print(f"\nOK  dist/{APP_NAME}/{APP_NAME}.exe  (folder build)")
    if "--check" in sys.argv:
        ok = check()
        print("SELF-TEST " + ("PASSED" if ok else "FAILED"))
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
