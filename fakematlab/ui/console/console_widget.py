"""
The command window.
===================
A transcript above, one input line below. History on ↑/↓, completion on Tab,
Shift+Return for a continuation line.

The input is a single line by default rather than a free-form editor, because
a REPL's value is that Return means "run this now". Multi-line blocks are
still possible — Shift+Return extends the buffer, and a line ending in ``:``
does so automatically — but the common case stays one keystroke.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...console.interpreter import Interpreter, Result
from .. import theme

PROMPT = ">> "
CONTINUATION = ".. "


class _InputLine(QLineEdit):
    """One line of input, with history and completion."""

    submitted = Signal(str)
    continued = Signal(str)
    history_move = Signal(int)
    complete = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            text = self.text()
            if event.modifiers() & Qt.ShiftModifier:
                self.continued.emit(text)
            else:
                self.submitted.emit(text)
            return
        if key == Qt.Key_Up:
            self.history_move.emit(-1)
            return
        if key == Qt.Key_Down:
            self.history_move.emit(+1)
            return
        if key == Qt.Key_Tab:
            self.complete.emit()
            return
        super().keyPressEvent(event)


class ConsoleWidget(QWidget):
    """Transcript plus prompt."""

    #: Something ran; the workspace browser listens for this.
    executed = Signal(object)              # Result

    def __init__(self, interpreter: Interpreter | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.interpreter = interpreter or Interpreter()
        self._history_index = 0
        self._pending: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._transcript = QPlainTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setFont(theme.data_font(10))
        self._transcript.setMaximumBlockCount(5000)
        layout.addWidget(self._transcript, stretch=1)

        row = QHBoxLayout()
        self._prompt = QLabel(PROMPT)
        self._prompt.setFont(theme.data_font(10))
        row.addWidget(self._prompt)
        self._input = _InputLine()
        self._input.setFont(theme.data_font(10))
        self._input.setPlaceholderText(
            "G = tf([1], [1, 2, 1])       — help_fm() lists the commands")
        self._input.submitted.connect(self._submit)
        self._input.continued.connect(self._extend)
        self._input.history_move.connect(self._recall)
        self._input.complete.connect(self._complete)
        row.addWidget(self._input, stretch=1)
        clear = QPushButton("Clear")
        clear.setMaximumWidth(64)
        clear.clicked.connect(self.clear_transcript)
        row.addWidget(clear)
        layout.addLayout(row)

        self._log: list[tuple[str, str]] = []
        self._restyle()
        theme.notifier().changed.connect(self._restyle)
        self._banner()

    def _restyle(self, *_args) -> None:
        """
        Surface background, and the transcript's colours re-read per theme.

        Echoed text carries its colour as inline HTML, so a theme switch has
        to replay the log to recolour what is already on screen.
        """
        t = theme.tokens()
        self._transcript.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.surface}; color: {t.ink};"
            f" border: 2px solid {t.ink_muted}; }}")
        self._prompt.setStyleSheet(f"color: {self._prompt_colour()};")
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {t.surface}; color: {t.ink};"
            f" border: 2px solid {t.ink_muted}; padding: 3px 6px; }}"
            f"QLineEdit:focus {{ border-color: {t.edge}; }}")
        if self._log:
            self._transcript.clear()
            for text, kind in self._log:
                self._paint(text, kind)

    @staticmethod
    def _prompt_colour() -> str:
        t = theme.tokens()
        return t.signal if t.is_night else t.ink

    # ── running ─────────────────────────────────────────────────

    def _submit(self, text: str) -> None:
        self._input.clear()
        if self._pending:
            self._pending.append(text)
            source = "\n".join(self._pending)
            self._pending = []
            self._prompt.setText(PROMPT)
        else:
            source = text
            # A block opener would fail on its own, so keep collecting.
            if text.rstrip().endswith(":"):
                self._extend(text)
                return
        self.execute(source)

    def _extend(self, text: str) -> None:
        self._pending.append(text)
        self._input.clear()
        self._prompt.setText(CONTINUATION)
        self._echo("\n".join(
            (PROMPT if i == 0 else CONTINUATION) + line
            for i, line in enumerate(self._pending)), "prompt")

    def execute(self, source: str) -> Result:
        """Run a command and show what it produced."""
        if not self._pending:
            self._echo(PROMPT + source, "prompt")
        result = self.interpreter.run(source)
        shown = result.display()
        if shown:
            self._echo(shown, "error" if result.error else "output")
        self._history_index = len(self.interpreter.history)
        self.executed.emit(result)
        return result

    def run_script(self, source: str) -> list[Result]:
        """Run a whole script, echoing each statement as it goes."""
        results = []
        for result in self.interpreter.run_script(source):
            self._echo(PROMPT + result.source.splitlines()[0]
                       + (" …" if "\n" in result.source else ""), "prompt")
            shown = result.display()
            if shown:
                self._echo(shown, "error" if result.error else "output")
            results.append(result)
        self.executed.emit(results[-1] if results else None)
        return results

    # ── transcript ──────────────────────────────────────────────

    @staticmethod
    def _colour(kind: str) -> str:
        """Prompt marker: signal on Night, ink on Day. Errors in hold_ink."""
        t = theme.tokens()
        return {"prompt": ConsoleWidget._prompt_colour(), "output": t.ink,
                "error": t.hold_ink, "note": t.ink_muted}[kind]

    def _echo(self, text: str, kind: str = "output") -> None:
        self._log.append((text, kind))
        del self._log[:-5000]
        self._paint(text, kind)

    def _paint(self, text: str, kind: str) -> None:
        cursor = self._transcript.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(
            f'<pre style="color:{self._colour(kind)};margin:0;'
            f'font-family:{theme.MONO}">{_escape(text)}</pre>')
        cursor.insertBlock()
        self._transcript.setTextCursor(cursor)
        self._transcript.ensureCursorVisible()

    def clear_transcript(self) -> None:
        self._transcript.clear()
        self._log.clear()
        self._banner()

    def _banner(self) -> None:
        self._echo(
            "FakeMatlab console — Python with MATLAB's vocabulary.\n"
            "help_fm() lists the commands.  's' is the Laplace variable.\n",
            "note")

    # ── history and completion ──────────────────────────────────

    def _recall(self, direction: int) -> None:
        history = self.interpreter.history
        if not history:
            return
        self._history_index = max(0, min(len(history),
                                         self._history_index + direction))
        self._input.setText(history[self._history_index]
                            if self._history_index < len(history) else "")
        self._input.setCursorPosition(len(self._input.text()))

    def _complete(self) -> None:
        text = self._input.text()
        cursor = self._input.cursorPosition()
        head = text[:cursor]
        prefix = _word_at_end(head)
        if not prefix:
            return

        matches = self.interpreter.completions(prefix)
        if not matches:
            return
        if len(matches) == 1:
            completed = matches[0]
        else:
            completed = _common_prefix(matches)
            if completed == prefix:
                # Nothing more to fill in, so show the options instead of
                # silently doing nothing — a Tab that appears broken is worse
                # than one that prints.
                self._echo("  " + "  ".join(matches[:40]), "note")
                return
        self._input.setText(head[:cursor - len(prefix)] + completed
                            + text[cursor:])
        self._input.setCursorPosition(cursor - len(prefix) + len(completed))

    def focus_input(self) -> None:
        self._input.setFocus()


def _word_at_end(text: str) -> str:
    out = []
    for char in reversed(text):
        if char.isalnum() or char in "_.":
            out.append(char)
        else:
            break
    return "".join(reversed(out))


def _common_prefix(items: list[str]) -> str:
    first = items[0]
    for i, char in enumerate(first):
        if any(len(other) <= i or other[i] != char for other in items[1:]):
            return first[:i]
    return first


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
