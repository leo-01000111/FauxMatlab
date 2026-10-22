"""
The floating *Ask Cedric* button: select text, and it appears beside it.

Attached to a text widget — the console's transcript and prompt, a script
tab, a live cell — it watches the selection. When the mouse or keyboard
finishes a selection it floats up just below its end; clicking it opens a
small menu:

* **Explain** — asks at once what the selection does or says;
* **Fix this error** — asks at once what is wrong and how to fix it;
* **Ask…** — attaches the selection to the panel and lets the user type.

Explain and Fix each spend one of the day's free requests, so neither fires
on the selection alone; the button only offers. It takes no focus, so the
selection it is about stays selected while the menu is open.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTextEdit,
    QToolButton,
    QWidget,
)

from .error_ask import ask_button

EXPLAIN = "explain"
FIX = "fix"
ASK = "ask"

#: What Explain and Fix this error send as the question.
QUESTIONS = {
    EXPLAIN: "Explain this.",
    FIX: "What is wrong here, and how do I fix it?",
}

#: Selections shorter than this are taken for a stray click-and-drag.
MIN_CHARS = 2


class AskCedricFloat(QObject):
    """The button for one text widget; ``on_action(action)`` when chosen."""

    def __init__(self, widget: QPlainTextEdit | QTextEdit | QLineEdit,
                 on_action: Callable[[str], None]) -> None:
        super().__init__(widget)
        self.widget = widget
        self._on_action = on_action
        self._line = isinstance(widget, QLineEdit)
        host: QWidget = widget if self._line else widget.viewport()

        self.button = ask_button(host)
        self.button.setObjectName("askCedric")
        self.button.setToolTip("Ask Cedric about the selection")
        self.button.setPopupMode(QToolButton.InstantPopup)
        self.button.hide()

        menu = QMenu(self.button)
        for action, label in ((EXPLAIN, "Explain"), (FIX, "Fix this error"),
                              (ASK, "Ask…")):
            menu.addAction(label, lambda a=action: self._choose(a))
        self.button.setMenu(menu)
        self.menu = menu

        widget.installEventFilter(self)
        if not self._line:
            widget.viewport().installEventFilter(self)
            widget.verticalScrollBar().valueChanged.connect(self._place)
            widget.horizontalScrollBar().valueChanged.connect(self._place)
        widget.selectionChanged.connect(self._selection_changed)

    # ── the selection ─────────────────────────────────────────

    def selected_text(self) -> str:
        if self._line:
            return self.widget.selectedText()
        return self.widget.textCursor().selectedText()

    def _selection_changed(self) -> None:
        if len(self.selected_text().strip()) < MIN_CHARS:
            self.button.hide()

    def eventFilter(self, obj, event) -> bool:   # noqa: N802 (Qt API)
        kind = event.type()
        if kind in (QEvent.MouseButtonRelease, QEvent.KeyRelease):
            # After Qt has finished updating the selection for this event.
            QTimer.singleShot(0, self.offer)
        elif kind == QEvent.FocusOut and obj is self.widget:
            if event.reason() != Qt.PopupFocusReason:
                self.button.hide()
        elif kind == QEvent.Resize:
            self._place()
        return False

    def offer(self) -> bool:
        """Show the button if there is a real selection; say whether it shows."""
        if len(self.selected_text().strip()) < MIN_CHARS:
            self.button.hide()
            return False
        self.button.adjustSize()
        self._place()
        self.button.show()
        self.button.raise_()
        return True

    def _place(self, *_ignored) -> None:
        if not self.button.isVisible() and not self.selected_text():
            return
        host = self.button.parentWidget()
        size = self.button.sizeHint()
        if self._line:
            # A one-line prompt: sit at its right end, over the margin.
            spot = QPoint(host.width() - size.width() - 2,
                          (host.height() - size.height()) // 2)
        else:
            cursor = self.widget.textCursor()
            rect = self.widget.cursorRect(cursor)
            spot = QPoint(rect.right() + 4, rect.bottom() + 2)
            if spot.y() + size.height() > host.height():
                spot.setY(rect.top() - size.height() - 2)
        spot.setX(max(0, min(spot.x(), host.width() - size.width())))
        spot.setY(max(0, min(spot.y(), host.height() - size.height())))
        self.button.move(spot)

    def _choose(self, action: str) -> None:
        self.button.hide()
        self._on_action(action)
