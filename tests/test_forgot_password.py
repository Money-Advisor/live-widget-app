"""Widget-side self-service password reset ("Forgot password?" on the login screen).

The important behaviours: the network call never runs on the UI thread, and the message
shown to the agent is the same whether or not the address is registered — the server
deliberately won't say, so the widget must not imply it either.
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
import requests

import main


class _Resp:
    def __init__(self, code):
        self.status_code = code


def test_success_returns_none(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return _Resp(200)

    monkeypatch.setattr(requests, "post", fake_post)
    assert main.api_forgot_password("http://srv:8080", "a@b.test") is None
    assert seen["url"] == "http://srv:8080/auth/forgot-password"
    assert seen["json"] == {"email": "a@b.test"}


def test_rate_limit_is_explained_not_raw(monkeypatch):
    """429 is the one server code an agent can act on, so it gets its own wording."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(429))
    with pytest.raises(main.BackendError) as e:
        main.api_forgot_password("http://srv:8080", "a@b.test")
    assert "wait" in str(e.value).lower()


def test_server_error_surfaces_the_code(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(500))
    with pytest.raises(main.BackendError) as e:
        main.api_forgot_password("http://srv:8080", "a@b.test")
    assert "500" in str(e.value)


def test_unreachable_server_is_a_friendly_message(monkeypatch):
    def boom(*a, **k):
        raise requests.RequestException("no route")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(main.BackendError) as e:
        main.api_forgot_password("http://srv:8080", "a@b.test")
    assert "connection" in str(e.value).lower()


def test_worker_emits_succeeded(monkeypatch):
    monkeypatch.setattr(main, "api_forgot_password", lambda base, email: None)
    w = main.ForgotPasswordWorker("http://srv:8080", "a@b.test")
    got = []
    w.succeeded.connect(lambda: got.append("ok"))
    w.run()                      # run() directly: no Qt event loop needed
    assert got == ["ok"]


def test_worker_emits_failed_with_the_reason(monkeypatch):
    def boom(base, email):
        raise main.BackendError("Too many attempts. Please wait a minute and try again.")

    monkeypatch.setattr(main, "api_forgot_password", boom)
    w = main.ForgotPasswordWorker("http://srv:8080", "a@b.test")
    got = []
    w.failed.connect(got.append)
    w.run()
    assert got and "wait" in got[0].lower()


def test_worker_is_a_qthread():
    """It must be a thread — a blocking request on the UI thread freezes the widget."""
    from PyQt6.QtCore import QThread
    assert issubclass(main.ForgotPasswordWorker, QThread)


def test_confirmation_does_not_reveal_whether_the_email_exists():
    """The reply must be conditional ('if that email is registered'), never 'sent'."""
    import inspect
    src = inspect.getsource(main.MainWindow._on_forgot_sent)
    assert "if that email is registered" in src.lower()
