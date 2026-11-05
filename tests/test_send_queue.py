"""The send queue: order is everything, and nothing may be lost.

Capture threads put frames in; one sender takes them out. A frame out of order puts a
customer's words in the wrong place in the recording, and a 'stop' that overtakes the
audio makes the server close the WAV before the last of the call arrives. These tests
pin the order across memory, the backlog file and back, under real concurrency.
"""
import os
import random
import struct
import threading

import pytest

import send_queue
from send_queue import AUDIO, CONTROL, SendQueue


def _drain(q, n, timeout=5.0):
    out = []
    while len(out) < n:
        item = q.get(timeout=timeout)
        assert item is not None, f"queue went quiet after {len(out)} of {n} frames"
        out.append(item)
        q.task_done()
    return out


def test_frames_come_out_in_the_order_they_went_in(tmp_path):
    q = SendQueue(tmp_path / "q.spool")
    items = [(AUDIO, b"a%d" % i) if i % 7 else (CONTROL, b"c%d" % i) for i in range(500)]
    for k, p in items:
        q.put(k, p)
    assert _drain(q, len(items)) == items
    assert q.empty()
    assert q.audio_bytes == 0


def test_a_backlog_over_the_memory_limit_moves_to_the_file_and_back_in_order(tmp_path):
    path = tmp_path / "q.spool"
    q = SendQueue(path, max_memory_bytes=2000)
    items = [(AUDIO, bytes([i % 251]) * 300) for i in range(40)]
    for k, p in items:
        q.put(k, p)
    assert q.spills == 1
    assert path.exists(), "the backlog never went to disk"
    assert _drain(q, len(items)) == items
    assert not path.exists(), "the backlog file was left behind after it was sent"
    assert q.audio_bytes == 0


def test_order_holds_with_producers_and_the_sender_running_at_once(tmp_path):
    """Two capture threads (mic, speaker) and the sender, all at full speed in bursts,
    with a memory limit small enough that the backlog goes to the file and comes back
    to memory many times over."""
    import time
    q = SendQueue(tmp_path / "q.spool", max_memory_bytes=5000)
    per = 3000
    got = []

    def produce(tag):
        rnd = random.Random(tag)
        for i in range(per):
            q.put(AUDIO, tag + struct.pack("<I", i) + b"x" * rnd.randint(0, 600))
            if i % 150 == 149:
                time.sleep(0.03)             # a pause lets the sender catch up

    def consume():
        while len(got) < 2 * per:
            item = q.get(timeout=5)
            assert item is not None
            got.append(item[1][:5])
            q.task_done()

    c = threading.Thread(target=consume)
    c.start()
    ps = [threading.Thread(target=produce, args=(t,)) for t in (b"M", b"S")]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    c.join(30)
    assert len(got) == 2 * per
    for tag in (b"M", b"S"):
        seq = [struct.unpack("<I", g[1:])[0] for g in got if g[:1] == tag]
        assert seq == list(range(per)), f"{tag} frames reordered or lost"
    assert q.spills >= 2, "the test never exercised the file"


def test_a_disk_that_refuses_writes_keeps_the_frames_in_memory_in_order(tmp_path, monkeypatch):
    """A full disk must never cost a frame while there is memory left."""
    q = SendQueue(tmp_path / "q.spool", max_memory_bytes=1000)
    items = [(AUDIO, bytes([i]) * 400) for i in range(10)]
    for k, p in items[:5]:
        q.put(k, p)                          # spilled to the file on the 3rd

    real_write = SendQueue._write_locked

    def refuse(self, kind, payload):
        print("[send] backlog file write failed (test) - keeping it in memory")
        return False

    monkeypatch.setattr(SendQueue, "_write_locked", refuse)
    for k, p in items[5:8]:
        q.put(k, p)                          # disk "full": these stay in memory
    monkeypatch.setattr(SendQueue, "_write_locked", real_write)
    for k, p in items[8:]:
        q.put(k, p)                          # disk back - must NOT jump ahead of 5-7
    assert _drain(q, len(items)) == items


def test_a_status_frame_goes_first_without_disturbing_the_rest(tmp_path):
    q = SendQueue(tmp_path / "q.spool")
    for i in range(5):
        q.put(AUDIO, b"%d" % i)
    q.get(timeout=1)                         # the sender is busy with frame 0
    q.task_done()
    q.put_urgent(CONTROL, b"status")
    assert q.get(timeout=1) == (CONTROL, b"status")
    q.task_done()
    assert [p for _, p in _drain(q, 4)] == [b"1", b"2", b"3", b"4"]


def test_get_waits_then_gives_up_quietly_when_there_is_nothing(tmp_path):
    q = SendQueue(tmp_path / "q.spool")
    assert q.get(timeout=0.05) is None
    assert q.empty() and q.idle()


def test_idle_is_false_while_the_sender_holds_a_frame(tmp_path):
    """flush() at quit waits for 'empty AND idle' - empty alone would let the process
    end while session_end is still on its way out."""
    q = SendQueue(tmp_path / "q.spool")
    q.put(CONTROL, b"end")
    assert q.get(timeout=1) is not None
    assert q.empty() and not q.idle()
    q.task_done()
    assert q.idle()


def test_an_unreadable_backlog_file_is_reported_not_spun_on(tmp_path, capsys):
    path = tmp_path / "q.spool"
    q = SendQueue(path, max_memory_bytes=500)
    for i in range(6):
        q.put(AUDIO, bytes([i]) * 200)
    assert path.exists()
    with open(path, "r+b") as f:             # tear the file mid-record
        f.truncate(300)
    seen = []
    for _ in range(10):
        item = q.get(timeout=0.2)
        if item is not None:
            seen.append(item)
            q.task_done()
    assert q.lost_records > 0
    assert "could not read the backlog file back" in capsys.readouterr().out
    assert q.empty()


def test_discard_deletes_the_backlog_file(tmp_path):
    path = tmp_path / "q.spool"
    q = SendQueue(path, max_memory_bytes=100)
    for i in range(5):
        q.put(AUDIO, b"z" * 80)
    assert path.exists()
    q.discard()
    assert not path.exists()
    assert q.empty() and q.audio_bytes == 0


def test_the_backlog_file_is_covered_by_the_spool_purge():
    """It holds call audio (PII); the widget's 7-day purge globs *.spool."""
    import main
    import inspect
    src = inspect.getsource(main.AudioStreamer._start_sender)
    assert '.queue.spool"' in src
    assert 'glob("*.spool")' in inspect.getsource(main.purge_old_spools)
