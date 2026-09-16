"""The socket handover must not be nested inside the stop-timing report.

Stopping a call keeps the websocket open for a few seconds, because
session_summary and upload_complete still have to arrive on it. Three things
happen together: the streamer is parked on _closing_streamer so
_close_finished_streamer can release it, a 15-second backstop is armed, and
_streamer is cleared so the next call starts clean.

For one build all three sat inside `if total > 0.25` - the timing report
added while measuring why long calls felt slow - so a stop quicker than a
quarter of a second did none of them. The socket was never released, the
backstop never armed, and the next call began with the previous call's
streamer still attached. The SLOW path, the one being measured, went on
working perfectly, which is why measuring did not show it.

Read off the source rather than by driving the widget. Building a MainWindow
and running the whole stop path aborts the process under offscreen Qt - the
handover is four lines in the middle of a long method, and a test that
crashes proves nothing about them.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "main.py"
TREE = ast.parse(SRC.read_text(encoding="utf-8"))


def _stop_recording():
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "_stop_recording":
            return node
    raise AssertionError("_stop_recording has gone")


def _assigns_closing_streamer(node):
    """Every assignment to self._closing_streamer inside this node."""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if (isinstance(t, ast.Attribute) and t.attr == "_closing_streamer"
                    and isinstance(t.value, ast.Name) and t.value.id == "self"):
                out.append(n)
    return out


def _timing_branches(node):
    """The `if total > 0.25:` guards around the timing print."""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.If):
            continue
        test = ast.unparse(n.test)
        if "total" in test and ">" in test:
            out.append(n)
    return out


def test_the_handover_happens_on_every_stop_not_just_a_slow_one():
    fn = _stop_recording()
    handovers = _assigns_closing_streamer(fn)
    assert handovers, "_stop_recording no longer parks the streamer at all"
    for branch in _timing_branches(fn):
        inside = _assigns_closing_streamer(branch)
        assert not inside, (
            "the socket handover is inside the timing guard "
            f"`if {ast.unparse(branch.test)}` - a stop faster than that "
            "leaves the socket open and the streamer attached to the next call")


def test_the_handover_is_guarded_by_having_a_streamer():
    """It belongs to `if self._streamer is not None`, and nothing else."""
    fn = _stop_recording()
    for n in ast.walk(fn):
        if not isinstance(n, ast.If):
            continue
        if "self._streamer is not None" not in ast.unparse(n.test):
            continue
        if _assigns_closing_streamer(n):
            return
    raise AssertionError(
        "the handover is not inside `if self._streamer is not None` - either "
        "it moved again, or it now runs when there is no streamer to hand over")


def test_the_timing_report_is_still_there():
    """It is how the long-call slowness gets measured; losing it would send
    the next person back to guessing."""
    fn = _stop_recording()
    assert _timing_branches(fn), "the stop timing report has gone"
