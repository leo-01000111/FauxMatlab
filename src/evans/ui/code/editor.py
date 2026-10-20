"""
A code editor: line numbers, breakpoints, sections, highlights, completion.

A ``QPlainTextEdit`` with a gutter on its left. Clicking the gutter toggles
a breakpoint on that line; the gutter also marks the line a debugger is
paused on. The line a run failed on is tinted until the text is edited.
``%%`` lines get a rule above them, so the cells read as cells.

Keys: a completion popup opens as a name is typed (Ctrl+Space opens it at
once; Up/Down pick, Tab or Return accept, Escape closes). With it closed,
Tab completes the word before the cursor, or indents when there is none or
lines are selected. Ctrl+Enter asks for the current section to run, Ctrl+Shift+Enter
to run it and move to the next.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from .. import theme
from .completer import Completer
from .completion import Request
from .highlighter import MatlabHighlighter, is_section_header
from .popup import CompletionController
from .sections import Section, section_at, split_sections

INDENT = "    "


class _Gutter(QWidget):
    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to set or clear a breakpoint")

    def sizeHint(self) -> QSize:                      # noqa: N802 (Qt API)
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:              # noqa: N802 (Qt API)
        self._editor.paint_gutter(event)

    def mousePressEvent(self, event) -> None:         # noqa: N802 (Qt API)
        line = self._editor.line_at(event.position().y())
        if line is not None:
            self._editor.toggle_breakpoint(line)


class CodeEditor(QPlainTextEdit):
    """The script editor's text area, reusable for any MATLAB or Python."""

    #: The set of breakpoint lines changed.
    breakpoints_changed = Signal(object)          # set[int]
    #: Ctrl+Enter (False) or Ctrl+Shift+Enter (True: then move on).
    run_section_requested = Signal(bool)

    def __init__(self, parent=None, language: str = "matlab") -> None:
        super().__init__(parent)
        self.setFont(theme.data_font(10))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.highlighter = MatlabHighlighter(self.document(), language)
        self.completer: CompletionController | None = None
        self._breakpoints: set[int] = set()
        self._error_line: int | None = None
        self._current_line: int | None = None
        self._blocks = self.blockCount()

        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(self._on_block_count)
        self.document().contentsChange.connect(self._on_contents_change)
        self.updateRequest.connect(self._on_update_request)
        self.textChanged.connect(self._on_text_changed)
        self._update_margins()
        self._restyle()
        theme.notifier().changed.connect(self._restyle)

    # ── setup ───────────────────────────────────────────────────

    def set_completion_source(self,
                              source: Callable[[str], list[str]]) -> None:
        """Turn on Tab completion, offering the names ``source(prefix)``."""
        self._set_completer(Completer(self, source))

    def set_completion(self,
                       request: Callable[[str], Request | None]) -> None:
        """
        Turn on the completion popup: ``request(text before the cursor)``
        says what to offer (see :func:`.completion.code_request`).
        """
        self._set_completer(CompletionController(self, request))

    def _set_completer(self, completer: CompletionController) -> None:
        if self.completer is not None:
            self.completer.close()
            self.removeEventFilter(self.completer)
            self.viewport().removeEventFilter(self.completer)
        self.completer = completer

    def set_language(self, language: str) -> None:
        self.highlighter.set_language(language)

    def _restyle(self, *_args) -> None:
        t = theme.tokens()
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.surface}; color: {t.ink};"
            f" border: 2px solid {t.ink_muted}; }}")
        self._refresh_selections()
        self._gutter.update()
        self.viewport().update()

    # ── gutter ──────────────────────────────────────────────────

    def gutter_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 22 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(),
                                rect.height())

    def resizeEvent(self, event) -> None:              # noqa: N802 (Qt API)
        super().resizeEvent(event)
        r = self.contentsRect()
        self._gutter.setGeometry(QRect(r.left(), r.top(),
                                       self.gutter_width(), r.height()))

    def line_at(self, y: float) -> int | None:
        """The (1-based) line drawn at height ``y`` in the gutter."""
        block = self.firstVisibleBlock()
        offset = self.contentOffset()
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(offset)
            if geo.top() <= y < geo.bottom():
                return block.blockNumber() + 1
            if geo.top() > y:
                break
            block = block.next()
        return None

    def paint_gutter(self, event) -> None:
        t = theme.tokens()
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(t.ground))
        painter.setFont(self.font())
        width = self._gutter.width()
        height = self.fontMetrics().height()
        block = self.firstVisibleBlock()
        offset = self.contentOffset()
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(offset)
            if geo.top() > event.rect().bottom():
                break
            if block.isVisible() and geo.bottom() >= event.rect().top():
                line = block.blockNumber() + 1
                top = int(geo.top())
                if line in self._breakpoints:
                    d = min(height - 4, 11)
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(t.hold))
                    painter.drawEllipse(4, top + (height - d) // 2, d, d)
                if line == self._current_line:
                    painter.setPen(QPen(QColor(_amber(t)), 2))
                    mid = top + height // 2
                    painter.drawLine(3, mid, 15, mid)
                    painter.drawLine(11, mid - 4, 15, mid)
                    painter.drawLine(11, mid + 4, 15, mid)
                painter.setPen(QColor(t.ink if line == self._current_line
                                      else t.ink_muted))
                painter.drawText(0, top, width - 6, height,
                                 Qt.AlignRight | Qt.AlignVCenter, str(line))
            block = block.next()
        painter.end()

    # ── breakpoints ─────────────────────────────────────────────

    @property
    def breakpoints(self) -> set[int]:
        return set(self._breakpoints)

    def set_breakpoints(self, lines) -> None:
        self._breakpoints = {n for n in lines if 0 < n <= self.blockCount()}
        self._gutter.update()
        self.breakpoints_changed.emit(self.breakpoints)

    def toggle_breakpoint(self, line: int) -> None:
        self.set_breakpoints(self._breakpoints ^ {line})

    def _on_block_count(self, _count: int) -> None:
        self._update_margins()

    def _on_contents_change(self, position: int, _removed: int,
                            _added: int) -> None:
        """Keep breakpoints on their lines as lines are added or removed."""
        count = self.blockCount()
        delta, self._blocks = count - self._blocks, count
        if not delta or not self._breakpoints:
            return
        block = self.document().findBlock(position)
        line = block.blockNumber() + 1
        # An edit starting at a line's very beginning moves that line too.
        first = line if position == block.position() else line + 1
        moved = set()
        for bp in self._breakpoints:
            if bp < first:
                moved.add(bp)
            elif delta > 0:
                moved.add(bp + delta)
            elif bp >= first - delta:         # below the deleted lines
                moved.add(bp + delta)
        self.set_breakpoints(moved)

    # ── highlights ──────────────────────────────────────────────

    def set_error_line(self, line: int | None) -> None:
        """Tint the line a run failed on (until the text changes)."""
        self._error_line = line
        self._refresh_selections()
        if line:
            self.reveal_line(line)

    @property
    def error_line(self) -> int | None:
        return self._error_line

    def set_current_line(self, line: int | None) -> None:
        """Mark the line the debugger is paused on (None: not paused)."""
        self._current_line = line
        self._refresh_selections()
        self._gutter.update()
        if line:
            self.reveal_line(line)

    @property
    def current_line(self) -> int | None:
        return self._current_line

    def reveal_line(self, line: int) -> None:
        block = self.document().findBlockByNumber(line - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

    def _refresh_selections(self) -> None:
        t = theme.tokens()
        selections = []
        for line, colour, alpha in ((self._error_line, t.hold, 60),
                                    (self._current_line, _amber(t), 90)):
            block = self.document().findBlockByNumber((line or 0) - 1)
            if not line or not block.isValid():
                continue
            sel = QTextEdit.ExtraSelection()
            tint = QColor(colour)
            tint.setAlpha(alpha)
            sel.format.setBackground(tint)
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = QTextCursor(block)
            selections.append(sel)
        self.setExtraSelections(selections)

    def _on_text_changed(self) -> None:
        if self._error_line is not None:
            self._error_line = None
            self._refresh_selections()

    # ── sections ────────────────────────────────────────────────

    def sections(self) -> list[Section]:
        return split_sections(self.toPlainText())

    def current_section(self) -> Section:
        return section_at(self.sections(),
                          self.textCursor().blockNumber() + 1)

    def goto_line(self, line: int) -> None:
        block = self.document().findBlockByNumber(
            min(line, self.blockCount()) - 1)
        self.setTextCursor(QTextCursor(block))
        self.ensureCursorVisible()

    def paintEvent(self, event) -> None:               # noqa: N802 (Qt API)
        super().paintEvent(event)
        t = theme.tokens()
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor(_amber(t)), 1))
        block = self.firstVisibleBlock()
        offset = self.contentOffset()
        width = self.viewport().width()
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(offset)
            if geo.top() > event.rect().bottom():
                break
            if block.blockNumber() > 0 and is_section_header(block.text()):
                y = int(geo.top())
                painter.drawLine(0, y, width, y)
            block = block.next()
        painter.end()

    # ── keys ────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:            # noqa: N802 (Qt API)
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter) and mods & Qt.ControlModifier:
            self.run_section_requested.emit(bool(mods & Qt.ShiftModifier))
            return
        if key == Qt.Key_Tab and not mods & Qt.ControlModifier:
            cursor = self.textCursor()
            if cursor.hasSelection() or self.completer is None \
                    or not self.completer.complete():
                self.indent()
            return
        super().keyPressEvent(event)

    def indent(self) -> None:
        """Indent the selected lines, or insert an indent at the cursor."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.insertText(INDENT)
            return
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        cursor.beginEditBlock()
        for n in range(first, last + 1):
            line = QTextCursor(doc.findBlockByNumber(n))
            line.insertText(INDENT)
        cursor.endEditBlock()


def _amber(t: theme.Tokens) -> str:
    """The signal yellow, darkened on Day where #f5c518 is ~1.3:1."""
    return "#f5c518" if t.is_night else "#b8900a"
