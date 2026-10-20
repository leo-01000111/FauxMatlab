"""
Reports from a live script: .tex (compiled only where a TeX engine exists),
the HTML fallback, and the matplotlib renderings they rely on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fakematlab.console.figures import FigureSpec
from fakematlab.console.interpreter import Interpreter
from fakematlab.console.live import (
    Cell,
    CellKind,
    LiveDocument,
    LiveRunner,
    load,
    workspace_evaluator,
)
from fakematlab.console.live.render import MathError, figure_png, math_png, png_size
from fakematlab.console.live.report import (
    ENGINES,
    compile_pdf,
    engine_command,
    find_engine,
    find_engines,
    tex_error,
    tex_folders,
    to_tex,
    write_html,
    write_tex,
)

SIPRO = Path(__file__).parent / "fixtures" / "sipro"
PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def ran():
    """A small lab, run: text, math, a placeholder, output and a figure."""
    interp = Interpreter()
    doc = LiveDocument([
        Cell.text("Step response lab", CellKind.TITLE),
        Cell.text("Setup", CellKind.HEADING, section_break=True),
        Cell.text("We take $G(s) = \\frac{4}{s^2+2s+4}$ & 50% damping, "
                  "with **w0 = {{w0}}**.\n\n$$\\zeta = \\frac{1}{2}$$\n\n"
                  "- first\n- second"),
        Cell.code("w0 = 2;\nG = tf(w0^2, [1 2 w0^2])"),
        Cell.text("Details", CellKind.HEADING2),
        Cell.code("t = 0:0.05:5;\nplot(t, sin(t)); title('sine')"),
    ])
    assert LiveRunner(interp).run_all(doc)
    return doc, workspace_evaluator(interp)


def test_tex_structure(ran):
    doc, evaluate = ran
    tex = to_tex(doc, evaluate=evaluate, figure_names={doc[5].id: ["f1.png"]})
    assert tex.startswith("\\documentclass")
    assert "\\title{Step response lab}" in tex and "\\maketitle" in tex
    assert "\\section*{Setup}" in tex and "\\subsection*{Details}" in tex
    # Text is escaped, math is passed through as written.
    assert "$G(s) = \\frac{4}{s^2+2s+4}$ \\& 50\\% damping" in tex
    assert "\\textbf{w0 = 2}" in tex                  # the placeholder, filled
    assert "\\[\n\\zeta = \\frac{1}{2}\n\\]" in tex
    assert "\\begin{itemize}" in tex
    assert "\\begin{lstlisting}\nw0 = 2;\nG = tf(w0^2, [1 2 w0^2])\n" \
        "\\end{lstlisting}" in tex
    assert "\\begin{verbatim}\nG =" in tex           # the printed output
    assert "\\includegraphics[width=0.8\\linewidth]{f1.png}" in tex
    assert tex.rstrip().endswith("\\end{document}")


def test_write_tex_saves_figures_beside_it(ran, tmp_path):
    doc, evaluate = ran
    report = write_tex(doc, tmp_path / "lab.tex", evaluate=evaluate)
    assert report.main.read_text(encoding="utf-8").count("\\includegraphics") \
        == 1
    assert [f.name for f in report.figures] == ["lab_fig1.png"]
    assert report.figures[0].read_bytes().startswith(PNG)


def test_html_report_embeds_math_and_figures(ran, tmp_path):
    doc, evaluate = ran
    report = write_html(doc, tmp_path / "lab.html", evaluate=evaluate)
    html = report.main.read_text(encoding="utf-8")
    assert "<h1>Step response lab</h1>" in html and "<h2>Setup</h2>" in html
    assert html.count('class="math"') >= 2            # inline and display
    assert 'class="figure"' in html and "data:image/png;base64," in html
    assert "w0 = 2" in html and "&amp; 50% damping" in html


def test_verbatim_output_is_made_safe_for_pdflatex():
    doc = LiveDocument([Cell.code("x")])
    from fakematlab.console.live import CellOutput
    doc[0].output = CellOutput(text="[1×500 double] … ω → \\end{verbatim}")
    tex = to_tex(doc)
    assert "[1x500 double] ... w -> \\end {verbatim}" in tex


def test_engine_detection_and_commands():
    assert find_engine(lambda name: None) is None
    found = find_engine(lambda name: f"/bin/{name}" if name == "pdflatex"
                        else None)
    assert found == ("pdflatex", "/bin/pdflatex")
    assert ENGINES[0] == "tectonic"                   # preferred
    # latexmk is a Perl script: without Perl it is skipped, not chosen.
    everything = lambda name: f"/bin/{name}" if name != "tectonic" else None
    assert [n for n, _ in find_engines(everything)] == [
        "pdflatex", "xelatex", "latexmk"]
    no_perl = lambda name: None if name in ("perl", "tectonic") \
        else f"/bin/{name}"
    assert [n for n, _ in find_engines(no_perl)] == ["pdflatex", "xelatex"]
    miktex = engine_command("pdflatex", r"C:\MiKTeX\pdflatex.exe", "a.tex")
    assert "--enable-installer" in miktex
    assert "--enable-installer" not in engine_command("pdflatex", "p", "a.tex")
    assert engine_command("tectonic", "t", "a.tex") == ["t", "--keep-logs",
                                                        "a.tex"]
    assert engine_command("latexmk", "l", "a.tex")[1] == "-pdf"
    assert "-halt-on-error" in engine_command("xelatex", "x", "a.tex")


@pytest.mark.skipif(find_engine() is None, reason="no TeX engine on PATH")
def test_report_compiles_to_pdf(ran, tmp_path):
    doc, evaluate = ran
    report = write_tex(doc, tmp_path / "lab.tex", evaluate=evaluate)
    result = compile_pdf(report, find_engine())
    assert result.ok, result.log[-2000:]
    assert result.pdf.read_bytes().startswith(b"%PDF")


def test_c3_report(tmp_path):
    doc = load(SIPRO / "C3.mlx")
    LiveRunner(Interpreter()).run_all(doc)
    tex = write_tex(doc, tmp_path / "c3.tex").main.read_text(encoding="utf-8")
    assert "\\title{C3 - Space shuttle attitude sim}" in tex
    assert "Discrete-time transfer function." in tex


# ── rendering ───────────────────────────────────────────────────

def test_math_renders_to_a_png():
    png = math_png(r"\sum_{n=0}^{N-1} x_n e^{-j\omega n}", display=True)
    assert png.startswith(PNG)
    width, height = png_size(png)
    assert width > height > 10


def test_unsupported_math_raises():
    with pytest.raises(MathError):
        math_png(r"\frac{1}{")


@pytest.mark.parametrize("kind", ["time", "xy", "bode", "nyquist", "pzmap",
                                  "rlocus"])
def test_every_figure_kind_draws(kind, tmp_path):
    spec = FigureSpec(kind, title=kind).add([1, 2, 3], [1, 4, 9], "pole")
    if kind == "bode":
        spec.extra["phase"] = [([1, 2, 3], [-10, -20, -30], "")]
    spec.extra["logx"] = kind == "xy"
    data = figure_png(spec, tmp_path / "f.png")
    assert data.startswith(PNG) and (tmp_path / "f.png").exists()


def test_tex_error_picks_the_line_that_matters():
    log = "lots\nof\nnoise\n! Missing $ inserted.\n<inserted text>\nl.7 x_1"
    assert tex_error(log).startswith("! Missing $ inserted.")
    assert "noise" not in tex_error(log)
    miktex = ("\nSorry, but latexmk.EXE did not succeed for the following "
              "reason:\n\n  MiKTeX could not find the script engine 'perl'")
    assert "perl" in tex_error(miktex)
    assert tex_error("a\nb\nc", lines=2) == "b\nc"


def test_tex_folders_cover_the_default_installs():
    folders = tex_folders({"LOCALAPPDATA": r"C:\U\AppData\Local",
                           "ProgramFiles": r"C:\Program Files",
                           "SystemDrive": "Z:"})
    assert any("AppData" in f and "MiKTeX" in f for f in folders)
    assert any(f.startswith(r"C:\Program Files") and "MiKTeX" in f
               for f in folders)
