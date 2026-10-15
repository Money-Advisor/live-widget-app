#!/usr/bin/env python3
"""
build_focus.py
--------------
Builds the Focus widget (focus_main.py) into dist/SparkFlowFocus/ with
PyInstaller - the same recipe as build_all.py (which is left untouched and
still builds the classic widget), plus the Focus page and Qt WebEngine.

    python build_focus.py                         # build build\focus-dist\SparkFlowFocus\
    python build_focus.py --check                 # + self-test the built exe
    python build_focus.py --installer --check     # + installer\Output\SparkFlowFocusSetup.exe,
                                                  #   installed into a throwaway folder, self-tested,
                                                  #   uninstalled, normal widget proven untouched

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
# Its own output folder, not dist\ - so a rebuild never fights a copy someone
# has open for testing (PyInstaller cannot replace a running exe), and never
# goes near dist\SparkFlow, the classic build. build\ is git-ignored.
DIST = os.path.join(HERE, "build", "focus-dist")

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
        "--distpath", DIST,
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
    exe = os.path.join(DIST, APP_NAME, f"{APP_NAME}.exe")
    result = os.path.join(tempfile.mkdtemp(prefix="sf-focus-build-"), "selftest.txt")
    code = subprocess.run([exe, f"--selftest={result}"], timeout=120).returncode
    text = open(result, encoding="utf-8").read() if os.path.exists(result) else "(no result written)"
    print(text)
    return code == 0 and "RESULT=OK" in text


ISCC_CANDIDATES = [
    os.path.expandvars(r"%USERPROFILE%\tools\InnoSetup6\ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
]
SETUP = os.path.join(HERE, "installer", "Output", "SparkFlowFocusSetup.exe")


def make_installer() -> bool:
    iscc = next((p for p in ISCC_CANDIDATES if os.path.exists(p)), None)
    if iscc is None:
        print("x  Inno Setup (ISCC.exe) not found")
        return False
    return subprocess.run([iscc, "/Q", os.path.join(HERE, "installer", "installer_focus.iss")],
                          cwd=HERE).returncode == 0 and os.path.exists(SETUP)


def _classic_fingerprint():
    """What the NORMAL widget owns on this PC - must be identical before and after."""
    import winreg
    out = {}
    classic_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Spark Flow")
    exe = os.path.join(classic_dir, "SparkFlow.exe")
    out["classic_exe"] = (os.path.getsize(exe), os.path.getmtime(exe)) if os.path.exists(exe) else None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            out["run_key"] = winreg.QueryValueEx(k, "SparkFlow")[0]
    except OSError:
        out["run_key"] = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Spark Flow\Widget\api") as k:
            out["api_base"] = winreg.QueryValueEx(k, "base_url")[0]
    except OSError:
        out["api_base"] = None
    return out


def check_installer() -> bool:
    """Install silently into a throwaway folder (no shortcuts), self-test the
    INSTALLED exe, uninstall - and prove the normal widget was not touched."""
    import shutil
    before = _classic_fingerprint()
    target = tempfile.mkdtemp(prefix="sf-focus-install-")
    shutil.rmtree(target)                       # Inno wants to create it
    ok = True
    r = subprocess.run([SETUP, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS",
                        '/TASKS=', f"/DIR={target}"], timeout=600)
    exe = os.path.join(target, f"{APP_NAME}.exe")
    print(f"install exit={r.returncode}  exe present={os.path.exists(exe)}")
    ok &= r.returncode == 0 and os.path.exists(exe)
    if ok:
        result = os.path.join(tempfile.mkdtemp(prefix="sf-focus-inst-"), "selftest.txt")
        code = subprocess.run([exe, f"--selftest={result}"], timeout=120).returncode
        text = open(result, encoding="utf-8").read() if os.path.exists(result) else "(no result)"
        print(text)
        ok &= code == 0 and "RESULT=OK" in text
    unins = os.path.join(target, "unins000.exe")
    if os.path.exists(unins):
        u = subprocess.run([unins, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
        # The uninstaller hands off to a copy of itself and returns at once; give it a moment.
        import time
        for _ in range(60):
            if not os.path.exists(exe):
                break
            time.sleep(1)
        print(f"uninstall exit={u.returncode}  exe gone={not os.path.exists(exe)}")
        ok &= not os.path.exists(exe)
    after = _classic_fingerprint()
    same = before == after
    print(f"normal widget untouched={same}  {before if same else (before, after)}")
    return ok and same


def main():
    if not build():
        print("\nBuild failed - check the output above.")
        sys.exit(1)
    print(f"\nOK  {os.path.join(DIST, APP_NAME, APP_NAME + '.exe')}  (folder build)")
    ok = True
    if "--check" in sys.argv:
        ok = check()
        print("SELF-TEST " + ("PASSED" if ok else "FAILED"))
    if ok and "--installer" in sys.argv:
        if not make_installer():
            print("x  installer build failed")
            sys.exit(1)
        print(f"OK  {SETUP}  ({os.path.getsize(SETUP) / 1e6:.0f} MB)")
        if "--check" in sys.argv:
            ok = check_installer()
            print("INSTALLER TEST " + ("PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
