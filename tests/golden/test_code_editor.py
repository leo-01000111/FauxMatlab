"""
The script editor's tooling: highlighting, completion, sections, gutter.

The lexer, the candidate list and the section split are plain functions and
are tested as such; the widgets are checked for wiring (formats applied, Tab
completing, a section running and appending).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from evans.console.interpreter import Interpreter
from evans.ui import theme
from evans.ui.code import (
    CodeEditor,
    Completer,
    MatlabHighlighter,
    completion_candidates,
    matlab_builtins,
    section_at,
    section_source,
    split_sections,
    tokenize_line,
)
from evans.ui.code.highlighter import BLOCK_COMMENT, NORMAL, syntax_formats


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _kinds(text: str, state: int = NORMAL, language: str = "matlab"):
    spans, _ = tokenize_line(text, state, language)
    return [(text[s:s + n], kind) for s, n, kind in spans]


# ──────────────────────────────────────────────────────────────
#  Highlighting
# ──────────────────────────────────────────────────────────────

def test_keywords_numbers_and_comments():
    assert _kinds("for k = 1:10 % loop") == [
        ("for", "keyword"), ("1", "number"), ("10", "number"),
        ("% loop", "comment")]
    assert _kinds("x = 2.5e-3;") == [("2.5e-3", "number")]
    assert _kinds("if a, end") == [("if", "keyword"), ("end", "keyword")]


def test_a_field_named_like_a_keyword_is_not_one():
    assert _kinds("s.end = 1") == [("1", "number")]


def test_both_quote_kinds_are_strings():
    assert _kinds("disp('it''s')") == [("'it''s'", "string")]
    assert _kinds('s = "a ""b"""') == [('"a ""b"""', "string")]


def test_transpose_is_not_a_string():
    """``A'`` and ``x(1)'`` transpose; ``['a' 'b']`` quotes."""
    assert _kinds("B = A';") == []
    assert _kinds("y = x(k)' + b.' + 2';") == [("2", "number")]
    assert _kinds("c = [a' 'b'];") == [("'b'", "string")]
    assert _kinds("case 'on'") == [("case", "keyword"), ("'on'", "string")]


def test_percent_inside_a_string_is_not_a_comment():
    assert _kinds("fprintf('%d\\n', k) % done") == [
        ("'%d\\n'", "string"), ("% done", "comment")]


def test_block_comments_carry_across_lines():
    spans, state = tokenize_line("%{", NORMAL)
    assert state == BLOCK_COMMENT and spans[0][2] == "comment"
    spans, state = tokenize_line("for x = 1", BLOCK_COMMENT)
    assert state == BLOCK_COMMENT and spans == [(0, 9, "comment")]
    _, state = tokenize_line("  %}", BLOCK_COMMENT)
    assert state == NORMAL


def test_section_headers():
    assert _kinds("%% Plot the response") == [
        ("%% Plot the response", "section")]
    assert _kinds("%%") == [("%%", "section")]
    assert _kinds("x = 1 %% not a header") == [
        ("1", "number"), ("%% not a header", "comment")]


def test_python_mode():
    assert _kinds("def f(x):  # hi", language="python") == [
        ("def", "keyword"), ("# hi", "comment")]
    assert _kinds("print('a')", language="python") == [("'a'", "string")]


def test_the_highlighter_applies_theme_formats(app):
    doc = QTextDocument()
    doc.setPlainText("%{\nx = 1\n%}\nif x, disp('y'), end")
    highlighter = MatlabHighlighter(doc)
    highlighter.rehighlight()
    formats = syntax_formats()

    def colours(n):
        layout = doc.findBlockByNumber(n).layout()
        return {f.format.foreground().color().name()
                for f in layout.formats()}

    comment = formats["comment"].foreground().color().name()
    assert colours(1) == {comment}                     # inside %{ %}
    keyword = formats["keyword"].foreground().color().name()
    string = formats["string"].foreground().color().name()
    assert {keyword, string} <= colours(3)


@pytest.mark.parametrize("tokens", [theme.DAY, theme.NIGHT])
def test_syntax_colours_differ_from_the_background(tokens):
    from PySide6.QtGui import QColor

    ground = QColor(tokens.surface)
    for kind, fmt in syntax_formats(tokens).items():
        colour = fmt.foreground().color()
        assert colour != ground, kind
        contrast = abs(colour.lightness() - ground.lightness())
        assert contrast > 60, (tokens.name, kind)


# ──────────────────────────────────────────────────────────────
#  Completion
# ──────────────────────────────────────────────────────────────

def test_builtins_come_from_the_matlab_library():
    names = matlab_builtins()
    assert {"zeros", "linspace", "pi", "disp"} <= names


def test_candidates_cover_variables_keywords_builtins_and_m_files(tmp_path):
    (tmp_path / "myscript.m").write_text("x = 1;")
    (tmp_path / "notes.txt").write_text("")
    interp = Interpreter()
    interp.run("myvar = 3")

    found = completion_candidates("my", interp, folder=tmp_path)
    assert found[0] == "myvar"                       # the workspace first
    assert "myscript" in found
    assert "while" in completion_candidates("whi", interp, folder=tmp_path)
    assert "linspace" in completion_candidates("linsp", interp,
                                               folder=tmp_path)
    assert completion_candidates("", interp, folder=tmp_path) == []
    assert all(not n.startswith("_") for n in
               completion_candidates("s", interp, folder=tmp_path))


def test_candidates_complete_attributes():
    interp = Interpreter()
    interp.run("import types\nobj = types.SimpleNamespace(alpha=1, beta=2)")
    assert completion_candidates("obj.al", interp) == ["obj.alpha"]


def test_one_match_completes_at_once(app):
    line = QLineEdit()
    completer = Completer(line, lambda p: [n for n in ("linspace",)
                                           if n.startswith(p)])
    line.setText("x = lins")
    line.setCursorPosition(8)
    assert completer.complete()
    assert line.text() == "x = linspace"
    assert not completer.is_open()


def test_several_matches_open_a_popup(app):
    editor = CodeEditor()
    editor.set_completion_source(
        lambda p: [n for n in ("stepinfo", "step", "stem") if n.startswith(p)])
    editor.show()
    editor.setPlainText("st")
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    assert editor.completer.complete()
    assert editor.completer.is_open()
    editor.completer.accept_current()
    assert editor.toPlainText() == "stepinfo"
    editor.close()


def test_common_prefix_is_filled_in_before_the_popup(app):
    line = QLineEdit()
    completer = Completer(line, lambda p: [n for n in ("stepinfo", "stepplot")
                                           if n.startswith(p)])
    line.setText("ste")
    line.setCursorPosition(3)
    completer.complete()
    assert line.text() == "step"


def test_tab_without_a_word_indents(app):
    editor = CodeEditor()
    editor.set_completion_source(lambda p: ["anything"])
    editor.setPlainText("x = 1\n")
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    QTest.keyClick(editor, Qt.Key_Tab)
    assert editor.toPlainText() == "x = 1\n    "


# ──────────────────────────────────────────────────────────────
#  Sections
# ──────────────────────────────────────────────────────────────

SCRIPT = """\
a = 1;
%% Second
b = a + 1;
%{
%% not a section: inside a block comment
%}
%% Third
c = b * 10;"""


def test_sections_split_at_double_percent():
    sections = split_sections(SCRIPT)
    assert [(s.start, s.end, s.title) for s in sections] == [
        (1, 1, ""), (2, 6, "Second"), (7, 8, "Third")]
    assert section_at(sections, 4).title == "Second"
    assert split_sections("x = 1") == [split_sections("x = 1")[0]]
    assert split_sections("%% Only\nx = 1")[0].title == "Only"


def test_a_section_keeps_its_line_numbers():
    sections = split_sections(SCRIPT)
    source = section_source(SCRIPT, sections[2])
    lines = source.split("\n")
    assert lines[6] == "%% Third" and lines[7] == "c = b * 10;"
    assert all(not line for line in lines[:6])


# ──────────────────────────────────────────────────────────────
#  Gutter and highlights
# ──────────────────────────────────────────────────────────────

def test_breakpoints_toggle_and_follow_their_lines(app):
    editor = CodeEditor()
    editor.setPlainText("a\nb\nc\nd")
    seen = []
    editor.breakpoints_changed.connect(seen.append)
    editor.toggle_breakpoint(3)
    editor.toggle_breakpoint(4)
    editor.toggle_breakpoint(4)
    assert editor.breakpoints == {3}
    assert seen[-1] == {3}

    # Inserting a line above moves the breakpoint down with its text.
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.insertText("new\n")
    assert editor.breakpoints == {4}
    assert editor.document().findBlockByNumber(3).text() == "c"


def test_gutter_click_sets_a_breakpoint(app):
    editor = CodeEditor()
    editor.setPlainText("a\nb\nc")
    editor.resize(300, 200)
    editor.show()
    QApplication.processEvents()
    block = editor.document().findBlockByNumber(1)
    y = editor.blockBoundingGeometry(block).translated(
        editor.contentOffset()).center().y()
    QTest.mouseClick(editor._gutter, Qt.LeftButton, pos=QPoint(5, int(y)))
    assert editor.breakpoints == {2}
    editor.close()


def test_error_line_is_tinted_until_the_text_changes(app):
    editor = CodeEditor()
    editor.setPlainText("a = 1\nb = oops\nc = 3")
    editor.set_error_line(2)
    assert editor.error_line == 2
    assert len(editor.extraSelections()) == 1
    editor.insertPlainText(" ")
    assert editor.error_line is None
    assert editor.extraSelections() == []
