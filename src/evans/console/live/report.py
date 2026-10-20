"""
A live script as a report: LaTeX (compiled to PDF when a TeX engine is
installed) or, failing that, a self-contained HTML page.

The .tex is written so it compiles with any of the engines looked for —
tectonic, pdflatex, xelatex, latexmk — using only packages every TeX
distribution ships: amsmath, graphicx, listings, xcolor, hyperref.

* The first title is ``\\title`` + ``\\maketitle``; any later title and the
  headings are ``\\section`` / ``\\subsection`` / ``\\subsubsection``,
  starred unless the template numbers sections.
* Text cells are LaTeX (see :mod:`.latex_text`), or with the template's
  ``latex_text`` off, the Markdown dialect with special characters escaped.
* Code is a ``lstlisting`` in MATLAB style; printed output is ``verbatim``;
  the template can leave either out.
* Each figure is a PNG beside the .tex, in a ``figure`` environment with its
  caption and ``\\label`` (``fig:<n>`` unless the cell gives one).

The layout — preamble, title page, header and footer — comes from a
:class:`~.template.ReportTemplate`, the same one the live preview uses.
Placeholders (``{{expr}}``) are filled with the workspace's values at export.
"""

from __future__ import annotations

import base64
import html
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .document import CellKind, LiveDocument
from .latex_text import inline_latex_text, latex_text
from .markup import Evaluator, inline_html, inline_latex, to_html, to_latex
from .render import MathError, figure_png, math_png
from .template import DEFAULT, ReportTemplate

#: In the order they are preferred. tectonic is a single self-contained
#: binary that fetches packages on demand; the others come with a TeX
#: distribution (MiKTeX, TeX Live). latexmk is last, and only used when Perl
#: is installed: it is a Perl script, and on Windows MiKTeX ships the
#: launcher without the interpreter — an install with latexmk on PATH but no
#: Perl is the usual MiKTeX setup, and choosing latexmk there failed every
#: export while pdflatex beside it worked.
ENGINES = ("tectonic", "pdflatex", "xelatex", "latexmk")

#: Engines that need a second pass for hyperref's outlines and page labels.
#: (tectonic and latexmk rerun by themselves.)
TWO_PASS = ("pdflatex", "xelatex")

INSTALL_HINT = (
    "No TeX engine was found, so the report was written as HTML instead.\n\n"
    "To get PDFs, install one of:\n"
    "  • MiKTeX (Windows, https://miktex.org/download) — pdflatex/xelatex, "
    "installs missing packages on first use;\n"
    "  • tectonic (https://tectonic-typesetting.github.io) — a single "
    "binary: download it, put it on PATH, done.\n"
    "Then export again.")


def tex_folders(environ=os.environ) -> list[str]:
    """
    Where TeX distributions install their binaries by default on Windows.

    Searched after PATH: an app started from the Start menu or the bundled
    exe can have a PATH that predates the TeX install, or MiKTeX may have
    been installed for one user without touching PATH at all.
    """
    miktex = os.path.join("MiKTeX", "miktex", "bin", "x64")
    folders = []
    if environ.get("LOCALAPPDATA"):                 # "for me only"
        folders.append(os.path.join(environ["LOCALAPPDATA"], "Programs",
                                    miktex))
    if environ.get("ProgramFiles"):                 # "for all users"
        folders.append(os.path.join(environ["ProgramFiles"], miktex))
    texlive = Path(environ.get("SystemDrive", "C:") + os.sep, "texlive")
    if texlive.is_dir():
        for year in sorted(texlive.iterdir(), reverse=True):
            folders.append(str(year / "bin" / "windows"))
            folders.append(str(year / "bin" / "win32"))
    return folders


def _which(name: str) -> str | None:
    """``shutil.which``, then the distributions' default folders."""
    return shutil.which(name) or shutil.which(
        name, path=os.pathsep.join(tex_folders()))


def find_engines(which=_which) -> list[tuple[str, str]]:
    """Every usable TeX engine, as (name, path), in order of preference."""
    found = []
    for name in ENGINES:
        if name == "latexmk" and not which("perl"):
            continue
        path = which(name)
        if path:
            found.append((name, path))
    return found


def find_engine(which=_which) -> tuple[str, str] | None:
    """(name, path) of the preferred TeX engine, or None."""
    engines = find_engines(which)
    return engines[0] if engines else None


def engine_command(name: str, path: str, tex: str) -> list[str]:
    """The command line that turns ``tex`` (a file name) into a PDF beside it."""
    if name == "tectonic":
        return [path, "--keep-logs", tex]
    # MiKTeX asks before fetching a missing package, in a dialog no one sees
    # from a background build; this lets it install without asking.
    miktex = ["--enable-installer"] if "miktex" in path.lower() else []
    if name == "latexmk":
        return [path, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
                *(["-latexoption=--enable-installer"] if miktex else []), tex]
    return [path, *miktex, "-interaction=nonstopmode", "-halt-on-error", tex]


def tex_error(log: str, lines: int = 15) -> str:
    """
    The part of a build log worth showing: TeX's own ``!`` error with the
    line it points at, or a distribution's "did not succeed" explanation,
    or else the log's last lines.
    """
    text = log.strip().splitlines()
    for i, line in enumerate(text):
        if line.startswith("! "):
            tail = text[i:i + 8]
            return "\n".join(row for row in tail if row.strip())
    for i, line in enumerate(text):
        if "did not succeed" in line:
            return "\n".join(row for row in text[i:i + 6] if row.strip())
    return "\n".join(text[-lines:])


@dataclass
class Report:
    """What an export wrote."""
    main:    Path                       # the .tex or .html
    figures: list[Path] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
#  LaTeX
# ──────────────────────────────────────────────────────────────

#: What every export wrote before templates: the default template's preamble.
_PREAMBLE = DEFAULT.preamble()

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


def _label(text: str) -> str:
    """A label as ``\\label`` accepts it: no braces, backslashes or spaces."""
    return "".join(c for c in text.strip() if c not in "{}\\%#" and
                   not c.isspace())


def to_tex(document: LiveDocument, *, evaluate: Evaluator | None = None,
           figure_names: dict[int, list[str]] | None = None,
           template: ReportTemplate | None = None) -> str:
    """
    The document as LaTeX source. ``figure_names`` maps a cell's id to the
    PNG file names (relative to the .tex) of its figures. ``template`` is
    the layout; the document's own, or the default, when not given.
    """
    template = template or document.template or DEFAULT
    figure_names = figure_names or {}
    labels = document.figure_labels()

    def inline(text: str) -> str:
        if template.latex_text:
            return inline_latex_text(text, evaluate=evaluate)
        return inline_latex(text, evaluate=evaluate)

    body: list[str] = []
    title_done = False
    for cell in document.cells:
        kind = cell.kind
        if kind is CellKind.TITLE and not title_done:
            title = inline(cell.source)
            author = template.author.strip()
            body.append(f"\\title{{{title}}}\n"
                        + (f"\\author{{{author}}}\n" if author else "")
                        + f"\\date{{{template.date.strip()}}}\n\\maketitle"
                        + ("\n\\tableofcontents" if template.contents else ""))
            title_done = True
        elif kind.is_heading:
            command = template.section_command(max(kind.level, 1))
            body.append(f"{command}{{{inline(cell.source)}}}")
        elif kind is CellKind.TEXT:
            text = (latex_text(cell.source, evaluate=evaluate)
                    if template.latex_text
                    else to_latex(cell.source, evaluate=evaluate))
            if text.strip():
                body.append(text)
        else:
            if template.show_code and cell.source.strip():
                body.append(_verbatim("lstlisting", cell.source))
            output = cell.output
            if output is None:
                continue
            printed = "\n".join(p for p in (output.text, output.error) if p)
            if template.show_output and printed.strip():
                body.append(_verbatim("verbatim", printed))
            for i, name in enumerate(figure_names.get(cell.id, [])):
                meta = cell.figure_meta[i] if i < len(cell.figure_meta) \
                    else None
                caption = inline(meta.caption) if meta and \
                    meta.caption.strip() else ""
                if not caption and i < len(output.figures):
                    caption = inline(output.figures[i].title or "")
                label = _label(labels.get((cell.id, i), ""))
                placement = template.figure_placement or "H"
                body.append(
                    f"\\begin{{figure}}[{placement}]\n\\centering\n"
                    f"\\includegraphics[width={template.figure_width}]"
                    f"{{{name}}}\n\\caption{{{caption}}}\n"
                    + (f"\\label{{{label}}}\n" if label else "")
                    + "\\end{figure}")
    if template.contents and not title_done:
        body.insert(0, "\\tableofcontents")
    return (template.preamble() + "\n\\begin{document}\n\n"
            + "\n\n".join(body) + "\n\n\\end{document}\n")


def figure_files(document: LiveDocument, path: Path,
                 cache: dict | None = None) -> tuple[dict[int, list[str]],
                                                     list[Path]]:
    """
    Draw every figure as ``<stem>_fig<n>.png`` beside ``path``. ``cache``
    (spec id → (spec, png bytes)) spares redrawing figures that have not
    changed since the last call — the live preview rebuilds often.
    """
    names: dict[int, list[str]] = {}
    files: list[Path] = []
    n = 0
    fresh = {}
    for cell in document.code_cells():
        if cell.output is None:
            continue
        for spec in cell.output.figures:
            n += 1
            file = path.with_name(f"{path.stem}_fig{n}.png")
            hit = cache.get(id(spec)) if cache is not None else None
            if hit is not None and hit[0] is spec:
                png = hit[1]
                if not file.exists() or file.read_bytes() != png:
                    file.write_bytes(png)
            else:
                png = figure_png(spec, file)
            fresh[id(spec)] = (spec, png)
            files.append(file)
            names.setdefault(cell.id, []).append(file.name)
    if cache is not None:
        cache.clear()
        cache.update(fresh)
    return names, files


def write_tex(document: LiveDocument, path: str | Path, *,
              evaluate: Evaluator | None = None,
              template: ReportTemplate | None = None,
              cache: dict | None = None) -> Report:
    """Write ``path`` (.tex) and its figures as ``<stem>_fig<n>.png`` beside it."""
    path = Path(path)
    names, files = figure_files(document, path, cache)
    path.write_text(to_tex(document, evaluate=evaluate, figure_names=names,
                           template=template), encoding="utf-8")
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
    with tempfile.TemporaryDirectory(prefix="evans-report-") as tmp:
        work = Path(tmp)
        shutil.copy2(report.main, work / report.main.name)
        for figure in report.figures:
            shutil.copy2(figure, work / figure.name)
        # No console window flashing up for each pass from the windowed exe.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log = ""
        for _ in range(2 if name in TWO_PASS else 1):
            try:
                done = subprocess.run(
                    engine_command(name, exe, report.main.name), cwd=work,
                    capture_output=True, text=True, timeout=timeout,
                    stdin=subprocess.DEVNULL, creationflags=flags,
                    encoding="utf-8", errors="replace")
            except (OSError, subprocess.TimeoutExpired) as exc:
                return BuildResult(False, None, f"{name}: {exc}")
            log = (done.stdout or "") + (done.stderr or "")
            if done.returncode != 0:
                break
        built = work / (report.main.stem + ".pdf")
        if done.returncode != 0 or not built.exists():
            return BuildResult(False, None, log)
        target = report.main.with_suffix(".pdf")
        shutil.copy2(built, target)
        return BuildResult(True, target, log)


def build_with(report: Report, engines, compile=None
               ) -> tuple[bool, Path | None, str]:
    """
    Try each engine in turn until one makes the PDF: (ok, pdf, log), the log
    on failure being each engine's error line. Runs on a build thread, so
    nothing may escape it — an exception would leave the caller waiting for
    ever. ``compile`` stands in for :func:`compile_pdf` (tests stub it).
    """
    compile = compile or compile_pdf
    failures = []
    for engine in engines:
        try:
            result = compile(report, engine)
        except Exception as exc:                      # noqa: BLE001
            result = BuildResult(False, None, f"{type(exc).__name__}: {exc}")
        if result.ok:
            return True, result.pdf, result.log
        failures.append(f"{engine[0]}:\n{tex_error(result.log)}")
    return False, None, "\n\n".join(failures)


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
p.caption { text-align: center; font-size: 0.9rem; margin-top: 0; }
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
                   evaluate: Evaluator | None = None,
                   template: ReportTemplate | None = None) -> str:
    """A single self-contained HTML file: math and figures embedded."""
    template = template or document.template or DEFAULT
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
            if template.show_code and cell.source.strip():
                parts.append(f'<pre class="code">{html.escape(cell.source)}'
                             "</pre>")
            output = cell.output
            if output is None:
                continue
            if template.show_output and output.text.strip():
                parts.append(f'<pre class="output">'
                             f"{html.escape(output.text)}</pre>")
            if output.error:
                parts.append(f'<pre class="error">{html.escape(output.error)}'
                             "</pre>")
            for i, spec in enumerate(output.figures):
                parts.append(f'<img class="figure" alt="figure" '
                             f'src="{_data_uri(figure_png(spec))}">')
                caption = cell.figure_meta[i].caption.strip() \
                    if i < len(cell.figure_meta) else ""
                if caption:
                    parts.append(f'<p class="caption">'
                                 f"{html.escape(caption)}</p>")
    title = html.escape(document.title)
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{title}</title><style>{_CSS}</style></head><body>\n"
            + "\n".join(parts) + "\n</body></html>\n")


def write_html(document: LiveDocument, path: str | Path, *,
               evaluate: Evaluator | None = None,
               template: ReportTemplate | None = None) -> Report:
    path = Path(path)
    path.write_text(to_html_report(document, evaluate=evaluate,
                                   template=template), encoding="utf-8")
    return Report(path)
