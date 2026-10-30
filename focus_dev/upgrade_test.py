# -*- coding: utf-8 -*-
r"""Prove the new SparkFlowSetup.exe upgrades an OLD Spark Flow in place.

    python focus_dev/upgrade_test.py <old_dist_dir> <old_installer.iss>

<old_dist_dir> is an old widget's dist\SparkFlow folder (e.g. 2.9.58 built
from main) and <old_installer.iss> that version's installer script. Both
installers are compiled from their REAL scripts with only the identity
swapped for a throwaway one (AppId, name, Run value) - so the real widget
installed on this PC, its auto-start entry and its settings are never touched.

Then, exactly as an agent's PC would see it:
  1. the old widget is installed silently with auto-start ticked,
  2. the new installer is run with the auto-updater's OWN command line
     (taken from main.build_updater_script),
  3. checked: same folder, new exe, no old runtime files left behind,
     auto-start kept, ONE install entry at the new version, the installed exe's
     self-test passes, and the real widget's registry is identical (bar its
     sign-in token and server config, if the real widget is running: it
     refreshes those itself, the token about hourly),
  4. uninstalled, and checked that nothing of it is left.

2.9.64 (Bilal, 30 Oct 2026): three upgrades, one after another, each from a
fresh old install:
  A. nothing running, the new widget's update helper (as before);
  B. the OLD widget OPEN while it updates, with the update helper every widget
     up to 2.9.63 runs (a fixed ~3s, then the installer) - what every agent's
     PC does next. Before 2.9.64 the installer could start while the widget's
     Qt WebEngine process still held _internal, and fail with nothing said;
  C. the old widget open, with the new helper (it waits for those processes).
The old widget is "open" in its own --selftest mode: the real window, page and
Qt WebEngine processes on throwaway settings (never signed in, no server).

    python focus_dev/upgrade_test.py <old_dist_dir> <old_installer.iss> [--no-installer-wait]

--no-installer-wait compiles the new installer WITHOUT its PrepareToInstall
wait (the revert check for B). UPGRADE_ONLY=B runs just that upgrade.
UPGRADE_SHORT_PATHS=1 runs from %TEMP% as given, often part 8.3: then only the
installer's wait can find the widget's processes (B), not the helper's (C).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ISCC = next(p for p in [Path(os.path.expandvars(r"%USERPROFILE%\tools\InnoSetup6\ISCC.exe")),
                        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
                        Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"))]
            if p.exists())
REAL_APPID = "{{8E2F1B40-7C2A-4E91-9D3A-NEXCALL00001}"
TEST_APPID = "{{8E2F1B40-7C2A-4E91-9D3A-UPGRADETEST1}"
TEST_KEY = "{8E2F1B40-7C2A-4E91-9D3A-UPGRADETEST1}_is1"
TEST_RUN = "SparkFlowUpgradeTest"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def reg_value(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_tree_values(path):
    """Every value under an HKCU key, its subkeys' too: "subkey|name" -> a fingerprint
    of its type and data (never the data itself - the sign-in token is among them)."""
    out = {}

    def walk(p):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, p)
        except OSError:
            out[p + "|"] = "<missing>"
            return
        with k:
            i = 0
            while True:
                try:
                    n, v, t = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[p[len(path):].lstrip("\\") + "|" + n] = hashlib.sha1(f"{t}|{v!r}".encode("utf-8", "replace")).hexdigest()
                i += 1
            subs, i = [], 0
            while True:
                try:
                    subs.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
        for s in subs:
            walk(p + "\\" + s)
    walk(path)
    return out


def reg_tree_hash(path):
    """A fingerprint of a whole HKCU key (values and subkeys)."""
    h = hashlib.sha1()

    def walk(p):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, p)
        except OSError:
            h.update(b"<missing>")
            return
        with k:
            i = 0
            while True:
                try:
                    n, v, t = winreg.EnumValue(k, i)
                except OSError:
                    break
                h.update(f"{p}|{n}|{t}|{v!r}".encode("utf-8", "replace"))
                i += 1
            subs, i = [], 0
            while True:
                try:
                    subs.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
        for s in sorted(subs):
            walk(p + "\\" + s)
    walk(path)
    return h.hexdigest()


def uninstall_entries():
    out = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL) as k:
        i = 0
        while True:
            try:
                out.append(winreg.EnumKey(k, i))
            except OSError:
                return out
            i += 1


# Values the real widget rewrites on its own while it runs (main.py: the token
# refresh, the config fetch).
REAL_WIDGET_REFRESHES = {"auth/token", "auth/refresh_token", "auth/user", "config/json", "config/etag"}


def setting_name(key):
    """reg_tree_values' "Widget\\auth|token" as the widget names it: "auth/token"."""
    sub, name = key.split("|", 1)
    return "/".join(sub.split("\\")[1:] + [name])


def real_widget_running():
    real = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Spark Flow").lower() + "\\"
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "Get-Process SparkFlow -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
                       capture_output=True, text=True, timeout=60)
    return any(ln.strip().lower().startswith(real) for ln in r.stdout.splitlines())


def real_fingerprint():
    real_dir = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Spark Flow"))
    exe = real_dir / "SparkFlow.exe"
    return {
        "settings": reg_tree_values(r"Software\Spark Flow"),
        "run": reg_value(RUN_KEY, "SparkFlow"),
        "real_install": reg_tree_hash(UNINSTALL + "\\" + REAL_APPID[1:] + "_is1"),
        "real_exe": (exe.stat().st_size, exe.stat().st_mtime) if exe.exists() else None,
    }


def test_iss(src_text, iss_dir, dist, out_dir, out_name):
    """The real script with only its identity and paths changed."""
    t = src_text
    for a, b in [(f"AppId={REAL_APPID}", f"AppId={TEST_APPID}"),
                 ('ValueName: "SparkFlow"', f'ValueName: "{TEST_RUN}"'),
                 ('#define AppName "Spark Flow"', '#define AppName "Spark Flow Upgrade Test"')]:
        assert t.count(a) == 1, f"{a!r} not found once in the installer script"
        t = t.replace(a, b)
    for pattern, repl in [(r"(?m)^OutputDir=.*$", f"OutputDir={out_dir}"),
                          (r"(?m)^OutputBaseFilename=.*$", f"OutputBaseFilename={out_name}"),
                          (r"(?m)^LicenseFile=.*$", f"LicenseFile={iss_dir / 'LICENSE.txt'}"),
                          (r"(?m)^SetupIconFile=.*$", f"SetupIconFile={APP / 'assets' / 'icon.ico'}"),
                          (r'(?m)^Source: "[^"]+"', f'Source: "{dist}' + '\\*"')]:
        t, n = re.subn(pattern, lambda _m, r=repl: r, t)    # a function: paths hold backslashes
        assert n == 1, pattern
    return t


def compile_iss(text, work, name):
    path = work / f"{name}.iss"
    path.write_text(text, encoding="utf-8-sig")
    r = subprocess.run([str(ISCC), "/Q", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
    exe = work / f"{name}.exe"
    assert r.returncode == 0 and exe.exists(), f"ISCC failed for {name}"
    return exe


# What every widget up to 2.9.63 runs to update (its main.build_updater_script, up
# to the install): a fixed ~3s, then the installer. /LOG is added so the test can
# read what the installer did; it only writes a log.
OLD_HELPER = ('@echo off\r\n'
              'ping 127.0.0.1 -n 4 >nul\r\n'
              '"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /LOG="{log}"\r\n')


def helper_script(kind, installer, exe, log):
    """The update helper up to and including the install - never the relaunch,
    which would start the installed widget for real."""
    if kind == "old":
        return OLD_HELPER.format(installer=installer, log=log)
    import main
    lines = main.build_updater_script(str(installer), str(exe), True, str(log)).split("\r\n")
    install = next(i for i, ln in enumerate(lines) if "/VERYSILENT" in ln)
    return "\r\n".join(lines[:install + 1]) + "\r\n"


def running_from(folder):
    """Names of the processes started from `folder` (this test's install only), by the
    folder's name as given or in full."""
    forms = {str(folder).rstrip("\\") + "\\", os.path.realpath(folder).rstrip("\\") + "\\"}
    d = ",".join("'" + f.replace("'", "''") + "'" for f in forms)
    ps = (f"$d=@({d}); Get-Process -ErrorAction SilentlyContinue | Where-Object {{ try {{ $p = $_.Path; $p -and "
          "($d | Where-Object { $p.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }) } catch { $false } } "
          "| ForEach-Object { $_.Name }")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, timeout=60)
    return [n.strip() for n in r.stdout.splitlines() if n.strip()]


def watch_for(folder, name, seconds):
    """A watcher for a `name` process started from `folder`, already looking (every
    100 ms, for `seconds`) when this returns; "seen" in its output if one appeared. Started
    BEFORE what it watches for: the old self-test's Qt WebEngine process can live under
    a second, less than a fresh PowerShell per look takes to start."""
    forms = {str(folder).rstrip("\\") + "\\", os.path.realpath(folder).rstrip("\\") + "\\"}
    d = ",".join("'" + f.replace("'", "''") + "'" for f in forms)
    ps = (f"$d=@({d}); [Console]::Out.WriteLine('ready'); [Console]::Out.Flush(); "
          f"$t=(Get-Date).AddSeconds({int(seconds)}); while ((Get-Date) -lt $t) {{ "
          f"if (Get-Process -Name '{name}' -ErrorAction SilentlyContinue | Where-Object {{ try {{ $p = $_.Path; $p -and "
          "($d | Where-Object { $p.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }) } catch { $false } }) "
          "{ [Console]::Out.WriteLine('seen'); exit }; Start-Sleep -Milliseconds 100 }")
    p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         stdout=subprocess.PIPE, text=True)
    p.stdout.readline()
    return p


def wait_until(cond, seconds, step=0.25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def files_under(root):
    return {str(p.relative_to(root)).lower() for p in root.rglob("*") if p.is_file()}


def upgrade(label, helper, open_old, old_exe, new_exe, new_dist, old_ver, new_ver, work):
    """One upgrade from a fresh old install, checked, then uninstalled."""
    print(f"\n=== {label}", flush=True)
    app_dir = work / f"app-{helper}{'-open' if open_old else ''}"
    log = work / f"install-{helper}{'-open' if open_old else ''}.log"
    old_proc = stand_in = None
    try:
        # 1. the old widget, as on an agent's PC (auto-start ticked, no shortcuts)
        r = subprocess.run([str(old_exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS",
                            f"/DIR={app_dir}", "/TASKS=startupicon"], timeout=600)
        check("the old widget installs", r.returncode == 0 and (app_dir / "SparkFlow.exe").exists())
        run_before = reg_value(RUN_KEY, TEST_RUN)
        check("it auto-starts at sign-in", run_before == f'"{app_dir / "SparkFlow.exe"}" --minimized', run_before)
        check("it is registered at the old version",
              reg_value(UNINSTALL + "\\" + TEST_KEY, "DisplayVersion") == old_ver)
        stale = app_dir / "_internal" / "left-by-the-old-build.txt"
        stale.write_text("stale", encoding="utf-8")
        old_exe_stat = (app_dir / "SparkFlow.exe").stat()

        # 2. the old widget OPEN, if asked: its own --selftest - the real window, page
        #    and Qt WebEngine processes, on throwaway settings (no sign-in, no server).
        #    The self-test closes itself within seconds, often before a fixed ~3s is
        #    up, so a stand-in Qt WebEngine process from the widget's own _internal
        #    (a copy of ping, ~12s) is what outlives it here - the case at fault: the
        #    widget's WebEngine process still running when the installer starts.
        if open_old:
            watcher = watch_for(app_dir, "QtWebEngineProcess", 60)
            old_proc = subprocess.Popen([str(app_dir / "SparkFlow.exe"), f"--selftest={work / ('open-' + helper + '.txt')}"])
            check("the old widget is open, its Qt WebEngine process running",
                  "seen" in watcher.communicate(timeout=120)[0])
            fake = app_dir / "_internal" / "QtWebEngineProcess.exe"
            shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE", fake)
            stand_in = subprocess.Popen([str(fake), "-n", "13", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        # 3. the update, run the way the widget runs it
        script = work / f"helper-{helper}{'-open' if open_old else ''}.cmd"
        script.write_text(helper_script(helper, new_exe, app_dir / "SparkFlow.exe", log), encoding="utf-8")
        t0 = time.monotonic()
        r = subprocess.run(["cmd", "/c", str(script)], timeout=900)
        took = time.monotonic() - t0
        check("the installer finishes without an error", r.returncode == 0, f"exit {r.returncode}, {took:.0f}s")
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        check("it wrote its log", "Installation process succeeded" in text, str(log))
        if open_old and helper == "old":
            check("the installer found the old widget still running and waited for it to exit",
                  "Waited " in text and "to exit" in text,
                  next((ln for ln in text.splitlines() if "Waited" in ln or "No widget process" in ln), "no wait line"))
        if open_old and helper == "new":
            check("the update helper waited for the old widget first: none left for the installer",
                  "No widget process running" in text,
                  next((ln for ln in text.splitlines() if "Waited" in ln or "No widget process" in ln), "no wait line"))
        if old_proc is not None:
            check("the old widget had exited by itself", old_proc.poll() is not None)
        if open_old:
            # Windows' Restart Manager, asked by Setup just before it replaces files,
            # finds anything still using them; the widget's processes must be gone.
            check("nothing of the widget's was still running when its files were replaced",
                  "found an application using one of our files" not in text,
                  next((ln.strip() for ln in text.splitlines() if "found an application" in ln), ""))

        # 4. what an agent's PC now has
        exe = app_dir / "SparkFlow.exe"
        new_stat = exe.stat()
        check("it landed in the SAME folder, over the old exe",
              exe.exists() and (new_stat.st_size, new_stat.st_mtime) != (old_exe_stat.st_size, old_exe_stat.st_mtime))
        check("the new panel is installed", (app_dir / "_internal" / "focus" / "index.html").exists())
        check("nothing of the old runtime is left behind", not stale.exists())
        installed = files_under(app_dir) - {f for f in files_under(app_dir) if f.startswith("unins")}
        shipped = files_under(new_dist)
        check("the installed files are exactly the new build", installed == shipped,
              f"extra {sorted(installed - shipped)[:3]} missing {sorted(shipped - installed)[:3]}")
        check("auto-start kept, unchanged", reg_value(RUN_KEY, TEST_RUN) == run_before)
        check("ONE install entry, now the new version",
              uninstall_entries().count(TEST_KEY) == 1
              and reg_value(UNINSTALL + "\\" + TEST_KEY, "DisplayVersion") == new_ver)
        check("still named Spark Flow (the test identity aside)",
              (reg_value(UNINSTALL + "\\" + TEST_KEY, "DisplayName") or "").startswith("Spark Flow"))
        out = work / f"selftest-{helper}{'-open' if open_old else ''}.txt"
        r = subprocess.run([str(exe), f"--selftest={out}"], timeout=180)
        st = out.read_text(encoding="utf-8") if out.exists() else ""
        check("the INSTALLED exe passes its self-test", r.returncode == 0 and "RESULT=OK" in st
              and f"version={new_ver}" in st, st.replace("\n", " ")[:160])
    finally:
        for p in (old_proc, stand_in):
            if p is not None and p.poll() is None:
                p.kill()
        # 5. uninstall, and leave nothing
        unins = app_dir / "unins000.exe"
        if unins.exists():
            subprocess.run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=600)
            for _ in range(60):                 # the uninstaller finishes in a copy of itself
                if TEST_KEY not in uninstall_entries() and not unins.exists():
                    break
                time.sleep(1)
    check("uninstall removes the install entry", TEST_KEY not in uninstall_entries())
    check("uninstall removes the auto-start entry", reg_value(RUN_KEY, TEST_RUN) is None)
    check("uninstall removes the exe", not (app_dir / "SparkFlow.exe").exists())


def main_():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    old_dist, old_iss = Path(args[0]).resolve(), Path(args[1]).resolve()
    new_dist = APP / "dist" / "SparkFlow"
    new_iss = APP / "installer" / "installer.iss"
    assert (old_dist / "SparkFlow.exe").exists() and (new_dist / "SparkFlow.exe").exists()
    if TEST_KEY in uninstall_entries():
        print("ABORT: a previous test install is still registered - uninstall it first")
        return 2

    work = Path(tempfile.mkdtemp(prefix="sf-upgrade-"))
    if not os.environ.get("UPGRADE_SHORT_PATHS"):
        # As on an agent's PC: the widget runs from its folder's full name. %TEMP% is
        # often part 8.3 (C:\Users\FASEEH~1.IQB\...), and a process started by such a
        # path is named by it; UPGRADE_SHORT_PATHS=1 keeps that, to prove the
        # installer still finds the widget's processes.
        work = work.resolve()
    before = real_fingerprint()
    new_text = new_iss.read_text(encoding="utf-8")
    if "--no-installer-wait" in sys.argv:
        # The revert check: the new installer without its PrepareToInstall wait.
        new_text = new_text[:re.search(r"(?m)^\[Code\]", new_text).start()]
        print("NOTE: the new installer is compiled WITHOUT its wait for the widget's processes")
    old_exe = compile_iss(test_iss(old_iss.read_text(encoding="utf-8"), old_iss.parent, old_dist, work, "old"),
                          work, "old")
    new_exe = compile_iss(test_iss(new_text, new_iss.parent, new_dist, work, "new"), work, "new")
    old_ver = re.search(r'#define AppVersion "([^"]+)"', old_iss.read_text(encoding="utf-8")).group(1)
    new_ver = re.search(r'#define AppVersion "([^"]+)"', new_text).group(1)
    print(f"old {old_ver} -> new {new_ver}; work folder {work}")

    only = os.environ.get("UPGRADE_ONLY", "")
    runs = [("A. nothing running, the new update helper", "new", False),
            ("B. the OLD widget OPEN, the update helper every widget up to 2.9.63 runs", "old", True),
            ("C. the old widget open, the new update helper", "new", True)]
    for label, helper, open_old in runs:
        if not only or label[0] in only:
            upgrade(label, helper, open_old, old_exe, new_exe, new_dist, old_ver, new_ver, work)

    after = real_fingerprint()
    changed = sorted(k for k in before["settings"].keys() | after["settings"].keys()
                     if before["settings"].get(k) != after["settings"].get(k))
    # The real widget, if it is running, refreshes its sign-in and its server config
    # by itself (the token about hourly); those are its writes, not this test's.
    own = [k for k in changed if setting_name(k) in REAL_WIDGET_REFRESHES] if real_widget_running() else []
    if own:
        print(f"NOTE: the running real widget refreshed {own} during the test", flush=True)
    others = [k for k in changed if k not in own]
    rest_same = {k: v for k, v in before.items() if k != "settings"} == {k: v for k, v in after.items() if k != "settings"}
    check("the REAL widget's settings, auto-start and install are untouched", not others and rest_same,
          "" if not others and rest_same else f"settings changed: {others}; "
          f"{ {k: v for k, v in before.items() if k != 'settings'} } -> { {k: v for k, v in after.items() if k != 'settings'} }")
    if all(results):
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"kept for a look: {work} (the installers' logs are install-*.log)")
    print(f"\n{sum(results)} of {len(results)} checks passed", flush=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main_())
