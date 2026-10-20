"""
Live-script files: MATLAB's .mlx (read and write), its plain-text live .m
(read and write, the native format), and running the SiPro labs.

The fixtures in tests/fixtures/sipro are real live scripts saved by MATLAB
R2023a, with the function files they call beside them.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pytest

from evans.console import matlab_runtime
from evans.console.interpreter import Interpreter
from evans.console.live import (
    Cell,
    CellKind,
    LiveDocument,
    LiveRunner,
    MlxError,
    is_live_text,
    load,
    parse_live_m,
    read_mlx,
    save,
    to_live_m,
)
from evans.console.live.livem import escape_math, unescape_math
from evans.console.live.mlx import document_xml, parse_document_xml

SIPRO = Path(__file__).parent / "fixtures" / "sipro"


def _kinds(doc: LiveDocument) -> str:
    """One letter a cell: T title, H heading, t text, c code; | = break."""
    letter = {CellKind.TITLE: "T", CellKind.HEADING: "H", CellKind.TEXT: "t",
              CellKind.CODE: "c", CellKind.HEADING2: "2", CellKind.HEADING3: "3"}
    return "".join(("|" if c.section_break else "") + letter[c.kind]
                   for c in doc)


# ──────────────────────────────────────────────────────────────
#  .mlx import — the SiPro labs
# ──────────────────────────────────────────────────────────────

def test_c1_imports_title_headings_text_and_code():
    doc = read_mlx(SIPRO / "C1.mlx")
    assert len(doc) == 43
    assert doc.title == "C1 - Fourier Transform"
    headings = [c.source for c in doc if c.kind is CellKind.HEADING]
    assert headings == ["Part a)", "Part b)", "Part c)", "Part d)"]
    # Every heading starts a section: the <w:sectPr/> breaks before them.
    assert all(c.section_break for c in doc if c.kind is CellKind.HEADING)
    assert doc[2].source == "First, we define constants and the n-range"
    first = doc.code_cells()[0].source.splitlines()
    assert first[0] == "Nt = 128;" and first[-1] == "n = 0:Nt-1;"
    assert len(doc.code_cells()) == 19
    assert doc.code_cells()[-1].source.splitlines()[-1] == \
        "plot(fd2, tfxd2)"


def test_c1_consecutive_paragraphs_join_one_text_cell_and_stay_literal():
    doc = read_mlx(SIPRO / "C1.mlx")
    cell = next(c for c in doc if "shannon formula" in c.source)
    assert cell.kind is CellKind.TEXT
    paragraphs = cell.source.split("\n\n")
    assert len(paragraphs) == 2
    # "k*f_s" is prose, not the start of italics: it was escaped on import.
    from evans.console.live.markup import parse_blocks, plain_text
    second = parse_blocks(cell.source)[1]
    assert plain_text(second.nodes) == "f_observed = min(k) |+/- f_actual + k*f_s|"


def test_c2_imports():
    doc = read_mlx(SIPRO / "C2.mlx")
    assert len(doc) == 19
    assert doc.title == "C2 - A basic codec"
    assert [c.source for c in doc if c.kind is CellKind.HEADING] == \
        ["C2.1 - Preliminary spectral analysis", "C2.2 Coder-decoder"]
    code = doc.code_cells()
    assert len(code) == 9
    assert code[0].source.splitlines()[0] == \
        '[y, fs0] = audioread("musique.wav\\musique.wav")'


def test_c3_imports():
    doc = read_mlx(SIPRO / "C3.mlx")
    assert _kinds(doc) == "T|c"
    assert doc.title == "C3 - Space shuttle attitude sim"
    lines = doc[1].source.splitlines()
    assert lines[0] == "w0 = 2;" and lines[-1] == "Atil, Btil, Ctil, Dtil"
    assert doc.folder == SIPRO.resolve() or doc.folder == SIPRO


def test_not_a_live_script_is_a_clear_error(tmp_path):
    bad = tmp_path / "bad.mlx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(MlxError):
        read_mlx(bad)


#: As MATLAB writes equations, nested headings and links (structure taken
#: from a live script saved by a recent MATLAB, abridged).
_EQUATIONS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
    'openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    '<w:p><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/'
    'markup-compatibility/2006"><mc:Choice Requires="R2018b"><w:pPr>'
    '<w:pStyle w:val="heading2"/><w:jc w:val="left"/></w:pPr></mc:Choice>'
    '<mc:Fallback><w:pPr><w:pStyle w:val="heading"/></w:pPr></mc:Fallback>'
    '</mc:AlternateContent><w:r><w:t>1.1.1 Headings</w:t></w:r></w:p>'
    '<w:p><w:pPr><w:pStyle w:val="text"/><w:jc w:val="left"/></w:pPr>'
    '<w:r><w:t>For the formula  </w:t></w:r><w:customXml w:element="equation">'
    '<w:customXmlPr><w:attr w:name="displayStyle" w:val="false"/>'
    '</w:customXmlPr><w:r><w:t>z=x^2+y^2</w:t></w:r></w:customXml>'
    '<w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>'
    '<w:hyperlink w:docLocation="https://example.org"><w:r><w:t>a link'
    '</w:t></w:r></w:hyperlink></w:p>'
    '<w:p><w:pPr><w:pStyle w:val="text"/></w:pPr><w:customXml '
    'w:element="equation"><w:customXmlPr><w:attr w:name="displayStyle" '
    'w:val="true"/></w:customXmlPr><w:r><w:t>\\frac{1}{s}</w:t></w:r>'
    '</w:customXml></w:p></w:body></w:document>')


def test_mlx_equations_headings_links_and_bold():
    cells = parse_document_xml(_EQUATIONS_XML)
    assert [c.kind for c in cells] == [CellKind.HEADING2, CellKind.TEXT]
    assert cells[0].source == "1.1.1 Headings"
    text = cells[1].source
    assert "For the formula  $z=x^2+y^2$**bold**[a link](https://example.org)" \
        in text
    assert text.endswith("\n\n$$\\frac{1}{s}$$")


def test_mlx_written_here_reads_back_the_same(tmp_path):
    doc = LiveDocument([
        Cell.text("My lab", CellKind.TITLE),
        Cell.text("Part 1", CellKind.HEADING, section_break=True),
        Cell.text("Sub", CellKind.HEADING2),
        Cell.text("Has **bold**, *it*, <u>under</u>, $x_1^2$ and "
                  "[a link](https://a.b).\n\n$$\\int_0^1 f(t)\\,dt$$"),
        Cell.code("x = 1;\ny = [x ]]> 2];"),     # CDATA terminator inside
    ])
    path = save(doc, tmp_path / "lab.mlx")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    assert {"matlab/document.xml", "matlab/output.xml", "[Content_Types].xml",
            "_rels/.rels", "metadata/mwcoreProperties.xml"} <= names
    again = read_mlx(path)
    assert again.same_content(doc), [c.source for c in again]


def test_document_xml_matches_the_shape_matlab_writes():
    xml = document_xml(read_mlx(SIPRO / "C3.mlx"))
    assert '<w:pStyle w:val="title"/>' in xml
    assert "<w:p><w:pPr><w:sectPr/></w:pPr></w:p>" in xml
    assert '<w:pStyle w:val="code"/></w:pPr><w:r><w:t><![CDATA[w0 = 2;' in xml


# ──────────────────────────────────────────────────────────────
#  The plain-text live .m (native format)
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["C1", "C2", "C3"])
def test_sipro_round_trips_through_the_plain_text_format(name):
    doc = read_mlx(SIPRO / f"{name}.mlx")
    again = LiveDocument(parse_live_m(to_live_m(doc)))
    assert again.same_content(doc)


def test_plain_text_round_trip_of_every_kind(tmp_path):
    doc = LiveDocument([
        Cell.text("Title $x$", CellKind.TITLE),
        Cell.text("Heading", CellKind.HEADING, section_break=True),
        Cell.text("Two", CellKind.HEADING2),
        Cell.text("Three", CellKind.HEADING3),
        Cell.text("Prose with $\\frac{a_1}{b}$ and **bold** {{w0}}.\n\n"
                  "- one\n- two $\\alpha$\n\n$$\\sum_{n=0}^{N-1} x_n$$"),
        Cell.code("a = 1;\n\nb = 2;  % comment"),
        Cell.code("c = 3"),          # adjacent code cells stay apart …
    ])
    path = save(doc, tmp_path / "live.m")
    again = load(path)
    # … by a section break, which is how MATLAB separates them.
    doc[-1].section_break = True
    assert again.same_content(doc), [(c.kind, c.source) for c in again]
    assert again.path == path.resolve()


def test_plain_text_writer_output():
    doc = LiveDocument([
        Cell.text("Lab", CellKind.TITLE),
        Cell.text("Eq: $\\omega_0$\n\n$$X(k)=\\sum_n x$$\n\n- a\n- b"),
        Cell.code("x = 1 % %[text] lookalike"),
    ])
    text = to_live_m(doc)
    lines = text.splitlines()
    assert lines[:6] == [
        "%[text] # Lab",
        "%[text] Eq: $\\\\omega\\_0$",
        '%[text]{"align":"center"} $X(k)=\\\\sum\\_n x$',
        "%[text] - a",
        "%[text] - b \\",
        "x = 1 % %[text] lookalike",
    ]
    assert '%[appendix]{"version":"1.0"}' in lines
    assert lines[lines.index('%[appendix]{"version":"1.0"}') - 1] == ""
    assert is_live_text(text)


#: Abridged from the examples in MathWorks' "Plain Text File Format for Live
#: Scripts" page (R2025a): outputs, escapes, centred equations, lists, an
#: anchor, a table, and an appendix with data blocks.
_MATHWORKS_STYLE = """\
%[text] # Discrete Fourier transform
%[text] Here is how to square four: $x = 4^2$
%[text]{"align":"center"} $ X(k) = \\\\sum\\_{n=0}^{N-1} x(n) e^{-j2\\\\pi kn/N} $
%%
%[text] ## Data
%[text:anchor:T_data]
%[text] - first item
%[text] - last item \\
x = 4^2;
fprintf("%d\\n", x); %[output:3ffe5f06]
s = 5; %[control:slider:9a1b]{"position":[5,6]}
%[text:table]
%[text]| a | b |
%[text]| --- | --- |
%[text]| 1 | 2 |
%[text:table]

%[appendix]{"version":"1.0"}
%---
%[output:3ffe5f06]
%   data: {"dataType":"text","outputData":{"text":"16\\n"}}
%---
%[metadata:view]
%   data: {"layout":"inline"}
%---
"""


def test_reads_the_mathworks_examples():
    cells = parse_live_m(_MATHWORKS_STYLE)
    kinds = [c.kind for c in cells]
    assert kinds == [CellKind.TITLE, CellKind.TEXT, CellKind.HEADING,
                     CellKind.TEXT, CellKind.CODE, CellKind.TEXT]
    assert cells[0].source == "Discrete Fourier transform"
    intro = cells[1].source.split("\n\n")
    assert intro[0] == "Here is how to square four: $x = 4^2$"
    assert intro[1] == "$$X(k) = \\sum_{n=0}^{N-1} x(n) e^{-j2\\pi kn/N}$$"
    assert cells[2].section_break
    assert cells[3].source == "- first item\n- last item"
    assert cells[4].source == 'x = 4^2;\nfprintf("%d\\n", x);\ns = 5;'
    assert cells[5].source == "- a · b\n- 1 · 2"
    # Nothing from the appendix leaks into the cells.
    assert not any("data:" in c.source for c in cells)


def test_math_escapes_are_inverse():
    latex = "$\\frac{a_1}{b} * c$ and \\_ outside"
    assert unescape_math(escape_math(latex)) == latex
    assert escape_math("$\\alpha_1$") == "$\\\\alpha\\_1$"


def test_an_ordinary_m_file_opens_as_cells(tmp_path):
    path = tmp_path / "plain.m"
    path.write_text("% setup\nx = 1;\n%% Plot it\nplot(x)\n", encoding="utf-8")
    assert not is_live_text(path.read_text())
    doc = load(path)
    assert [c.kind for c in doc] == [CellKind.CODE, CellKind.HEADING,
                                     CellKind.CODE]
    assert doc[1].source == "Plot it" and doc[1].section_break
    assert doc[2].source == "plot(x)"


# ──────────────────────────────────────────────────────────────
#  Running
# ──────────────────────────────────────────────────────────────

def test_c3_runs_end_to_end():
    doc = load(SIPRO / "C3.mlx")
    interp = Interpreter()
    assert LiveRunner(interp).run_all(doc)
    output = doc[1].output
    assert output.ok, output.error
    assert "sysd =" in output.text and "Discrete-time transfer function." \
        in output.text
    assert "Atil =" in output.text and "Dtil = 0" in output.text
    np.testing.assert_allclose(interp.namespace["Atil"],
                               [[0.9801, 0.0993], [-0.3973, 0.9801]],
                               atol=1e-4)


def test_cells_run_in_the_scripts_folder(tmp_path, monkeypatch):
    doc = LiveDocument([Cell.code("x = 1")], tmp_path / "lab.m")
    interp = Interpreter()
    seen = []
    real = interp.run_script
    monkeypatch.setattr(interp, "run_script",
                        lambda src, lang, folder=None:
                        seen.append((os.getcwd(), folder)) or
                        real(src, lang, folder=folder))
    before = os.getcwd()
    LiveRunner(interp).run_all(doc)
    cwd, folder = seen[0]
    assert Path(cwd).resolve() == tmp_path.resolve()
    assert Path(folder).resolve() == tmp_path.resolve()  # and MATLAB's pwd
    assert os.getcwd() == before               # and the folder is restored


def test_figures_and_errors_stay_with_their_cell():
    from evans.console.figures import figure_sink, set_figure_sink

    drawn = []
    previous = set_figure_sink(drawn.append)
    try:
        doc = LiveDocument([
            Cell.code("t = 0:0.1:1; plot(t, t.^2); title('square')"),
            Cell.code("y = undefined_thing + 1"),
            Cell.code("z = 3"),
        ])
        runner = LiveRunner(Interpreter())
        assert not runner.run_all(doc)
        assert figure_sink() == drawn.append    # the sink is put back
    finally:
        set_figure_sink(previous)
    assert drawn == []                          # nothing leaked to the console
    assert [f.title for f in doc[0].output.figures] == ["square"]
    assert "undefined_thing" in doc[1].output.error
    assert doc[2].output is None                # Run all stopped at the error


def test_run_to_here_stops_at_the_cell():
    doc = LiveDocument([Cell.code("a = 1"), Cell.text("note"),
                        Cell.code("b = a + 1"), Cell.code("c = 99")])
    interp = Interpreter()
    assert LiveRunner(interp).run_to(doc, doc[2])
    assert interp.namespace["b"] == 2 and "c" not in interp.namespace
    assert "b = 2" in doc[2].output.text


@pytest.mark.parametrize("name", ["C1", "C2", "C3"])
def test_sipro_live_scripts_run_end_to_end(name, tmp_path, monkeypatch):
    # A copy, since C2 writes compressed\musique.wav beside the script.
    folder = tmp_path / "sipro"
    shutil.copytree(SIPRO, folder)
    monkeypatch.setattr(matlab_runtime, "_play", lambda data, rate: None)
    monkeypatch.setattr(matlab_runtime, "_pause_for", lambda seconds: None)
    doc = load(folder / f"{name}.mlx")
    assert LiveRunner(Interpreter()).run_all(doc), [
        c.output.error for c in doc.cells if c.is_code and c.output and c.output.error]
