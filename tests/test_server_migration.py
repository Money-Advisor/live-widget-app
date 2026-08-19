"""The Aug-2026 server move: 192.168.80.52 -> .53.

A new build alone does NOT fix an existing agent. QSettings takes precedence over
DEFAULT_*, so anyone who had ever run the widget kept the retired address and hit a
502 at login (the old box still serves nginx but no API). These cover the migration
that rewrites it, and that a deliberately-chosen server is left alone.
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main


class _FakeSettings:
    """Minimal QSettings stand-in: value/setValue/sync over a dict."""

    def __init__(self, initial=None):
        self._d = dict(initial or {})
        self.synced = False

    def value(self, key, default=None):
        return self._d.get(key, default)

    def setValue(self, key, val):
        self._d[key] = val

    def sync(self):
        self.synced = True


def _run_migration(api, ws):
    """Drive _migrate_server_urls in isolation, without building the whole window."""
    obj = main.MainWindow.__new__(main.MainWindow)   # no __init__: avoids Qt setup
    obj._settings = _FakeSettings({"api/base_url": api, "ws/url": ws})
    obj._api_base = api
    obj._ws_url = ws
    obj._migrate_server_urls()
    return obj


def test_retired_host_is_rewritten_and_persisted():
    obj = _run_migration("http://192.168.80.52:8080", "ws://192.168.80.52:8765")
    assert obj._api_base == main.DEFAULT_API_BASE_URL
    assert obj._ws_url == main.DEFAULT_RECORDING_WS
    # must be written back, or it reverts on the next launch
    assert obj._settings.value("api/base_url") == main.DEFAULT_API_BASE_URL
    assert obj._settings.value("ws/url") == main.DEFAULT_RECORDING_WS
    assert obj._settings.synced


def test_current_server_is_left_untouched():
    obj = _run_migration(main.DEFAULT_API_BASE_URL, main.DEFAULT_RECORDING_WS)
    assert obj._api_base == main.DEFAULT_API_BASE_URL
    assert not obj._settings.synced          # nothing to do -> no write


def test_a_deliberately_chosen_server_is_not_hijacked():
    """An agent pointed at a test box must stay there — we only retire the old host."""
    obj = _run_migration("http://10.0.0.9:8080", "ws://10.0.0.9:8765")
    assert obj._api_base == "http://10.0.0.9:8080"
    assert obj._ws_url == "ws://10.0.0.9:8765"
    assert not obj._settings.synced


def test_defaults_point_at_the_new_server():
    assert "192.168.80.53" in main.DEFAULT_API_BASE_URL
    assert "192.168.80.53" in main.DEFAULT_RECORDING_WS
    assert "192.168.80.52" not in main.DEFAULT_API_BASE_URL
    assert "192.168.80.52" not in main.DEFAULT_RECORDING_WS
