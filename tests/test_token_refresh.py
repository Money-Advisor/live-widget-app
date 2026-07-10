"""Pure unit tests for the silent token-refresh decision — no Qt / MainWindow, so
this never touches the offscreen display."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import time

import main


def test_no_refresh_when_token_fresh():
    assert main._needs_token_refresh("tok", "rtok", False, time.time() + 3600) is False


def test_refresh_when_token_near_expiry():
    assert main._needs_token_refresh("tok", "rtok", False, time.time() + 120) is True


def test_refresh_when_expiry_unknown():
    # Cold start with a remembered token: expiry unknown (0) -> renew promptly.
    assert main._needs_token_refresh("tok", "rtok", False, 0.0) is True


def test_no_refresh_without_refresh_token():
    assert main._needs_token_refresh("tok", "", False, 0.0) is False


def test_no_refresh_without_token():
    assert main._needs_token_refresh("", "rtok", False, 0.0) is False


def test_no_refresh_when_one_already_inflight():
    assert main._needs_token_refresh("tok", "rtok", True, 0.0) is False


def test_as_expires_in_is_tolerant():
    assert main._as_expires_in("3600") == 3600
    assert main._as_expires_in(3600) == 3600
    assert main._as_expires_in(None) == 3600
    assert main._as_expires_in("garbage") == 3600
