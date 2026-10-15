# -*- coding: utf-8 -*-
"""What Windows shows while the Focus widget opens - watched from OUTSIDE.

    python focus_dev/startup_windows.py [signed-in|signed-out]
    python focus_dev/startup_windows.py --exe build/focus-dist/SparkFlowFocus/SparkFlowFocus.exe

Starts the widget as a separate process and, every ~2ms, lists every visible
top-level window that process (or a child of it) owns: where it is, and its
transparency as Windows has it. startup_blinks.py watches from inside Qt and
was blind to both squares Faseeh still saw on 15 Oct - the classic checklist
panel briefly shown as a window of its own, and (signed out) the widget shown
solid before Windows had its transparency. This sees what the screen sees.

PASS needs exactly one window ever seen non-transparent, and only ever at its
final docked rectangle. The source run uses throwaway settings and no network
(the same stand-ins as startup_blinks.py); --exe runs the build's own
--selftest, which uses throwaway settings of its own.
"""
import ctypes
import ctypes.wintypes as W
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent


def child(mode):
    """focus_main.run() exactly, on throwaway settings, closing itself after 6s."""
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    from PyQt6.QtCore import Qt, QCoreApplication, QSettings
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    import main
    import focus_main
    ini = os.path.join(tempfile.mkdtemp(prefix="sf-windows-"), "widget.ini")
    main.QSettings = lambda *a, **k: QSettings(ini, QSettings.Format.IniFormat)
    s = QSettings(ini, QSettings.Format.IniFormat)
    s.setValue("audio/mic_name", "x")
    if mode == "signed-in":
        s.setValue("auth/token", "stand-in")
    s.sync()
    main.ValidateWorker.start = lambda self: None     # no network
    main.acquire_single_instance = lambda: True       # never the real lock
    main.setup_logging = lambda: None                 # never the real widget.log
    sys.argv = [sys.argv[0]]
    focus_main.run()


u = ctypes.windll.user32
dwm = ctypes.windll.dwmapi
k32 = ctypes.windll.kernel32
k32.CreateToolhelp32Snapshot.restype = W.HANDLE
EnumProc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


class _PE(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD),
                ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                ("pcPriClassBase", W.LONG), ("dwFlags", W.DWORD), ("szExeFile", ctypes.c_char * 260)]


def family(root):
    """root and every process descended from it (a venv's python.exe is a launcher)."""
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    pe = _PE()
    pe.dwSize = ctypes.sizeof(_PE)
    parent = {}
    ok = k32.Process32First(snap, ctypes.byref(pe))
    while ok:
        parent[pe.th32ProcessID] = pe.th32ParentProcessID
        ok = k32.Process32Next(snap, ctypes.byref(pe))
    k32.CloseHandle(snap)
    fam, grew = {root}, True
    while grew:
        grew = False
        for c, p in parent.items():
            if p in fam and c not in fam:
                fam.add(c)
                grew = True
    return fam


def describe(h):
    r = W.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    alpha, flags = ctypes.c_ubyte(255), W.DWORD(0)
    a = None                                          # None = not transparent at all
    if u.GetWindowLongW(h, -20) & 0x80000 and u.GetLayeredWindowAttributes(
            h, None, ctypes.byref(alpha), ctypes.byref(flags)) and flags.value & 2:
        a = alpha.value
    cloaked = W.DWORD(0)
    dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), 4)
    return (r.left, r.top, r.right - r.left, r.bottom - r.top), a, cloaked.value


def watch(cmd, seconds):
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pids, next_family, last, log = {proc.pid}, 0.0, {}, []

    def scan():
        seen = {}

        def cb(h, _):
            owner = W.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(owner))
            if owner.value in pids and u.IsWindowVisible(h):
                seen[h] = describe(h)
            return True
        u.EnumWindows(EnumProc(cb), 0)
        return seen

    while proc.poll() is None and time.perf_counter() - t0 < seconds:
        if time.perf_counter() > next_family:
            pids = family(proc.pid)
            next_family = time.perf_counter() + 0.05
        now, t = scan(), round(time.perf_counter() - t0, 3)
        for h, v in now.items():
            if last.get(h) != v:
                log.append((t, h, v))
        last = now
        time.sleep(0.002)
    code = proc.poll()
    for p in family(proc.pid):
        subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
    return log, code


def judge(label, log):
    for t, h, (rect, alpha, cloaked) in log:
        print(f"  {t:6.3f}s window {h:#x} at {rect} alpha={'solid' if alpha is None else alpha}"
              f"{' cloaked' if cloaked else ''}")
    seen = [(h, rect) for _, h, (rect, alpha, cloaked) in log if alpha != 0 and not cloaked]
    windows = {h for h, _ in seen}
    final = seen[-1][1] if seen else None
    wrong = [s for s in seen if s[1] != final]
    ok = bool(seen) and len(windows) == 1 and not wrong and final[2] == 360
    print(f"RESULT {label}: windows seen={len(windows)} frames not at the final place={len(wrong)} "
          f"final={final} -> {'PASS' if ok else 'FAIL'}")
    return ok


def main_():
    args = sys.argv[1:]
    if args[:1] == ["--child"]:
        child(args[1])
        return 0
    if args[:1] == ["--exe"]:
        exe = str(Path(args[1]).resolve())
        out = os.path.join(tempfile.mkdtemp(prefix="sf-windows-exe-"), "selftest.txt")
        log, code = watch([exe, f"--selftest={out}"], 40)
        ok = judge("exe", log)
        result = Path(out).read_text(encoding="utf-8") if os.path.exists(out) else ""
        print(f"  exe self-test exit={code} {'RESULT=OK' if 'RESULT=OK' in result else 'self-test did not pass'}")
        return 0 if ok and "RESULT=OK" in result else 1
    mode = args[0] if args else "signed-in"
    log, _ = watch([sys.executable, "-u", str(Path(__file__).resolve()), "--child", mode], 7)
    return 0 if judge(mode, log) else 1


if __name__ == "__main__":
    sys.exit(main_())
