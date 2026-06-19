"""
Krisp dual-capture probe  (THROWAWAY diagnostic — not part of the shipped app).

Question it answers: on a real PC with Krisp running, can we record the RAW
physical mic AND the Krisp virtual mic AT THE SAME TIME? (i.e. does Krisp let us
share the physical mic, or does it lock it in WASAPI exclusive mode?)

What it does:
  1. Lists every Windows (WASAPI) input device.
  2. Picks the Krisp virtual mic (by name) + the first real physical mic.
  3. Opens BOTH at once, records 5 seconds each to a WAV.
  4. Measures loudness of each and prints a clear PASS / FAIL verdict.

Run it while Krisp is ON and you are TALKING into the headset for the 5 seconds.

Results are printed AND written to  krisp_probe_result.txt  next to this file,
so it still works when double-clicked as a built .exe.
"""
import os
import sys
import time
import wave
import threading
from datetime import datetime

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("pyaudiowpatch not installed.  Run:  pip install pyaudiowpatch")
    input("\nPress Enter to close...")
    sys.exit(1)

try:
    import audioop  # stdlib (<=3.12); used only for a loudness number
    def _rms(data):
        return audioop.rms(data, 2)
except Exception:
    import struct
    def _rms(data):
        if not data:
            return 0
        n = len(data) // 2
        samples = struct.unpack("<%dh" % n, data[: n * 2])
        return int((sum(s * s for s in samples) / n) ** 0.5) if n else 0


RECORD_SECONDS = 5
CHUNK = 4096
# When frozen by PyInstaller (--onefile), __file__ points at a temp extraction
# dir that is deleted on exit — write next to the .exe instead so the agent can
# find the result file + WAVs. When run as a .py, use the script's own folder.
if getattr(sys, "frozen", False):
    OUT_DIR = os.path.dirname(sys.executable)
else:
    OUT_DIR = os.path.dirname(os.path.abspath(__file__))
_lines = []


def log(msg=""):
    print(msg)
    _lines.append(str(msg))


def list_inputs(pa):
    """Return [(index, name, channels, default_rate)] for WASAPI input devices."""
    info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    out = []
    for i in range(int(info["deviceCount"])):
        dev = pa.get_device_info_by_host_api_device_index(int(info["index"]), i)
        if dev.get("isLoopbackDevice", False):
            continue  # speaker loopback = customer side, not what we're probing
        if int(dev.get("maxInputChannels", 0)) > 0:
            out.append((int(dev["index"]), dev["name"],
                        min(int(dev["maxInputChannels"]), 2),
                        int(dev["defaultSampleRate"])))
    return out


def record(pa, device_index, channels, rate, label, results):
    """Open one input device and record RECORD_SECONDS to a WAV. Fills results[label]."""
    fname = os.path.join(OUT_DIR, f"krisp_probe_{label}.wav")
    stream = None
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                         input=True, input_device_index=device_index,
                         frames_per_buffer=CHUNK)
    except Exception as exc:
        # THE key failure: device busy / exclusive mode -> can't share the mic.
        results[label] = {"ok": False, "error": str(exc), "peak": 0, "file": None}
        return

    frames = []
    peak = 0
    end = time.time() + RECORD_SECONDS
    try:
        while time.time() < end:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            peak = max(peak, _rms(data))
    except Exception as exc:
        results[label] = {"ok": False, "error": f"read failed: {exc}",
                          "peak": peak, "file": None}
        return
    finally:
        try:
            stream.stop_stream(); stream.close()
        except Exception:
            pass

    with wave.open(fname, "wb") as wf:
        wf.setnchannels(channels); wf.setsampwidth(2); wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
    results[label] = {"ok": True, "error": None, "peak": peak, "file": fname}


def main():
    log("=" * 64)
    log(f"Krisp dual-capture probe   {datetime.now().isoformat(timespec='seconds')}")
    log("=" * 64)

    pa = pyaudio.PyAudio()
    try:
        devices = list_inputs(pa)
    except Exception as exc:
        log(f"Could not read audio devices (WASAPI required, Windows only): {exc}")
        _finish()
        return

    log("\nInput devices found:")
    for idx, name, ch, rate in devices:
        tag = "  <-- looks like KRISP" if "krisp" in name.lower() else ""
        log(f"  [{idx}]  {name}   ({ch}ch @ {rate}Hz){tag}")

    krisp = next((d for d in devices if "krisp" in d[1].lower()), None)
    physical = next((d for d in devices if "krisp" not in d[1].lower()), None)

    if not physical:
        log("\nNo physical microphone found. Plug in a headset and retry.")
        _finish(); return
    if not krisp:
        log("\nNo 'Krisp' device found. Is Krisp installed AND running?")
        log("Tip: open Krisp first, then run this probe.")
        # still probe the physical mic alone so the run isn't wasted
        krisp = None

    log(f"\nRecording {RECORD_SECONDS}s on BOTH at once — TALK into the headset now...\n")

    results = {}
    threads = []
    pidx, pname, pch, prate = physical
    threads.append(threading.Thread(target=record,
                   args=(pa, pidx, pch, prate, "raw_physical", results)))
    if krisp:
        kidx, kname, kch, krate = krisp
        threads.append(threading.Thread(target=record,
                       args=(pa, kidx, kch, krate, "krisp", results)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()
    pa.terminate()

    log("-" * 64)
    log("RESULTS")
    log("-" * 64)

    def verdict(label, devname):
        r = results.get(label)
        if not r:
            log(f"{label}: (not run)"); return False
        if not r["ok"]:
            log(f"{label}  [{devname}]")
            log(f"   FAILED to open/record: {r['error']}")
            return False
        loud = "LOUD (real sound)" if r["peak"] > 200 else \
               ("quiet (some signal)" if r["peak"] > 30 else "SILENT (no audio!)")
        log(f"{label}  [{devname}]")
        log(f"   recorded OK  ->  {os.path.basename(r['file'])}   loudness={r['peak']}  ({loud})")
        return r["peak"] > 30

    raw_ok = verdict("raw_physical", pname)
    krisp_ok = verdict("krisp", krisp[1]) if krisp else None

    log("-" * 64)
    if krisp is None:
        log("VERDICT: Krisp not detected — only the physical mic was tested.")
        log("Install/launch Krisp, then run again to test true parallel capture.")
    elif raw_ok and krisp_ok:
        log("VERDICT: PASS  ✅   Both streams recorded real audio AT THE SAME TIME.")
        log("Krisp shares the mic — dual raw+krisp recording is safe to build.")
    elif krisp_ok and not raw_ok:
        log("VERDICT: FAIL  ❌   Raw physical mic was SILENT or blocked while Krisp ran.")
        log("Likely Krisp holds the mic in EXCLUSIVE mode — we need a workaround first.")
    else:
        log("VERDICT: INCONCLUSIVE — check the loudness numbers above.")
        log("Make sure you were talking into the headset during the 5 seconds.")
    log("-" * 64)
    _finish()


def _finish():
    path = os.path.join(OUT_DIR, "krisp_probe_result.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(_lines))
        print(f"\nSaved results to: {path}")
    except Exception as exc:
        print(f"(could not write result file: {exc})")
    # Keep the window open when double-clicked as an .exe.
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
