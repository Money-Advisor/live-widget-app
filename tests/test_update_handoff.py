# -*- coding: utf-8 -*-
"""Updates that land (2.9.64, W1 - Bilal, 30 Oct 2026).

The update helper waited a fixed ~3s before running the silent installer. Since
2.9.59 the widget has a Qt WebEngine process beside it, and the widget or that
process could still hold its files when the installer replaced them, so the
install failed with nothing said; after two tries a version was blocked for good
and agents stayed on 2.9.59-2.9.62. Now the helper waits until nothing runs from
the widget's own folder (60s at most), the installer writes a log beside
widget.log, the widget says on its next start whether the update took, and a
version is tried twice a DAY rather than twice ever.

The helper is also RUN here, for real, against a stand-in widget process in a
temp folder: the installer must start only after that process has gone.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QSettings

import main

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PING = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"


# ── what the helper says ────────────────────────────────────────────────────
def test_it_waits_for_the_widgets_own_processes_before_installing():
    s = main.build_updater_script(r"C:\tmp\Setup.exe", r"C:\Users\a\Programs\Spark Flow\SparkFlow.exe", True)
    lines = s.split("\r\n")
    wait = next(i for i, ln in enumerate(lines) if ln.startswith("powershell"))
    install = next(i for i, ln in enumerate(lines) if "/VERYSILENT" in ln)
    first_ping = next(i for i, ln in enumerate(lines) if ln.startswith("ping"))
    assert first_ping < wait < install, "settle, wait for the processes, then install"
    assert r"$d=@('C:\Users\a\Programs\Spark Flow\')" in lines[wait], "its own folder, ending in a backslash"
    assert f"AddSeconds({main.UPDATE_WAIT_SECONDS})" in lines[wait]
    assert main.UPDATE_WAIT_SECONDS == 60


def test_the_installer_writes_its_log():
    s = main.build_updater_script(r"C:\tmp\Setup.exe", r"C:\app\SparkFlow.exe", False,
                                  r"C:\Users\a\AppData\Local\Spark Flow\logs\update-install.log")
    line = next(ln for ln in s.split("\r\n") if "/VERYSILENT" in ln)
    assert line.endswith(r' /LOG="C:\Users\a\AppData\Local\Spark Flow\logs\update-install.log"')
    assert "/CLOSEAPPLICATIONS" in line, "the flags as before"


def test_without_a_log_the_install_line_is_as_before():
    s = main.build_updater_script(r"C:\tmp\Setup.exe", r"C:\app\SparkFlow.exe", False)
    assert '"C:\\tmp\\Setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS\r\n' in s


def test_the_log_sits_beside_widget_log():
    assert main.update_log_path() == main.log_path().with_name("update-install.log")


def test_a_folder_with_an_apostrophe_or_percent_is_quoted():
    s = main.build_updater_script(r"C:\tmp\Setup.exe", r"C:\Users\O'Brien\100% app\SparkFlow.exe", False,
                                  r"C:\Users\O'Brien\100% logs\update-install.log")
    wait = next(ln for ln in s.split("\r\n") if ln.startswith("powershell"))
    assert r"$d=@('C:\Users\O''Brien\100%% app\')" in wait, "PowerShell doubles ', cmd doubles %"
    assert '/LOG="' + r"C:\Users\O'Brien\100%% logs\update-install.log" + '"' in s, "cmd doubles %"


def test_with_no_folder_there_is_nothing_to_wait_for():
    s = main.build_updater_script("S.exe", "A.exe", False)
    assert "powershell" not in s


def test_the_relaunch_and_clean_up_are_unchanged():
    s = main.build_updater_script(r"C:\tmp\Setup.exe", r"C:\app\SparkFlow.exe", True, r"C:\l\u.log")
    assert s.count('start "" "C:\\app\\SparkFlow.exe" --minimized') == 2
    assert s.index("/VERYSILENT") < s.index('start ""') < s.index('del "%~f0"')


def test_the_widget_hands_the_installer_its_log(tmp_path, monkeypatch):
    """_apply_pending_update: the helper it writes logs the install beside widget.log,
    whose folder it makes if need be."""
    monkeypatch.setattr(main, "log_path", lambda: tmp_path / "logs" / "widget.log")
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    started = []
    monkeypatch.setattr(main.subprocess, "Popen", lambda *a, **k: started.append(a[0]))
    quit_ = []
    fake = SimpleNamespace(_pending_update=(r"C:\t\Setup.exe", "2.9.65"), _recording=False, _starting=False,
                           _quit=lambda: quit_.append(1))
    main.MainWindow._apply_pending_update(fake)
    script = (tmp_path / "sparkflow_update.cmd").read_text(encoding="utf-8")
    assert f'/LOG="{tmp_path / "logs" / "update-install.log"}"' in script
    assert (tmp_path / "logs").is_dir()
    assert started and quit_ == [1]


# ── what the helper does: run for real ──────────────────────────────────────
def _stand_in(folder: Path, seconds: int, launch_as: str | None = None) -> subprocess.Popen:
    """A process started from `folder`, alive for about `seconds` (a copy of ping).
    `launch_as`: the folder's name to start it by (an 8.3 name, say)."""
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "SparkFlow.exe"
    shutil.copy(PING, exe)
    path = str(Path(launch_as) / "SparkFlow.exe") if launch_as else str(exe)
    return subprocess.Popen([path, "-n", str(seconds + 1), "127.0.0.1"], stdout=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)


def _run_until_installed(tmp: Path, exe: Path, proc: subprocess.Popen, drop_wait=False, limit=60):
    """Run the helper's lines up to the install (never the relaunch); the "installer"
    writes a file. -> (seconds until it ran, seconds until the stand-in exited)."""
    setup = tmp / "setup" / "Setup.cmd"
    setup.parent.mkdir(parents=True, exist_ok=True)
    marker = tmp / "installed.txt"
    setup.write_text(f'@echo off\r\necho ran> "{marker}"\r\n', encoding="utf-8")
    script = main.build_updater_script(str(setup), str(exe), True, str(tmp / "update-install.log"))
    lines = script.split("\r\n")
    install = next(i for i, ln in enumerate(lines) if "/VERYSILENT" in ln)
    kept = [ln for ln in lines[:install + 1] if not (drop_wait and ln.startswith("powershell"))]
    helper = tmp / "handoff.cmd"
    helper.write_text("\r\n".join(kept) + "\r\n", encoding="utf-8")
    t0 = time.monotonic()
    subprocess.Popen(["cmd", "/c", str(helper)], creationflags=NO_WINDOW)
    ran = exited = None
    while time.monotonic() - t0 < limit and (ran is None or exited is None):
        now = time.monotonic() - t0
        if exited is None and proc.poll() is not None:
            exited = now
        if ran is None and marker.exists():
            ran = now
        time.sleep(0.05)
    if proc.poll() is None:
        proc.kill()
    return ran, exited


@pytest.mark.skipif(os.name != "nt" or not PING.exists(), reason="Windows only")
def test_the_installer_runs_only_once_the_widgets_process_has_gone(tmp_path):
    proc = _stand_in(tmp_path / "Spark Flow", seconds=7)
    ran, exited = _run_until_installed(tmp_path, tmp_path / "Spark Flow" / "SparkFlow.exe", proc)
    assert ran is not None and exited is not None
    assert ran >= exited, f"the installer ran at {ran:.1f}s, the widget's process ended at {exited:.1f}s"


@pytest.mark.skipif(os.name != "nt" or not PING.exists(), reason="Windows only")
def test_without_the_wait_it_ran_while_the_process_was_still_there(tmp_path):
    """The fault this fixes, shown: the fixed ~3s alone starts the installer over a
    folder still in use."""
    proc = _stand_in(tmp_path / "Spark Flow", seconds=7)
    ran, exited = _run_until_installed(tmp_path, tmp_path / "Spark Flow" / "SparkFlow.exe", proc,
                                       drop_wait=True)
    assert ran is not None and exited is not None and ran < exited


@pytest.mark.skipif(os.name != "nt" or not PING.exists(), reason="Windows only")
def test_it_gives_up_waiting_after_its_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "UPDATE_WAIT_SECONDS", 2)
    proc = _stand_in(tmp_path / "Spark Flow", seconds=30)
    ran, exited = _run_until_installed(tmp_path, tmp_path / "Spark Flow" / "SparkFlow.exe", proc, limit=20)
    assert ran is not None and ran < 15, "installs anyway once the wait is up"


@pytest.mark.skipif(os.name != "nt" or not PING.exists(), reason="Windows only")
def test_a_copy_running_from_another_folder_is_not_waited_for(tmp_path):
    proc = _stand_in(tmp_path / "Somewhere else", seconds=20)
    (tmp_path / "Spark Flow").mkdir()
    ran, _ = _run_until_installed(tmp_path, tmp_path / "Spark Flow" / "SparkFlow.exe", proc, limit=20)
    assert ran is not None and ran < 12


def _short(path: Path) -> str:
    """The 8.3 name Windows can also give a folder (C:\\Users\\FASEEH~1.IQB...)."""
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024)
    return buf.value if 0 < n < 1024 else str(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_a_short_folder_name_is_waited_for_by_its_full_name(tmp_path):
    """Found 30 Oct by focus_dev/upgrade_test.py: given the 8.3 name, the wait looked
    for processes under a path no running program reports."""
    folder = tmp_path / "Spark Flow Long Folder"
    folder.mkdir()
    short = _short(folder)
    if short == str(folder):
        pytest.skip("this volume gives no 8.3 names")
    s = main.build_updater_script(r"C:\t\Setup.exe", short + r"\SparkFlow.exe", False)
    wait = next(ln for ln in s.split("\r\n") if ln.startswith("powershell"))
    assert "'" + os.path.realpath(folder).replace("'", "''") + "\\'" in wait, "the folder in full"
    assert "'" + short.replace("'", "''") + "\\'" in wait, "and by its 8.3 name"
    assert 'start "" "' + short + '\\SparkFlow.exe"' in s, "the relaunch keeps the path it was given"


@pytest.mark.skipif(os.name != "nt" or not PING.exists(), reason="Windows only")
def test_given_a_short_folder_name_it_still_waits(tmp_path):
    folder = tmp_path / "Spark Flow Long Folder"
    proc = _stand_in(folder, seconds=7)
    short = _short(folder)
    if short == str(folder):
        pytest.skip("this volume gives no 8.3 names")
    ran, exited = _run_until_installed(tmp_path, Path(short) / "SparkFlow.exe", proc)
    assert ran is not None and exited is not None and ran >= exited


@pytest.mark.skipif(os.name != "nt" or not PING.exists(), reason="Windows only")
def test_a_process_started_by_the_8_3_name_is_waited_for(tmp_path):
    """Windows names a process by the path it was started with: one started by the
    8.3 name runs from a path that does not start with the folder's full name."""
    folder = tmp_path / "Spark Flow Long Folder"
    folder.mkdir()
    short = _short(folder)
    if short == str(folder):
        pytest.skip("this volume gives no 8.3 names")
    proc = _stand_in(folder, seconds=7, launch_as=short)
    ran, exited = _run_until_installed(tmp_path, folder / "SparkFlow.exe", proc)
    assert ran is not None and exited is not None and ran >= exited


@pytest.mark.skipif(os.name != "nt" or not PING.exists(), reason="Windows only")
def test_an_apostrophe_and_percent_in_the_folder_still_wait(tmp_path):
    folder = tmp_path / "O'Brien 100% Spark Flow"
    proc = _stand_in(folder, seconds=7)
    ran, exited = _run_until_installed(tmp_path, folder / "SparkFlow.exe", proc)
    assert ran is not None and exited is not None and ran >= exited


# ── twice a day, not twice ever ─────────────────────────────────────────────
def test_tries_count_for_their_day_only():
    a = {"2.9.64": {"tries": 2, "day": "2026-10-30"}}
    assert main.update_tries_today(a, "2.9.64", "2026-10-30") == 2
    assert main.update_tries_today(a, "2.9.64", "2026-10-31") == 0
    assert main.update_tries_today(a, "2.9.65", "2026-10-30") == 0
    assert main.update_tries_today({}, "2.9.64", "2026-10-30") == 0


def test_the_old_count_no_longer_blocks():
    """Before 2.9.64 a bare number, no day: that block was for good."""
    assert main.update_tries_today({"2.9.64": 2}, "2.9.64", "2026-10-30") == 0
    assert main.update_tries_today({"2.9.64": {"tries": "x", "day": "2026-10-30"}}, "2.9.64", "2026-10-30") == 0


def _fake(tmp_path, attempts):
    s = QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat)
    applied = []
    fake = SimpleNamespace(_update_attempts=attempts, _settings=s, _pending_update=None)
    fake._apply_pending_update = lambda: applied.append(fake._pending_update)
    return fake, applied


def test_two_tries_a_day_then_tomorrow(tmp_path, monkeypatch, capsys):
    import datetime as dt

    class Day(dt.date):
        current = dt.date(2026, 10, 30)

        @classmethod
        def today(cls):
            return cls.current
    monkeypatch.setattr(main.datetime, "date", Day)
    fake, applied = _fake(tmp_path, {})
    for _ in range(3):
        main.MainWindow._on_update_ready(fake, r"C:\t\Setup.exe", "2.9.65")
    assert len(applied) == 2, "two tries on the day"
    assert json.loads(fake._settings.value("update/attempts")) == {"2.9.65": {"tries": 2, "day": "2026-10-30"}}
    assert "trying again tomorrow" in capsys.readouterr().out
    Day.current = dt.date(2026, 10, 31)
    main.MainWindow._on_update_ready(fake, r"C:\t\Setup.exe", "2.9.65")
    assert len(applied) == 3, "the next day it tries again"
    assert fake._update_attempts == {"2.9.65": {"tries": 1, "day": "2026-10-31"}}


def test_a_widget_blocked_before_2_9_64_tries_again(tmp_path):
    fake, applied = _fake(tmp_path, {"2.9.65": 2})
    main.MainWindow._on_update_ready(fake, r"C:\t\Setup.exe", "2.9.65")
    assert applied == [(r"C:\t\Setup.exe", "2.9.65")]


# ── the next start says whether it took ─────────────────────────────────────
def test_nothing_to_say_with_no_try():
    assert main.update_outcome({}, "2.9.64", Path("x")) is None


def test_it_says_when_the_update_installed():
    assert main.update_outcome({"2.9.64": {"tries": 1, "day": "2026-10-30"}}, "2.9.64",
                               Path("x")) == "[update] now on 2.9.64 - the update installed"


def test_it_says_why_an_update_did_not_install(tmp_path):
    log = tmp_path / "update-install.log"
    log.write_text("2026-10-30 10:00:01.000   Setup version: Inno Setup 6\n"
                   "2026-10-30 10:00:02.000   Deleting directory: C:\\x\\_internal\n"
                   "2026-10-30 10:00:02.100   Failed to delete the directory (5).\n"
                   "2026-10-30 10:00:03.000   Got EAbort exception.\n", encoding="utf-8")
    msg = main.update_outcome({"2.9.65": {"tries": 1, "day": "2026-10-30"}}, "2.9.64", log)
    assert msg.startswith("[update] 2.9.65 did not install (last tried 2026-10-30); still on 2.9.64")
    assert "Failed to delete the directory (5)." in msg and "Got EAbort exception." in msg
    assert "Setup version" not in msg, "the lines that say why, not the whole log"


def test_it_says_so_when_there_is_no_installer_log(tmp_path):
    msg = main.update_outcome({"2.9.65": 2}, "2.9.64", tmp_path / "missing.log")
    assert "did not install (last tried before 2.9.64)" in msg and "no installer log" in msg


def test_an_older_try_is_not_reported():
    assert main.update_outcome({"2.9.60": {"tries": 1, "day": "2026-10-20"}}, "2.9.64", Path("x")) is None


def test_the_try_is_forgotten_once_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)

    class Worker:
        def __init__(self, *a):
            self.update_ready = self.no_update = SimpleNamespace(connect=lambda *a: None)

        def start(self):
            pass
    monkeypatch.setattr(main, "UpdateCheckWorker", Worker)
    s = QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat)
    s.setValue("update/attempts", json.dumps({main.APP_VERSION: {"tries": 1, "day": "2026-10-30"}}))
    fake = SimpleNamespace(_update_checked=False, _recording=False, _starting=False, _settings=s,
                           _api_base="http://127.0.0.1:9", _on_update_ready=lambda *a: None)
    main.MainWindow._maybe_check_for_update(fake)
    assert f"now on {main.APP_VERSION}" in capsys.readouterr().out
    assert fake._update_attempts == {} and s.value("update/attempts") is None
