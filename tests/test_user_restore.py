"""Remember-me relaunch must restore the agent's identity (name, id, email),
not just the token — otherwise the widget shows no name and sends agent_id
'unknown'. The token is still valid, so we re-fetch /api/me on launch."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless Qt

import main


def test_user_from_me_maps_to_login_shape():
    me = {
        "id": "u-1", "email": "agent@x.test", "full_name": "Umair Khan",
        "role": "agent",
        "company": {"id": "co-1", "name": "TIG", "onboarding_completed": True},
    }
    u = main._user_from_me(me)
    assert u["id"] == "u-1"
    assert u["name"] == "Umair Khan"
    assert u["email"] == "agent@x.test"
    assert u["company_name"] == "TIG"
    assert u["role"] == "agent"


def test_user_from_me_tolerates_missing_fields():
    u = main._user_from_me({})
    assert u == {"id": "", "name": "", "email": "", "company_name": "", "role": ""}


def test_validate_worker_emits_user_profile(monkeypatch):
    """On launch with a stored token, ValidateWorker fetches /api/me and includes
    the user profile in its `valid` signal (alongside config + etag)."""
    class FakeResp:
        status_code = 200
        headers = {"ETag": "etag-1"}
        def json(self):
            return {"company_name": "TIG"}   # a config payload

    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main, "api_get_me", lambda base, token: {
        "id": "u-1", "email": "agent@x.test", "full_name": "Umair Khan",
        "role": "agent", "company": {"name": "TIG"}})

    captured = {}
    w = main.ValidateWorker("http://x", "tok", "")
    w.valid.connect(lambda cfg, etag, user: captured.update(
        cfg=cfg, etag=etag, user=user))
    w.run()                                   # run synchronously in this thread

    assert captured["user"]["id"] == "u-1"
    assert captured["user"]["name"] == "Umair Khan"
    assert captured["etag"] == "etag-1"


def test_validate_worker_still_valid_when_me_fails(monkeypatch):
    """If /api/me hiccups, validation must still succeed (token is good); the
    user profile just comes back empty rather than breaking launch."""
    class FakeResp:
        status_code = 304
        headers = {}
        def json(self):
            return {}

    monkeypatch.setattr(main, "api_get_config", lambda *a, **k: FakeResp())
    def boom(*a, **k):
        raise main.BackendError("me down")
    monkeypatch.setattr(main, "api_get_me", boom)

    seen = {"valid": 0, "invalid": 0}
    w = main.ValidateWorker("http://x", "tok", "old-etag")
    w.valid.connect(lambda cfg, etag, user: seen.__setitem__("valid", seen["valid"] + 1))
    w.invalid.connect(lambda: seen.__setitem__("invalid", seen["invalid"] + 1))
    w.run()

    assert seen["valid"] == 1 and seen["invalid"] == 0
