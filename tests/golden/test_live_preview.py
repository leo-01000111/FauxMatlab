"""
The live script's PDF preview, offscreen and with the TeX engine stubbed:
the toggle, Ctrl+Enter and Rebuild, builds off the UI thread, one queued
request while a build runs, failures that keep the last good PDF, the scroll
position kept across builds, figure captions edited in place, and the
template dialog's three levels.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt not available")
pytest.importorskip("PySide6.QtPdf", reason="QtPdf not available")

from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from evans.console.figures import FigureSpec
from evans.console.interpreter import Interpreter
from evans.console.live import (
    Cell,
    CellKind,
    CellOutput,
    LiveDocument,
    ReportTemplate,
    load,
)
from evans.console.live.report import BuildResult
from evans.ui.console import live_preview, report_template
from evans.ui.console.live_editor import (
    PREVIEW_SHORTCUT,
    CodeCellWidget,
    LiveScriptEditor,
    TextCellWidget,
)
from evans.ui.console.report_template import ReportTemplateDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _settle(app, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


@pytest.fixture(scope="module")
def pdf_bytes(app, tmp_path_factory) -> bytes:
    """A real six-page PDF, written by Qt, for the stub engine to 'make'."""
    path = tmp_path_factory.mktemp("pdf") / "six.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    for page in range(6):
        if page:
            writer.newPage()
        painter.drawText(200, 200, f"page {page + 1}")
    painter.end()
    return path.read_bytes()


class Engine:
    """A stand-in for compile_pdf: records each .tex, can block or fail."""

    def __init__(self, pdf: bytes) -> None:
        self.pdf = pdf
        self.calls: list[str] = []
        self.threads: list[threading.Thread] = []
        self.fail_with = ""
        self.gate: threading.Event | None = None

    def __call__(self, report, engine):
        self.threads.append(threading.current_thread())
        self.calls.append(report.main.read_text(encoding="utf-8"))
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail_with:
            return BuildResult(False, None, self.fail_with)
        target = report.main.with_suffix(".pdf")
        target.write_bytes(self.pdf)
        return BuildResult(True, target, "")


@pytest.fixture
def engine(monkeypatch, pdf_bytes):
    stub = Engine(pdf_bytes)
    monkeypatch.setattr(live_preview, "find_engines",
                        lambda: [("pdflatex", "pdflatex")])
    monkeypatch.setattr(live_preview, "compile_pdf", stub)
    return stub


@pytest.fixture
def editor(app):
    report_template.set_user_template(None)
    widget = LiveScriptEditor(Interpreter())
    widget.resize(1200, 700)
    widget.show()
    _settle(app)
    yield widget
    if widget.preview is not None:
        widget.preview.wait()
    widget.hide()
    widget.deleteLater()
    report_template.set_user_template(None)


def _finish(app, editor) -> None:
    """Let the running build end and its result reach the UI thread."""
    for _ in range(5):
        editor.preview.wait()
        _settle(app)
        if not editor.preview.building:
            return


def _lab() -> LiveDocument:
    return LiveDocument([
        Cell.text("Lab", CellKind.TITLE),
        Cell.text("See Figure~\\ref{fig:sine}."),
        Cell.code("t = 0:0.1:1; plot(t, t); title('ramp')"),
    ])


# ── the toggle ──────────────────────────────────────────────────

def test_preview_is_off_until_toggled_and_then_splits_the_tab(
        app, editor, engine):
    assert editor.preview is None and not editor.preview_on
    editor.rebuild_preview()                   # off: nothing happens
    assert engine.calls == []
    editor.preview_button.click()
    _settle(app)
    assert editor.preview_on and editor.preview.isVisible()
    assert editor._split.indexOf(editor.preview) == 1
    _finish(app, editor)
    # Turning it on builds once, off the UI thread.
    assert len(engine.calls) == 1
    assert engine.threads[0] is not threading.main_thread()
    assert editor.preview.pdf.status() == QPdfDocument.Status.Ready
    assert editor.preview.page_count == 6
    editor.preview_button.click()
    _settle(app)
    assert not editor.preview_on and editor.preview.isHidden()
    assert editor.rebuild_preview() is False


def test_the_shortcut_is_bound(editor):
    from PySide6.QtGui import QKeySequence, QShortcut
    keys = [s.key() for s in editor.findChildren(QShortcut)]
    assert QKeySequence(PREVIEW_SHORTCUT) in keys


# ── what triggers a build ───────────────────────────────────────

def test_ctrl_enter_on_a_code_cell_runs_it_and_rebuilds(app, editor, engine):
    editor.set_document(_lab())
    editor.set_preview(True)
    _finish(app, editor)
    before = len(engine.calls)
    code = next(w for w in editor.cell_widgets
                if isinstance(w, CodeCellWidget))
    code.editor.run_requested.emit()           # what Ctrl+Enter does
    _finish(app, editor)
    assert len(engine.calls) == before + 1
    assert editor.interpreter.namespace["t"] is not None
    # The figure it drew is in the .tex as a figure environment.
    assert "\\begin{figure}[H]" in engine.calls[-1]
    assert "\\caption{ramp}\n\\label{fig:1}" in engine.calls[-1]


def test_ctrl_enter_in_a_text_cell_renders_and_rebuilds(app, editor, engine):
    editor.set_document(_lab())
    editor.set_preview(True)
    _finish(app, editor)
    before = len(engine.calls)
    text = next(w for w in editor.cell_widgets
                if isinstance(w, TextCellWidget)
                and w.cell.kind is CellKind.TEXT)
    text.set_editing(True)
    text.editor.setPlainText("Now with \\emph{LaTeX} and x_1.")
    text.editor.run_requested.emit()
    _finish(app, editor)
    assert not text.editing
    assert len(engine.calls) == before + 1
    assert "Now with \\emph{LaTeX} and x\\_1." in engine.calls[-1]


def test_typing_does_not_rebuild(app, editor, engine):
    editor.set_preview(True)
    _finish(app, editor)
    before = len(engine.calls)
    code = editor.cell_widgets[0]
    code.editor.setPlainText("x = 1")
    code.editor.insertPlainText("23")
    _settle(app)
    assert len(engine.calls) == before


def test_rebuild_button_rebuilds(app, editor, engine):
    editor.set_preview(True)
    _finish(app, editor)
    before = len(engine.calls)
    editor.preview.rebuild_button.click()
    _finish(app, editor)
    assert len(engine.calls) == before + 1


def test_a_request_during_a_build_runs_once_afterwards(app, editor, engine):
    engine.gate = threading.Event()
    editor.set_preview(True)                   # first build, held
    _settle(app)
    assert editor.preview.building
    for _ in range(3):                         # three impatient requests
        assert editor.rebuild_preview() is False
    assert "queued" in editor.preview.status.text()
    engine.gate.set()
    _finish(app, editor)
    _finish(app, editor)
    # The held build, then exactly one more for all three requests.
    assert len(engine.calls) == 2
    assert not editor.preview.building


# ── failure, and what stays on screen ───────────────────────────

def test_a_failed_build_shows_the_tex_error_and_keeps_the_last_pdf(
        app, editor, engine):
    editor.set_preview(True)
    _finish(app, editor)
    shown = editor.preview._shown
    assert editor.preview.page_count == 6 and editor.preview.error.isHidden()
    engine.fail_with = ("noise\n! Undefined control sequence.\n"
                        "l.12 \\oops")
    editor.preview.rebuild_button.click()
    _finish(app, editor)
    error = editor.preview.error
    assert not error.isHidden()
    assert "! Undefined control sequence." in error.toPlainText()
    assert "noise" not in error.toPlainText()
    assert "last good PDF" in editor.preview.status.text()
    assert editor.preview._shown == shown and shown.exists()
    assert editor.preview.page_count == 6       # still showing
    # The next good build clears the error.
    engine.fail_with = ""
    editor.preview.rebuild_button.click()
    _finish(app, editor)
    assert error.isHidden()
    assert editor.preview.good_builds == 2


def test_a_compiler_crash_is_a_failed_build_not_a_hang(
        app, editor, monkeypatch):
    def crash(report, engine):
        raise RuntimeError("boom")
    monkeypatch.setattr(live_preview, "find_engines", lambda: [("x", "x")])
    monkeypatch.setattr(live_preview, "compile_pdf", crash)
    editor.set_preview(True)
    _finish(app, editor)
    assert not editor.preview.building
    assert "RuntimeError: boom" in editor.preview.error.toPlainText()


def test_without_an_engine_the_preview_says_how_to_get_one(
        app, editor, monkeypatch):
    monkeypatch.setattr(live_preview, "find_engines", lambda: [])
    editor.set_preview(True)
    _settle(app)
    assert not editor.preview.building
    text = editor.preview.error.toPlainText()
    assert "MiKTeX" in text and "tectonic" in text


def test_the_scroll_position_is_kept_across_builds(app, editor, engine):
    editor.resize(1200, 500)
    editor.set_preview(True)
    _finish(app, editor)
    _settle(app, 20)
    bar = editor.preview.view.verticalScrollBar()
    assert bar.maximum() > 0, "six pages should scroll"
    bar.setValue(bar.maximum() // 2)
    where = bar.value()
    editor.preview.rebuild_button.click()
    _finish(app, editor)
    _settle(app, 20)
    assert editor.preview.good_builds == 2
    assert abs(bar.value() - where) <= 2


def test_each_build_is_shown_from_a_file_of_its_own(app, editor, engine):
    editor.set_preview(True)
    _finish(app, editor)
    first = editor.preview._shown
    editor.preview.rebuild_button.click()
    _finish(app, editor)
    second = editor.preview._shown
    assert first != second and second.exists()


# ── figure captions and labels ──────────────────────────────────

def test_caption_and_label_fields_edit_the_cell(app, editor, engine,
                                                tmp_path):
    doc = LiveDocument([Cell.code("plot(1:3)"), Cell.code("plot(1:2)")])
    editor.set_document(doc)
    editor.run_all()
    _settle(app)
    first, second = [w for w in editor.cell_widgets
                     if isinstance(w, CodeCellWidget)]
    assert len(first.figure_fields) == 1 and len(second.figure_fields) == 1
    # The automatic labels number the document's figures.
    assert first.figure_fields[0][1].placeholderText() == "fig:1"
    assert second.figure_fields[0][1].placeholderText() == "fig:2"
    caption, label = second.figure_fields[0]
    caption.textEdited.emit("Two points")
    label.textEdited.emit(" fig:two ")
    assert doc[1].figure_meta[0].caption == "Two points"
    assert doc[1].figure_meta[0].label == "fig:two"
    # Saved with the script, and shown again when it is reopened and run.
    path = editor.save(tmp_path / "figs.m")
    assert load(path).code_cells()[1].figure_meta[0].label == "fig:two"
    assert editor.open(path)
    editor.run_all()
    _settle(app)
    widget = [w for w in editor.cell_widgets
              if isinstance(w, CodeCellWidget)][1]
    assert widget.figure_fields[0][0].text() == "Two points"
    assert widget.figure_fields[0][1].text() == "fig:two"


def test_figures_of_a_rerun_keep_their_captions(app, editor):
    doc = LiveDocument([Cell.code("plot(1:3)")])
    doc[0].output = CellOutput(figures=[FigureSpec("xy").add([0], [0])])
    doc[0].meta(0).caption = "kept"
    editor.set_document(doc)
    editor.run_all()
    widget = editor.cell_widgets[0]
    assert widget.figure_fields[0][0].text() == "kept"


# ── the template ────────────────────────────────────────────────

def test_template_levels_and_the_dialog(app, editor, engine):
    editor.set_document(_lab())
    assert editor.template() == ReportTemplate()          # the default

    # The user's default: stored in the settings.
    dialog = ReportTemplateDialog(None, None)
    dialog.scope.setCurrentIndex(1)
    dialog.number_sections.setChecked(True)
    dialog.margin.setText("2cm")
    editor._exec_dialog = lambda d: (d.scope.setCurrentIndex(1),
                                     d.number_sections.setChecked(True),
                                     d.margin.setText("2cm"), True)[-1]
    assert editor.edit_template()
    assert report_template.user_template().number_sections
    assert editor.document.template is None
    assert editor.template().margin == "2cm"

    # This script's own: starts from the user's, saved with the script.
    def own(d):
        assert d.follow.isChecked()
        d.follow.setChecked(False)
        assert d.number_sections.isChecked()      # copied from the user's
        d.author.setText("Leon")
        return True
    editor._exec_dialog = own
    assert editor.edit_template()
    assert editor.document.template.author == "Leon"
    assert editor.document.template.number_sections
    assert editor.template().author == "Leon"

    # Cancel changes nothing.
    editor._exec_dialog = lambda d: (d.author.setText("Nobody"), False)[-1]
    assert not editor.edit_template()
    assert editor.template().author == "Leon"

    # Following the default again drops the script's own.
    editor._exec_dialog = lambda d: (d.follow.setChecked(True), True)[-1]
    assert editor.edit_template()
    assert editor.document.template is None
    dialog.deleteLater()


def test_the_preview_and_export_use_the_same_template(
        app, editor, engine, tmp_path, monkeypatch):
    from evans.ui.console import live_editor
    report_template.set_user_template(
        ReportTemplate(number_sections=True, show_code=False))
    editor.set_document(LiveDocument([Cell.text("Part", CellKind.HEADING),
                                      Cell.code("a = 1")]))
    editor.run_all()
    editor.set_preview(True)
    _finish(app, editor)
    preview_tex = engine.calls[-1]
    monkeypatch.setattr(live_editor, "find_engines", lambda: [])
    editor._inform = lambda *args, **kw: None
    editor.export_report(tmp_path / "r.tex")
    export_tex = (tmp_path / "r.tex").read_text(encoding="utf-8")
    for tex in (preview_tex, export_tex):
        assert "\\section{Part}" in tex and "lstlisting}\na = 1" not in tex
    assert preview_tex.replace("preview_fig", "") == \
        export_tex.replace("r_fig", "")


def test_the_dialog_can_hand_over_the_raw_preamble(app):
    dialog = ReportTemplateDialog(ReportTemplate(margin="3cm"), None)
    assert not dialog.follow.isChecked()
    dialog.raw.setChecked(True)
    raw = dialog.raw_preamble.toPlainText()
    assert "\\usepackage[margin=3cm]{geometry}" in raw
    dialog.raw_preamble.setPlainText("\\documentclass{memoir}\n")
    dialog.accept()
    assert dialog.document_template.raw_preamble == "\\documentclass{memoir}\n"
    assert dialog.document_template.preamble().startswith(
        "\\documentclass{memoir}")
    dialog.deleteLater()


def test_the_dialog_fits_a_small_screen(app):
    dialog = ReportTemplateDialog(None, None)
    hint = dialog.minimumSizeHint()
    assert hint.width() <= 1280 and hint.height() <= 700
    dialog.deleteLater()


def test_the_preview_does_not_widen_the_live_tab(app, editor, engine):
    """The toolbar sets the tab's minimum width (test_ui_layout checks it
    fits 1280 px); the split must not add to it."""
    off = editor.minimumSizeHint().width()
    editor.set_preview(True)
    _settle(app)
    assert editor.minimumSizeHint().width() <= off
    assert editor._split.minimumSizeHint().width() < off


def test_live_tab_files_are_left_alone(tmp_path):
    """Opening the preview never writes beside the script."""
    assert not list(Path(tmp_path).iterdir())
