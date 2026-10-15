# -*- coding: utf-8 -*-
"""Photograph every Focus scenario in headless Edge, at its real pixel size.

    python focus_dev/shoot_harness.py <out_dir> [scenario ...]

Uses the Edge already on every TIG PC - no Playwright, no download. Each
scenario is drawn by focus/app.js from the fixtures in focus_dev/scenarios.js,
the same files the widget loads, so these pictures are the panel itself.
"""
import re
import subprocess
import sys
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
HERE = Path(__file__).resolve().parent


def scenarios():
    text = (HERE / "scenarios.js").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"S\['([a-z0-9-]+)'\]\s*=\s*\{\s*size:\s*\[(\d+),\s*(\d+)\]", text):
        out.append((m.group(1), int(m.group(2)), int(m.group(3))))
    # summary-all reuses another scenario's steps and has no size of its own
    if "summary-all" not in [n for n, *_ in out]:
        out.append(("summary-all", 360, 900))
    return out


def shoot(name, w, h, out_dir):
    url = (HERE / "harness.html").as_uri() + "?s=" + name
    png = out_dir / f"{name}.png"
    if png.exists():
        png.unlink()
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars",
           # Taller than the panel: headless Edge's visible area is a little
           # shorter than the window, which clipped the panel's last rows.
           "--force-device-scale-factor=1", f"--window-size={max(w, 800)},{h + 120}",
           "--virtual-time-budget=3000", "--allow-file-access-from-files",
           f"--screenshot={png}", url]
    subprocess.run(cmd, capture_output=True, timeout=60)
    if not png.exists():
        return False
    # Crop to the panel's real width (the harness pins it at the left edge).
    from PyQt6.QtGui import QImage
    img = QImage(str(png))
    img.copy(0, 0, w, h).save(str(png))
    return True


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "shots"
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(sys.argv[2:])
    ok = bad = 0
    for name, w, h in scenarios():
        if wanted and name not in wanted:
            continue
        if shoot(name, w, h, out_dir):
            ok += 1
        else:
            bad += 1
            print("FAILED", name)
    print(f"{ok} shot, {bad} failed -> {out_dir}")


if __name__ == "__main__":
    main()
