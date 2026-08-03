"""Auto-update: the widget should pick up a new release itself.

The install is per-user (Inno PrivilegesRequired=lowest -> %LOCALAPPDATA%\\Programs),
so a silent install needs no UAC prompt. A running exe can't overwrite itself, so the
handoff goes through a detached helper. Everything here is best-effort by design: a
failed update must leave the agent working, never stuck.
"""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

import main


# ── version comparison ──────────────────────────────────────────────────────
@pytest.mark.parametrize("latest,current,expected", [
    ("2.4.2", "2.4.1", True),
    ("2.4.10", "2.4.9", True),      # numeric, not string ("10" < "9" as text)
    ("2.5", "2.4.9", True),
    ("3.0.0", "2.9.9", True),
    ("2.4.1", "2.4.1", False),      # same build -> no update
    ("2.4.0", "2.4.1", False),      # never downgrade
    ("2.4", "2.4.0", False),        # 2.4 == 2.4.0
    ("2.4.0", "2.4", False),
    ("", "2.4.1", False),           # empty registry entry
    ("v2.4.2", "2.4.1", True),      # tolerate a leading v
    ("garbage", "2.4.1", False),
])
def test_is_newer_version(latest, current, expected):
    assert main.is_newer_version(latest, current) is expected


def test_app_version_matches_the_installer():
    """APP_VERSION drives the update check; if it drifts from the installer's
    AppVersion the widget would reinstall the same build forever (or never update)."""
    iss = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(main.__file__))),
                       "live-widget-app", "installer", "installer.iss")
    if not os.path.exists(iss):
        iss = os.path.join(os.path.dirname(os.path.abspath(main.__file__)),
                           "installer", "installer.iss")
    if not os.path.exists(iss):
        pytest.skip("installer.iss not present")
    with open(iss, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    import re
    m = re.search(r'#define\s+AppVersion\s+"([^"]+)"', text)
    assert m, "AppVersion not found in installer.iss"
    assert m.group(1) == main.APP_VERSION, (
        f"installer.iss AppVersion {m.group(1)!r} != main.APP_VERSION {main.APP_VERSION!r}")


# ── download URL safety ─────────────────────────────────────────────────────
@pytest.mark.parametrize("url,ok", [
    ("https://example.com/SparkFlowSetup.exe", True),
    ("http://192.168.80.52:8080/dl/SparkFlowSetup.exe", True),
    ("https://example.com/setup.exe?v=2", True),
    ("https://example.com/notes.txt", False),
    ("file:///C:/evil.exe", False),          # local file
    ("\\\\attacker\\share\\evil.exe", False),  # UNC path
    ("ftp://example.com/x.exe", False),
    ("", False),
    (None, False),
])
def test_is_safe_installer_url(url, ok):
    assert main.is_safe_installer_url(url) is ok


# ── the handoff script ──────────────────────────────────────────────────────
def test_updater_script_installs_silently_and_relaunches():
    s = main.build_updater_script(r"C:\tmp\Setup.exe", r"C:\app\SparkFlow.exe", False)
    assert "/VERYSILENT" in s and "/SUPPRESSMSGBOXES" in s and "/NORESTART" in s
    assert r"C:\tmp\Setup.exe" in s
    assert r'start "" "C:\app\SparkFlow.exe"' in s
    assert "--minimized" not in s
    assert 'del "C:\\tmp\\Setup.exe"' in s, "the installer must be cleaned up"
    assert 'del "%~f0"' in s, "the helper must delete itself"


def test_updater_script_preserves_minimized_start():
    s = main.build_updater_script("S.exe", "A.exe", True)
    assert 'start "" "A.exe" --minimized' in s


def test_updater_script_waits_before_installing():
    """It must give the widget time to exit — you can't overwrite a running exe."""
    s = main.build_updater_script("S.exe", "A.exe", False)
    assert "ping 127.0.0.1" in s
    assert s.index("ping") < s.index("S.exe"), "the wait has to come first"


# ── the worker ──────────────────────────────────────────────────────────────
class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def _run(monkeypatch, payload, current="2.4.1"):
    monkeypatch.setattr(main, "api_get_version", lambda base: payload)
    w = main.UpdateCheckWorker("http://x", current)
    seen = {"ready": [], "none": 0}
    w.update_ready.connect(lambda p, v: seen["ready"].append((p, v)))
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    return seen


def test_no_update_when_already_current(monkeypatch):
    seen = _run(monkeypatch, {"version": "2.4.1", "windows_url": "https://x/S.exe"})
    assert seen["none"] == 1 and not seen["ready"]


def test_no_update_when_registry_url_is_unusable(monkeypatch):
    seen = _run(monkeypatch, {"version": "9.9.9", "windows_url": "https://x/readme.txt"})
    assert seen["none"] == 1 and not seen["ready"]


def test_version_endpoint_failure_is_silent(monkeypatch):
    monkeypatch.setattr(main, "api_get_version",
                        lambda base: (_ for _ in ()).throw(main.BackendError("down")))
    w = main.UpdateCheckWorker("http://x", "2.4.1")
    seen = {"ready": [], "none": 0}
    w.update_ready.connect(lambda p, v: seen["ready"].append((p, v)))
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    assert seen["none"] == 1, "a failed check must never surface to the agent"


def test_rejects_a_download_that_is_not_an_executable(monkeypatch, tmp_path):
    """An HTML error page saved as .exe would brick the update — refuse it."""
    monkeypatch.setattr(main, "api_get_version",
                        lambda base: {"version": "9.9.9", "windows_url": "https://x/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Stream:
        status_code = 200
        def iter_content(self, chunk_size=0):
            yield b"<html>404 not found</html>"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Stream())
    w = main.UpdateCheckWorker("http://x", "2.4.1")
    seen = {"ready": [], "none": 0}
    w.update_ready.connect(lambda p, v: seen["ready"].append((p, v)))
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    assert seen["none"] == 1 and not seen["ready"]


def test_accepts_a_real_windows_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "api_get_version",
                        lambda base: {"version": "9.9.9", "windows_url": "https://x/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Stream:
        status_code = 200
        def iter_content(self, chunk_size=0):
            yield b"MZ" + b"\x00" * 100
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Stream())
    w = main.UpdateCheckWorker("http://x", "2.4.1")
    seen = {"ready": [], "none": 0}
    w.update_ready.connect(lambda p, v: seen["ready"].append((p, v)))
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    assert len(seen["ready"]) == 1
    path, version = seen["ready"][0]
    assert version == "9.9.9" and os.path.exists(path)


def test_oversized_download_is_aborted(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "api_get_version",
                        lambda base: {"version": "9.9.9", "windows_url": "https://x/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Stream:
        status_code = 200
        def iter_content(self, chunk_size=0):
            for _ in range(5):
                yield b"M" * (1024 * 1024)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Stream())
    w = main.UpdateCheckWorker("http://x", "2.4.1")
    w.MAX_BYTES = 2 * 1024 * 1024
    seen = {"ready": [], "none": 0}
    w.update_ready.connect(lambda p, v: seen["ready"].append((p, v)))
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    assert seen["none"] == 1 and not seen["ready"]
