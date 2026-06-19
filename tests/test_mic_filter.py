"""Krisp (and other processed/virtual mics) must never be offered as a record
source — they carry noise-cancelled / accent-converted audio, not the raw agent
voice the audit pipeline needs."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless Qt

import main


def test_krisp_microphone_is_excluded():
    assert main._is_excluded_mic("Krisp Microphone") is True


def test_krisp_match_is_case_insensitive():
    assert main._is_excluded_mic("KRISP microphone (Krisp Audio)") is True


def test_real_microphone_is_kept():
    assert main._is_excluded_mic("Headset Microphone (Realtek Audio)") is False


def test_blank_name_is_kept():
    assert main._is_excluded_mic("") is False


def test_filter_drops_krisp_keeps_physical():
    devices = [
        {"name": "Krisp Microphone"},
        {"name": "Headset (Realtek)"},
    ]
    kept = [d for d in devices if not main._is_excluded_mic(d["name"])]
    assert [d["name"] for d in kept] == ["Headset (Realtek)"]
