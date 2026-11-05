"""One call's outbound frames, in order, without ever making the capture wait.

Why this exists (Bilal, 4 Nov 2026): the capture threads used to send each chunk to
the recording server themselves. Windows keeps only about 0.175 s of captured sound
waiting for us (measured on the mic and the speaker loopback with the widget's own
open() settings), so whenever a send took longer than that - a busy network - the
sound captured in the meantime was thrown away by Windows, and the gap-fill pasted
exact digital silence in its place. Agents on 4 Nov lost up to 100% of the client's
side for minutes at a time while the headsets were working perfectly.

Now the capture threads only `put()` frames here, which never touches the network,
and ONE sender thread takes them off with `get()` in exactly the order they were put.
A slow connection makes the recording arrive late; it no longer makes it incomplete.

Memory first. Past `max_memory_bytes` (16 MB, about a minute of a call's audio) the
backlog moves to a file in the spool folder, so a long slowdown cannot eat the PC's
memory. Order is kept exactly by one rule: every frame in memory is newer than every
frame in the file. A spill moves ALL of memory into the file; while the file is in
use new frames go to the file too; and the file is emptied before memory is read
again. If the disk refuses a write, the frame stays in memory (newer than the file)
and nothing more goes to the file until it has been emptied - a frame is never lost
to a full disk while there is memory left.

The file holds call audio, so it is named `<session>.queue.spool`: the widget's
existing 7-day spool purge (`purge_old_spools`) covers it if a crash ever strands one.
"""
from __future__ import annotations

import collections
import os
import struct
import threading
from pathlib import Path

AUDIO = 0
CONTROL = 1

_HEAD = struct.Struct("<BI")   # kind, payload length


class SendQueue:
    """Thread-safe FIFO: many producers (`put`), one consumer (`get`)."""

    def __init__(self, spill_path, max_memory_bytes: int = 16 * 1024 * 1024):
        self._spill_path = Path(spill_path)
        self._max = int(max_memory_bytes)
        self._cv = threading.Condition()
        self._mem = collections.deque()      # (kind, payload), all newer than the file
        self._mem_bytes = 0
        self._urgent = collections.deque()   # out-of-band status frames, sent next
        self._in_file = 0                    # records written + flushed, not yet read
        self._w = None
        self._r = None
        self._spilling = False
        self._busy = False                   # the consumer holds a frame it took
        # Observability (read by the sender's backlog report and by tests).
        self.audio_bytes = 0                 # audio waiting, memory + file
        self.spills = 0
        self.lost_records = 0                # only on an unreadable spill file

    # ── producers ──────────────────────────────────────────────────────────
    def put(self, kind: int, payload: bytes) -> None:
        """Add a frame at the back. Never blocks on the network; a disk write happens
        only while a backlog is spilled, and is one small appended record."""
        with self._cv:
            if self._spilling and not self._mem:
                if not self._write_locked(kind, payload):
                    self._mem_append_locked(kind, payload)
            else:
                self._mem_append_locked(kind, payload)
                if not self._spilling and self._mem_bytes > self._max:
                    self._spill_locked()
            if kind == AUDIO:
                self.audio_bytes += len(payload)
            self._cv.notify()

    def put_urgent(self, kind: int, payload: bytes) -> None:
        """A frame that must not wait behind the backlog (a status report). Only for
        frames whose position in the stream does not matter."""
        with self._cv:
            self._urgent.append((kind, payload))
            self._cv.notify()

    # ── the one consumer ───────────────────────────────────────────────────
    def get(self, timeout: float | None = None):
        """The next frame in order as (kind, payload), or None if nothing arrived
        within `timeout` seconds."""
        with self._cv:
            if not self._cv.wait_for(
                    lambda: self._urgent or self._in_file or self._mem, timeout):
                return None
            self._busy = True
            if self._urgent:
                return self._urgent.popleft()
            if not self._in_file:
                kind, payload = self._mem.popleft()
                self._mem_bytes -= len(payload)
                if kind == AUDIO:
                    self.audio_bytes -= len(payload)
                return kind, payload
            try:
                reader = self._reader_locked()
            except OSError:
                reader = None
        # Read outside the lock so producers are never held up by the disk. Only
        # complete records are counted in _in_file, so this one is whole.
        rec = self._read_record(reader) if reader is not None else None
        with self._cv:
            if rec is None:
                # The file cannot be read back. Its frames are gone; say so loudly,
                # drop the file, and carry on with memory rather than spin here.
                self.lost_records += self._in_file
                print(f"[send] could not read the backlog file back - "
                      f"{self._in_file} frame(s) lost")
                self._in_file = 0
                self._file_reset_locked()
                self._busy = False
                return None
            self._in_file -= 1
            if rec[0] == AUDIO:
                self.audio_bytes -= len(rec[1])
            if self._in_file == 0:
                self._file_reset_locked()
            return rec

    def task_done(self) -> None:
        """The consumer has finished with the frame it last took."""
        with self._cv:
            self._busy = False

    def idle(self) -> bool:
        """True when the consumer is not in the middle of a frame."""
        with self._cv:
            return not self._busy

    def empty(self) -> bool:
        with self._cv:
            return not (self._urgent or self._in_file or self._mem)

    def discard(self) -> None:
        """Drop everything and delete the file (the call is closed)."""
        with self._cv:
            self._mem.clear()
            self._urgent.clear()
            self._mem_bytes = 0
            self._in_file = 0
            self.audio_bytes = 0
            self._file_reset_locked()

    # ── internals (call with the lock held) ────────────────────────────────
    def _mem_append_locked(self, kind, payload):
        self._mem.append((kind, payload))
        self._mem_bytes += len(payload)

    def _spill_locked(self):
        """Move all of memory into the file, oldest first. A write the disk refuses
        stops the move: what is left stays in memory, still newer than the file."""
        self.spills += 1
        self._spilling = True
        while self._mem:
            kind, payload = self._mem[0]
            if not self._write_locked(kind, payload):
                break
            self._mem.popleft()
            self._mem_bytes -= len(payload)
        size = (f"{self._max // (1024 * 1024)} MB" if self._max >= 1024 * 1024
                else f"{self._max // 1024} KB")
        print(f"[send] backlog over {size} - keeping it in {self._spill_path.name} "
              f"until it is sent")

    def _write_locked(self, kind, payload) -> bool:
        try:
            if self._w is None:
                self._w = open(self._spill_path, "wb")
            self._w.write(_HEAD.pack(kind, len(payload)) + payload)
            self._w.flush()
        except OSError as exc:
            print(f"[send] backlog file write failed ({exc}) - keeping it in memory")
            return False
        self._in_file += 1
        return True

    def _reader_locked(self):
        if self._r is None:
            self._r = open(self._spill_path, "rb", buffering=0)
        return self._r

    @staticmethod
    def _read_exact(f, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = f.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)

    def _read_record(self, f):
        try:
            head = self._read_exact(f, _HEAD.size)
            if head is None:
                return None
            kind, n = _HEAD.unpack(head)
            payload = self._read_exact(f, n) if n else b""
            if payload is None:
                return None
            return kind, payload
        except (OSError, struct.error, ValueError):
            return None

    def _file_reset_locked(self):
        """The file is empty (or unusable): close it, delete it, back to memory."""
        for name in ("_r", "_w"):
            h = getattr(self, name)
            if h is not None:
                try:
                    h.close()
                except OSError:
                    pass
                setattr(self, name, None)
        try:
            if self._spill_path.exists():
                os.unlink(self._spill_path)
        except OSError:
            pass
        self._spilling = False
