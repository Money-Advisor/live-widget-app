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


# ── remembered mic selection (agent's last manual pick) ──────────────

def test_saved_mic_selects_its_index():
    names = ["Microphone Array", "Headset (PLT Focus Hands-Free AG Audio)"]
    assert main._index_for_saved_mic(names, "Headset (PLT Focus Hands-Free AG Audio)") == 1


def test_saved_mic_not_in_list_defaults_to_zero():
    names = ["Microphone Array", "Headset (Realtek)"]
    assert main._index_for_saved_mic(names, "Old Unplugged Headset") == 0


def test_blank_saved_mic_defaults_to_zero():
    names = ["Microphone Array", "Headset (Realtek)"]
    assert main._index_for_saved_mic(names, "") == 0


def test_empty_device_list_returns_zero():
    assert main._index_for_saved_mic([], "anything") == 0


def test_on_mic_selected_persists_device_name():
    """User picking a mic saves its name so the next launch restores it."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = main.MainWindow()
    w._settings.remove("audio/mic_name")
    w._mic_devices = [{"name": "Microphone Array"},
                      {"name": "Headset (PLT Focus Hands-Free AG Audio)"}]

    w._on_mic_selected(1)

    assert w._settings.value("audio/mic_name", "") == "Headset (PLT Focus Hands-Free AG Audio)"
    w._settings.remove("audio/mic_name")


    # ── speaker auto-follow (default output) + remembered override ──

def test_pick_format_returns_first_supported():
    # Picks the first (channels, rate) combo the device actually supports —
    # so we capture at the device's true format instead of a wrong guess.
    supported = {(2, 48000)}
    chosen = main._pick_stream_format(lambda ch, r: (ch, r) in supported,
                                      [2, 1], [44100, 48000])
    assert chosen == (2, 48000)


def test_pick_format_prefers_earlier_candidate():
    # Both supported -> earliest candidate wins (device-native is listed first).
    supported = {(2, 48000), (1, 16000)}
    chosen = main._pick_stream_format(lambda ch, r: (ch, r) in supported,
                                      [2, 1], [48000, 16000])
    assert chosen == (2, 48000)


def test_pick_format_none_when_nothing_supported():
    chosen = main._pick_stream_format(lambda ch, r: False, [2, 1], [48000, 44100])
    assert chosen is None


def test_saved_mic_matches_despite_curly_apostrophe():
    # AirPods names use a typographic apostrophe; the saved string may differ by
    # that one char. Tolerant matching must still re-select the headset.
    names = ["Microphone Array (Intel)", "Headset (Faseeh’s AirPods)"]  # curly ’
    assert main._index_for_saved_mic(names, "Headset (Faseeh's AirPods)") == 1  # straight '


def test_saved_mic_matches_case_insensitive():
    names = ["Microphone Array", "Headset (Realtek)"]
    assert main._index_for_saved_mic(names, "headset (realtek)") == 1


def test_saved_mic_matches_substring_profile_suffix():
    # Bluetooth profile changes can append/trim a suffix between sessions.
    names = ["Microphone Array", "Headset (AirPods) Hands-Free"]
    assert main._index_for_saved_mic(names, "Headset (AirPods)") == 1


def test_saved_speaker_wins():
    names = ["Speakers (Realtek) [Loopback]", "Headset (PLT) [Loopback]"]
    assert main._index_for_saved_or_default_spk(
        names, "Headset (PLT) [Loopback]", "Speakers (Realtek)") == 1


def test_speaker_follows_default_output_when_no_saved():
    # Loopback names embed the output device name; match the default output.
    names = ["Speakers (Realtek) [Loopback]", "Headset (PLT Focus) [Loopback]"]
    assert main._index_for_saved_or_default_spk(
        names, "", "Headset (PLT Focus)") == 1


def test_speaker_defaults_to_zero_when_no_saved_no_match():
    names = ["Speakers (Realtek) [Loopback]", "Monitor (HDMI) [Loopback]"]
    assert main._index_for_saved_or_default_spk(names, "", "Unknown Device") == 0


def test_speaker_empty_list_returns_zero():
    assert main._index_for_saved_or_default_spk([], "x", "y") == 0


def test_saved_speaker_missing_falls_back_to_default_output():
    names = ["Speakers (Realtek) [Loopback]", "Headset (PLT) [Loopback]"]
    # saved device no longer connected -> follow the default output instead
    assert main._index_for_saved_or_default_spk(
        names, "Unplugged Dock [Loopback]", "Headset (PLT)") == 1


def test_on_mic_selected_ignores_out_of_range_index():
    """A placeholder/empty selection (no real device) saves nothing."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = main.MainWindow()
    w._settings.remove("audio/mic_name")
    w._mic_devices = []

    w._on_mic_selected(0)   # e.g. the "no microphone devices found" placeholder

    assert (w._settings.value("audio/mic_name", "") or "") == ""


def test_rescan_skips_while_recording(monkeypatch):
    """Never recreate PyAudio / re-enumerate during an active recording — it
    would break the live audio streams."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = main.MainWindow()
    w._recording = True
    called = {"n": 0}
    monkeypatch.setattr(w, "_enumerate_devices", lambda: called.__setitem__("n", called["n"] + 1))

    w._rescan_devices()

    assert called["n"] == 0


def test_rescan_reenumerates_when_idle(monkeypatch):
    """When idle, rescan re-enumerates so a hot-plugged device shows up."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = main.MainWindow()
    w._recording = False
    # Avoid creating a second real PyAudio instance in the test.
    monkeypatch.setattr(main.pyaudio, "PyAudio", lambda: object())
    called = {"n": 0}
    monkeypatch.setattr(w, "_enumerate_devices", lambda: called.__setitem__("n", called["n"] + 1))

    w._rescan_devices()

    assert called["n"] == 1


def test_gate_runs_rescan_poll_then_stops_when_cleared():
    """The hot-plug poll runs while the setup gate is open and stops once cleared."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = main.MainWindow()
    w.show()
    w._mic_devices = [{"name": "Headset (Realtek)"}]

    w._show_mic_gate()
    assert w._rescan_timer.isActive()

    w._gate_combo.setCurrentIndex(0)
    w._confirm_gate_mic()
    assert not w._rescan_timer.isActive()
    w._settings.remove("audio/mic_name")


def test_on_spk_selected_persists_device_name():
    """User picking a speaker saves its name so it's remembered next launch."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = main.MainWindow()
    w._settings.remove("audio/spk_name")
    w._spk_devices = [{"name": "Speakers (Realtek) [Loopback]"},
                      {"name": "Headset (PLT) [Loopback]"}]

    w._on_spk_selected(1)

    assert w._settings.value("audio/spk_name", "") == "Headset (PLT) [Loopback]"
    w._settings.remove("audio/spk_name")
