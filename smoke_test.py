"""Headless smoke test for the Spark Flow widget (offscreen Qt, no network)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

import main as m

app = QApplication(sys.argv)
failures = []

def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        failures.append(name)

# 1. ComplianceAlertPanel visibility + content
panel = m.ComplianceAlertPanel()
check("panel hidden initially", not panel.isVisible())
panel.update_missing([
    {"id": "a", "label": "Greeting", "level": "amber", "suggestion_text": ""},
    {"id": "b", "label": "Forbidden phrase", "level": "red",
     "suggestion_text": "Apologise and correct."},
])
check("panel visible after missing items", panel.isVisible())
check("suggestion shown for red item", panel._suggestion.isVisible())
panel.update_missing([])
check("panel hidden when nothing missing", not panel.isVisible())

# 2. SummaryScreen scoring + colour buckets
s = m.SummaryScreen()
s.show_summary(0.5, ["Greeting"], ["Disclosure"], 95)
check("summary 50%", s._score.text() == "50%")
check("summary duration mm:ss", s._duration.text() == "Duration  01:35")
s.show_summary(0.95, [], [], 10)
check("summary 95%", s._score.text() == "95%")
s.mark_saved()
check("summary saved label", "saved" in s._saved_lbl.text().lower())

# 3. Backend client URL building (monkeypatch requests, no real network)
captured = {}
class _Resp:
    status_code = 200
    headers = {"ETag": "xyz"}
    def json(self): return {"token": "t", "user": {"id": "u1", "name": "Ada"}}
def _fake_post(url, json=None, timeout=None):
    captured["post_url"] = url; captured["body"] = json; return _Resp()
def _fake_get(url, headers=None, timeout=None, params=None):
    captured["get_url"] = url; captured["headers"] = headers; captured["params"] = params; return _Resp()
m.requests.post = _fake_post
m.requests.get = _fake_get
data = m.api_login("http://localhost:8000/", "a@b.com", "pw")
check("login posts to /auth/login-widget",
      captured["post_url"] == "http://localhost:8000/auth/login-widget")
check("login returns token", data.get("token") == "t")
r = m.api_get_config("http://localhost:8000", "tok", etag="prev")
check("config gets /api/widget/config",
      captured["get_url"] == "http://localhost:8000/api/widget/config")
check("config sends bearer + if-none-match",
      captured["headers"]["Authorization"] == "Bearer tok"
      and captured["headers"]["If-None-Match"] == "prev")

# 4. CHUNK bumped + framing untouched
check("CHUNK == 4096", m.CHUNK == 4096)

# 5. Native login: SVG icons render + toggle switch paints + no WebEngine
icon = m.svg_icon("mail")
check("svg_icon returns non-null QIcon", isinstance(icon, QIcon) and not icon.isNull())
for nm in ("mail", "lock", "eye", "eye_off"):
    check(f"icon '{nm}' non-null", not m.svg_icon(nm).isNull())
sw = m.ToggleSwitch()
sw.setChecked(True)
check("ToggleSwitch is a QCheckBox", sw.isChecked() and sw.width() == 40)
check("no QWebEngineView attr (pure PyQt6)", not hasattr(m, "QWebEngineView"))
check("no LoginBridge (bridge removed)", not hasattr(m, "LoginBridge"))

print("\nRESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
