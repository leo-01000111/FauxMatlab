"""
The live script as LaTeX under a report template: sections, listings,
figure environments with captions and labels, raw LaTeX in text cells, the
template's preamble — and the captions, labels and template surviving a
save and reopen.
"""

from __future__ import annotations

from evans.console.figures import FigureSpec
from evans.console.live import (
    DEFAULT,
    Cell,
    CellKind,
    CellOutput,
    FigureMeta,
    LiveDocument,
    ReportTemplate,
    load,
    parse_live_document,
    resolve_template,
    save,
    to_live_m,
)
from evans.console.live.latex_text import inline_latex_text, latex_text
from evans.console.live.livem import EVANS_ENTRY
from evans.console.live.report import to_tex, write_tex


def _figure(title: str = "") -> FigureSpec:
    return FigureSpec("xy", title=title).add([0, 1], [0, 1])


def _lab() -> LiveDocument:
    """Title, headings, prose, and code that 'drew' two figures."""
    doc = LiveDocument([
        Cell.text("Lab", CellKind.TITLE),
        Cell.text("Setup", CellKind.HEADING),
        Cell.text("Detail", CellKind.HEADING2),
        Cell.text("Deeper", CellKind.HEADING3),
        Cell.text("Second title", CellKind.TITLE),
        Cell.text("See Figure~\\ref{fig:step}."),
        Cell.code("step(G)"),
        Cell.code("bode(G)"),
    ])
    doc[6].output = CellOutput(text="ans = 1", figures=[_figure("Step")])
    doc[7].output = CellOutput(figures=[_figure("Bode"), _figure()])
    doc[6].meta(0).caption = "The step response, $y(t)$"
    doc[6].meta(0).label = "fig:step"
    return doc


def _tex(doc, template=None, **names) -> str:
    figure_names = {doc[6].id: ["a.png"], doc[7].id: ["b.png", "c.png"]}
    return to_tex(doc, figure_names=figure_names, template=template)


# ── structure ───────────────────────────────────────────────────

def test_first_title_is_maketitle_and_the_rest_are_sections():
    tex = _tex(_lab())
    assert "\\title{Lab}\n\\date{}\n\\maketitle" in tex
    assert tex.count("\\maketitle") == 1
    assert "\\section*{Setup}" in tex
    assert "\\subsection*{Detail}" in tex
    assert "\\subsubsection*{Deeper}" in tex
    assert "\\section*{Second title}" in tex      # a later title


def test_numbered_sections_drop_the_star():
    tex = _tex(_lab(), ReportTemplate(number_sections=True))
    assert "\\section{Setup}" in tex and "\\subsection{Detail}" in tex
    assert "\\subsubsection{Deeper}" in tex and "\\section*" not in tex


def test_code_and_output_can_be_left_out():
    doc = _lab()
    tex = _tex(doc)
    assert "\\begin{lstlisting}\nstep(G)\n\\end{lstlisting}" in tex
    assert "\\begin{verbatim}\nans = 1\n\\end{verbatim}" in tex
    no_code = _tex(doc, ReportTemplate(show_code=False))
    assert "lstlisting}\nstep" not in no_code and "ans = 1" in no_code
    no_output = _tex(doc, ReportTemplate(show_output=False))
    assert "ans = 1" not in no_output and "step(G)" in no_output
    # Figures stay either way.
    assert no_code.count("\\begin{figure}") == 3


def test_every_figure_is_a_figure_environment_with_caption_and_label():
    tex = _tex(_lab())
    assert tex.count("\\begin{figure}[H]") == 3
    assert ("\\begin{figure}[H]\n\\centering\n"
            "\\includegraphics[width=0.8\\linewidth]{a.png}\n"
            "\\caption{The step response, $y(t)$}\n"
            "\\label{fig:step}\n\\end{figure}") in tex
    # No caption of its own: the plot's title; no label: fig:<n>.
    assert "{b.png}\n\\caption{Bode}\n\\label{fig:2}" in tex
    assert "{c.png}\n\\caption{}\n\\label{fig:3}" in tex
    assert "See Figure~\\ref{fig:step}." in tex


def test_figure_width_and_placement_come_from_the_template():
    tex = _tex(_lab(), ReportTemplate(figure_width="12cm",
                                      figure_placement="htbp"))
    assert "\\begin{figure}[htbp]" in tex
    assert "\\includegraphics[width=12cm]{a.png}" in tex


def test_labels_are_sanitised():
    doc = _lab()
    doc[6].meta(0).label = "fig: my {plot}"
    assert "\\label{fig:myplot}" in _tex(doc)


def test_figure_labels_count_across_the_document():
    doc = _lab()
    labels = doc.figure_labels()
    assert labels[doc[6].id, 0] == "fig:step"
    assert labels[doc[7].id, 0] == "fig:2" and labels[doc[7].id, 1] == "fig:3"


def test_write_tex_names_figures_and_reuses_unchanged_drawings(tmp_path):
    doc = _lab()
    cache: dict = {}
    report = write_tex(doc, tmp_path / "lab.tex", cache=cache)
    assert [f.name for f in report.figures] == [
        "lab_fig1.png", "lab_fig2.png", "lab_fig3.png"]
    assert len(cache) == 3
    first = {k: v[1] for k, v in cache.items()}
    write_tex(doc, tmp_path / "lab.tex", cache=cache)
    # The same spec objects: the very same PNG bytes, not redrawn.
    assert all(cache[k][1] is first[k] for k in first)


# ── text cells are LaTeX ────────────────────────────────────────

def test_raw_latex_passes_through():
    source = ("Intro with \\textbf{bold}, \\cite{ogata} and "
              "\\includegraphics[width=2cm]{my_plot.png}.\n\n"
              "\\begin{align*}\na &= b_1 \\\\\nc &= 2\n\\end{align*}\n\n"
              "\\[ \\frac{1}{s} \\]")
    tex = latex_text(source)
    assert "\\textbf{bold}, \\cite{ogata}" in tex
    # Arguments are left as written: no escaping inside them.
    assert "\\includegraphics[width=2cm]{my_plot.png}" in tex
    assert "\\begin{align*}\na &= b_1 \\\\\nc &= 2\n\\end{align*}" in tex
    assert "\\[ \\frac{1}{s} \\]" in tex


def test_markdown_marks_still_work_in_latex_text():
    tex = latex_text("**bold** and *it* and `x_1` and [site](http://a.b/c)"
                     "\n\n- one\n- two\n\n1. first\n2. second\n\n$$x^2$$")
    assert "\\textbf{bold} and \\emph{it} and \\texttt{x\\_1}" in tex
    assert "\\href{http://a.b/c}{site}" in tex
    assert "\\begin{itemize}\n  \\item one\n  \\item two\n\\end{itemize}" in tex
    assert "\\begin{enumerate}" in tex
    assert "\\[\nx^2\n\\]" in tex


def test_prose_is_forgiven_the_characters_latex_rejects():
    tex = inline_latex_text("x_1 & y #2 ^ 50% done, $a_1$ ok")
    assert tex == "x\\_1 \\& y \\#2 \\textasciicircum{} 50\\% done, $a_1$ ok"
    # A % after a space is a comment, to the end of its line only.
    tex = latex_text("kept % dropped by TeX\nnext line")
    assert tex == "kept % dropped by TeX\nnext line"
    # Escapes stay escapes; Markdown's \\* is a literal star.
    assert inline_latex_text("\\$5 \\% \\*") == "\\$5 \\% *"


def test_placeholders_are_filled_in_prose_math_and_environments():
    values = {"w": 3, "name": "a_b"}
    tex = latex_text("w = {{w}}, $\\omega = {{w}}$, {{name}}\n\n"
                     "\\begin{equation}\nk = {{w}}\n\\end{equation}",
                     evaluate=values.__getitem__)
    assert "w = 3, $\\omega = 3$, a\\_b" in tex
    assert "\\begin{equation}\nk = 3\n\\end{equation}" in tex


def test_to_tex_uses_latex_text_or_the_old_escaping():
    doc = LiveDocument([Cell.text("\\emph{x} & y")])
    assert "\\emph{x} \\& y" in to_tex(doc)
    escaped = to_tex(doc, template=ReportTemplate(latex_text=False))
    assert "\\textbackslash{}emph\\{x\\} \\& y" in escaped


# ── the template ────────────────────────────────────────────────

def test_default_preamble_matches_the_old_export():
    pre = DEFAULT.preamble()
    assert pre.startswith("\\documentclass[11pt,a4paper]{article}")
    for line in ("\\usepackage[margin=2.5cm]{geometry}",
                 "\\usepackage{listings}", "\\usepackage[hidelinks]{hyperref}",
                 "\\usepackage{float}", "\\usepackage{lmodern}"):
        assert line in pre
    assert "fancyhdr" not in pre
    tex = to_tex(LiveDocument([Cell.text("T", CellKind.TITLE)]))
    assert tex.startswith(pre)


def test_template_shapes_the_preamble_and_title():
    template = ReportTemplate(
        document_class="report", font_size="12pt", paper="letterpaper",
        margin="1in", font="Palatino", title_page=True, author="Leon",
        date="\\today", contents=True, footer_right="\\thepage",
        header_left="Lab 3", extra_preamble="\\usepackage{siunitx}")
    pre = template.preamble()
    assert pre.startswith(
        "\\documentclass[12pt,letterpaper,titlepage]{report}")
    assert "\\usepackage[margin=1in]{geometry}" in pre
    assert "\\usepackage{mathpazo}" in pre
    assert "\\usepackage{fancyhdr}" in pre and "\\pagestyle{fancy}" in pre
    assert "\\fancyhead[L]{Lab 3}" in pre and "\\fancyfoot[R]{\\thepage}" in pre
    assert "\\usepackage{siunitx}" in pre
    assert pre.index("siunitx") < pre.index("hyperref")
    tex = to_tex(LiveDocument([Cell.text("T", CellKind.TITLE)]),
                 template=template)
    assert ("\\title{T}\n\\author{Leon}\n\\date{\\today}\n\\maketitle\n"
            "\\tableofcontents") in tex


def test_a_raw_preamble_replaces_the_generated_one():
    template = ReportTemplate(raw_preamble="\\documentclass{memoir}\n"
                              "\\usepackage{listings}\n", margin="9cm")
    tex = to_tex(LiveDocument([Cell.code("x")]), template=template)
    assert tex.startswith("\\documentclass{memoir}\n\\usepackage{listings}\n"
                          "\n\\begin{document}")
    assert "geometry" not in tex


def test_template_dict_round_trip_keeps_only_changes():
    assert DEFAULT.to_dict() == {}
    template = ReportTemplate(number_sections=True, margin="2cm")
    assert template.to_dict() == {"number_sections": True, "margin": "2cm"}
    assert ReportTemplate.from_dict(template.to_dict()) == template
    # Junk is ignored, booleans may come back as text from QSettings.
    odd = ReportTemplate.from_dict({"margin": 3, "nope": 1,
                                    "show_code": "false"})
    assert odd.margin == DEFAULT.margin and odd.show_code is False
    assert ReportTemplate.from_dict(None) == DEFAULT


def test_the_document_template_wins_then_the_users_then_the_default():
    mine, users = ReportTemplate(margin="1cm"), ReportTemplate(margin="2cm")
    assert resolve_template(mine, users) is mine
    assert resolve_template(None, users) is users
    assert resolve_template(None, None) is DEFAULT
    doc = LiveDocument([Cell.text("x")], template=mine)
    assert "margin=1cm" in to_tex(doc)               # used when none is given


# ── saved with the live script ──────────────────────────────────

def test_captions_labels_and_template_survive_save_and_reopen(tmp_path):
    doc = _lab()
    doc.template = ReportTemplate(number_sections=True, author="L. G.")
    path = save(doc, tmp_path / "lab.m")
    text = path.read_text(encoding="utf-8")
    assert EVANS_ENTRY in text
    # The entry is in the appendix, after MATLAB's own: the code is untouched.
    assert text.index('%[appendix]{"version":"1.0"}') < text.index(EVANS_ENTRY)
    back = load(path)
    assert [(c.kind, c.source) for c in back] == \
        [(c.kind, c.source) for c in doc]
    code = back.code_cells()
    assert code[0].figure_meta == [FigureMeta("The step response, $y(t)$",
                                              "fig:step")]
    assert code[1].figure_meta == []
    assert back.template == doc.template


def test_a_script_without_extras_has_no_evans_entry():
    doc = LiveDocument([Cell.code("x = 1")])
    doc[0].meta(2)                     # empty entries are not written
    assert EVANS_ENTRY not in to_live_m(doc)


def test_figure_keys_skip_empty_code_cells():
    # An empty code cell is not written, so it must not shift the keys.
    doc = LiveDocument([Cell.code(""), Cell.text("t"), Cell.code("plot(1)")])
    doc[2].meta(0).label = "fig:one"
    back = parse_live_document(to_live_m(doc))
    assert back.code_cells()[0].figure_meta[0].label == "fig:one"


def test_a_broken_evans_entry_is_ignored():
    text = to_live_m(LiveDocument([Cell.code("x")])) + \
        f"{EVANS_ENTRY}\n%   data: {{not json\n%---\n"
    back = parse_live_document(text)
    assert back.template is None and back.code_cells()[0].figure_meta == []


def test_mlx_still_opens_and_saves(tmp_path):
    from pathlib import Path
    sipro = Path(__file__).parent / "fixtures" / "sipro"
    doc = load(sipro / "C1.mlx")
    assert doc.cells and doc.template is None
    doc.code_cells()[0].meta(0).caption = "kept in .m only"
    back = load(save(doc, tmp_path / "c1.mlx"))
    assert back.same_content(doc)
