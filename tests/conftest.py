"""Keep the widget's tests isolated from the real installed widget.

main.py stores everything in QSettings("Spark Flow", "Widget"), which on Windows is the
REAL registry key (HKCU\\Software\\Spark Flow\\Widget) that the installed widget uses.
Without redirecting it, a developer machine with the widget signed in leaks its stored
token and cached config into the tests: MainWindow.__init__ sees auth/token, decides it
is logged in, applies the cached config (so e.g. hide_customer_fields=True bleeds into
unrelated assertions) and even starts a ValidateWorker against the live server.

That made the suite pass or fail depending on WHO ran it. Point QSettings at a throwaway
directory for the whole session so every test starts from a clean, empty store.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QSettings


@pytest.fixture(scope="session", autouse=True)
def _isolate_qsettings(tmp_path_factory):
    store = tmp_path_factory.mktemp("qsettings")
    # INI format + a temp path keeps us off the Windows registry entirely.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(store))
    yield
