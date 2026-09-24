"""The saved-server migration, and why it is now switched off.

Aug 2026: the servers moved 192.168.80.52 -> .53. A new build alone did NOT fix an
existing agent, because QSettings takes precedence over DEFAULT_*, so anyone who had
ever run the widget kept the retired address and hit a 502 at login. `RETIRED_HOSTS`
rewrote it on startup.

Sep 2026: **192.168.80.52 is the STAGING box again**, and the whole AI pipeline is
developed against it. A widget deliberately pointed there was being dragged back to
production on every launch, and the staging login then failed against production's
database — the two boxes have separate databases. So `RETIRED_HOSTS` is now empty, and
.52 must never go back into it.

The migration machinery is kept because the next server move will need it; these tests
cover that it is inert today, that it still works when a host IS listed, and that a
deliberately-chosen server is never hijacked.
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


def test_the_staging_box_is_no_longer_retired():
    """THE one that matters. 192.168.80.52 is staging now, and a widget pointed there
    on purpose must stay there. While it was in RETIRED_HOSTS the address was silently
    rewritten to production on every launch, so the staging login failed — the two
    boxes have separate databases and the account simply does not exist on production."""
    assert "192.168.80.52" not in main.MainWindow.RETIRED_HOSTS

    obj = _run_migration("http://192.168.80.52:8080", "ws://192.168.80.52:8765")
    assert obj._api_base == "http://192.168.80.52:8080"
    assert obj._ws_url == "ws://192.168.80.52:8765"
    assert not obj._settings.synced          # nothing rewritten -> no write


def test_the_migration_still_works_when_a_host_IS_listed(monkeypatch):
    """Kept for the next server move: the mechanism must still rewrite and persist.
    Without this, emptying the list could quietly rot into a no-op function."""
    monkeypatch.setattr(main.MainWindow, "RETIRED_HOSTS", ("10.9.9.9",))
    obj = _run_migration("http://10.9.9.9:8080", "ws://10.9.9.9:8765")
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
