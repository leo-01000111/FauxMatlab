"""
A live script as a report: LaTeX (compiled to PDF when a TeX engine is
installed) or, failing that, a self-contained HTML page.

The .tex is written so it compiles with any of the engines looked for —
tectonic, pdflatex, xelatex, latexmk — using only packages every TeX
distribution ships: amsmath, graphicx, listings, xcolor, hyperref.

* The first title is ``\\title`` + ``\\maketitle``; any later title and the
  headings are ``\\section*`` / ``\\subsection*`` / ``\\subsubsection*``.
* Prose is converted from the cell markup; math is passed through as-is.
* Code is a ``lstlisting`` in MATLAB style; printed output is ``verbatim``.
* Figures are PNGs beside the .tex, placed with ``\\includegraphics``.

Placeholders (``{{expr}}``) are filled with the workspace's values at export.
"""

from __future__ import annotations

import base64
import html
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .document import CellKind, LiveDocument
from .markup import Evaluator, inline_html, inline_latex, to_html, to_latex
from .render import MathError, figure_png, math_png

#: In the order they are preferred. tectonic is a single self-contained
#: binary that fetches packages on demand; the others come with a TeX
#: distribution (MiKTeX, TeX Live).
ENGINES = ("tectonic", "latexmk", "pdflatex", "xelatex")

INSTALL_HINT = (
    "No TeX engine was found, so the report was written as HTML instead.\n\n"
    "To get PDFs, install one of:\n"
    "  • MiKTeX (Windows, https://miktex.org/download) — pdflatex/xelatex, "
    "installs missing packages on first use;\n"
    "  • tectonic (https://tectonic-typesetting.github.io) — a single "
    "binary: download it, put it on PATH, done.\n"
    "Then export again.")


def find_engine(which=shutil.which) -> tuple[str, str] | None:
    """(name, path) of the first TeX engine on PATH, or None."""
    for name in ENGINES:
        path = which(name)
        if path:
            return name, path
    return None


def engine_command(name: str, path: str, tex: str) -> list[str]:
    """The command line that turns ``tex`` (a file name) into a PDF beside it."""
    if name == "tectonic":
        return [path, "--keep-logs", tex]
    if name == "latexmk":
        return [path, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
                tex]
    return [path, "-interaction=nonstopmode", "-halt-on-error", tex]


@dataclass
class Report:
    """What an export wrote."""
    main:    Path                       # the .tex or .html
    figures: list[Path] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
#  LaTeX
# ──────────────────────────────────────────────────────────────

_PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[utf8]{inputenc}
  \usepackage[T1]{fontenc}
\fi
\usepackage[margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage{listings}
\usepackage[hidelinks]{hyperref}
\lstset{language=Matlab, basicstyle=\ttfamily\small, breaklines=true,
  frame=single, rulecolor=\color{black!40}, columns=fullflexible,
  keywordstyle=\color{blue!60!black}, commentstyle=\color{green!40!black},
  stringstyle=\color{red!60!black}, upquote=true}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.6em}
"""

#: Verbatim and listings blocks are passed to the engine untouched, and
#: pdflatex has no glyphs for these. ASCII spellings keep every engine happy.
_ASCII = str.maketrans({
    "×": "x", "…": "...", "→": "->", "←": "<-", "−": "-", "–": "-",
    "—": "--", "°": " deg", "ω": "w", "ζ": "zeta", "π": "pi", "≈": "~",
    "≤": "<=", "≥": ">=", "·": ".", "µ": "u", "Δ": "D", "φ": "phi",
    "‘": "'", "’": "'", "“": '"', "”": '"',
})


def _ascii(text: str) -> str:
    text = text.translate(_ASCII)
    return "".join(c if ord(c) < 128 or c in "\n\t" else "?" for c in text)


def _verbatim(env: str, text: str, options: str = "") -> str:
    body = _ascii(text.rstrip("\n")).replace(f"\\end{{{env}}}",
                                             f"\\end {{{env}}}")
    return f"\\begin{{{env}}}{options}\n{body}\n\\end{{{env}}}"


def to_tex(document: LiveDocument, *, evaluate: Evaluator | None = None,
           figure_names: dict[int, list[str]] | None = None) -> str:
    """
    The document as LaTeX source. ``figure_names`` maps a cell's id to the
    PNG file names (relative to the .tex) of its figures.
    """
    figure_names = figure_names or {}
    body: list[str] = []
    title_done = False
    for cell in document.cells:
        kind = cell.kind
        if kind is CellKind.TITLE and not title_done:
            title = inline_latex(cell.source, evaluate=evaluate)
            body.append(f"\\title{{{title}}}\n\\date{{}}\n\\maketitle")
            title_done = True
        elif kind.is_heading:
            command = {CellKind.TITLE: "section", CellKind.HEADING: "section",
                       CellKind.HEADING2: "subsection",
                       CellKind.HEADING3: "subsubsection"}[kind]
            body.append(f"\\{command}*{{"
                        f"{inline_latex(cell.source, evaluate=evaluate)}}}")
        elif kind is CellKind.TEXT:
            text = to_latex(cell.source, evaluate=evaluate)
            if text.strip():
                body.append(text)
        else:
            if cell.source.strip():
                body.append(_verbatim("lstlisting", cell.source))
            output = cell.output
            if output is not None:
                printed = "\n".join(p for p in (output.text, output.error)
                                    if p)
                if printed.strip():
                    body.append(_verbatim("verbatim", printed))
                for name in figure_names.get(cell.id, []):
                    body.append("\\begin{center}\n"
                                f"\\includegraphics[width=0.8\\linewidth]"
                                f"{{{name}}}\n\\end{{center}}")
    return (_PREAMBLE + "\n\\begin{document}\n\n" + "\n\n".join(body)
            + "\n\n\\end{document}\n")


def write_tex(document: LiveDocument, path: str | Path, *,
              evaluate: Evaluator | None = None) -> Report:
    """Write ``path`` (.tex) and its figures as ``<stem>_fig<n>.png`` beside it."""
    path = Path(path)
    names: dict[int, list[str]] = {}
    files: list[Path] = []
    n = 0
    for cell in document.code_cells():
        if cell.output is None:
            continue
        for spec in cell.output.figures:
            n += 1
            file = path.with_name(f"{path.stem}_fig{n}.png")
            figure_png(spec, file)
            files.append(file)
            names.setdefault(cell.id, []).append(file.name)
    path.write_text(to_tex(document, evaluate=evaluate, figure_names=names),
                    encoding="utf-8")
    return Report(path, files)


@dataclass
class BuildResult:
    ok:  bool
    pdf: Path | None
    log: str


def compile_pdf(report: Report, engine: tuple[str, str],
                timeout: float = 300) -> BuildResult:
    """
    Compile a written .tex to PDF in a temporary folder, and copy the PDF
    back beside the .tex. Blocking — the editor runs it off the UI thread.
    """
    name, exe = engine
    with tempfile.TemporaryDirectory(prefix="fauxmatlab-report-") as tmp:
        work = Path(tmp)
        shutil.copy2(report.main, work / report.main.name)
        for figure in report.figures:
            shutil.copy2(figure, work / figure.name)
        try:
            done = subprocess.run(
                engine_command(name, exe, report.main.name), cwd=work,
                capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return BuildResult(False, None, str(exc))
        log = (done.stdout or "") + (done.stderr or "")
        built = work / (report.main.stem + ".pdf")
        if done.returncode != 0 or not built.exists():
            return BuildResult(False, None, log)
        target = report.main.with_suffix(".pdf")
        shutil.copy2(built, target)
        return BuildResult(True, target, log)


# ──────────────────────────────────────────────────────────────
#  HTML
# ──────────────────────────────────────────────────────────────

_CSS = """
body { font-family: "Segoe UI", Helvetica, Arial, sans-serif; color: #121314;
       background: #f5f5f2; max-width: 52rem; margin: 2rem auto;
       padding: 0 1rem; line-height: 1.5; }
h1 { font-size: 1.9rem; border-bottom: 3px solid #121314; }
h2 { font-size: 1.4rem; margin-top: 2rem; }
h3, h4 { font-size: 1.15rem; }
pre { font-family: Consolas, "Cascadia Mono", Menlo, monospace;
      font-size: 0.85rem; padding: 0.6rem 0.8rem; overflow-x: auto; }
pre.code { background: #e7e8e3; border-left: 4px solid #f5c518; }
pre.output { background: #ffffff; border: 1px solid #c4c7bf; }
pre.error { background: #fff; border: 1px solid #c1122e; color: #b0102a; }
img.math { vertical-align: middle; }
img.figure { max-width: 100%; display: block; margin: 0.5rem auto; }
"""


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def html_math_image(latex: str, display: bool) -> str | None:
    """Math as an embedded PNG, drawn at 2× and shown at 1× for sharpness."""
    from .render import png_size
    try:
        png = math_png(latex, display=display, dpi=200)
    except MathError:
        return None
    width, height = png_size(png)
    return (f'<img class="math" alt="{html.escape(latex, quote=True)}" '
            f'width="{round(width * 96 / 200)}" '
            f'height="{round(height * 96 / 200)}" src="{_data_uri(png)}">')


def to_html_report(document: LiveDocument, *,
                   evaluate: Evaluator | None = None) -> str:
    """A single self-contained HTML file: math and figures embedded."""
    parts: list[str] = []
    for cell in document.cells:
        kind = cell.kind
        if kind.is_heading:
            tag = f"h{kind.level + 1}"
            parts.append(f"<{tag}>{inline_html(cell.source, evaluate=evaluate, math_image=html_math_image)}</{tag}>")
        elif kind is CellKind.TEXT:
            parts.append(to_html(cell.source, evaluate=evaluate,
                                 math_image=html_math_image))
        else:
            if cell.source.strip():
                parts.append(f'<pre class="code">{html.escape(cell.source)}'
                             "</pre>")
            output = cell.output
            if output is None:
                continue
            if output.text.strip():
                parts.append(f'<pre class="output">'
                             f"{html.escape(output.text)}</pre>")
            if output.error:
                parts.append(f'<pre class="error">{html.escape(output.error)}'
                             "</pre>")
            for spec in output.figures:
                parts.append(f'<img class="figure" alt="figure" '
                             f'src="{_data_uri(figure_png(spec))}">')
    title = html.escape(document.title)
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{title}</title><style>{_CSS}</style></head><body>\n"
            + "\n".join(parts) + "\n</body></html>\n")


def write_html(document: LiveDocument, path: str | Path, *,
               evaluate: Evaluator | None = None) -> Report:
    path = Path(path)
    path.write_text(to_html_report(document, evaluate=evaluate),
                    encoding="utf-8")
    return Report(path)
