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
    ("https://github.com/Money-Advisor/live-widget-app/releases/download/v2.9.0/S.exe", True),
    ("https://objects.githubusercontent.com/x/S.exe", True),
    ("https://example.com/SparkFlowSetup.exe", False),   # untrusted host
    ("http://github.com/x/S.exe", False),                # trusted host but no TLS
    ("https://github.com/x/notes.txt", False),
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
    seen = _run(monkeypatch, {"version": "2.4.1", "windows_url": "https://github.com/o/r/S.exe"})
    assert seen["none"] == 1 and not seen["ready"]


def test_no_update_when_registry_url_is_unusable(monkeypatch):
    seen = _run(monkeypatch, {"version": "9.9.9", "windows_url": "https://github.com/o/r/readme.txt"})
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
                        lambda base: {"version": "9.9.9", "windows_url": "https://github.com/o/r/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Stream:
        status_code = 200
        url = "https://github.com/o/r/S.exe"
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
                        lambda base: {"version": "9.9.9", "windows_url": "https://github.com/o/r/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Stream:
        status_code = 200
        url = "https://github.com/o/r/S.exe"
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
                        lambda base: {"version": "9.9.9", "windows_url": "https://github.com/o/r/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Stream:
        status_code = 200
        url = "https://github.com/o/r/S.exe"
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


# ── download origin (the reviewer's critical finding) ───────────────────────
def test_installer_must_come_from_the_backend_host():
    """/api/version is plaintext http on the LAN today, so anyone who can answer it
    could otherwise point us at any .exe — which we then EXECUTE."""
    api = "http://192.168.80.52:8080"
    assert main.is_safe_installer_url("http://192.168.80.52:8080/dl/S.exe", api) is True
    assert main.is_safe_installer_url("https://192.168.80.52:8080/dl/S.exe", api) is True
    assert main.is_safe_installer_url("http://evil.example.com/S.exe", api) is False
    assert main.is_safe_installer_url("http://192.168.80.53:8080/S.exe", api) is False
    # Releases live on GitHub, so that host is trusted too — but only over HTTPS.
    assert main.is_safe_installer_url("https://github.com/o/r/releases/download/v1/S.exe", api) is True
    assert main.is_safe_installer_url("http://github.com/o/r/S.exe", api) is False
    assert main.is_safe_installer_url("https://github.com.evil.net/S.exe", api) is False
    # A different PORT on the same machine is fine (nginx may serve downloads
    # separately); a different HOST is the boundary that matters.
    assert main.is_safe_installer_url("http://192.168.80.52:9999/S.exe", api) is True


def test_untrusted_host_is_not_downloaded(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "api_get_version", lambda base: {
        "version": "9.9.9", "windows_url": "http://evil.example.com/S.exe"})
    fetched = []
    monkeypatch.setattr(main.requests, "get",
                        lambda *a, **k: fetched.append(a) or None)
    w = main.UpdateCheckWorker("http://192.168.80.52:8080", "2.4.1")
    seen = {"none": 0}
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    assert seen["none"] == 1
    assert not fetched, "must not even fetch from an untrusted host"


def test_redirect_to_an_untrusted_host_is_refused(monkeypatch, tmp_path):
    """Redirects ARE followed (GitHub bounces release assets to its CDN), so the host we
    actually landed on must be re-checked — otherwise a redirect smuggles us anywhere."""
    monkeypatch.setattr(main, "api_get_version", lambda base: {
        "version": "9.9.9", "windows_url": "https://github.com/o/r/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Redirected:
        status_code = 200
        url = "https://evil.example.com/payload.exe"      # ended up somewhere else
        def iter_content(self, chunk_size=0): yield b"MZ" + bytes(10)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Redirected())
    w = main.UpdateCheckWorker("http://api.host", "2.4.1")
    seen = {"ready": [], "none": 0}
    w.update_ready.connect(lambda p, v: seen["ready"].append((p, v)))
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    assert seen["none"] == 1 and not seen["ready"], "must refuse an untrusted redirect"


def test_redirect_within_github_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "api_get_version", lambda base: {
        "version": "9.9.9", "windows_url": "https://github.com/o/r/S.exe"})
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))

    class Cdn:
        status_code = 200
        url = "https://objects.githubusercontent.com/abc/S.exe"   # GitHub's CDN
        def iter_content(self, chunk_size=0): yield b"MZ" + bytes(10)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Cdn())
    w = main.UpdateCheckWorker("http://api.host", "2.4.1")
    seen = {"ready": [], "none": 0}
    w.update_ready.connect(lambda p, v: seen["ready"].append((p, v)))
    w.no_update.connect(lambda: seen.__setitem__("none", seen["none"] + 1))
    w.run()
    assert len(seen["ready"]) == 1, "GitHub's own CDN must still work"


@pytest.mark.parametrize("version,expected", [
    ("2.4.2", "SparkFlowSetup-2.4.2.exe"),
    ("../../../evil", "SparkFlowSetup-......evil.exe"),
    ("a/b\\c", "SparkFlowSetup-abc.exe"),
    ("", "SparkFlowSetup-update.exe"),
    ("x" * 100, "SparkFlowSetup-" + "x" * 32 + ".exe"),
])
def test_installer_filename_is_sanitised(version, expected):
    """The version string is network-controlled; interpolating it raw into a path
    would allow writing outside the temp directory."""
    name = main.safe_installer_filename(version)
    assert name == expected
    assert "/" not in name and "\\" not in name
