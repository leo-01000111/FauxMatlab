"""
Hover for a function's syntax, Ctrl+click to go to it.

:func:`resolve` is checked on its own first — MATLAB's order of meaning, the
text a popup shows — then the controller in the real console panel: a click
on a local function, on a function file, on a built-in with a help page.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from evans.ui.code.follow import (  # noqa: E402
    FILE,
    HELP,
    LOCAL,
    SIGNATURE,
    Context,
    name_at,
    popup_html,
    resolve,
)

SCRIPT = """\
y = helper(2);
z = step_of(y);

function r = helper(x)
    % Adds one to its input.
    r = x + 1;
end

function [a, b] = two_out(x)  % trailing note
    a = x; b = x;
end
"""


# ── the name under a position ───────────────────────────────────

def test_the_name_under_a_column():
    line = "y = helper(2) + 'helper' % helper"
    assert name_at(line, 5) == (4, 10)
    assert name_at(line, 3) is None                    # the '='
    assert name_at(line, line.index("'helper") + 2) is None    # a string
    assert name_at(line, len(line) - 2) is None        # a comment


def test_a_transpose_is_not_a_string():
    line = "b = a' * helper(1)"
    assert name_at(line, line.index("helper") + 1) == (9, 15)


# ── what a name means ───────────────────────────────────────────

def test_a_local_function_with_its_h1_line():
    target = resolve("helper", Context(text=SCRIPT))
    assert target.kind == LOCAL and target.line == 4
    assert target.syntax == ["r = helper(x)"]
    assert target.summary == "Adds one to its input."


def test_a_local_function_signature_drops_the_trailing_comment():
    target = resolve("two_out", Context(text=SCRIPT))
    assert target.syntax == ["[a, b] = two_out(x)"]
    assert target.summary == ""


def test_a_function_file(tmp_path):
    path = tmp_path / "scale.m"
    path.write_text("function y = scale(x, k)\n% Multiplies x by k.\n"
                    "y = k*x;\nend\n", encoding="utf-8")
    target = resolve("scale", Context(
        find_file=lambda name: path if name == "scale" else None))
    assert target.kind == FILE and target.path == path and target.line == 1
    assert target.syntax == ["y = scale(x, k)"]
    assert target.summary == "Multiplies x by k."


def test_a_built_in_shows_every_form_on_its_help_page():
    target = resolve("step")
    assert target.kind == HELP
    assert "step(sys)" in target.syntax and len(target.syntax) > 2
    assert target.summary


def test_no_page_falls_back_to_the_signature_table():
    target = resolve("atan2")
    assert target.kind == SIGNATURE and not target.followable
    assert target.syntax == ["atan2(y, x)"]


def test_matlab_order_variable_then_local_then_file_then_built_in(tmp_path):
    shadow = tmp_path / "step.m"
    shadow.write_text("function step(x)\nend\n", encoding="utf-8")
    files = Context(find_file=lambda name: shadow if name == "step" else None)
    assert resolve("step", files).kind == FILE         # a file before a page
    local = "function step(x)\nend\n"
    assert resolve("step", Context(text=local,
                                   find_file=files.find_file)).kind == LOCAL
    assert resolve("step", Context(is_variable=lambda n: True)) is None
    assert resolve("end") is None and resolve("not_a_thing") is None


def test_the_popup_text():
    target = resolve("helper", Context(text=SCRIPT))
    shown = popup_html(target)
    assert "r = helper(x)" in shown and "Adds one" in shown
    assert "Ctrl+click to go to it" in shown
    assert "help page" in popup_html(resolve("step"))
    assert "Ctrl+click" not in popup_html(resolve("atan2"))


# ── in the panel ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def panel():
    from PySide6.QtWidgets import QApplication

    from evans.console.figures import set_figure_sink
    from evans.ui.console import ConsolePanel, FigureArea

    app = QApplication.instance() or QApplication([])
    previous = set_figure_sink(None)
    set_figure_sink(previous)
    widget = ConsolePanel(FigureArea())
    widget.resize(900, 600)
    widget.show()
    app.processEvents()
    yield widget
    widget.hide()
    set_figure_sink(previous)


def _controller(widget):
    from evans.ui.code import FollowController
    return widget.findChild(FollowController)


def _point(code, line: int, column: int):
    """The middle of character ``column`` (0-based) of ``line``."""
    from PySide6.QtGui import QTextCursor

    cursor = QTextCursor(code.document().findBlockByNumber(line - 1))
    cursor.movePosition(QTextCursor.Right, n=column)
    rect = code.cursorRect(cursor)
    return rect.center() + type(rect.center())(3, 0)


def _ctrl_click(code, line: int, column: int) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(code.viewport(), Qt.LeftButton, Qt.ControlModifier,
                     _point(code, line, column))


def test_every_place_code_appears_can_follow(panel):
    assert _controller(panel.console._input) is not None
    assert _controller(panel.console._transcript) is not None
    assert _controller(panel.editor.code) is not None
    panel.editor.new_document()
    assert _controller(panel.editor.code) is not None   # a new tab too
    from evans.ui.console.live_editor import CodeCellWidget
    cells = [w for w in panel.live._widgets if isinstance(w, CodeCellWidget)]
    assert cells and all(_controller(c.editor) for c in cells)


def test_ctrl_click_on_a_local_function_goes_to_it(panel):
    panel.editor.new_document()
    panel.editor.set_text(SCRIPT)
    code = panel.editor.code
    code.goto_line(1)
    _ctrl_click(code, 1, 6)                       # y = he|lper(2);
    assert code.textCursor().blockNumber() + 1 == 4


def test_ctrl_click_on_a_function_file_opens_it_in_a_tab(panel, tmp_path):
    (tmp_path / "scale.m").write_text(
        "% scale: a function file\n\nfunction y = scale(x, k)\n"
        "    y = k*x;\nend\n", encoding="utf-8")
    main = tmp_path / "uses_scale.m"
    main.write_text("v = scale(2, 3);\n", encoding="utf-8")
    document = panel.editor.load_file(main)
    _ctrl_click(document.code, 1, 6)
    shown = panel.editor.current_document()
    assert shown.name == "scale.m"
    assert shown.code.textCursor().blockNumber() + 1 == 3
    assert panel._tabs.currentWidget() is panel.editor


def test_ctrl_click_on_a_built_in_opens_its_help_page(panel, monkeypatch):
    import evans.ui.help as help_module

    opened = []
    monkeypatch.setattr(help_module, "open_help", opened.append)
    panel.editor.new_document()
    panel.editor.set_text("step(tf(1, [1 1]))")
    _ctrl_click(panel.editor.code, 1, 1)
    assert opened == ["step"]


def test_holding_ctrl_underlines_only_what_can_be_followed(panel):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    panel.editor.new_document()
    panel.editor.set_text("y = atan2(1, 2) + abs(-1);")
    code = panel.editor.code

    def move(column):
        pos = QPointF(_point(code, 1, column))
        event = QMouseEvent(QMouseEvent.Type.MouseMove, pos, pos,
                            Qt.NoButton, Qt.NoButton, Qt.ControlModifier)
        QApplication.sendEvent(code.viewport(), event)
        return [s for s in code.extraSelections()
                if s.format.fontUnderline()]

    assert not move(6)                            # atan2: a signature only
    underlined = move(19)                         # abs: it has a page
    assert len(underlined) == 1
    cursor = underlined[0].cursor
    assert cursor.selectedText() == "abs"


def test_the_prompt_resolves_names_too(panel):
    from PySide6.QtCore import QPoint

    prompt = panel.console._input
    controller = _controller(prompt)
    prompt.setText("bode(G)")
    x = prompt.fontMetrics().horizontalAdvance("bo") + 6
    found = controller.target_at(QPoint(x, prompt.height() // 2))
    assert found is not None and found[0].name == "bode"


def test_a_workspace_variable_is_not_a_function(panel):
    panel.execute("step_size = 0.1;")
    controller = _controller(panel.console._input)
    target = controller._context()
    assert target.is_variable("step_size")
    assert resolve("step_size", target) is None
