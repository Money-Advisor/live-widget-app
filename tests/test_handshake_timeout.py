"""A busy server must not be mistaken for an unreachable one.

websocket-client's create_connection(timeout=N) silently applies N to every later
read on that socket too. Both budgets were therefore 10s — but they answer different
questions. "Is the server reachable?" should fail fast. "How long may the server take
to ANSWER?" cannot: answering session_start means authenticating the agent's token and
writing a session row, and under fleet load the server can legitimately spend seconds
waiting for a database connection.

The consequence in production (Aug 4): agents got "Connection Issue … Detail:
Connection timed out" after and during calls, calls refused to start, and buffered
calls could not be resumed so they were stored as dropped recordings — all while the
server was healthy, just busy. These tests pin the two budgets apart and keep them
consistent with the server's own worst-case wait.
"""
import json
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

import main


class HandshakeWS:
    """Records the socket timeouts applied, and replies to the handshake."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.timeouts = []
        self.sent = []
        self.closed = False

    def settimeout(self, t):
        self.timeouts.append(t)

    def send(self, data):
        self.sent.append(json.loads(data))

    def recv(self):
        return json.dumps(self._replies.pop(0))

    def close(self):
        self.closed = True


@pytest.fixture
def opened(monkeypatch):
    """Capture the kwargs create_connection is called with, and the socket handed back."""
    made = {}

    def fake_create(url, **kw):
        made["url"] = url
        made["kw"] = kw
        return made["ws"]

    monkeypatch.setattr(main._websocket, "create_connection", fake_create)
    return made


# ── the two budgets are different numbers, in the right order ───────────────
def test_handshake_budget_is_larger_than_the_connect_budget():
    assert main.WS_HANDSHAKE_TIMEOUT > main.WS_CONNECT_TIMEOUT, (
        "waiting for the server to answer is not the same as waiting for it to "
        "accept a socket; sharing one number is the bug")


def test_handshake_budget_covers_the_servers_worst_case_db_wait():
    """THE regression. The server retries acquiring a DB connection with backoff; if
    that ladder can outlast the widget's read budget, a saturated pool shows up on the
    agent's screen as 'Connection timed out' and the call refuses to start.

    Server ladder (live-widget-server/persistence.py):
      _ACQUIRE_RETRIES attempts of _ACQUIRE_TIMEOUT, with _ACQUIRE_BACKOFF doubling
      between them. Plus validate_token's own 5s HTTP budget.
    """
    acquire_retries, acquire_timeout, acquire_backoff = 3, 3.0, 0.25
    validate_token_timeout = 5.0

    worst_case = acquire_retries * acquire_timeout + sum(
        acquire_backoff * (2 ** i) for i in range(acquire_retries - 1)
    ) + validate_token_timeout

    assert main.WS_HANDSHAKE_TIMEOUT > worst_case, (
        f"the widget gives up after {main.WS_HANDSHAKE_TIMEOUT}s but the server can "
        f"legitimately take {worst_case}s to answer session_start")


# ── connect() applies them to the right phases ──────────────────────────────
def test_connect_fails_fast_on_the_socket_then_waits_on_the_server(opened, monkeypatch):
    opened["ws"] = HandshakeWS([
        {"status": "identified"},
        {"status": "session_started", "live_pipeline": False},
    ])
    st = main.AudioStreamer(
        "ws://test.invalid", "c-1", "s-1", "a-1", "Cust", "cid", "REF",
        token="tok", register_for_dialer=False)
    monkeypatch.setattr(st, "_receiver_loop", lambda ws=None: None)

    st.connect()

    assert opened["kw"]["timeout"] == main.WS_CONNECT_TIMEOUT, \
        "an unreachable server must still fail fast"
    assert opened["ws"].timeouts, "the handshake reads inherited the connect timeout"
    assert opened["ws"].timeouts[0] == main.WS_HANDSHAKE_TIMEOUT
    assert st._session_live.is_set()


def test_the_longer_budget_is_set_before_the_first_read(opened, monkeypatch):
    """Order matters: setting it after identify would leave that read on 10s, which is
    the read that stalls when the server's event loop is busy."""
    order = []

    class Ordered(HandshakeWS):
        def settimeout(self, t):
            order.append(("settimeout", t))
            super().settimeout(t)

        def recv(self):
            order.append(("recv",))
            return super().recv()

    opened["ws"] = Ordered([
        {"status": "identified"},
        {"status": "session_started"},
    ])
    st = main.AudioStreamer(
        "ws://test.invalid", "c-1", "s-1", "a-1", "Cust", "cid", "REF",
        token="tok", register_for_dialer=False)
    monkeypatch.setattr(st, "_receiver_loop", lambda ws=None: None)

    st.connect()

    assert order[0] == ("settimeout", main.WS_HANDSHAKE_TIMEOUT), order


# ── resume gets the same treatment ──────────────────────────────────────────
def test_resume_waits_on_the_server_too(opened, monkeypatch, tmp_path):
    """A resume that times out costs us the recording: the server's grace window
    expires and a complete, safely-buffered call is stored as 'connection dropped'."""
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    opened["ws"] = HandshakeWS([
        {"status": "identified"},
        {"status": "session_resumed"},
    ])
    st = main.AudioStreamer(
        "ws://test.invalid", "c-1", "s-1", "a-1", "Cust", "cid", "REF",
        token="tok", register_for_dialer=False)
    monkeypatch.setattr(st, "_receiver_loop", lambda ws=None: None)
    monkeypatch.setattr(st, "_drain_spool", lambda: True)

    assert st._reconnect_once() is True
    assert opened["kw"]["timeout"] == main.WS_CONNECT_TIMEOUT
    assert opened["ws"].timeouts[0] == main.WS_HANDSHAKE_TIMEOUT


def test_control_connection_waits_on_the_server_too(opened):
    """The persistent control connection is how the dialer reaches an agent. If its
    identify read times out it backs off and retries, dropping the agent out of the
    dialer index and adding churn to the load that caused it."""
    opened["ws"] = HandshakeWS([{"status": "not-identified"}])
    cc = main.ControlConnection("ws://test.invalid", "c-1", "a-1", "a@x.com")

    cc._serve_once()

    assert opened["kw"]["timeout"] == main.WS_CONNECT_TIMEOUT
    assert opened["ws"].timeouts[0] == main.WS_HANDSHAKE_TIMEOUT


# ── the streaming timeout governs SENDS, not just the receiver's poll ───────
def test_receiver_does_not_impose_a_one_second_budget_on_audio_sends():
    """THE second regression. websocket-client applies one timeout to the whole
    socket, so the receiver's setting decides how long an audio send may take. At 1.0s
    a single busy second on the server made a 16KB chunk time out, send_audio read that
    as a dead socket, and a healthy call was recorded as 'connection dropped'."""
    ws = HandshakeWS([])
    st = main.AudioStreamer(
        "ws://test.invalid", "c-1", "s-1", "a-1", "Cust", "cid", "REF",
        register_for_dialer=False)
    st._receiver_stop.set()          # exit immediately after applying the timeout
    st._receiver_loop(ws)

    assert ws.timeouts == [main.WS_STREAM_TIMEOUT]
    assert main.WS_STREAM_TIMEOUT >= 3, (
        "a sub-second server hiccup must not be mistaken for a dead connection")


def test_streaming_timeout_stays_short_enough_to_bound_audio_loss():
    """The other side of it: the capture thread blocks on a stuck send for this long
    and the audio device's buffer overflows meanwhile, so it cannot be generous. Once
    we do give up, the spool preserves everything from that point on."""
    assert main.WS_STREAM_TIMEOUT <= 10
    assert main.WS_STREAM_TIMEOUT < main.WS_HANDSHAKE_TIMEOUT


def test_a_slow_send_is_recoverable_not_a_lost_chunk(tmp_path, monkeypatch):
    """Whatever the budget, a send that does fail must keep its chunk. This is the
    guarantee that makes an eager degrade cheap rather than a hole in the recording."""
    monkeypatch.setattr(main, "_spool_dir", lambda: tmp_path)
    st = main.AudioStreamer(
        "ws://test.invalid", "c-1", "s-1", "a-1", "Cust", "cid", "REF",
        register_for_dialer=False)
    st._session_live.set()
    st._reconnect_loop = lambda: None

    class Stalled:
        def send_binary(self, _d):
            raise TimeoutError("timed out")     # exactly what a 1s socket raises

        def send(self, _d):
            raise TimeoutError("timed out")

        def close(self):
            pass

        def settimeout(self, _t):
            pass

    st._ws = Stalled()
    st.send_audio("mic", b"\x07\x08")

    assert st._degraded.is_set()
    assert st._spool_next() is not None, "the chunk that failed to send must be kept"
