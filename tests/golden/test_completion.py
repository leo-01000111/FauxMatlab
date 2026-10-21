r"""
Code completion: what is offered, in what order, and the popup's keys in
each place code or LaTeX is typed — the console prompt, the Script editor,
live-script code cells (MATLAB) and text cells (LaTeX, \ref to figures).

The candidate sources and the ranking are plain functions; the widgets are
driven with real key presses, which pass through the popup's event filter
exactly as typing does.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from evans.console.figures import FigureSpec, figure_sink, set_figure_sink
from evans.console.interpreter import Interpreter
from evans.console.live import Cell, CellKind, CellOutput, LiveDocument
from evans.ui.code import CodeEditor, code_request, rank, warm_up
from evans.ui.code.completion import (
    Completion,
    match,
    rank_scored,
    workspace_items,
)
from evans.ui.code.latex import latex_request, open_environments
from evans.ui.console.console_widget import ConsoleWidget
from evans.ui.console.live_editor import LiveScriptEditor


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    warm_up(wait=True)            # typing never waits for the fixed lists
    return app


@pytest.fixture
def interp():
    it = Interpreter()
    it.run("G = tf([1], [1, 2, 1])\nstepsize = 0.1\nA = eye(3)")
    return it


def _names(request, n=None):
    items = rank(request.prefix, request.items(True))
    return [c.text for c in items][:n]


def _type(widget, text: str) -> None:
    # QTest.keyClicks with a newline in it ends the process (PySide6 6.x):
    # a new line is a Return key.
    for i, line in enumerate(text.split("\n")):
        if i:
            QTest.keyClick(widget, Qt.Key_Return)
        if line:
            QTest.keyClicks(widget, line)


def _key(widget, key, mods=Qt.NoModifier) -> None:
    QTest.keyClick(widget, key, mods)


# ──────────────────────────────────────────────────────────────
#  Ranking
# ──────────────────────────────────────────────────────────────

def test_exact_prefix_then_case_insensitive_then_fuzzy():
    assert match("ste", "step") == (0, 0)
    assert match("ste", "Step") == (1, 0)
    assert match("sp", "step")[0] == 2
    assert match("xyz", "step") is None
    pool = [Completion(n) for n in ("isstable", "Step", "step", "stepinfo")]
    assert [c.text for c in rank("ste", pool)] == [
        "step", "stepinfo", "Step", "isstable"]


def test_fuzzy_matches_rank_by_how_few_letters_they_skip():
    pool = [Completion(n) for n in ("bandwidth", "bode")]
    assert [c.text for c in rank("bd", pool)] == ["bode", "bandwidth"]


def test_ties_keep_the_order_of_the_sources():
    pool = [Completion("myvar", "variable"), Completion("myfile", "file")]
    assert [c.text for c in rank("my", pool)] == ["myvar", "myfile"]
    tiers = [tier for tier, _ in rank_scored("my", pool)]
    assert tiers == [0, 0]


# ──────────────────────────────────────────────────────────────
#  Sources: MATLAB, Python, the workspace, attributes, files
# ──────────────────────────────────────────────────────────────

def test_matlab_offers_commands_with_their_calls(app, interp):
    items = {c.text: c.resolved()
             for c in code_request("x", "matlab", interp).items(True)}
    assert items["step"].signature == "step(sys, t)"
    assert items["bode"].signature == "bode(sys, w)"
    assert items["lqr"].signature == "lqr(A, B, Q, R)"
    assert items["step"].detail == "Step response"
    # The MATLAB runtime's own builtins, described too.
    assert items["linspace"].signature == "linspace(a, b, n)"
    assert items["zeros"].detail
    assert "while" in items and items["while"].kind == "keyword"
    assert "def" not in items                       # a Python keyword


def test_workspace_variables_come_first_and_say_what_they_hold(app, interp):
    names = _names(code_request("ste", "matlab", interp))
    assert names[0] == "stepsize"
    assert {"step", "stepinfo"} <= set(names)
    detail = {c.text: c.resolved().detail for c in workspace_items(interp)}
    assert detail["stepsize"] == "float = 0.1"
    assert detail["A"].endswith("3×3")


def test_python_scripts_offer_python_keywords_and_builtins(app, interp):
    names = _names(code_request("pri", "python", interp))
    assert names[0] == "print"
    assert "def" in _names(code_request("de", "python", interp))
    assert "end" not in _names(code_request("en", "python", interp), 3)


def test_the_console_offers_matlab_keywords_and_python_builtins(app, interp):
    names = _names(code_request("lin", "console", interp))
    assert "linspace" in names
    assert "otherwise" in _names(code_request("othe", "console", interp))
    assert "print" in _names(code_request("pri", "console", interp))


def test_attributes_of_workspace_objects(app, interp):
    request = code_request("x = A.sh", "console", interp)
    assert request.prefix == "sh"
    names = _names(request)
    assert names[0] == "shape"
    assert _names(code_request("G.npo", "console", interp))   # no error
    assert code_request("np.lins", "console", interp).items(True)


def test_attribute_heads_are_looked_up_never_evaluated(app, interp):
    interp.run("calls = []")
    request = code_request("calls.append(1).re", "console", interp)
    assert request is None or not request.items(True)
    assert interp.namespace["calls"] == []


def test_m_files_in_the_folder(app, interp, tmp_path):
    (tmp_path / "mysim.m").write_text("x = 1;")
    names = _names(code_request("mys", "matlab", interp, tmp_path))
    assert names == ["mysim"]


def test_nothing_in_strings_comments_or_numbers(app, interp):
    assert code_request("% ste", "matlab", interp) is None
    assert code_request("disp('ste", "matlab", interp) is None
    assert code_request("# ste", "python", interp) is None
    assert code_request("x = 1e5", "matlab", interp) is None
    # A closed string, then code again.
    assert code_request("s = 'a'; ste", "matlab", interp).prefix == "ste"
    # A transpose is not a string.
    assert code_request("y = A'; ste", "matlab", interp).prefix == "ste"


# ──────────────────────────────────────────────────────────────
#  LaTeX
# ──────────────────────────────────────────────────────────────

def test_latex_commands_after_a_backslash():
    request = latex_request(r"the gain is $\fr")
    assert request.prefix == r"\fr"
    first = rank(request.prefix, request.items(True))[0]
    assert first.text == r"\frac"
    assert first.insertion == r"\frac{}{}" and first.cursor == 6
    greek = _names(latex_request(r"$\alp"))
    assert greek[0] == r"\alpha"
    assert r"\section" in _names(latex_request(r"\sec"))
    assert r"\sum" in _names(latex_request(r"\su"))


def test_a_line_break_is_not_a_command():
    assert latex_request("a \\\\") is None


def test_begin_inserts_the_matching_end():
    request = latex_request(r"\begin{al")
    item = rank(request.prefix, request.items(True))[0]
    assert item.text == "align"
    assert item.insertion == "align}\n\n\\end{align}"
    assert item.insertion[:item.cursor] == "align}\n"


def test_end_offers_the_environment_still_open():
    text = r"\begin{equation}x\end{equation} \begin{cases} a \end{"
    assert open_environments(text) == ["cases"]
    assert _names(latex_request(text)) == ["cases"]


def test_ref_offers_the_documents_labels():
    request = latex_request(r"as \ref{", lambda: ["fig:1", "fig:bode"])
    assert request.prefix == ""
    assert _names(request) == ["fig:1", "fig:bode"]
    assert _names(latex_request(r"\eqref{bo", lambda: ["fig:1", "fig:bode"])
                  ) == ["fig:bode"]


def test_the_document_names_its_figure_labels():
    spec = FigureSpec("xy", title="t")
    drawn = Cell.code("plot(1:3)")
    drawn.output = CellOutput(figures=[spec, spec])
    drawn.meta(1).label = "fig:bode"
    later = Cell.code("step(G)")
    later.meta(0).label = "fig:step"
    text = Cell.text(r"see \label{eq:loop}")
    editor = LiveScriptEditor(Interpreter())
    editor.set_document(LiveDocument([drawn, later, text]))
    assert editor.reference_labels() == ["fig:1", "fig:bode", "fig:step",
                                         "eq:loop"]
    editor.deleteLater()


# ──────────────────────────────────────────────────────────────
#  The popup in the console prompt
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def console(app):
    widget = ConsoleWidget(Interpreter())
    widget.resize(700, 400)
    widget.show()
    app.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()


def test_console_typing_opens_and_narrows_the_popup(console):
    line = console._input
    _type(line, "s")
    assert not console.completer.is_open()          # one letter: not yet
    _type(line, "te")
    assert console.completer.is_open()
    assert console.completer.popup.isVisible()
    before = len(console.completer.items())
    assert "stepinfo" in [c.text for c in console.completer.items()]
    _type(line, "pi")
    texts = [c.text for c in console.completer.items()]
    assert texts[0] == "stepinfo" and len(texts) < before
    _key(line, Qt.Key_Tab)
    assert line.text() == "stepinfo()"                # a function: brackets
    assert line.cursorPosition() == len("stepinfo(")  # the arguments go here
    assert not console.completer.is_open()


def test_console_up_down_move_the_selection_not_the_history(console):
    console.execute("history_line = 1")
    line = console._input
    _type(line, "ste")
    first = console.completer.current().text
    _key(line, Qt.Key_Down)
    second = console.completer.current().text
    assert second != first
    _key(line, Qt.Key_Up)
    assert console.completer.current().text == first
    assert line.text() == "ste"                       # no history recalled
    _key(line, Qt.Key_Down)
    _key(line, Qt.Key_Return)                         # accepts, does not run
    assert line.text() == second + "()"
    assert console.interpreter.history[-1] == "history_line = 1"


def test_console_escape_closes_and_keeps_the_text(console):
    line = console._input
    _type(line, "x = bod")
    assert console.completer.is_open()
    _key(line, Qt.Key_Escape)
    assert not console.completer.is_open()
    assert line.text() == "x = bod"
    _key(line, Qt.Key_Space, Qt.ControlModifier)      # Ctrl+Space reopens
    assert console.completer.is_open()
    _key(line, Qt.Key_Backspace)
    _key(line, Qt.Key_Backspace)
    _key(line, Qt.Key_Backspace)                      # the word is gone
    assert not console.completer.is_open()


def test_console_return_on_a_name_typed_in_full_runs_it(console):
    line = console._input
    _type(line, "step")
    assert console.completer.is_open()                # stepinfo, stepplot…
    assert console.completer.current().text == "step"
    _key(line, Qt.Key_Return)
    assert not console.completer.is_open()
    assert console.interpreter.history[-1] == "step"
    assert line.text() == ""


def test_console_attribute_popup_after_a_dot(console):
    console.execute("A = eye(2)")
    line = console._input
    _type(line, "A.")
    assert console.completer.is_open()
    _type(line, "sha")
    _key(line, Qt.Key_Enter)
    assert line.text() == "A.shape"                   # a value: no brackets


def test_console_attribute_methods_get_brackets_too(console):
    console.execute("A = eye(2)")
    line = console._input
    _type(line, "A.resh")
    _key(line, Qt.Key_Tab)
    assert line.text() == "A.reshape()"
    assert line.cursorPosition() == len("A.reshape(")


def test_functions_come_with_their_brackets():
    from evans.ui.code.popup import call_insertion
    step = Completion("step", "command", signature="step(sys, t)")
    assert call_insertion(step) == ("step()", 5)        # cursor inside
    toc = Completion("toc", "function", signature="toc()")
    assert call_insertion(toc) == ("toc()", 5)          # no arguments: after
    assert call_insertion(step, after="(") == ("step", None)  # already there
    clc = Completion("clc", "function")                 # a bare command
    assert call_insertion(clc) == ("clc", None)
    var = Completion("stepsize", "variable")
    assert call_insertion(var) == ("stepsize", None)
    unknown = Completion("helper", "function")          # arguments unknown
    assert call_insertion(unknown) == ("helper()", 7)


# ──────────────────────────────────────────────────────────────
#  The Script editor
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def script(app, interp):
    editor = CodeEditor()
    language = {"value": "matlab"}
    editor.set_completion(
        lambda before: code_request(before, language["value"], interp))
    editor.language = language
    editor.resize(600, 400)
    editor.show()
    app.processEvents()
    yield editor
    editor.close()
    editor.deleteLater()


def test_script_popup_keys(script):
    _type(script, "y = lq")
    popup = script.completer
    assert popup.is_open()
    assert [c.text for c in popup.items()][:3] == ["lqe", "lqi", "lqr"]
    _key(script, Qt.Key_Up)                           # wraps to the last
    assert popup.current().resolved().signature == "lqr(A, B, Q, R)"
    _key(script, Qt.Key_Up)
    _key(script, Qt.Key_Tab)
    assert script.toPlainText() == "y = lqi()"
    script.moveCursor(script.textCursor().MoveOperation.End)
    _type(script, "\nz = ste")
    assert popup.is_open()
    _key(script, Qt.Key_Escape)
    assert not popup.is_open()
    assert script.toPlainText() == "y = lqi()\nz = ste"


def test_script_tab_still_indents_with_no_popup(script):
    _type(script, "x = 1;")
    _key(script, Qt.Key_Return)
    assert not script.completer.is_open()
    _key(script, Qt.Key_Tab)
    assert script.toPlainText() == "x = 1;\n    "


def test_script_tab_completes_when_the_popup_is_closed(script):
    script.setPlainText("stepi")
    script.moveCursor(script.textCursor().MoveOperation.End)
    _key(script, Qt.Key_Tab)
    assert script.toPlainText() == "stepinfo()"


def test_script_ctrl_return_still_runs_the_section(script):
    ran = []
    script.run_section_requested.connect(ran.append)
    _type(script, "ste")
    assert script.completer.is_open()
    _key(script, Qt.Key_Return, Qt.ControlModifier)
    assert ran == [False]
    assert not script.completer.is_open()


def test_script_python_completes_python(script):
    script.language["value"] = "python"
    _type(script, "pri")
    assert script.completer.current().text == "print"
    _key(script, Qt.Key_Return)
    assert script.toPlainText() == "print()"


def test_script_editor_in_the_console_panel_uses_the_popup(app):
    from evans.ui.console import ConsolePanel, FigureArea
    previous = figure_sink()
    try:
        panel = ConsolePanel(FigureArea())
        panel.resize(900, 600)
        panel.show()
        panel._tabs.setCurrentWidget(panel.editor)
        app.processEvents()
        code = panel.editor.code
        code.setFocus()
        _type(code, "bo")
        assert code.completer.is_open()
        assert code.completer.current().text == "bode"
        panel.hide()
    finally:
        set_figure_sink(previous)


# ──────────────────────────────────────────────────────────────
#  Live-script cells
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def live(app):
    editor = LiveScriptEditor(Interpreter())
    editor.resize(900, 700)
    editor.show()
    app.processEvents()
    yield editor
    editor.hide()
    editor.deleteLater()


def test_live_code_cell_completes_matlab(app, live):
    cell = live.cell_widgets[0]
    _type(cell.editor, "G = tf(1, [1 1]);\nst")
    assert cell.completer.is_open()
    _type(cell.editor, "ep")
    assert cell.completer.current().text == "step"
    assert cell.completer.current().resolved().signature == "step(sys, t)"
    _key(cell.editor, Qt.Key_Down)
    _key(cell.editor, Qt.Key_Up)
    _key(cell.editor, Qt.Key_Tab)
    assert cell.editor.toPlainText().endswith("\nstep()")
    assert live.document.cells[0].source.endswith("\nstep()")
    _type(cell.editor, "G")                           # between the brackets
    assert cell.editor.toPlainText().endswith("\nstep(G)")
    cell.editor.moveCursor(cell.editor.textCursor().MoveOperation.End)
    _type(cell.editor, "\n% ste")
    assert not cell.completer.is_open()               # a comment


def test_live_code_cell_tab_with_nothing_to_complete_types_a_tab(live):
    cell = live.cell_widgets[0]
    _key(cell.editor, Qt.Key_Tab)
    assert cell.editor.toPlainText() == "\t"


def test_live_text_cell_completes_latex(app, live):
    live.set_document(LiveDocument([Cell.text("", CellKind.TEXT)]))
    cell = live.cell_widgets[0]
    assert cell.editing
    text = cell.editor
    _type(text, "$\\fr")
    assert cell.completer.is_open()
    assert cell.completer.current().text == "\\frac"
    _key(text, Qt.Key_Return)
    assert text.toPlainText() == "$\\frac{}{}"
    assert text.textCursor().position() == len("$\\frac{")
    _type(text, "1")
    _key(text, Qt.Key_Escape)
    text.moveCursor(text.textCursor().MoveOperation.End)
    _type(text, "$ \\begin{eq")
    assert [c.text for c in cell.completer.items()][0] == "equation"
    _key(text, Qt.Key_Tab)
    assert text.toPlainText().endswith(
        "\\begin{equation}\n\n\\end{equation}")
    _key(text, Qt.Key_Escape)
    _type(text, "x")
    assert "\\begin{equation}\nx\n\\end{equation}" in text.toPlainText()


def test_live_text_cell_refs_name_the_figures(app, live):
    drawn = Cell.code("plot(1:3)")
    drawn.output = CellOutput(figures=[FigureSpec("xy", title="t")])
    live.set_document(LiveDocument([drawn, Cell.text("", CellKind.TEXT)]))
    text = live.cell_widgets[1].editor
    completer = live.cell_widgets[1].completer
    _type(text, "Figure \\ref{")
    assert completer.is_open()
    assert [c.text for c in completer.items()] == ["fig:1"]
    _key(text, Qt.Key_Tab)
    assert text.toPlainText() == "Figure \\ref{fig:1}"
    # \ref accepted from the command list goes straight on to the labels.
    text.setPlainText("")
    _type(text, "\\eqre")
    _key(text, Qt.Key_Tab)
    assert text.toPlainText() == "\\eqref{}"
    assert completer.is_open()
    _key(text, Qt.Key_Tab)
    assert text.toPlainText() == "\\eqref{fig:1}"
