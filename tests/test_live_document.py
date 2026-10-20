"""
The live-script model: cells, the text-cell markup, and placeholders filled
from the workspace. All headless — no Qt.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from evans.console.interpreter import Interpreter
from evans.console.live import (
    Cell,
    CellKind,
    InterpolationError,
    LiveDocument,
    format_value,
    workspace_evaluator,
)
from evans.console.live.markup import (
    escape_markdown,
    inline_latex,
    parse_blocks,
    parse_inline,
    plain_text,
    to_html,
    to_latex,
    value_latex,
)

# ──────────────────────────────────────────────────────────────
#  The document
# ──────────────────────────────────────────────────────────────


def _doc() -> LiveDocument:
    return LiveDocument([
        Cell.text("Lab 1", CellKind.TITLE),
        Cell.text("Intro with $x^2$."),
        Cell.code("a = 1;"),
        Cell.code("b = a + 1", section_break=True),
    ], path="C:/labs/lab1.m")


def test_title_and_folder_come_from_the_cells_and_path():
    doc = _doc()
    assert doc.title == "Lab 1"
    assert doc.folder.name == "labs"
    assert LiveDocument([Cell.code("x=1")], "C:/a/run.m").title == "run"
    assert LiveDocument().title == "untitled"


def test_insert_move_remove():
    doc = _doc()
    a, b = doc[2], doc[3]
    assert doc.move(b, -1) == 2 and doc[2] is b and doc[3] is a
    assert doc.move(b, -10) == 0                 # clamps at the top
    assert doc.move(b, 99) == len(doc) - 1       # and at the bottom
    new = doc.insert(1, Cell.code("c = 3"))
    assert doc.index(new) == 1
    assert doc.remove(new) == 1
    with pytest.raises(ValueError):
        doc.index(new)


def test_cell_kinds_know_what_they_are():
    assert CellKind.CODE.is_code and not CellKind.TEXT.is_code
    assert [k.level for k in (CellKind.TITLE, CellKind.HEADING,
                              CellKind.HEADING2, CellKind.HEADING3)] \
        == [0, 1, 2, 3]
    assert not CellKind.TEXT.is_heading
    assert Cell("code").kind is CellKind.CODE    # strings are accepted


def test_plain_script_keeps_only_code_with_section_marks():
    assert _doc().to_plain_script() == "a = 1;\n%%\nb = a + 1\n"


# ──────────────────────────────────────────────────────────────
#  Markup
# ──────────────────────────────────────────────────────────────

def test_inline_markup_parses_into_a_tree():
    nodes = parse_inline(r"**bold $x_1$** and *it* `code` {{G}} "
                         r"[link](http://a.b) $$y$$ \$5")
    kinds = [n.kind for n in nodes if n.kind != "text"]
    assert kinds == ["bold", "italic", "code", "interp", "link", "math"]
    bold = nodes[0]
    assert [c.kind for c in bold.children] == ["text", "math"]
    assert bold.children[1].text == "x_1"
    assert nodes[-1].text.endswith("$5")         # escaped dollar is literal
    display = [n for n in nodes if n.kind == "math"][0]
    assert display.display and display.text == "y"


def test_math_is_not_parsed_as_emphasis():
    nodes = parse_inline(r"$a*b*c$ then *x*")
    assert nodes[0].kind == "math" and nodes[0].text == "a*b*c"
    assert nodes[-1].kind == "italic"


def test_blocks_paragraph_list_and_display_math():
    blocks = parse_blocks("First line\ncontinues.\n\n- one\n- two\n\n"
                          "1. a\n2. b\n\n$$\\int_0^1 f$$")
    assert [b.kind for b in blocks] == ["paragraph", "ul", "ol", "math"]
    assert plain_text(blocks[0].nodes) == "First line continues."
    assert len(blocks[1].items) == 2
    assert blocks[3].math == r"\int_0^1 f"


def test_escape_markdown_makes_text_literal():
    text = r"k*f_s costs $5 [sic] {{x}} \ok"
    assert plain_text(parse_inline(escape_markdown(text))) == text


def test_html_uses_the_math_image_or_falls_back_to_source():
    html = to_html("Hi $x$ **b**", math_image=lambda latex, d: f"<img alt={latex}>")
    assert "<img alt=x>" in html and "<b>b</b>" in html
    plain = to_html("Hi $x<y$")
    assert "<code>$x&lt;y$</code>" in plain


def test_latex_escapes_text_and_keeps_math():
    tex = to_latex("50% of a_b & {c}: $\\frac{1}{s}$\n\n- *it*\n\n$$x^2$$")
    assert r"50\% of a\_b \& \{c\}: $\frac{1}{s}$" in tex
    assert "\\begin{itemize}\n  \\item \\emph{it}\n\\end{itemize}" in tex
    assert "\\[\nx^2\n\\]" in tex
    assert inline_latex("**Part** a)") == r"\textbf{Part} a)"


# ──────────────────────────────────────────────────────────────
#  Placeholders
# ──────────────────────────────────────────────────────────────

def test_values_are_formatted_as_matlab_shows_them():
    assert format_value(np.pi) == "3.1416"
    assert format_value(2.0) == "2"
    assert format_value(np.array([1.0, 2.0, 3.0])) == "[1 2 3]"
    assert format_value(np.array([[1.0, 2.0], [3.0, 4.0]])) == "[1 2; 3 4]"
    assert format_value(np.arange(500.0)) == "1×500 double"
    assert format_value("hello") == "hello"
    assert format_value(True) == "1"
    assert format_value(np.array([7.5])) == "7.5000"


def test_transfer_functions_render_as_fractions():
    G = ctl.tf([4], [1, 0, 4])
    assert value_latex(G) == r"\frac{4}{s^{2} + 4}"
    assert value_latex(ctl.tf([1, -2], [1, 3], 0.1)) == r"\frac{z - 2}{z + 3}"
    assert value_latex(3.0) is None


@pytest.fixture
def interp():
    return Interpreter()


def test_placeholders_read_the_shared_workspace(interp):
    interp.run_matlab("w0 = 2; v = [1 2 3];")
    evaluate = workspace_evaluator(interp)
    assert evaluate("w0") == 2
    html = to_html("w0 is {{w0}}, twice is {{2*w0}}, v is {{v}}",
                   evaluate=evaluate)
    assert "w0 is 2, twice is 4, v is [1 2 3]" in html


def test_placeholders_are_re_evaluated_on_each_render(interp):
    evaluate = workspace_evaluator(interp)
    interp.run_matlab("k = 1;")
    assert "k=1" in to_html("k={{k}}", evaluate=evaluate)
    interp.run_matlab("k = 5;")
    assert "k=5" in to_html("k={{k}}", evaluate=evaluate)


def test_evaluating_leaves_no_trace(interp):
    interp.run_matlab("a = 3;")
    history = list(interp.history)
    before = set(interp.variables())
    assert workspace_evaluator(interp)("a^2 + 1") == 10
    assert interp.history == history
    assert set(interp.variables()) == before


def test_a_bad_placeholder_is_shown_not_raised(interp):
    evaluate = workspace_evaluator(interp)
    with pytest.raises(InterpolationError):
        evaluate("no_such_thing + 1")
    html = to_html("value: {{no_such_thing}}", evaluate=evaluate)
    assert "{{no_such_thing}}" in html and "<code>" in html


def test_transfer_function_placeholder_becomes_math(interp):
    interp.run_matlab("G = tf(4, [1 0 4]);")
    seen = []
    to_html("G = {{G}}", evaluate=workspace_evaluator(interp),
            math_image=lambda latex, d: seen.append(latex) or "<img>")
    assert seen == [r"\frac{4}{s^{2} + 4}"]
