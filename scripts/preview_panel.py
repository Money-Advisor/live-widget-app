"""Offscreen render of ComplianceAlertPanel to a PNG for visual QA."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout  # noqa: E402

import main as widget_main  # noqa: E402

app = QApplication(sys.argv)

# replicate the REAL context: panel = own floating column LEFT of the card
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

host = QWidget()
host.setStyleSheet("background:#0E0E1A;")
lay = QHBoxLayout(host)
lay.setContentsMargins(16, 16, 16, 16)
lay.setSpacing(6)

panel = widget_main.ComplianceAlertPanel()
lay.addWidget(panel, 0, Qt.AlignmentFlag.AlignTop)

card = QFrame()
card.setObjectName("frontCard")
card.setFixedWidth(340)
card.setMinimumHeight(420)
card.setStyleSheet("QFrame#frontCard { background:white; border-radius:18px; }")
card_lay = QVBoxLayout(card)
card_lay.setContentsMargins(24, 24, 24, 24)
card_lay.addWidget(QLabel("call form placeholder"))
card_lay.addStretch(1)
lay.addWidget(card)

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
