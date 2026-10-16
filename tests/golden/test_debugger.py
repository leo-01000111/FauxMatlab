"""
Stopping and debugging what the console runs.

The engine half is driven without Qt: ``poll`` and ``on_pause`` are plain
callables, so a test can request a stop after a few event-loop turns, or
answer each pause with the next debugger command. The panel half drives the
real Stop button, breakpoints and nested event loop with timers.
"""

from __future__ import annotations

import sys

import pytest

from fakematlab.console.interpreter import Interpreter
from fakematlab.console.tracer import CONTINUE, STEP, STEP_IN, STOP


def _stop_after(interp: Interpreter, polls: int = 5) -> None:
    """Request a stop on the ``polls``-th event-loop turn."""
    tracer = interp.tracer
    tracer.poll_interval = 0
    count = [0]

    def poll():
        count[0] += 1
        if count[0] >= polls:
            tracer.request_stop()

    tracer.poll = poll


def _answers(interp: Interpreter, *actions: str) -> list[tuple]:
    """Answer each pause with the next action; record (line, variables)."""
    seen: list[tuple] = []
    queue = list(actions)

    def on_pause(pause):
        seen.append((pause.line, dict(interp.variables())))
        return queue.pop(0) if queue else CONTINUE

    interp.tracer.on_pause = on_pause
    return seen


# ──────────────────────────────────────────────────────────────
#  Interrupting
# ──────────────────────────────────────────────────────────────

def test_an_endless_matlab_loop_is_interrupted():
    interp = Interpreter()
    _stop_after(interp)
    results = interp.run_script(
        "x = 0;\nwhile true\n    x = x + 1;\nend\ndisp('never')", "matlab")
    last = results[-1]
    assert last.error.startswith("Interrupted at line ")
    assert last.line in (2, 3)
    assert interp.namespace["x"] > 0                 # what ran, stays
    assert not interp.tracer.running
    # The workspace is usable straight after.
    interp.tracer.poll = None
    assert interp.run("y = x + 1").ok
    assert interp.namespace["y"] == interp.namespace["x"] + 1


def test_try_catch_does_not_swallow_an_interrupt():
    interp = Interpreter()
    _stop_after(interp)
    results = interp.run_script(
        "n = 0;\nwhile true\n  try\n    n = n + 1;\n  catch\n  end\nend",
        "matlab")
    assert results[-1].error.startswith("Interrupted")


def test_an_endless_command_at_the_prompt_is_interrupted():
    interp = Interpreter()
    _stop_after(interp)
    result = interp.run("k = 0\nwhile True:\n    k += 1")
    assert result.error.startswith("Interrupted at line")
    assert interp.namespace["k"] > 0


def test_a_function_left_in_the_workspace_can_still_be_stopped():
    interp = Interpreter()
    interp.run_script("def spin():\n    while True:\n        pass\n",
                      "python")
    _stop_after(interp)
    result = interp.run("spin()")
    assert result.error.startswith("Interrupted at line 3")


def test_monitoring_is_released_after_a_run():
    interp = Interpreter()
    interp.run_script("a = 1;\nb = 2;", "matlab")
    assert sys.monitoring.get_tool(sys.monitoring.DEBUGGER_ID) is None


# ──────────────────────────────────────────────────────────────
#  Breakpoints and stepping
# ──────────────────────────────────────────────────────────────

SCRIPT = """\
a = 1;
b = twice(a);
c = b + 1;
d = c * 2;
function y = twice(x)
    y = 2 * x;
end
"""


def test_a_breakpoint_pauses_with_the_workspace_at_that_point():
    interp = Interpreter()
    interp.tracer.breakpoints = {3}
    seen = _answers(interp, CONTINUE)
    interp.run_script(SCRIPT, "matlab", debuggable=True)
    assert [line for line, _ in seen] == [3]
    variables = seen[0][1]
    assert variables["b"] == 2 and "c" not in variables
    assert interp.namespace["d"] == 6                  # then ran to the end


def test_step_goes_line_by_line_over_calls():
    interp = Interpreter()
    interp.tracer.breakpoints = {1}
    seen = _answers(interp, STEP, STEP, STEP, CONTINUE)
    interp.run_script(SCRIPT, "matlab", debuggable=True)
    assert [line for line, _ in seen] == [1, 2, 3, 4]


def test_step_in_enters_a_user_function():
    interp = Interpreter()
    interp.tracer.breakpoints = {2}
    seen = _answers(interp, STEP_IN, STEP, STEP, CONTINUE)
    interp.run_script(SCRIPT, "matlab", debuggable=True)
    lines = [line for line, _ in seen]
    # Into the body (not the `function` line), past its `end`, back out.
    assert lines == [2, 6, 7, 3]
    inside = seen[1][1]
    assert inside["x"] == 1 and inside["y"] is None   # the function's scope
    assert "a" not in inside


def test_breakpoints_only_apply_to_debuggable_runs():
    interp = Interpreter()
    interp.tracer.breakpoints = {1}
    seen = _answers(interp)
    interp.run_script("a = 1;\nb = 2;", "matlab")
    interp.run("a = 5")
    assert seen == []


def test_stop_while_paused_interrupts_at_that_line():
    interp = Interpreter()
    interp.tracer.breakpoints = {3}
    _answers(interp, STOP)
    results = interp.run_script(SCRIPT, "matlab", debuggable=True)
    assert results[-1].error == "Interrupted at line 3"
    assert "c" not in interp.namespace


def test_the_prompt_evaluates_in_the_paused_function():
    """A command typed while paused sees, and can change, the locals."""
    interp = Interpreter()
    interp.tracer.breakpoints = {6}
    answers = []

    def on_pause(pause):
        answers.append(interp.run("x").value)
        interp.run("x = 10")
        return CONTINUE

    interp.tracer.on_pause = on_pause
    interp.run_script(SCRIPT, "matlab", debuggable=True)
    assert answers == [1]
    assert interp.namespace["b"] == 20      # twice(10), not twice(1)


def test_python_scripts_break_on_their_own_lines():
    interp = Interpreter()
    interp.tracer.breakpoints = {3}
    seen = _answers(interp)
    interp.run_script("p = 1\nq = p + 1\nr = q + 1\n", "python",
                      debuggable=True)
    assert seen[0][0] == 3 and seen[0][1]["q"] == 2


def test_output_so_far_can_be_shown_at_a_pause():
    interp = Interpreter()
    interp.tracer.breakpoints = {3}
    shown = []
    interp.tracer.on_pause = lambda p: shown.append(
        interp.drain_output()) or CONTINUE
    results = interp.run_script(
        "if true\n  disp('before')\n  disp('after')\nend", "matlab",
        debuggable=True)
    assert shown == ["before\n"]
    assert results[0].output == "after\n"


# ──────────────────────────────────────────────────────────────
#  The panel: Stop button, sections, breakpoints in the editor
# ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def panel():
    pytest.importorskip("PySide6", reason="Qt not available")
    from PySide6.QtWidgets import QApplication

    from fakematlab.console.figures import set_figure_sink
    from fakematlab.ui.console import ConsolePanel, FigureArea

    app = QApplication.instance() or QApplication([])
    previous = set_figure_sink(None)
    set_figure_sink(previous)
    figures = FigureArea()
    widget = ConsolePanel(figures)
    widget.resize(900, 600)
    widget.show()
    app.processEvents()
    yield widget
    widget.hide()
    set_figure_sink(previous)


def _later(ms: int, fn) -> None:
    from PySide6.QtCore import QTimer
    QTimer.singleShot(ms, fn)


def _transcript(panel) -> str:
    return panel.console._transcript.toPlainText()


def test_the_stop_button_interrupts_an_endless_script(panel):
    panel.editor.set_text("n = 0;\nwhile true\n    n = n + 1;\nend")
    _later(150, lambda: panel.console._stop_button.click())
    assert panel._run_script(panel.editor.text(), "matlab")
    assert "Interrupted at line" in _transcript(panel)
    assert panel.editor.code.error_line in (2, 3)
    assert not panel.running
    assert not panel.console._stop_button.isEnabled()
    assert panel.execute("m = n + 1").ok              # the session lives on


def test_ctrl_c_at_the_prompt_interrupts(panel):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _later(150, lambda: QTest.keyClick(panel.console._input, Qt.Key_C,
                                       Qt.ControlModifier))
    result = panel.execute("while True:\n    pass")
    assert result.error.startswith("Interrupted")


def test_the_prompt_waits_while_something_runs(panel):
    typed = []
    _later(100, lambda: typed.append(panel.execute("z = 1")))
    _later(250, panel.stop)
    panel.execute("while True:\n    pass")
    assert typed and typed[0].error.startswith("Busy")
    assert "z" not in panel.interpreter.namespace


def test_running_a_section_appends_and_moves_on(panel):
    panel.execute("before_sections = 1")
    text = "s1 = 1;\n%% two\ns2 = 2;\n%% three\ns3 = s2 + 1;"
    panel.editor.set_text(text)
    panel.editor.code.goto_line(3)
    panel.editor.run_section(advance=True)
    namespace = panel.interpreter.namespace
    assert namespace["s2"] == 2
    assert "s1" not in namespace and "s3" not in namespace
    assert ">> before_sections = 1" in _transcript(panel)   # not cleared
    assert ">> s2 = 2;" in _transcript(panel)
    assert panel.editor.code.textCursor().blockNumber() + 1 == 4

    panel.editor.run_section()                               # Ctrl+Enter
    assert namespace["s3"] == 3


def test_ctrl_enter_runs_the_section(panel):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    panel.editor.set_text("%% only\nkeyed = 41 + 1;")
    panel.editor.code.goto_line(2)
    QTest.keyClick(panel.editor.code, Qt.Key_Return, Qt.ControlModifier)
    assert panel.interpreter.namespace["keyed"] == 42


def test_a_section_error_names_the_editor_line(panel):
    panel.editor.set_text("ok = 1;\n%% bad\nx = 1;\ny = undefined_thing + 1;")
    panel.editor.code.goto_line(3)
    panel.editor.run_section()
    assert panel.editor.code.error_line == 4
    assert "Error in line 4" in _transcript(panel)


def test_a_breakpoint_pauses_steps_and_continues(panel):
    """The full loop: gutter breakpoint, pause, inspect, step, continue."""
    panel.editor.set_text(SCRIPT)
    panel.editor.code.set_breakpoints({2})
    log = {}

    def at_breakpoint():
        log["line"] = panel.editor.code.current_line
        log["prompt"] = panel.console._prompt.text()
        log["paused_a"] = panel.execute("a").value
        log["step_enabled"] = panel.editor._step_button.isEnabled()
        panel._debug(STEP)
        _later(50, after_step)

    def after_step():
        log["stepped_to"] = panel.editor.code.current_line
        log["b"] = panel.interpreter.variables().get("b")
        panel._debug(CONTINUE)

    _later(100, at_breakpoint)
    panel._run_script(panel.editor.text(), "matlab")
    panel.editor.code.set_breakpoints(())

    assert log["line"] == 2
    assert log["prompt"].startswith("K>>")
    assert log["paused_a"] == 1
    assert log["step_enabled"]
    assert log["stepped_to"] == 3 and log["b"] == 2
    assert panel.interpreter.namespace["d"] == 6
    assert panel.editor.code.current_line is None
    assert not panel.editor._step_button.isEnabled()
    assert panel.console._prompt.text() == ">> "


def test_stop_while_paused_ends_the_run(panel):
    panel.editor.set_text(SCRIPT)
    panel.editor.code.set_breakpoints({3})
    panel.interpreter.namespace.pop("c", None)
    _later(100, panel.stop)
    panel._run_script(panel.editor.text(), "matlab")
    panel.editor.code.set_breakpoints(())
    assert "Interrupted at line 3" in _transcript(panel)
    assert "c" not in panel.interpreter.namespace
