"""
The live-script editor: cells of MATLAB and formatted text, stacked.

A code cell shows what it printed and the figures it drew right beneath it.
A text cell is either being edited (its markup) or rendered (Markdown with
math drawn by matplotlib's mathtext, and ``{{expr}}`` placeholders filled from
the shared workspace). Double-click a rendered cell to edit it; *Done* or
Ctrl+Enter renders it again.

*Preview* splits the tab: the script on the left, its PDF on the right
(:mod:`.live_preview`), rebuilt on Ctrl+Enter, on *Rebuild* and after a run —
never on a keystroke. Each inline figure has a caption and a label for the
report under it, saved with the script.

The document model, the file formats, the runner and the report writers are
all in :mod:`evans.console.live`; this module is only the widgets.

Highlighting hook
-----------------
Code cells are plain ``QPlainTextEdit``\\ s. The script editor's syntax
highlighter can be attached to every one of them — present and future — with
:func:`set_code_highlighter`, which takes a factory called with each cell's
``QTextDocument``.
"""

from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
    QKeySequence,
    QShortcut,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...console.figures import FigureSpec
from ...console.live import (
    TEXT_KINDS,
    Cell,
    CellKind,
    LiveDocument,
    LiveRunner,
    load,
    save,
    workspace_evaluator,
)
from ...console.live.markup import inline_html, to_html
from ...console.live.render import MathError, math_png, png_size
from ...console.live.report import (
    INSTALL_HINT,
    build_with,
    compile_pdf,
    find_engines,
    write_html,
    write_tex,
)
from ...console.live.template import ReportTemplate, resolve_template
from .. import iconset, keys, theme
from ..code.completion import code_request
from ..code.latex import labels_in, latex_request
from ..code.popup import CompletionController
from ..design import NORMAL, TIGHT
from . import report_template
from .figure_view import FigureView

#: Shows and hides the PDF preview. (Ctrl+Shift+P exports a figure.)
PREVIEW_SHORTCUT = "Ctrl+Alt+P"

#: Height of a figure drawn inline under its cell.
FIGURE_HEIGHT = 260
#: Tallest an output pane grows before it scrolls.
OUTPUT_MAX_HEIGHT = 320

_KIND_LABELS = {CellKind.TEXT: "Text", CellKind.TITLE: "Title",
                CellKind.HEADING: "Heading 1", CellKind.HEADING2: "Heading 2",
                CellKind.HEADING3: "Heading 3"}

# ── the highlighter hook ─────────────────────────────────────────

_highlighter_factory: Callable[[QTextDocument], object] | None = None
_code_editors: weakref.WeakSet = weakref.WeakSet()


def set_code_highlighter(factory: Callable[[QTextDocument], object] | None) -> None:
    """
    Highlight every code cell with ``factory(document)`` — typically a
    ``QSyntaxHighlighter`` subclass. Applies to existing cells too.
    """
    global _highlighter_factory
    _highlighter_factory = factory
    for editor in list(_code_editors):
        try:
            editor.attach_highlighter()
        except RuntimeError:                  # the C++ side is gone
            _code_editors.discard(editor)


class _GrowingEditor(QPlainTextEdit):
    """A plain-text editor as tall as its contents: cells never scroll."""

    run_requested = Signal()
    focused = Signal()

    def __init__(self, code: bool, parent=None) -> None:
        super().__init__(parent)
        self._code = code
        self._highlighter = None
        self.setFont(theme.data_font(10) if code else theme.ui_font(10))
        self.setLineWrapMode(QPlainTextEdit.NoWrap if code
                             else QPlainTextEdit.WidgetWidth)
        self.setTabChangesFocus(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.textChanged.connect(self._fit)
        if code:
            _code_editors.add(self)
            self.attach_highlighter()
        self._fit()

    def attach_highlighter(self) -> None:
        if _highlighter_factory is not None and self._code:
            self._highlighter = _highlighter_factory(self.document())

    def _fit(self) -> None:
        lines = max(self.document().blockCount(), 1)
        if not self._code:
            # Wrapped prose: count the laid-out lines, not the paragraphs.
            layout_lines = 0
            block = self.document().begin()
            while block.isValid():
                layout = block.layout()
                layout_lines += max(layout.lineCount() if layout else 1, 1)
                block = block.next()
            lines = max(lines, layout_lines)
        spacing = self.fontMetrics().lineSpacing()
        extra = 2 * self.frameWidth() + 12
        if self._code and self.horizontalScrollBar().maximum() > 0:
            extra += self.horizontalScrollBar().sizeHint().height()
        self.setFixedHeight(lines * spacing + extra)

    def resizeEvent(self, event) -> None:              # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._fit()

    def keyPressEvent(self, event) -> None:            # noqa: N802 (Qt API)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and \
                event.modifiers() & Qt.ControlModifier:
            self.run_requested.emit()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:             # noqa: N802 (Qt API)
        super().focusInEvent(event)
        self.focused.emit()


class MathTextView(QTextBrowser):
    """
    Rendered prose: HTML with each equation an image resource drawn by
    mathtext, sized to its contents. Double-click asks to edit.
    """

    edit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().setDefaultFont(theme.ui_font(10.5))
        self._images = 0
        #: Equations mathtext could not draw, shown as source — for tests
        #: and for the tooltip.
        self.failed: list[str] = []

    def math_image(self, latex: str, display: bool) -> str | None:
        """Register an equation's image; returns its <img> tag."""
        ratio = 2.0
        try:
            png = math_png(latex, display=display, color=theme.tokens().ink,
                           fontsize=11.0, dpi=round(96 * ratio))
        except MathError:
            self.failed.append(latex)
            return None
        image = QImage.fromData(png, "PNG")
        self._images += 1
        name = f"mathimg://{self._images}"
        self.document().addResource(QTextDocument.ImageResource, QUrl(name),
                                    image)
        width, height = png_size(png)
        return (f'<img src="{name}" width="{round(width / ratio)}" '
                f'height="{round(height / ratio)}" '
                f'style="vertical-align: middle">')

    def set_markup_html(self, html: str) -> None:
        self.setHtml(html)
        self._fit()

    def _fit(self) -> None:
        self.document().setTextWidth(max(self.viewport().width(), 50))
        height = int(self.document().size().height()) + 4
        self.setFixedHeight(max(height, self.fontMetrics().lineSpacing() + 6))

    def resizeEvent(self, event) -> None:              # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._fit()

    def mouseDoubleClickEvent(self, event) -> None:    # noqa: N802 (Qt API)
        self.edit_requested.emit()


class _WheelToScroll(QObject):
    """Wheel over an inline figure scrolls the page instead of zooming."""

    def __init__(self, target: QWidget) -> None:
        super().__init__(target)
        self._target = target

    def eventFilter(self, obj, event) -> bool:         # noqa: N802 (Qt API)
        if event.type() == QEvent.Wheel:
            area = self._target
            while area is not None and not isinstance(area, QScrollArea):
                area = area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(), event)
            return True
        return False


# ──────────────────────────────────────────────────────────────
#  Cells
# ──────────────────────────────────────────────────────────────

class CellWidget(QFrame):
    """The frame every cell shares: a header of controls, then a body."""

    #: (cell widget, action) — action: run, up, down, delete, focus.
    action = Signal(object, str)

    def __init__(self, cell: Cell, parent=None) -> None:
        super().__init__(parent)
        self.cell = cell
        self._current = False
        self.setObjectName("liveCell")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(NORMAL, TIGHT, NORMAL, NORMAL)
        outer.setSpacing(TIGHT)

        self._header = QHBoxLayout()
        self._header.setSpacing(TIGHT)
        outer.addLayout(self._header)
        self._build_header_start()
        self._header.addStretch()
        for text, key, tip in (("↑", "up", "Move this cell up"),
                               ("↓", "down", "Move this cell down"),
                               ("✕", "delete", "Delete this cell")):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.clicked.connect(lambda _=False, k=key: self.action.emit(self, k))
            self._header.addWidget(button)

        self.body = QVBoxLayout()
        self.body.setSpacing(TIGHT)
        outer.addLayout(self.body)
        self._restyle()
        theme.notifier().changed.connect(self._restyle)

    def _build_header_start(self) -> None:
        pass

    def set_current(self, current: bool) -> None:
        self._current = current
        self._restyle()

    def _restyle(self, *_args) -> None:
        t = theme.tokens()
        edge = t.edge if self._current else t.rule
        self.setStyleSheet(
            f"QFrame#liveCell {{ background: {t.surface};"
            f" border: 2px solid {edge}; border-radius: {theme.RADIUS_PLATE}px; }}")

    def mousePressEvent(self, event) -> None:          # noqa: N802 (Qt API)
        self.action.emit(self, "focus")
        super().mousePressEvent(event)

    def refresh(self, evaluate=None) -> None:
        """Bring the widget up to date with its cell (outputs, rendering)."""

    def sync_to_cell(self) -> None:
        """Copy what was typed into the cell model."""


class CodeCellWidget(CellWidget):
    """MATLAB, with its printed output and figures underneath."""

    #: A figure drawn inline should open in the figure area.
    figure_requested = Signal(object)

    def _build_header_start(self) -> None:
        tag = QLabel("CODE")
        tag.setFont(theme.label_font())
        self._header.addWidget(tag)
        run = QToolButton()
        run.setText("Run")
        iconset.bind(run, "run")
        run.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        run.setToolTip(keys.label("Run this cell (Ctrl+Enter)"))
        run.clicked.connect(lambda: self.action.emit(self, "run"))
        self._header.addWidget(run)
        self.run_button = run

    def __init__(self, cell: Cell, parent=None) -> None:
        super().__init__(cell, parent)
        self.editor = _GrowingEditor(code=True)
        self.editor.setPlainText(cell.source)
        self.editor.setPlaceholderText(
            keys.label("% MATLAB — Ctrl+Enter runs this cell"))
        self.editor.run_requested.connect(lambda: self.action.emit(self, "run"))
        self.editor.focused.connect(lambda: self.action.emit(self, "focus"))
        self.editor.textChanged.connect(self.sync_to_cell)
        self.body.addWidget(self.editor)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(theme.data_font(9.5))
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body.addWidget(self.output)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setFont(theme.data_font(9.5))
        self.error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.addWidget(self.error)
        self.figures_box = QVBoxLayout()
        self.figures_box.setSpacing(TIGHT)
        self.body.addLayout(self.figures_box)
        self.figure_views: list[FigureView] = []
        #: (caption, label) editors, one pair per figure shown.
        self.figure_fields: list[tuple[QLineEdit, QLineEdit]] = []
        self.refresh()

    def _restyle(self, *_args) -> None:
        super()._restyle()
        if not hasattr(self, "editor"):
            return
        t = theme.tokens()
        self.editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.ground}; color: {t.ink};"
            f" border: 1px solid {t.rule}; }}")
        self.output.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.surface}; color: {t.ink};"
            f" border: none; border-left: 3px solid {t.signal}; }}")
        self.error.setStyleSheet(f"color: {t.hold_ink};")

    def sync_to_cell(self) -> None:
        self.cell.source = self.editor.toPlainText()

    def set_completion(self, request) -> None:
        """MATLAB completion in the cell: ``request(text before cursor)``."""
        self.completer = CompletionController(self.editor, request,
                                              tab_completes=True)

    def refresh(self, evaluate=None) -> None:
        output = self.cell.output
        text = output.text if output else ""
        self.output.setPlainText(text)
        self.output.setVisible(bool(text.strip()))
        if text.strip():
            lines = text.count("\n") + 1
            height = lines * self.output.fontMetrics().lineSpacing() + 16
            self.output.setFixedHeight(min(height, OUTPUT_MAX_HEIGHT))
        error = output.error if output else ""
        self.error.setText(error)
        self.error.setVisible(bool(error))
        self._show_figures(output.figures if output else [])
        self._restyle()

    def _show_figures(self, specs: list[FigureSpec]) -> None:
        for view in self.figure_views:
            view.setParent(None)
            view.deleteLater()
        self.figure_views = []
        self.figure_fields = []
        while self.figures_box.count():
            item = self.figures_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for spec in specs:
            frame = QWidget()
            column = QVBoxLayout(frame)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            row = QHBoxLayout()
            row.addStretch()
            pop = QToolButton()
            pop.setText("Open in window")
            pop.setToolTip("Open this figure larger, in a window of its own, "
                           "where it can be zoomed and saved. Its Dock button "
                           "moves it to the Console's figure area.")
            pop.setAutoRaise(True)
            pop.clicked.connect(lambda _=False, s=spec: self.figure_requested.emit(s))
            row.addWidget(pop)
            column.addLayout(row)
            view = FigureView(spec)
            view.setFixedHeight(FIGURE_HEIGHT * (2 if spec.kind == "bode" else 1))
            wheel = _WheelToScroll(view)
            for child in [view, *view.findChildren(QWidget)]:
                child.installEventFilter(wheel)
            column.addWidget(view)
            column.addLayout(self._figure_fields(len(self.figure_views)))
            self.figures_box.addWidget(frame)
            self.figure_views.append(view)

    def _figure_fields(self, index: int) -> QHBoxLayout:
        """The figure's caption and label in the report, edited in place."""
        meta = self.cell.figure_meta[index] \
            if index < len(self.cell.figure_meta) else None
        row = QHBoxLayout()
        row.setSpacing(TIGHT)
        caption = QLineEdit(meta.caption if meta else "")
        caption.setPlaceholderText("Caption in the report (LaTeX)")
        caption.setToolTip("The figure's caption in the PDF report")
        caption.textEdited.connect(
            lambda text, i=index: setattr(self.cell.meta(i), "caption", text))
        label = QLineEdit(meta.label if meta else "")
        label.setPlaceholderText(f"fig:{index + 1}")
        label.setToolTip("\\label for \\ref{…} in text cells; empty: the "
                         "automatic label shown in grey")
        label.setFixedWidth(120)
        label.textEdited.connect(
            lambda text, i=index: setattr(self.cell.meta(i), "label",
                                          text.strip()))
        row.addWidget(caption, stretch=1)
        row.addWidget(label)
        self.figure_fields.append((caption, label))
        return row

    def set_auto_labels(self, labels: list[str]) -> None:
        """Show the automatic label each figure gets when it has none."""
        for (_caption, label), auto in zip(self.figure_fields, labels):
            label.setPlaceholderText(auto)


class TextCellWidget(CellWidget):
    """Prose, a title or a heading: rendered, or its markup being edited."""

    def _build_header_start(self) -> None:
        self.kind_box = QComboBox()
        for kind in TEXT_KINDS:
            self.kind_box.addItem(_KIND_LABELS[kind], kind.value)
        self.kind_box.setToolTip("What this text cell is")
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self._header.addWidget(self.kind_box)
        self.toggle = QToolButton()
        self.toggle.setToolTip(keys.label(
            "Switch between the markup and the rendered text "
            "(Ctrl+Enter renders)"))
        self.toggle.clicked.connect(self._toggle)
        self._header.addWidget(self.toggle)

    def __init__(self, cell: Cell, parent=None, *, editing: bool = False,
                 evaluate=None) -> None:
        #: Fills {{expr}} placeholders; the editor's workspace evaluator.
        self._evaluate = evaluate
        super().__init__(cell, parent)
        index = self.kind_box.findData(cell.kind.value)
        self.kind_box.blockSignals(True)
        self.kind_box.setCurrentIndex(max(index, 0))
        self.kind_box.blockSignals(False)

        self.view = MathTextView()
        self.view.edit_requested.connect(lambda: self.set_editing(True))
        self.editor = _GrowingEditor(code=False)
        self.editor.setPlainText(cell.source)
        self.editor.setPlaceholderText(
            "**bold**, *italic*, `code`, $x^2$ inline, $$\\frac{1}{s}$$ "
            "on its own, {{G}} or {{max(y)}} for workspace values — and in "
            "the PDF, any LaTeX: \\ref{fig:1}, \\cite{…}, environments")
        self.editor.run_requested.connect(self._render_requested)
        self.editor.focused.connect(lambda: self.action.emit(self, "focus"))
        self.editor.textChanged.connect(self.sync_to_cell)
        # Both live in the body; only one is shown, and a hidden widget
        # takes no room, so the cell is always as tall as what it shows.
        self.body.addWidget(self.view)
        self.body.addWidget(self.editor)
        self.set_editing(editing or not cell.source.strip())

    @property
    def editing(self) -> bool:
        return not self.editor.isHidden()

    def set_editing(self, editing: bool) -> None:
        if not editing:
            self.sync_to_cell()
            self.refresh(self._evaluate)
        self.editor.setVisible(editing)
        self.view.setVisible(not editing)
        self.toggle.setText("Done" if editing else "Edit")
        if editing:
            self.editor.setFocus()

    def _toggle(self) -> None:
        self.set_editing(not self.editing)

    def _render_requested(self) -> None:
        """Ctrl+Enter: render, and tell the editor (it rebuilds the PDF)."""
        self.set_editing(False)
        self.action.emit(self, "render")

    def _kind_changed(self) -> None:
        self.cell.kind = CellKind(self.kind_box.currentData())
        self.refresh(self._evaluate)

    def sync_to_cell(self) -> None:
        self.cell.source = self.editor.toPlainText()

    def set_completion(self, labels) -> None:
        r"""LaTeX completion in the markup; ``labels()`` for ``\ref{``."""
        self.completer = CompletionController(
            self.editor, lambda before: latex_request(before, labels),
            tab_completes=True)

    def refresh(self, evaluate=None) -> None:
        if evaluate is not None:
            self._evaluate = evaluate
        evaluate = self._evaluate
        self.view.failed.clear()
        kind = self.cell.kind
        source = self.cell.source
        if kind.is_heading:
            tag = f"h{kind.level + 1}"
            body = inline_html(source, evaluate=evaluate,
                               math_image=self.view.math_image)
            html = f"<{tag}>{body}</{tag}>"
        else:
            html = to_html(source, evaluate=evaluate,
                           math_image=self.view.math_image)
        t = theme.tokens()
        self.view.document().setDefaultStyleSheet(
            f"a {{ color: {t.edge}; }} code {{ color: {t.ink_muted}; }}")
        self.view.setStyleSheet(
            f"QTextBrowser {{ background: transparent; color: {t.ink}; }}")
        self.view.set_markup_html(html)
        if self.view.failed:
            self.view.setToolTip("mathtext could not draw: "
                                 + "; ".join(self.view.failed))
        else:
            self.view.setToolTip("Double-click to edit")


# ──────────────────────────────────────────────────────────────
#  The editor
# ──────────────────────────────────────────────────────────────

class LiveScriptEditor(QWidget):
    """
    A live script: open (.mlx or .m), edit, run cell by cell, save, export.

    ``path`` and ``folder`` say where the script lives, the way
    ``ScriptEditor.path`` does; ``folder`` is the current folder while its
    cells run.
    """

    #: Cells ran — the workspace view should refresh.
    ran = Signal()
    #: An inline figure should open in the figure area.
    figure_requested = Signal(object)
    #: A PDF build finished: (ok, pdf path or None, log). Emitted from the
    #: build thread, delivered on the UI thread.
    pdf_finished = Signal(bool, object, str)

    def __init__(self, interpreter, parent=None) -> None:
        super().__init__(parent)
        self.interpreter = interpreter
        self.runner = LiveRunner(interpreter)
        self.document = LiveDocument([Cell.code("")])
        self._widgets: list[CellWidget] = []
        self._current: Cell | None = None
        self._build_thread: threading.Thread | None = None
        #: The PDF beside the script; made the first time it is shown.
        self.preview = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addLayout(self._build_toolbar())

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._page = QWidget()
        self._column = QVBoxLayout(self._page)
        self._column.setContentsMargins(NORMAL, NORMAL, NORMAL, NORMAL)
        self._column.setSpacing(NORMAL)
        self._column.addStretch()
        self._scroll.setWidget(self._page)
        self._split = QSplitter(Qt.Horizontal)
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(self._scroll)
        layout.addWidget(self._split, stretch=1)

        self._status = QLabel("")
        layout.addWidget(self._status)

        self.pdf_finished.connect(self._on_pdf_finished)
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self,
                  activated=self.run_all)
        save = QShortcut(QKeySequence.Save, self)
        save.setContext(Qt.WidgetWithChildrenShortcut)
        save.activated.connect(lambda: self.save())
        preview = QShortcut(QKeySequence(PREVIEW_SHORTCUT), self)
        preview.setContext(Qt.WidgetWithChildrenShortcut)
        preview.activated.connect(self.preview_button.toggle)
        self._rebuild()

    # ── toolbar ─────────────────────────────────────────────────

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()

        def button(text: str, tip: str, slot, icon: str = "") -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            if icon:
                iconset.bind(b, icon)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        button("Run all", keys.label("Run every code cell from the top "
                                     "(Ctrl+Shift+Enter)"),
               self.run_all, "run")
        button("Run to here", "Run every code cell down to the selected one",
               self.run_to_here)
        button("Run cell",
               keys.label("Run the selected code cell (Ctrl+Enter)"),
               self.run_current)
        row.addSpacing(8)   # group gaps: 8 px keeps the row in the 1280 budget
        button("+ Code", "Insert a code cell below the selected one",
               lambda: self.add_cell(CellKind.CODE))
        button("+ Text", "Insert a text cell below the selected one",
               lambda: self.add_cell(CellKind.TEXT))
        row.addSpacing(8)
        # Open and Save stay words: this row sets the Live tab's minimum
        # width, and two more icons put the window over its 1280 px budget.
        # "Open", not "Open…": the Save split button's arrow took the few
        # pixels this row had left in the 1280 px budget.
        button("Open", "Open a live script (.mlx or .m)…",
               lambda: self.open())
        # Save is a split button: the click saves to the file it came from,
        # in its own format; the arrow is Save as…, with either format.
        self.save_button = QToolButton()
        self.save_button.setText("Save")
        self.save_button.setToolTip(keys.label(
            "Save to the same file, in its format (Ctrl+S). The arrow: "
            "Save as… a MATLAB .mlx or a plain-text .m"))
        self.save_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.save_button.clicked.connect(lambda: self.save())
        save_menu = QMenu(self.save_button)
        save_menu.addAction("Save", lambda: self.save())
        save_menu.addAction("Save as…", lambda: self.save_as())
        self.save_button.setMenu(save_menu)
        row.addWidget(self.save_button)
        export = QPushButton("Export")
        iconset.bind(export, "export")
        menu = QMenu(export)
        menu.addAction("Export report (LaTeX / PDF)…", self.export_report)
        menu.addAction("Report template…", self.edit_template)
        export.setMenu(menu)
        row.addWidget(export)
        self.preview_button = QPushButton("Preview")
        self.preview_button.setCheckable(True)
        self.preview_button.setToolTip(keys.label(
            f"Show the PDF beside the script ({PREVIEW_SHORTCUT}); "
            "Ctrl+Enter rebuilds it"))
        self.preview_button.toggled.connect(self.set_preview)
        row.addWidget(self.preview_button)
        # The file name takes the room that is left and asks for none: it is
        # what gave the Preview button its place in the 1280 px budget. The
        # whole path is in its tooltip.
        self._path_label = QLabel("untitled")
        self._path_label.setStyleSheet("color: palette(mid);")
        self._path_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._path_label.setSizePolicy(QSizePolicy.Ignored,
                                       QSizePolicy.Preferred)
        row.addWidget(self._path_label, stretch=1)
        return row

    def _show_path(self, path: Path | None) -> None:
        self._path_label.setText(path.name if path else "untitled")
        self._path_label.setToolTip(str(path) if path else "")

    # ── document ↔ widgets ──────────────────────────────────────

    @property
    def path(self) -> Path | None:
        """The file the live script was opened from or saved to, if any."""
        return self.document.path

    @property
    def folder(self) -> Path | None:
        """The live script's folder — the current folder while it runs."""
        return self.document.folder

    def set_document(self, document: LiveDocument) -> None:
        self.document = document
        if not document.cells:
            document.append(Cell.code(""))
        self._current = document.cells[0]
        self._show_path(document.path)
        self._rebuild()
        self._update_auto_labels()

    def _make_widget(self, cell: Cell) -> CellWidget:
        if cell.is_code:
            widget = CodeCellWidget(cell)
            widget.figure_requested.connect(self.figure_requested)
            widget.set_completion(self._code_request)
        else:
            widget = TextCellWidget(cell, evaluate=self._evaluator())
            widget.set_completion(self.reference_labels)
        widget.action.connect(self._on_action)
        return widget

    def _rebuild(self) -> None:
        for widget in self._widgets:
            self._column.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._widgets = []
        evaluate = self._evaluator()
        for cell in self.document.cells:
            widget = self._make_widget(cell)
            self._column.insertWidget(self._column.count() - 1, widget)
            self._widgets.append(widget)
            if not cell.is_code:
                widget.refresh(evaluate)
        if self._current not in self.document.cells:
            self._current = self.document.cells[0] if self.document.cells \
                else None
        self._mark_current()

    def _code_request(self, before: str):
        return code_request(before, "matlab", self.interpreter, self.folder)

    def reference_labels(self) -> list[str]:
        r"""
        What ``\ref{`` can name: every drawn figure's label (its own or
        the automatic ``fig:<n>``), labels given to figures not drawn yet,
        and ``\label{…}`` in the text cells.
        """
        self._sync()
        labels = list(self.document.figure_labels().values())
        for cell in self.document.code_cells():
            labels += [m.label.strip() for m in cell.figure_meta
                       if m.label.strip()]
        labels += labels_in(c.source for c in self.document.cells
                            if not c.is_code)
        return list(dict.fromkeys(labels))

    def widget_for(self, cell: Cell) -> CellWidget:
        for widget in self._widgets:
            if widget.cell is cell:
                return widget
        raise KeyError("no widget for that cell")

    @property
    def cell_widgets(self) -> list[CellWidget]:
        return list(self._widgets)

    def _sync(self) -> None:
        for widget in self._widgets:
            widget.sync_to_cell()

    # ── selection ───────────────────────────────────────────────

    @property
    def current_cell(self) -> Cell | None:
        return self._current

    def select(self, cell: Cell) -> None:
        self._current = cell
        self._mark_current()

    def _mark_current(self) -> None:
        for widget in self._widgets:
            widget.set_current(widget.cell is self._current)

    def _on_action(self, widget: CellWidget, action: str) -> None:
        cell = widget.cell
        if action == "focus":
            self.select(cell)
        elif action == "run":
            self.select(cell)
            self.run_cell(cell)
            self.rebuild_preview()
        elif action == "render":
            self.select(cell)
            self.rebuild_preview()
        elif action in ("up", "down"):
            self.move_cell(cell, -1 if action == "up" else 1)
        elif action == "delete":
            self.delete_cell(cell)

    # ── editing ─────────────────────────────────────────────────

    def add_cell(self, kind: CellKind, source: str = "") -> Cell:
        """Insert a cell below the selected one (at the end if none)."""
        self._sync()
        cell = Cell(kind, source)
        index = (self.document.index(self._current) + 1
                 if self._current in self.document.cells else len(self.document))
        self.document.insert(index, cell)
        widget = self._make_widget(cell)
        self._column.insertWidget(index, widget)
        self._widgets.insert(index, widget)
        self.select(cell)
        if isinstance(widget, TextCellWidget):
            widget.set_editing(True)
        else:
            widget.editor.setFocus()
        return cell

    def delete_cell(self, cell: Cell) -> None:
        self._sync()
        index = self.document.remove(cell)
        widget = self.widget_for(cell)
        self._widgets.remove(widget)
        self._column.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()
        if not self.document.cells:
            self.document.append(Cell.code(""))
            self._rebuild()
            return
        self.select(self.document.cells[min(index, len(self.document) - 1)])

    def move_cell(self, cell: Cell, offset: int) -> None:
        self._sync()
        index = self.document.move(cell, offset)
        widget = self.widget_for(cell)
        self._widgets.remove(widget)
        self._widgets.insert(index, widget)
        self._column.removeWidget(widget)
        self._column.insertWidget(index, widget)
        self.select(cell)

    # ── running ─────────────────────────────────────────────────

    def _evaluator(self):
        return workspace_evaluator(self.interpreter)

    def _run(self, job) -> bool:
        self._sync()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        self.runner.on_cell_done = lambda cell: self.widget_for(cell).refresh()
        try:
            ok = job()
        finally:
            self.runner.on_cell_done = None
            QGuiApplication.restoreOverrideCursor()
        self._render_text()
        self._update_auto_labels()
        failed = next((c for c in self.document.code_cells()
                       if c.output is not None and not c.output.ok), None)
        self._status.setText(
            "Stopped at an error." if not ok and failed else
            f"Ran in {self.folder}" if self.folder else "")
        self.ran.emit()
        return ok

    def _render_text(self) -> None:
        """Placeholders may show new values now: render the text again."""
        evaluate = self._evaluator()
        for widget in self._widgets:
            if isinstance(widget, TextCellWidget) and not widget.editing:
                widget.refresh(evaluate)

    def run_cell(self, cell: Cell | None = None) -> bool:
        cell = cell or self._current
        if cell is None or not cell.is_code:
            return False
        return self._run(lambda: self.runner.run_cell(cell, self.folder).ok)

    def run_current(self) -> bool:
        return self.run_cell(self._current)

    def run_all(self) -> bool:
        ok = self._run(lambda: self.runner.run_all(self.document))
        self.rebuild_preview()
        return ok

    def run_to_here(self) -> bool:
        cell = self._current or (self.document.cells[-1]
                                 if self.document.cells else None)
        if cell is None:
            return False
        ok = self._run(lambda: self.runner.run_to(self.document, cell))
        self.rebuild_preview()
        return ok

    def _update_auto_labels(self) -> None:
        """Each figure's label field shows the label it gets by default."""
        n = 0
        for widget in self._widgets:
            if isinstance(widget, CodeCellWidget):
                count = len(widget.figure_fields)
                widget.set_auto_labels([f"fig:{n + k + 1}"
                                        for k in range(count)])
                n += count

    # ── the PDF preview and the template ────────────────────────

    @property
    def preview_on(self) -> bool:
        return self.preview is not None and not self.preview.isHidden()

    def set_preview(self, on: bool) -> None:
        """Split the tab: the script, and its PDF beside it — or not."""
        if self.preview_button.isChecked() != on:
            self.preview_button.setChecked(on)     # comes back here
            return
        if on and self.preview is None:
            from .live_preview import LivePreview
            self.preview = LivePreview()
            self.preview.rebuild_requested.connect(self.rebuild_preview)
            self.preview.template_requested.connect(self.edit_template)
            self._split.addWidget(self.preview)
            self._split.setStretchFactor(0, 1)
            self._split.setStretchFactor(1, 1)
        if self.preview is None:
            return
        self.preview.setVisible(on)
        if on:
            width = max(self._split.width(), 2)
            self._split.setSizes([width // 2, width - width // 2])
            if self.preview.good_builds == 0 and not self.preview.building:
                self.rebuild_preview()

    def template(self) -> ReportTemplate:
        """The template in force: this script's, the user's, or the default."""
        return resolve_template(self.document.template,
                                report_template.user_template())

    def rebuild_preview(self) -> bool:
        """Build the PDF preview, if it is showing. Returns whether it began."""
        if not self.preview_on:
            return False
        self._sync()
        return self.preview.build(self.document, self._evaluator(),
                                  self.template())

    def _exec_dialog(self, dialog) -> bool:
        """Run a modal dialog. A method so tests can answer it."""
        return bool(dialog.exec())

    def edit_template(self) -> bool:
        """Edit this script's report template or the user's default."""
        dialog = report_template.ReportTemplateDialog(
            self.document.template, report_template.user_template(), self)
        if not self._exec_dialog(dialog):
            return False
        dialog.commit()
        self.document.template = dialog.document_template
        report_template.set_user_template(dialog.user_template)
        self.rebuild_preview()
        return True

    # ── files ───────────────────────────────────────────────────

    def _ask_open_path(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open live script", str(self.folder or ""),
            "Live scripts (*.mlx *.m);;MATLAB live scripts (*.mlx);;"
            "Plain-text live scripts (*.m);;All files (*)")
        return path

    def _ask_save_path(self, title: str, default: str, filters: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, default, filters)
        return path

    def _inform(self, title: str, text: str, warning: bool = False) -> None:
        """A message for the user. A method so tests can answer it."""
        (QMessageBox.warning if warning else QMessageBox.information)(
            self, title, text)

    def _default_path(self, suffix: str) -> str:
        base = self.path or Path.cwd() / "live_script.m"
        return str(base.with_suffix(suffix))

    def open(self, path: str | Path | None = None) -> bool:
        path = path or self._ask_open_path()
        if not path:
            return False
        try:
            document = load(path)
        except (OSError, ValueError) as exc:
            self._inform("Could not open", str(exc), warning=True)
            return False
        self.set_document(document)
        return True

    #: Save as… filters, by format. The current file's format comes first.
    SAVE_FILTERS = {".mlx": "MATLAB live scripts (*.mlx)",
                    ".m": "Plain-text live scripts (*.m)"}

    def save(self, path: str | Path | None = None) -> Path | None:
        """
        Save: to ``path`` if given, else to the file this script came from,
        in that file's own format (.mlx stays .mlx). A script never saved
        goes to Save as…. Returns the file written, or None.

        The toolbar button used to be connected straight to this method, so
        Qt's ``clicked(False)`` arrived as the path, looked empty, and the
        click returned without saving anything.
        """
        if isinstance(path, bool):          # a signal's argument, not a path
            path = None
        self._sync()
        if path is None:
            if self.path is None:
                return self.save_as()
            path = self.path
        return self._write(Path(path))

    def save_as(self, fmt: str | None = None) -> Path | None:
        """Ask where, offering both formats, starting from the current one."""
        self._sync()
        fmt = fmt or (self.path.suffix.lower() if self.path
                      and self.path.suffix.lower() in self.SAVE_FILTERS
                      else ".mlx")
        order = [fmt] + [f for f in self.SAVE_FILTERS if f != fmt]
        filters = ";;".join(self.SAVE_FILTERS[f] for f in order)
        path = self._ask_save_path("Save live script as",
                                   self._default_path(fmt), filters)
        if not path:
            return None
        path = Path(path)
        if path.suffix.lower() not in self.SAVE_FILTERS:
            path = path.with_suffix(fmt)
        return self._write(path)

    def export_mlx(self, path: str | Path | None = None) -> Path | None:
        """Save as a MATLAB .mlx (kept for scripts and tests that call it)."""
        if isinstance(path, bool):
            path = None
        return self._write(Path(path)) if path else self.save_as(".mlx")

    def _write(self, path: Path) -> Path | None:
        """Write the file, after warning when .mlx would drop Evans's extras."""
        if path.suffix.lower() == ".mlx" and self._mlx_would_lose():
            choice = self._ask_mlx_loss(path)
            if choice == "cancel":
                return None
            if choice == "m":
                path = path.with_suffix(".m")
        try:
            written = save(self.document, path)
        except OSError as exc:
            self._inform("Could not save", str(exc), warning=True)
            return None
        self._show_path(written)
        self._status.setText(f"Saved {written.name}")
        return written

    def _mlx_would_lose(self) -> bool:
        """Captions, labels or a report template: things .mlx cannot hold."""
        if self.document.template is not None:
            return True
        return any(not meta.empty for cell in self.document.code_cells()
                   for meta in getattr(cell, "figure_meta", []))

    def _ask_mlx_loss(self, path: Path) -> str:
        """'mlx', 'm' or 'cancel'. A method so tests can answer it."""
        box = QMessageBox(self)
        box.setWindowTitle("Save as .mlx")
        box.setText(f"{path.name} is a MATLAB live script, which has no place "
                    f"for figure captions, figure labels or this script's "
                    f"report template. Saving it as .mlx drops them.")
        box.setInformativeText("A plain-text .m live script keeps everything "
                               "and opens in Evans the same way.")
        as_mlx = box.addButton("Save as .mlx anyway", QMessageBox.AcceptRole)
        as_m = box.addButton("Save as .m instead", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(as_m)
        box.exec()
        clicked = box.clickedButton()
        return "mlx" if clicked is as_mlx else "m" if clicked is as_m \
            else "cancel"

    def export_report(self, path: str | Path | None = None) -> Path | None:
        """
        Write the .tex (and figure PNGs); build the PDF off the UI thread if
        a TeX engine is installed, otherwise write HTML too and say how to
        get an engine. If every engine fails the HTML is written as well, so
        an export always ends with something readable.
        """
        self._sync()
        path = path or self._ask_save_path(
            "Export report", self._default_path(".tex"),
            "LaTeX documents (*.tex)")
        if not path:
            return None
        evaluate = self._evaluator()
        template = self.template()
        report = write_tex(self.document, Path(path), evaluate=evaluate,
                           template=template)
        engines = find_engines()
        if not engines:
            html = write_html(self.document, report.main.with_suffix(".html"),
                              evaluate=evaluate, template=template)
            self._status.setText(f"Wrote {report.main.name} and "
                                 f"{html.main.name}.")
            self._inform("Report exported as HTML",
                         f"Wrote {report.main}\nand {html.main}.\n\n"
                         + INSTALL_HINT)
            return html.main
        self._status.setText(f"Wrote {report.main.name}; building the PDF "
                             f"with {engines[0][0]}…")
        self._report = report
        self._build_thread = threading.Thread(
            target=lambda: self.pdf_finished.emit(
                *_build(report, engines)), daemon=True)
        self._build_thread.start()
        return report.main

    def _on_pdf_finished(self, ok: bool, pdf, log: str) -> None:
        if ok:
            self._status.setText(f"PDF written: {pdf}")
            return
        main = self._report.main
        try:
            html = write_html(self.document, main.with_suffix(".html"),
                              evaluate=self._evaluator(),
                              template=self.template()).main
        except (OSError, ValueError):
            html = None
        also = f" and {html.name}" if html else ""
        self._status.setText(f"The PDF build failed; wrote {main.name}{also}.")
        self._inform("PDF build failed",
                     f"No PDF was made. {main.name} was written and can be "
                     f"fixed by hand"
                     + (f"; the report is also in {html}" if html else "")
                     + f".\n\n{log}", warning=True)


def _build(report, engines) -> tuple[bool, object, str]:
    """Every engine in turn, with this module's ``compile_pdf`` (tests stub
    it); see :func:`~evans.console.live.report.build_with`."""
    return build_with(report, engines, compile=compile_pdf)
