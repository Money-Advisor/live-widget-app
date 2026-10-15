# -*- coding: utf-8 -*-
"""Does the Focus screen starve audio capture? Measure it.

    python focus_dev/audio_ab.py classic|focus [seconds]

Runs the widget's REAL RecordingThread on the microphone the installed widget
uses, for N seconds, behind either the classic screen or the Focus screen
showing a busy live call (cards, animations, a server message every 2s), and
prints how much silence the gap-fill had to insert - the same number the
widget logs as "[gapfill] mic: X s of silence inserted".

The audio goes nowhere: send_callback counts bytes and drops them. Nothing is
saved, nothing is sent, and the window runs on throwaway settings (the real
widget's registry is read once, read-only, for the microphone's NAME only).
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from PyQt6.QtCore import Qt, QCoreApplication, QSettings, QEventLoop, QTimer  # noqa: E402
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

import main      # noqa: E402
import focus_ui  # noqa: E402

real = QSettings(main.ORG, main.APP)                     # read-only: the mic's name
MIC_NAME = real.value("audio/mic_name", "") or ""
_INI = os.path.join(tempfile.mkdtemp(prefix="sf-audio-ab-"), "widget.ini")
main.QSettings = lambda *a, **k: QSettings(_INI, QSettings.Format.IniFormat)

from PyQt6.QtWidgets import QApplication  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "focus"
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
app = QApplication(sys.argv)


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


win = focus_ui.FocusWindow(start=(mode == "focus"))
assert win._settings.format() == QSettings.Format.IniFormat and not win._token
win.show()
if mode == "focus":
    t0 = time.time()
    while not win._focus.ready and time.time() - t0 < 20:
        pump(100)

names = [d["name"] for d in win._mic_devices]
idx = main._index_for_saved_mic(names, MIC_NAME) if names else -1
dev = win._mic_devices[idx]
print(f"mode={mode} mic={dev['name']!r} rate={int(dev['defaultSampleRate'])}")

# A live call on screen, with the server's traffic: a full state every 2s.
import json, subprocess  # noqa: E401,E402
sc = json.loads(subprocess.run(
    ["node", "-e", "global.self=global; require(process.argv[1]); console.log(JSON.stringify(global.FocusScenarios))",
     str(HERE / "scenarios.js")], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
msgs = [s["data"] for s in sc["live-three"]["steps"] if s["kind"] == "msg"]
win._recording = True
win._live_pipeline = True
win._reference_edit.setText("REF-TEST")
win._focus.push_state(force=True) if mode == "focus" else None
for m in msgs:
    win.server_message.emit(m)
traffic = QTimer()
traffic.timeout.connect(lambda: [win.server_message.emit(m) for m in msgs[-2:]])
traffic.start(2000)
tick = QTimer()
tick.timeout.connect(lambda: setattr(win, "_elapsed", win._elapsed + 1))
tick.start(1000)

both = "--both" in sys.argv
got = {"bytes": 0}
sink = lambda st, d: got.__setitem__("bytes", got["bytes"] + len(d))  # noqa: E731
start_ref = main._now()
threads = [main.RecordingThread(device_index=int(dev["index"]), stream_type="mic",
                                sample_rate=int(dev["defaultSampleRate"]),
                                channels=min(int(dev["maxInputChannels"]), 2),
                                send_callback=sink, start_ref=start_ref if both else None)]
if both:
    # The customer side exactly as a call opens it (_on_call_connected): the
    # selected loopback, with its render endpoint held open by RenderKeepAlive.
    spk = win._spk_devices[win._spk_combo.currentIndex()]
    keep = main._render_index_for_loopback(getattr(win, "_all_devices", []), spk.get("name", ""))
    print(f"speaker={spk['name']!r} keepalive_index={keep}")
    threads.append(main.RecordingThread(device_index=int(spk["index"]), stream_type="speaker",
                                        sample_rate=int(spk["defaultSampleRate"]),
                                        channels=min(int(spk["maxInputChannels"]), 2),
                                        send_callback=sink, is_loopback=True,
                                        keepalive_device_index=keep, start_ref=start_ref))
for t in threads:
    t.stream_ready.connect(lambda *a, _t=t: _t._start_ack.set())
    t.start()
pump(int(seconds * 1000))
for t in threads:
    t.stop() if hasattr(t, "stop") else t._stop_event.set()
for t in threads:
    t.wait(3000)
traffic.stop()
for t in threads:
    pct = 100.0 * t.seconds_filled / seconds
    print(f"RESULT mode={mode} channel={t.stream_type} seconds={seconds:.0f} "
          f"silence_inserted={t.seconds_filled:.2f}s ({pct:.0f}%) gaps={t.gaps_filled}")
win._recording = False
os._exit(0)
