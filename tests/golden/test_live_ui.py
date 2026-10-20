"""
The live-script editor, offscreen: cells build, run, render math, move,
save, open and export — and it sits in the Console as the "Live" tab.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtWidgets import QApplication

from fakematlab.console.figures import figure_sink, set_figure_sink
from fakematlab.console.interpreter import Interpreter
from fakematlab.console.live import Cell, CellKind, LiveDocument, load
from fakematlab.ui.console.live_editor import (
    CodeCellWidget,
    LiveScriptEditor,
    TextCellWidget,
    set_code_highlighter,
)

SIPRO = Path(__file__).parent.parent / "fixtures" / "sipro"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def editor(app):
    widget = LiveScriptEditor(Interpreter())
    widget.resize(900, 700)
    widget.show()
    _settle(app)
    messages = []
    widget._inform = lambda title, text, warning=False: messages.append(
        (title, text))
    widget.messages = messages
    yield widget
    widget.hide()
    widget.deleteLater()


def _settle(app, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


def test_starts_with_one_code_cell(editor):
    assert len(editor.document) == 1
    assert isinstance(editor.cell_widgets[0], CodeCellWidget)
    assert editor.path is None and editor.folder is None


def test_opens_c3_and_runs_it(app, editor):
    assert editor.open(SIPRO / "C3.mlx")
    _settle(app)
    assert editor.folder == (SIPRO / "C3.mlx").resolve().parent
    widgets = editor.cell_widgets
    assert isinstance(widgets[0], TextCellWidget) and not widgets[0].editing
    assert "Space shuttle" in widgets[0].view.toPlainText()
    assert editor.run_all()
    _settle(app)
    code = widgets[1]
    assert "sysd =" in code.output.toPlainText()
    assert not code.output.isHidden() and code.error.isHidden()
    assert "Atil" in editor.interpreter.variables()


def test_code_cell_shows_its_figure_inline_not_in_the_console(app, editor):
    drawn = []
    previous = set_figure_sink(drawn.append)
    try:
        cell = editor.document[0]
        editor.cell_widgets[0].editor.setPlainText(
            "t = 0:0.1:2; plot(t, t.^2); title('parabola')")
        assert editor.run_cell(cell)
        _settle(app)
        assert figure_sink() == drawn.append
    finally:
        set_figure_sink(previous)
    assert drawn == []
    views = editor.widget_for(cell).figure_views
    assert len(views) == 1 and views[0].spec.title == "parabola"
    requested = []
    editor.figure_requested.connect(requested.append)
    editor.widget_for(cell).figure_requested.emit(views[0].spec)
    assert requested and requested[0].title == "parabola"


def test_an_error_is_shown_under_its_cell(app, editor):
    editor.cell_widgets[0].editor.setPlainText("x = nope + 1")
    assert not editor.run_current()
    _settle(app)
    widget = editor.cell_widgets[0]
    assert "nope" in widget.error.text() and not widget.error.isHidden()


def test_text_cell_renders_math_and_workspace_values(app, editor):
    editor.interpreter.run_matlab("gain = 2.5;")
    cell = editor.add_cell(CellKind.TEXT)
    widget = editor.widget_for(cell)
    assert widget.editing
    widget.editor.setPlainText("Gain is {{gain}} and $\\frac{1}{s}$.\n\n"
                               "$$\\int_0^1 t\\,dt$$")
    widget.set_editing(False)
    _settle(app)
    assert not widget.editing
    assert "Gain is 2.5000" in widget.view.toPlainText()
    html = widget.view.toHtml()
    assert html.count("mathimg://") == 2 and not widget.view.failed
    # Re-evaluated on the next run.
    editor.interpreter.run_matlab("gain = 4;")
    editor.run_all()
    _settle(app)
    assert "Gain is 4" in widget.view.toPlainText()


def test_unparseable_math_falls_back_to_source(app, editor):
    cell = editor.add_cell(CellKind.TEXT)
    widget = editor.widget_for(cell)
    widget.editor.setPlainText("Bad: $\\frac{1}{$ here")
    widget.set_editing(False)
    assert widget.view.failed and "$\\frac{1}{$" in widget.view.toPlainText()


def test_kind_switch_makes_a_heading(app, editor):
    cell = editor.add_cell(CellKind.TEXT, "Results")
    widget = editor.widget_for(cell)
    widget.kind_box.setCurrentIndex(widget.kind_box.findData("heading"))
    widget.set_editing(False)
    assert cell.kind is CellKind.HEADING
    assert "<h2" in widget.view.toHtml()


def test_add_move_delete_keep_widgets_in_document_order(app, editor):
    first = editor.document[0]
    second = editor.add_cell(CellKind.CODE, "b = 2")
    third = editor.add_cell(CellKind.TEXT, "note")
    assert [w.cell for w in editor.cell_widgets] == [first, second, third]
    editor.move_cell(third, -2)
    assert editor.document.cells == [third, first, second]
    assert [w.cell for w in editor.cell_widgets] == editor.document.cells
    editor.delete_cell(first)
    assert editor.document.cells == [third, second]
    assert [w.cell for w in editor.cell_widgets] == editor.document.cells
    assert editor.current_cell is second


def test_run_to_here(app, editor):
    editor.set_document(LiveDocument([Cell.code("p = 1"), Cell.code("q = p + 1"),
                                      Cell.code("r = 3")]))
    editor.select(editor.document[1])
    assert editor.run_to_here()
    names = editor.interpreter.variables()
    assert names["q"] == 2 and "r" not in names


def test_save_open_and_mlx_round_trip(app, editor, tmp_path):
    editor.set_document(LiveDocument([
        Cell.text("Saved", CellKind.TITLE), Cell.text("With $x^2$."),
        Cell.code("z = 1")]))
    path = editor.save(tmp_path / "saved.m")
    assert path.read_text(encoding="utf-8").startswith("%[text] # Saved")
    mlx = editor.export_mlx(tmp_path / "saved.mlx")
    for source in (path, mlx):
        assert editor.open(source)
        assert editor.document.same_content(load(path))


def test_export_report_without_tex_writes_html_and_says_how(
        app, editor, tmp_path, monkeypatch):
    from fakematlab.ui.console import live_editor
    monkeypatch.setattr(live_editor, "find_engine", lambda: None)
    editor.set_document(LiveDocument([Cell.text("R", CellKind.TITLE),
                                      Cell.code("a = 1")]))
    editor.run_all()
    written = editor.export_report(tmp_path / "r.tex")
    assert written == tmp_path / "r.html" and written.exists()
    assert (tmp_path / "r.tex").exists()
    title, text = editor.messages[-1]
    assert "MiKTeX" in text and "tectonic" in text


def test_export_report_builds_pdf_off_the_ui_thread(
        app, editor, tmp_path, monkeypatch):
    import threading

    from fakematlab.console.live.report import BuildResult
    from fakematlab.ui.console import live_editor

    release = threading.Event()
    threads = []

    def slow_compile(report, engine):
        threads.append(threading.current_thread())
        release.wait(5)
        return BuildResult(True, report.main.with_suffix(".pdf"), "")

    monkeypatch.setattr(live_editor, "find_engine",
                        lambda: ("tectonic", "tectonic"))
    monkeypatch.setattr(live_editor, "compile_pdf", slow_compile)
    editor.export_report(tmp_path / "p.tex")
    # export_report has returned while the build is still blocked.
    assert "building the PDF" in editor._status.text()
    release.set()
    editor._build_thread.join(5)
    _settle(app)
    assert threads and threads[0] is not threading.main_thread()
    assert "PDF written" in editor._status.text()


def test_highlighter_hook_reaches_every_code_cell(app, editor):
    seen = []
    set_code_highlighter(lambda document: seen.append(document) or object())
    try:
        editor.add_cell(CellKind.CODE, "x = 1")
        documents = [w.editor.document() for w in editor.cell_widgets
                     if isinstance(w, CodeCellWidget)]
        assert all(d in seen for d in documents)
    finally:
        set_code_highlighter(None)


def test_console_panel_has_a_live_tab_on_the_shared_workspace(app):
    from fakematlab.ui.console import ConsolePanel, FigureArea

    previous = figure_sink()
    try:
        panel = ConsolePanel(FigureArea())
        labels = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        assert labels == ["Console", "Script", "Live"]
        assert panel.live.interpreter is panel.interpreter
        panel.live.set_document(LiveDocument([Cell.code("shared = 42;")]))
        panel.live.run_all()
        assert panel.interpreter.namespace["shared"] == 42
        panel.live.figure_requested.emit(
            __import__("fakematlab.console.figures", fromlist=["FigureSpec"])
            .FigureSpec("xy", title="popped").add([0, 1], [0, 1]))
        assert panel.figures.figure_count == 1
    finally:
        set_figure_sink(previous)


def test_live_tab_hides_the_figure_area_and_pops_figures_out(app):
    from fakematlab.console.figures import FigureSpec
    from fakematlab.ui.console import ConsolePanel, FigureArea

    previous = figure_sink()
    try:
        panel = ConsolePanel(FigureArea())
        wanted = []
        panel.figure_area_wanted.connect(wanted.append)
        panel._tabs.setCurrentWidget(panel.live)
        assert panel.live_active and wanted[-1] is False
        # From the Live tab a figure opens in its own window, not in the
        # area that is hidden underneath.
        panel.live.figure_requested.emit(
            FigureSpec("xy", title="popped").add([0, 1], [0, 1]))
        view = panel.figures.figures[0]
        assert panel.figures.window_for(view) is not None
        panel._tabs.setCurrentIndex(0)
        assert wanted[-1] is True
        panel.figures.close_all()
    finally:
        set_figure_sink(previous)
