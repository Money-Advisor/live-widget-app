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
     self-test passes, and the real widget's registry is identical,
  4. uninstalled, and checked that nothing of it is left.
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


def real_fingerprint():
    real_dir = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Spark Flow"))
    exe = real_dir / "SparkFlow.exe"
    return {
        "settings": reg_tree_hash(r"Software\Spark Flow"),
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


def updater_command_line(installer):
    """The install line exactly as the auto-updater writes it."""
    import main
    script = main.build_updater_script(str(installer), r"C:\x\SparkFlow.exe", True)
    line = next(ln for ln in script.splitlines() if "/VERYSILENT" in ln)
    m = re.match(r'"([^"]+)"\s+(.*)$', line.strip())
    return [m.group(1)] + m.group(2).split()


def files_under(root):
    return {str(p.relative_to(root)).lower() for p in root.rglob("*") if p.is_file()}


def main_():
    old_dist, old_iss = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    new_dist = APP / "dist" / "SparkFlow"
    new_iss = APP / "installer" / "installer.iss"
    assert (old_dist / "SparkFlow.exe").exists() and (new_dist / "SparkFlow.exe").exists()
    if TEST_KEY in uninstall_entries():
        print("ABORT: a previous test install is still registered - uninstall it first")
        return 2

    work = Path(tempfile.mkdtemp(prefix="sf-upgrade-"))
    app_dir = work / "app"
    before = real_fingerprint()

    old_exe = compile_iss(test_iss(old_iss.read_text(encoding="utf-8"), old_iss.parent, old_dist, work, "old"),
                          work, "old")
    new_exe = compile_iss(test_iss(new_iss.read_text(encoding="utf-8"), new_iss.parent, new_dist, work, "new"),
                          work, "new")
    old_ver = re.search(r'#define AppVersion "([^"]+)"', old_iss.read_text(encoding="utf-8")).group(1)
    new_ver = re.search(r'#define AppVersion "([^"]+)"', new_iss.read_text(encoding="utf-8")).group(1)
    print(f"old {old_ver} -> new {new_ver}; test folder {app_dir}")

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

        # 2. the new installer, run the way the auto-updater runs it
        cmd = updater_command_line(new_exe)
        print("updater runs:", " ".join(cmd[1:]))
        r = subprocess.run(cmd, timeout=900)
        check("the new installer runs silently, as the updater runs it", r.returncode == 0, f"exit {r.returncode}")

        # 3. what an agent's PC now has
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
              reg_value(UNINSTALL + "\\" + TEST_KEY, "DisplayName").startswith("Spark Flow"))
        out = work / "selftest.txt"
        r = subprocess.run([str(exe), f"--selftest={out}"], timeout=180)
        text = out.read_text(encoding="utf-8") if out.exists() else ""
        check("the INSTALLED exe passes its self-test", r.returncode == 0 and "RESULT=OK" in text
              and f"version={new_ver}" in text, text.replace("\n", " ")[:160])
    finally:
        # 4. uninstall, and leave nothing
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
    after = real_fingerprint()
    check("the REAL widget's settings, auto-start and install are untouched", before == after,
          "" if before == after else f"{before} -> {after}")
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main_())
