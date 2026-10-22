"""
*Ask Cedric* beside an error: a button at the right end of the line it
names, which asks him at once to fix it.

:class:`ErrorMarks` keeps such buttons on one text widget — the console's
transcript (one per failed command) or a script tab (the line a run failed
on). Each is anchored to a ``QTextCursor``, which Qt moves with the text, and
follows scrolling and resizing; it hides while its line is out of view and
goes away when its line does.

:func:`ask_button` is the look shared with the floating button: a location
plate (the primary buttons' black and yellow) with Cedric on it, so it reads
as a button even floating over code.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QToolButton, QWidget

from .. import theme
from ..cedric import cedric_icon

#: Buttons kept per widget; older errors lose theirs first.
MAX_MARKS = 12


def spaced(font: QFont) -> QFont:
    """
    The sign font with room between words: its kerning closes the space in
    some pairs ("ASK CEDRIC" set as "ASKCEDRIC").
    """
    font.setWordSpacing(font.pointSizeF() * 0.6)
    return font


def ask_button(parent: QWidget, text: str = "Ask Cedric") -> QToolButton:
    """The Ask Cedric plate: his drawing and a sign-font label, no focus."""
    button = QToolButton(parent)
    button.setText(text)
    button.setFocusPolicy(Qt.NoFocus)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    button.setIconSize(QSize(20, 14))
    button.setFont(spaced(theme.sign_font(8)))
    button.setProperty("_hp_font", True)       # keep it past the theme's hook

    def restyle(*_ignored) -> None:
        t = theme.tokens()
        button.setIcon(cedric_icon(20, 14))
        button.setStyleSheet(
            f"QToolButton {{ background: {t.plate}; color: {t.on_plate};"
            f" border: 1px solid {t.on_plate}; padding: 1px 6px;"
            f" border-radius: {theme.RADIUS_PLATE}px; }}"
            f"QToolButton::menu-indicator {{ image: none; width: 0; }}")

    restyle()
    theme.notifier().changed.connect(restyle)
    return button


class _Mark:
    def __init__(self, cursor: QTextCursor, line_text: str,
                 button: QToolButton) -> None:
        self.cursor = cursor
        self.line_text = line_text
        self.button = button


class ErrorMarks(QObject):
    """The Ask Cedric buttons beside errors in one text widget."""

    def __init__(self, widget: QPlainTextEdit | QTextEdit) -> None:
        super().__init__(widget)
        self.widget = widget
        self._marks: list[_Mark] = []
        # Placing asks the layout for cursor rectangles, which must not
        # happen while the document is mid-change (a cleared transcript
        # crashed Qt that way): every trigger waits for the next turn of
        # the event loop, and a burst of them places once.
        self._later = QTimer(self)
        self._later.setSingleShot(True)
        self._later.setInterval(0)
        self._later.timeout.connect(self.place)
        widget.viewport().installEventFilter(self)
        widget.verticalScrollBar().valueChanged.connect(self._later.start)
        widget.horizontalScrollBar().valueChanged.connect(self._later.start)
        widget.document().contentsChanged.connect(self._later.start)

    @property
    def count(self) -> int:
        return len(self._marks)

    def buttons(self) -> list[QToolButton]:
        return [m.button for m in self._marks]

    def add(self, position: int, on_click: Callable[[], None],
            tooltip: str = "Ask Cedric to fix this") -> QToolButton:
        """A button at the end of the line holding ``position``."""
        cursor = QTextCursor(self.widget.document())
        cursor.setPosition(max(0, min(position,
                                      self.widget.document().characterCount() - 1)))
        cursor.movePosition(QTextCursor.EndOfBlock)
        button = ask_button(self.widget.viewport())
        button.setToolTip(tooltip)
        button.clicked.connect(on_click)
        self._marks.append(_Mark(cursor, cursor.block().text(), button))
        while len(self._marks) > MAX_MARKS:
            self._drop(self._marks[0])
        self.place()
        return button

    def add_line(self, line: int, on_click: Callable[[], None],
                 tooltip: str = "Ask Cedric to fix this") -> QToolButton | None:
        """A button at the end of ``line`` (1-based)."""
        block = self.widget.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return None
        return self.add(block.position(), on_click, tooltip)

    def clear(self) -> None:
        for mark in list(self._marks):
            self._drop(mark)

    def _drop(self, mark: _Mark) -> None:
        self._marks.remove(mark)
        mark.button.hide()
        mark.button.deleteLater()

    def eventFilter(self, obj, event) -> bool:   # noqa: N802 (Qt API)
        if event.type() in (QEvent.Resize, QEvent.Show):
            self._later.start()
        return False

    def place(self, *_ignored) -> None:
        """Put each button at the end of its line, or hide it."""
        viewport = self.widget.viewport()
        for mark in list(self._marks):
            # A cleared transcript or a rewritten line takes its button away.
            if mark.cursor.block().text() != mark.line_text:
                self._drop(mark)
                continue
            cursor = QTextCursor(mark.cursor)
            cursor.movePosition(QTextCursor.EndOfBlock)
            rect = self.widget.cursorRect(cursor)
            size = mark.button.sizeHint()
            x = min(rect.right() + 12, viewport.width() - size.width() - 2)
            y = rect.center().y() - size.height() // 2
            visible = 0 <= rect.center().y() <= viewport.height()
            mark.button.move(QPoint(max(0, x), y))
            mark.button.setVisible(visible)
            if visible:
                mark.button.raise_()
