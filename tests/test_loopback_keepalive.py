"""The customer channel must stay on the wall clock, however the loopback behaves.

Background. WASAPI loopback only produces samples while its render endpoint is
actually rendering. When the softphone plays nothing the loopback delivers NOTHING —
not silence, no samples — and `stream.read()` blocks. Measured on this hardware:
15.0s of capture with nothing playing yielded 0.00s of audio. Those lost seconds
never reach the customer WAV, so it comes out shorter than the mic WAV; the post-call
merge lines the two up at sample 0, and every lost second slides the customer's speech
earlier until the agent's question audibly lands after the customer's answer. Two real
calls were short by 10s and 51s.

Two defences, tested here:
  1. RenderKeepAlive holds the render endpoint open with silence, so it never starves.
  2. RecordingThread fills any gap it still sees, so the channel tracks the clock even
     if the keep-alive could not be started.

The safety property matters as much as the fix: the gap-fill must NEVER fabricate time
when the stall was ours (a slow socket send) rather than the device's, because inserted
silence would then push the channel late instead of keeping it honest.
"""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

import main


# ── mapping a loopback back to the render endpoint it taps ────────────

def _dev(name, index, out=2, inp=0, loop=False):
    return {"name": name, "index": index, "maxOutputChannels": out,
            "maxInputChannels": inp, "isLoopbackDevice": loop,
            "defaultSampleRate": 48000.0}


DEVICES = [
    _dev("Speakers (2- Realtek(R) Audio)", 12),
    _dev("Headphones (PLT Focus)", 13),
    _dev("Headset (PLT Focus)", 14, out=0, inp=1),
    _dev("Speakers (2- Realtek(R) Audio) [Loopback]", 16, out=0, inp=2, loop=True),
    _dev("Headphones (PLT Focus) [Loopback]", 17, out=0, inp=2, loop=True),
]


def test_loopback_maps_to_its_render_endpoint():
    assert main._render_index_for_loopback(
        DEVICES, "Headphones (PLT Focus) [Loopback]") == 13


def test_each_loopback_maps_to_its_own_device_not_the_first():
    assert main._render_index_for_loopback(
        DEVICES, "Speakers (2- Realtek(R) Audio) [Loopback]") == 12


def test_input_only_device_is_never_chosen_as_a_render_target():
    """'Headset (PLT Focus)' is the MIC — it has no output channels, so silence can
    never be written to it. Better to return -1 and fall back to the gap-fill than to
    hand RenderKeepAlive a device that will only ever raise."""
    idx = main._render_index_for_loopback(DEVICES, "Headset (PLT Focus) [Loopback]")
    assert idx != 14
    assert idx == -1


def test_a_loopback_is_never_matched_as_its_own_render_endpoint():
    idx = main._render_index_for_loopback(DEVICES, "Headphones (PLT Focus) [Loopback]")
    assert idx not in (16, 17)


def test_renamed_bluetooth_profile_still_matches_by_substring():
    """Same tolerance _match_device_index already relies on: Windows appends profile
    suffixes to Bluetooth endpoints between sessions."""
    devs = [_dev("Headphones (PLT Focus) Hands-Free AG", 20)]
    assert main._render_index_for_loopback(
        devs, "Headphones (PLT Focus) [Loopback]") == 20


def test_curly_apostrophe_variance_still_matches():
    devs = [_dev("Faseeh’s AirPods", 21)]
    assert main._render_index_for_loopback(devs, "Faseeh's AirPods [Loopback]") == 21


def test_unmatchable_loopback_returns_minus_one_rather_than_guessing():
    assert main._render_index_for_loopback(DEVICES, "Some Other Thing [Loopback]") == -1


def test_blank_and_empty_inputs_are_safe():
    assert main._render_index_for_loopback(DEVICES, "") == -1
    assert main._render_index_for_loopback([], "Headphones (PLT Focus) [Loopback]") == -1
    assert main._render_index_for_loopback(DEVICES, " [Loopback]") == -1


def test_name_without_the_loopback_suffix_still_resolves():
    assert main._render_index_for_loopback(DEVICES, "Headphones (PLT Focus)") == 13


# ── the gap-fill decision ─────────────────────────────────────────────

CHUNK_S = 0.085   # 4096 frames @ 48 kHz


def test_a_chunk_still_filling_is_not_a_gap():
    """In normal running we are always up to one chunk behind — the chunk has to fill
    before it can be read. Treating that as a gap would fill silence continuously."""
    assert main.RecordingThread._gap_to_fill(CHUNK_S, CHUNK_S) == 0.0
    assert main.RecordingThread._gap_to_fill(0.0, CHUNK_S) == 0.0


def test_jitter_below_tolerance_fills_nothing():
    assert main.RecordingThread._gap_to_fill(CHUNK_S + 0.2, CHUNK_S) == 0.0


def test_starved_device_is_filled_minus_the_chunk_of_slack():
    fill = main.RecordingThread._gap_to_fill(3.0 + CHUNK_S, CHUNK_S)
    assert fill == pytest.approx(3.0, abs=0.01)


def test_fill_is_capped():
    fill = main.RecordingThread._gap_to_fill(9999.0, CHUNK_S)
    assert fill == main.RecordingThread.GAP_FILL_CAP_S


def test_negative_deficit_fills_nothing():
    """A device running slightly fast puts us ahead. Never trim — only ever pad."""
    assert main.RecordingThread._gap_to_fill(-1.0, CHUNK_S) == 0.0


# ── emitting the silence ──────────────────────────────────────────────

def _thread(send, **kw):
    kw.setdefault("device_index", 1)
    kw.setdefault("stream_type", "speaker")
    kw.setdefault("sample_rate", 48000)
    kw.setdefault("channels", 2)
    return main.RecordingThread(send_callback=send, **kw)


def test_emit_silence_sends_exactly_the_requested_duration():
    sent = []
    t = _thread(lambda st, d: sent.append(d))
    frames = t._emit_silence(1.0, 48000, frame_bytes=4)
    assert frames == 48000
    assert sum(len(d) for d in sent) == 48000 * 4
    assert all(set(d) == {0} for d in sent)


def test_emit_silence_uses_the_normal_audio_path_so_pause_and_spool_apply():
    seen = []
    t = _thread(lambda st, d: seen.append(st))
    t._emit_silence(0.5, 48000, frame_bytes=4)
    assert seen and set(seen) == {"speaker"}


def test_emit_silence_chunks_at_the_wire_size():
    sizes = []
    t = _thread(lambda st, d: sizes.append(len(d)))
    t._emit_silence(1.0, 48000, frame_bytes=4)
    assert all(s <= main.CHUNK * 4 for s in sizes)
    assert sizes[0] == main.CHUNK * 4


def test_emit_silence_accumulates_seconds_but_does_not_count_gaps():
    """A dead device is topped up repeatedly for what is ONE gap, so counting belongs
    to the loop. Counting here produced a log line every 0.25s on real hardware."""
    t = _thread(lambda st, d: None)
    t._emit_silence(0.5, 48000, frame_bytes=4)
    t._emit_silence(0.25, 48000, frame_bytes=4)
    assert t.seconds_filled == pytest.approx(0.75, abs=0.001)
    assert t.gaps_filled == 0


def test_emit_silence_stops_when_the_call_ends_mid_fill():
    sent = []
    t = _thread(lambda st, d: sent.append(d))
    t._stop_event.set()
    assert t._emit_silence(30.0, 48000, frame_bytes=4) == 0
    assert sent == []


# ── the keep-alive ────────────────────────────────────────────────────

class _StubPA:
    """Stands in for the capture thread's PyAudio handle, which the keep-alive
    borrows rather than creating its own (see RenderKeepAlive)."""

    def __init__(self, stream=None, fail=False):
        self.stream, self.fail, self.kw = stream, fail, None
        self.terminated = False

    def open(self, **kw):
        if self.fail:
            raise OSError("device in use")
        self.kw = kw
        return self.stream

    def terminate(self):
        self.terminated = True


def test_keepalive_declines_an_unknown_render_device():
    ka = main.RenderKeepAlive(_StubPA(), -1)
    assert ka.start() is False
    assert ka.active is False


def test_keepalive_declines_without_a_pyaudio_handle():
    assert main.RenderKeepAlive(None, 13).start() is False


def test_keepalive_failure_is_survivable():
    """A refused endpoint must degrade to 'no keep-alive', never break the call."""
    ka = main.RenderKeepAlive(_StubPA(fail=True), 3)
    assert ka.start() is False
    assert ka.active is False


def test_keepalive_writes_silence_to_the_render_device():
    import time as _t
    written = []

    class Stream:
        def write(self, data): written.append(data)
        def stop_stream(self): pass
        def close(self): pass

    pa = _StubPA(Stream())
    ka = main.RenderKeepAlive(pa, 13, channels=2, rate=48000)
    assert ka.start() is True
    for _ in range(200):
        if written:
            break
        _t.sleep(0.01)
    ka.stop()
    assert written, "keep-alive never wrote to the render endpoint"
    assert set(written[0]) == {0}, "keep-alive must be inaudible digital silence"
    assert pa.kw["output"] is True
    assert pa.kw["output_device_index"] == 13
    assert ka.active is False


def test_keepalive_never_terminates_the_borrowed_pyaudio_handle():
    """The capture thread owns that handle and still needs it. Terminating PortAudio
    out from under a live capture is how this crashed while being built."""
    class Stream:
        def write(self, data): pass
        def stop_stream(self): pass
        def close(self): pass

    pa = _StubPA(Stream())
    ka = main.RenderKeepAlive(pa, 13)
    ka.start()
    ka.stop()
    assert pa.terminated is False


def test_keepalive_stop_is_idempotent():
    ka = main.RenderKeepAlive(_StubPA(), -1)
    ka.stop()
    ka.stop()
    assert ka.active is False


# ── end to end: the capture loop against a starving device ────────────

class Clock:
    """Deterministic stand-in for time.monotonic, advanced by the fake device."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeDevice:
    """A capture endpoint that can stop producing — the whole point of these tests.

    `script` is [(seconds, producing?), ...]. While producing it accrues frames at the
    nominal rate; while not, it accrues nothing at all and get_read_available() returns
    0 forever, which is exactly what a WASAPI loopback does once the softphone stops
    rendering. Simulated time advances on each poll, so the test runs instantly.
    """

    TICK = 0.01

    def __init__(self, clock, rate, channels, script, stop_event):
        self.clock, self.rate, self.channels = clock, rate, channels
        self.script, self.stop_event = list(script), stop_event
        self.avail = 0.0
        self.seg = 0
        self.left = self.script[0][0] if self.script else 0.0

    def _tick(self):
        dt = self.TICK
        while dt > 1e-12 and self.seg < len(self.script):
            take = min(dt, self.left)
            if self.script[self.seg][1]:
                self.avail += take * self.rate
            self.clock.advance(take)
            self.left -= take
            dt -= take
            if self.left <= 1e-12:
                self.seg += 1
                if self.seg < len(self.script):
                    self.left = self.script[self.seg][0]
        if self.seg >= len(self.script):
            self.stop_event.set()

    def stall_but_keep_producing(self, seconds):
        """OUR stall: wall time passes while the device happily buffers through it."""
        self.clock.advance(seconds)
        self.avail += seconds * self.rate

    def get_read_available(self):
        self._tick()
        return int(self.avail)

    def read(self, n, exception_on_overflow=False):
        n = min(n, int(self.avail))
        self.avail -= n
        return b"\x11\x22" * (n * self.channels)

    def stop_stream(self):
        pass

    def close(self):
        pass


class BlockingOnlyDevice(FakeDevice):
    """A backend too old to report availability — must fall back, not crash."""

    def get_read_available(self):
        raise OSError("not supported")

    def read(self, n, exception_on_overflow=False):
        self._tick()
        self.avail = max(0.0, self.avail - n)
        return b"\x11\x22" * (n * self.channels)


class FakePA:
    def __init__(self, stream, rate, channels):
        self._stream, self.rate, self.channels = stream, rate, channels
        self.terminated = False

    def is_format_supported(self, rate, **kw):
        return rate == self.rate and kw.get("input_channels") == self.channels

    def open(self, **kw):
        return self._stream

    def terminate(self):
        self.terminated = True


def _run_capture(monkeypatch, script, rate=48000, channels=2, device_cls=FakeDevice,
                 send_hook=None):
    clock = Clock()
    monkeypatch.setattr(main, "_now", clock)
    # Real sleeping would make these tests take as long as the calls they simulate;
    # simulated time is advanced by the device instead.
    monkeypatch.setattr(main.RecordingThread, "POLL_S", 0.0)
    sent = []
    holder = {}

    def send(stream_type, data):
        sent.append(data)
        if send_hook is not None:
            send_hook(holder["dev"], len(sent))

    t = _thread(send, sample_rate=rate, channels=channels, is_loopback=True,
                keepalive_device_index=-1)
    dev = device_cls(clock, rate, channels, script, t._stop_event)
    holder["dev"] = dev
    pa = FakePA(dev, rate, channels)
    monkeypatch.setattr(main.pyaudio, "PyAudio", lambda: pa)
    t._start_ack.set()
    t0 = clock.t
    t.run()
    audio_seconds = sum(len(d) for d in sent) / float(2 * channels) / rate
    return t, sent, audio_seconds, clock.t - t0, pa


def test_healthy_capture_tracks_the_clock_and_fills_nothing(monkeypatch):
    t, sent, audio_s, elapsed, _ = _run_capture(monkeypatch, [(20.0, True)])
    assert t.gaps_filled == 0
    assert audio_s == pytest.approx(elapsed, abs=0.2)


def test_starving_loopback_is_brought_back_onto_the_clock(monkeypatch):
    """The bug, reproduced: two dead stretches totalling 7s inside a ~13s capture.
    Unfilled, the channel would be 7s short and everything after the first stretch
    would sit 7s early against the agent."""
    script = [(2.0, True), (4.0, False), (2.0, True), (3.0, False), (2.0, True)]
    t, sent, audio_s, elapsed, _ = _run_capture(monkeypatch, script)
    assert t.gaps_filled >= 2
    assert audio_s == pytest.approx(elapsed, abs=0.5), (
        "customer channel must be as long as the call, or the merge misaligns it")


def test_a_device_that_never_resumes_is_still_kept_on_the_clock(monkeypatch):
    """THE case that actually happens, and the one a blocking read cannot handle: the
    customer hangs up, the softphone stops rendering, and the loopback is finished for
    the rest of the call. Two real recordings ended 10s and 51s short exactly here."""
    t, sent, audio_s, elapsed, _ = _run_capture(
        monkeypatch, [(3.0, True), (30.0, False)])
    assert t.gaps_filled >= 1
    assert t.seconds_filled > 25.0
    assert audio_s == pytest.approx(elapsed, abs=0.5)


def test_a_dead_device_does_not_strand_the_thread(monkeypatch):
    """A blocking read on a dead loopback never returns, so _stop_event went unseen and
    the thread outlived the call — _stop_recording's 1.5s join just timed out."""
    clock = Clock()
    monkeypatch.setattr(main, "_now", clock)
    monkeypatch.setattr(main.RecordingThread, "POLL_S", 0.0)
    seen = []
    t = _thread(lambda st, d: seen.append(d), is_loopback=True,
                keepalive_device_index=-1)
    dev = FakeDevice(clock, 48000, 2, [(1.0, True), (600.0, False)], t._stop_event)
    monkeypatch.setattr(main.pyaudio, "PyAudio", lambda: FakePA(dev, 48000, 2))
    t._start_ack.set()

    # Stop the capture partway through the dead stretch, the way the agent hanging up
    # does. The loop has to notice while the device is producing nothing at all.
    original = main.RecordingThread._emit_silence

    def stop_midway(self, seconds, rate, frame_bytes):
        out = original(self, seconds, rate, frame_bytes)
        if self.seconds_filled > 5.0:
            self._stop_event.set()
        return out

    monkeypatch.setattr(main.RecordingThread, "_emit_silence", stop_midway)
    t.run()
    assert t._stop_event.is_set()
    assert clock.t - 1000.0 < 500.0, "loop ran past the stop instead of exiting"


def test_silence_is_inserted_before_the_chunk_that_ends_the_gap(monkeypatch):
    """Ordering matters: the dead stretch happened BEFORE the resuming chunk, so the
    silence belongs in front of it. Put it after and the fix shifts audio the wrong way."""
    t, sent, _, _, _ = _run_capture(
        monkeypatch, [(1.0, True), (4.0, False), (1.0, True)])
    kinds = ["fill" if set(d) == {0} else "audio" for d in sent]
    first_fill = kinds.index("fill")
    assert "audio" in kinds[:first_fill]
    assert "audio" in kinds[first_fill:], "the resuming chunk must follow the silence"


def test_our_own_slow_send_never_fabricates_time(monkeypatch):
    """THE safety property. The socket stalls 5s on the 3rd send while the device keeps
    producing. The backlog is sitting in the stream, so get_read_available() hands it
    straight back and the fill branch is never reached. Inserting silence here would
    invent time and push the channel LATE — the very fault being fixed."""
    def hook(dev, n):
        if n == 3:
            dev.stall_but_keep_producing(5.0)

    t, sent, audio_s, elapsed, _ = _run_capture(
        monkeypatch, [(20.0, True)], send_hook=hook)
    assert t.gaps_filled == 0, "silence was invented for a stall that was ours"
    assert audio_s == pytest.approx(elapsed, abs=0.3)


def test_mono_and_odd_rate_devices_are_handled(monkeypatch):
    t, sent, audio_s, elapsed, _ = _run_capture(
        monkeypatch, [(2.0, True), (5.0, False), (2.0, True)], rate=16000, channels=1)
    assert t.gaps_filled >= 1
    assert audio_s == pytest.approx(elapsed, abs=0.5)


def test_backend_without_availability_falls_back_to_blocking_reads(monkeypatch):
    """Degrade, never crash: an old backend loses gap detection but must still record."""
    t, sent, audio_s, elapsed, _ = _run_capture(
        monkeypatch, [(10.0, True)], device_cls=BlockingOnlyDevice)
    assert sent, "fallback path recorded nothing at all"
    assert t.gaps_filled == 0


def test_capture_still_releases_the_device(monkeypatch):
    """Regression guard: the poll loop sits inside the try/finally that releases the
    device. Leaking it would leave the headset held after the call."""
    t, sent, _, _, pa = _run_capture(monkeypatch, [(2.0, True)])
    assert pa.terminated is True


def test_one_dead_stretch_counts_as_one_gap_however_long(monkeypatch, capsys):
    """A dead device is topped up a fraction of a second at a time. Counting each
    top-up made a 51s tail print 200 log lines and report 200 'gaps'."""
    t, sent, audio_s, elapsed, _ = _run_capture(
        monkeypatch, [(2.0, True), (20.0, False)])
    assert t.gaps_filled == 1
    assert t.seconds_filled > 15.0
    out = capsys.readouterr().out
    assert out.count("device stopped producing") == 1


def test_each_separate_stretch_counts_once(monkeypatch):
    t, sent, audio_s, elapsed, _ = _run_capture(
        monkeypatch,
        [(2.0, True), (4.0, False), (2.0, True), (4.0, False), (2.0, True)])
    assert t.gaps_filled == 2


def test_a_gap_still_open_at_the_end_is_reported(monkeypatch, capsys):
    """The common case: customer hangs up, loopback never returns. The summary has to
    survive the loop exiting mid-gap or the worst gaps are the ones never logged."""
    _run_capture(monkeypatch, [(2.0, True), (20.0, False)])
    out = capsys.readouterr().out
    assert "call ended" in out
    assert "across 1 gap(s) this call" in out


# ── PortAudio init is not thread-safe ─────────────────────────────────

def test_pyaudio_construction_is_serialised(monkeypatch):
    """Both RecordingThreads construct a PyAudio handle as their first act, and they
    are started back to back. Doing that concurrently segfaults the interpreter —
    reproduced 5 times out of 5 on real hardware, versus never when sequential. A crash
    there takes the whole widget down mid-call with nothing to show for it.
    """
    import threading
    import time as _t

    inside = []
    overlapped = []

    class SlowPA:
        def __init__(self):
            inside.append(1)
            if len(inside) > 1:
                overlapped.append(True)
            _t.sleep(0.05)
            inside.pop()

        def terminate(self):
            pass

    monkeypatch.setattr(main.pyaudio, "PyAudio", SlowPA)
    threads = [threading.Thread(target=lambda: main._end_pyaudio(main._new_pyaudio()))
               for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlapped == [], "two threads were inside Pa_Initialize at once"


def test_end_pyaudio_tolerates_none_and_failures():
    """Teardown runs in a finally on every error path; it may never raise."""
    class Boom:
        def terminate(self): raise OSError("already gone")

    main._end_pyaudio(None)
    main._end_pyaudio(Boom())


# ── both channels must start at the same instant ──────────────────────

def _run_with_ref(monkeypatch, open_delay, script=((5.0, True),), rate=48000,
                  channels=2):
    """Capture where the device takes `open_delay` seconds to open after start_ref."""
    clock = Clock()
    monkeypatch.setattr(main, "_now", clock)
    monkeypatch.setattr(main.RecordingThread, "POLL_S", 0.0)
    sent = []
    ref = clock.t

    class SlowToOpenPA(FakePA):
        def open(self, **kw):
            clock.advance(open_delay)          # PortAudio init + device open
            return self._stream

    t = _thread(lambda st, d: sent.append(d), sample_rate=rate, channels=channels,
                is_loopback=True, keepalive_device_index=-1, start_ref=ref)
    dev = FakeDevice(clock, rate, channels, list(script), t._stop_event)
    monkeypatch.setattr(main.pyaudio, "PyAudio",
                        lambda: SlowToOpenPA(dev, rate, channels))
    t._start_ack.set()
    t.run()
    lead_bytes = 0
    for d in sent:
        if set(d) != {0}:
            break
        lead_bytes += len(d)
    audio_s = sum(len(d) for d in sent) / float(2 * channels) / rate
    return t, lead_bytes / float(2 * channels) / rate, audio_s, clock.t - ref


def test_a_late_opening_stream_pads_the_difference(monkeypatch):
    """The loopback opened 0.5s before the mic on real hardware. Unpadded, that is a
    constant half-second of the agent sounding late, for the whole call."""
    t, lead_s, audio_s, elapsed = _run_with_ref(monkeypatch, open_delay=0.6)
    assert lead_s == pytest.approx(0.6, abs=0.1)
    assert audio_s == pytest.approx(elapsed, abs=0.2)


def test_a_promptly_opening_stream_pads_nothing(monkeypatch):
    t, lead_s, audio_s, elapsed = _run_with_ref(monkeypatch, open_delay=0.05)
    assert lead_s == 0.0


def test_the_padding_comes_before_any_real_audio(monkeypatch):
    """Padding placed after the first chunk would shift the channel the wrong way."""
    clock = Clock()
    monkeypatch.setattr(main, "_now", clock)
    monkeypatch.setattr(main.RecordingThread, "POLL_S", 0.0)
    sent = []
    ref = clock.t

    class SlowToOpenPA(FakePA):
        def open(self, **kw):
            clock.advance(1.0)
            return self._stream

    t = _thread(lambda st, d: sent.append(d), is_loopback=True,
                keepalive_device_index=-1, start_ref=ref)
    dev = FakeDevice(clock, 48000, 2, [(4.0, True)], t._stop_event)
    monkeypatch.setattr(main.pyaudio, "PyAudio", lambda: SlowToOpenPA(dev, 48000, 2))
    t._start_ack.set()
    t.run()
    kinds = ["fill" if set(d) == {0} else "audio" for d in sent]
    assert kinds[0] == "fill"
    assert "audio" in kinds


def test_without_a_start_ref_behaviour_is_unchanged(monkeypatch):
    """start_ref is optional; nothing outside _start_recording supplies one."""
    t, sent, audio_s, elapsed, _ = _run_capture(monkeypatch, [(5.0, True)])
    assert sent and set(sent[0]) != {0}


def test_both_channels_end_up_the_same_length(monkeypatch):
    """The property the whole fix exists for: two devices opening at different times,
    one of them starving, still produce two channels of equal length — which is what
    merge_to_stereo assumes when it lines them up at sample 0."""
    # Both channels run from the same start_ref to the same stop, 12s later. One opens
    # promptly and never starves; the other opens 0.9s late and dies for 4s mid-call.
    lengths = []
    for delay, script in ((0.1, [(11.9, True)]),
                          (0.9, [(3.0, True), (4.0, False), (4.1, True)])):
        t, lead_s, audio_s, elapsed = _run_with_ref(
            monkeypatch, open_delay=delay, script=script)
        assert elapsed == pytest.approx(12.0, abs=0.05)   # same call, same wall clock
        lengths.append(audio_s)
    assert lengths[0] == pytest.approx(lengths[1], abs=0.3), (
        f"channels differ by {abs(lengths[0] - lengths[1]):.2f}s — the merge would "
        f"pad the short one at the END and the call would drift")
