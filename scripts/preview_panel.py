"""Offscreen render of ComplianceAlertPanel to a PNG for visual QA."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout  # noqa: E402

import main as widget_main  # noqa: E402

app = QApplication(sys.argv)

# replicate the REAL context: panel lives inside the white 340px front card
from PyQt6.QtWidgets import QFrame, QLabel  # noqa: E402

host = QWidget()
host.setStyleSheet("background:#0E0E1A;")
host.setFixedWidth(380)
lay = QVBoxLayout(host)
lay.setContentsMargins(16, 16, 16, 16)

card = QFrame()
card.setObjectName("frontCard")
card.setFixedWidth(340)
card.setStyleSheet("QFrame#frontCard { background:white; border-radius:18px; }")
card_lay = QVBoxLayout(card)
card_lay.setContentsMargins(24, 24, 24, 24)
card_lay.setSpacing(10)

timer_lbl = QLabel("00:05")
timer_lbl.setStyleSheet("font-size:12px; color:#8888A8;")
card_lay.addWidget(timer_lbl)

panel = widget_main.ComplianceAlertPanel()
card_lay.addWidget(panel)
card_lay.addStretch(1)

lay.addWidget(card)
lay.addStretch(1)

panel.update_missing([
    {"id": "1", "level": "red", "label": "Recording disclosure",
     "suggestion_text": "Say: just to let you know, this call is recorded."},
    {"id": "2", "level": "amber", "label": "Signpost free debt advice", "suggestion_text": None},
    {"id": "3", "level": "amber", "label": "Closing check", "suggestion_text": None},
])

host.adjustSize()
host.resize(380, host.sizeHint().height())
app.processEvents()

out = Path(__file__).resolve().parent / "panel_preview.png"
host.grab().save(str(out))
print(f"saved {out} size={host.size().width()}x{host.size().height()}")
