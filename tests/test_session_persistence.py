"""Agents must stay signed in across restarts.

The widget auto-starts the moment Windows logs in — before the network is ready — and
its stored id token is ~1 hour old, so it's usually expired. The old code validated
that stale token first and treated ANY failure (no network, 5xx, expired token) as
"this agent is not allowed in", wiping the session. These tests pin down the two rules
that fix it: renew before validating, and only a definitive rejection signs out.
"""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless Qt

import pytest

import main


class FakeResp:
    def __init__(self, status, payload=None, etag="etag-1"):
        self.status_code = status
        self._payload = payload if payload is not None else {"company_name": "TIG"}
        self.headers = {"ETag": etag}

    def json(self):
        return self._payload


def _capture(worker):
    """Wire all three outcomes and report which fired."""
    seen = {"valid": [], "invalid": 0, "unreachable": []}
    worker.valid.connect(lambda *a: seen["valid"].append(a))
    worker.invalid.connect(lambda: seen.__setitem__("invalid", seen["invalid"] + 1))
    worker.unreachable.connect(lambda r: seen["unreachable"].append(r))
    return seen


# ── api_refresh error classification ────────────────────────────────────────
@pytest.mark.parametrize("status", [400, 401, 403])
def test_refresh_rejects_are_auth_errors(monkeypatch, status):
    """A refresh token the backend rejects is a real sign-out."""
    class R:
        status_code = status
        def json(self): return {}

    monkeypatch.setattr(main.requests, "post", lambda *a, **k: R())
    with pytest.raises(main.AuthError):
        main.api_refresh("http://x", "rt")


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_refresh_server_errors_are_transient(monkeypatch, status):
    """A 5xx must NOT be mistaken for rejected credentials."""
    class R:
        status_code = status
        def json(self): return {}

    monkeypatch.setattr(main.requests, "post", lambda *a, **k: R())
    with pytest.raises(main.BackendError) as exc:
        main.api_refresh("http://x", "rt")
    assert not isinstance(exc.value, main.AuthError)


def test_refresh_network_failure_is_transient(monkeypatch):
    def boom(*a, **k):
        raise main.requests.RequestException("no route to host")

    monkeypatch.setattr(main.requests, "post", boom)
    with pytest.raises(main.BackendError) as exc:
        main.api_refresh("http://x", "rt")
    assert not isinstance(exc.value, main.AuthError)


# ── the startup path ────────────────────────────────────────────────────────
def test_renews_token_before_validating(monkeypatch):
    """THE morning-logout fix: the stored token is renewed first, and the fresh one
    is what gets validated and handed back to be stored."""
    order = []
    monkeypatch.setattr(main, "api_refresh", lambda base, rt: (
        order.append("refresh"),
        {"token": "fresh-tok", "refresh_token": "fresh-rt", "expires_in": "3600"})[1])

    def cfg(base, token, etag=None, department=None):
        order.append(f"config:{token}")
        return FakeResp(200)

    monkeypatch.setattr(main, "api_get_config", cfg)
    monkeypatch.setattr(main, "api_get_me", lambda b, t: {"id": "u-1", "full_name": "A"})

    w = main.ValidateWorker("http://x", "stale-tok", "", "rt")
    seen = _capture(w)
    w.run()

    assert order == ["refresh", "config:fresh-tok"], order
    assert seen["invalid"] == 0 and not seen["unreachable"]
    cfg_, etag_, user_, token_, rt_, exp_ = seen["valid"][0]
    assert token_ == "fresh-tok" and rt_ == "fresh-rt" and exp_ == 3600
    assert user_["id"] == "u-1"


def test_network_down_keeps_the_session(monkeypatch):
    """Auto-start before the network is up must NOT sign the agent out."""
    monkeypatch.setattr(main, "api_refresh",
                        lambda *a: (_ for _ in ()).throw(main.BackendError("no network")))

    def cfg(*a, **k):
        raise main.BackendError("Could not reach the server.")

    monkeypatch.setattr(main, "api_get_config", cfg)

    w = main.ValidateWorker("http://x", "tok", "", "rt")
    seen = _capture(w)
    w.run()

    assert seen["invalid"] == 0, "a network failure must never sign the agent out"
    assert len(seen["unreachable"]) == 1


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error_keeps_the_session(monkeypatch, status):
    """A backend 5xx (e.g. a migration not yet applied) must not log everyone out."""
    monkeypatch.setattr(main, "api_refresh", lambda base, rt: {
        "token": "fresh", "refresh_token": "rt2", "expires_in": 3600})
    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp(status))

    w = main.ValidateWorker("http://x", "tok", "", "rt")
    seen = _capture(w)
    w.run()

    assert seen["invalid"] == 0
    assert len(seen["unreachable"]) == 1


def test_401_on_a_freshly_renewed_token_signs_out(monkeypatch):
    """If the token is definitely fresh and STILL rejected, that's a real sign-out."""
    monkeypatch.setattr(main, "api_refresh", lambda base, rt: {
        "token": "fresh", "refresh_token": "rt2", "expires_in": 3600})
    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp(401))

    w = main.ValidateWorker("http://x", "tok", "", "rt")
    seen = _capture(w)
    w.run()

    assert seen["invalid"] == 1
    assert not seen["unreachable"]


def test_401_on_a_stale_token_we_could_not_renew_is_transient(monkeypatch):
    """The subtle one: refresh failed for network reasons, so the 401 just means
    'expired', not 'rejected'. Keep the session and retry."""
    monkeypatch.setattr(main, "api_refresh",
                        lambda *a: (_ for _ in ()).throw(main.BackendError("offline")))
    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp(401))

    w = main.ValidateWorker("http://x", "stale", "", "rt")
    seen = _capture(w)
    w.run()

    assert seen["invalid"] == 0, "an unrenewable stale token is not a rejection"
    assert len(seen["unreachable"]) == 1


def test_rejected_refresh_token_signs_out(monkeypatch):
    """Password changed / account removed -> the refresh token is dead -> sign out."""
    monkeypatch.setattr(main, "api_refresh",
                        lambda *a: (_ for _ in ()).throw(main.AuthError("revoked")))
    called = []
    monkeypatch.setattr(main, "api_get_config",
                        lambda *a, **k: called.append(1) or FakeResp(200))

    w = main.ValidateWorker("http://x", "tok", "", "rt")
    seen = _capture(w)
    w.run()

    assert seen["invalid"] == 1
    assert not called, "must not bother validating once the refresh token is rejected"


def test_401_without_any_refresh_token_signs_out(monkeypatch):
    """No refresh token to fall back on, and the id token is rejected -> sign out."""
    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp(403))

    w = main.ValidateWorker("http://x", "tok", "", "")
    seen = _capture(w)
    w.run()

    assert seen["invalid"] == 1


def test_304_keeps_cached_config(monkeypatch):
    monkeypatch.setattr(main, "api_refresh", lambda base, rt: {
        "token": "fresh", "refresh_token": "rt2", "expires_in": 3600})
    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp(304, {}))
    monkeypatch.setattr(main, "api_get_me", lambda b, t: {"id": "u-9"})

    w = main.ValidateWorker("http://x", "tok", "old-etag", "rt")
    seen = _capture(w)
    w.run()

    cfg_, etag_, user_, token_, _rt, _e = seen["valid"][0]
    assert cfg_ == {} and etag_ == "old-etag"


def test_me_hiccup_still_validates(monkeypatch):
    """/api/me failing must not fail the launch — the token is still good."""
    monkeypatch.setattr(main, "api_refresh", lambda base, rt: {
        "token": "fresh", "refresh_token": "rt2", "expires_in": 3600})
    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp(200))
    monkeypatch.setattr(main, "api_get_me",
                        lambda *a: (_ for _ in ()).throw(main.BackendError("me down")))

    w = main.ValidateWorker("http://x", "tok", "", "rt")
    seen = _capture(w)
    w.run()

    assert len(seen["valid"]) == 1 and seen["invalid"] == 0


def test_no_token_at_all_signs_out(monkeypatch):
    w = main.ValidateWorker("http://x", "", "", "")
    seen = _capture(w)
    w.run()
    assert seen["invalid"] == 1


# ── identity cache ──────────────────────────────────────────────────────────
def test_user_setting_roundtrip(tmp_path):
    """The cached profile lets a restart know who's signed in with no network."""
    from PyQt6.QtCore import QSettings

    s = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    assert main._load_json_setting(s, "auth/user") == {}
    s.setValue("auth/user", main.json.dumps({"id": "u-1", "name": "A"}))
    assert main._load_json_setting(s, "auth/user")["id"] == "u-1"
    s.setValue("auth/user", "{not json")
    assert main._load_json_setting(s, "auth/user") == {}
    s.setValue("auth/user", main.json.dumps(["a", "list"]))
    assert main._load_json_setting(s, "auth/user") == {}, "non-dict must not leak through"


# ── revocation during a running session ─────────────────────────────────────
def test_refresh_worker_reports_revocation_separately(monkeypatch):
    """AuthError subclasses BackendError. If the worker catches the parent first, a
    revoked account keeps working for as long as the widget stays open."""
    monkeypatch.setattr(main, "api_refresh",
                        lambda *a: (_ for _ in ()).throw(main.AuthError("revoked")))
    w = main.RefreshWorker("http://x", "rt")
    seen = {"failed": 0, "rejected": 0}
    w.failed.connect(lambda m: seen.__setitem__("failed", seen["failed"] + 1))
    w.rejected.connect(lambda: seen.__setitem__("rejected", seen["rejected"] + 1))
    w.run()
    assert seen["rejected"] == 1 and seen["failed"] == 0


def test_refresh_worker_treats_outages_as_transient(monkeypatch):
    monkeypatch.setattr(main, "api_refresh",
                        lambda *a: (_ for _ in ()).throw(main.BackendError("offline")))
    w = main.RefreshWorker("http://x", "rt")
    seen = {"failed": 0, "rejected": 0}
    w.failed.connect(lambda m: seen.__setitem__("failed", seen["failed"] + 1))
    w.rejected.connect(lambda: seen.__setitem__("rejected", seen["rejected"] + 1))
    w.run()
    assert seen["failed"] == 1 and seen["rejected"] == 0, "an outage must not sign out"


# ── diagnosability (three field failures had no evidence to work from) ──────
def test_logging_writes_a_file_and_survives_failure(tmp_path, monkeypatch):
    """--windowed builds have no console, so print() is lost. Every sign-out and update
    decision must land in a file an agent can send us."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    real_out, real_err = main.sys.stdout, main.sys.stderr
    try:
        path = main.setup_logging()
        assert path is not None and path.exists()
        print("hello from the widget")
        main.sys.stdout.flush()
        assert "hello from the widget" in path.read_text(encoding="utf-8")
        assert main.APP_VERSION in path.read_text(encoding="utf-8")
    finally:
        main.sys.stdout, main.sys.stderr = real_out, real_err


def test_logging_never_blocks_startup(monkeypatch):
    monkeypatch.setattr(main, "log_path",
                        lambda: (_ for _ in ()).throw(OSError("no disk")))
    assert main.setup_logging() is None, "a logging failure must be survivable"
