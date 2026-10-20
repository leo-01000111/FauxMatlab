"""
The command window.
===================
A transcript above, one input line below. History on ↑/↓, Shift+Return for
a continuation line. Completions pop up as a name is typed (Up/Down pick,
Tab or Return accept, Escape closes — ↑/↓ are the popup's while it shows);
Tab completes on demand, Ctrl+Space lists everything that fits.

The input is a single line by default rather than a free-form editor, because
a REPL's value is that Return means "run this now". Multi-line blocks are
still possible — Shift+Return extends the buffer, and a line ending in ``:``
does so automatically — but the common case stays one keystroke.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...console.interpreter import Interpreter, Result
from .. import theme
from ..code.completion import code_request, completion_candidates
from ..code.popup import CompletionController

PROMPT = ">> "
CONTINUATION = ".. "
#: The prompt while the debugger is paused, as MATLAB writes it.
DEBUG_PROMPT = "K>> "


class _InputLine(QLineEdit):
    """One line of input, with history and completion."""

    submitted = Signal(str)
    continued = Signal(str)
    history_move = Signal(int)
    complete = Signal()
    #: Ctrl+C with nothing selected.
    interrupt = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # While the completion popup shows, its controller (an event filter)
        # takes the keys it needs before they get here.
        key = event.key()
        if event.matches(QKeySequence.Copy) and not self.hasSelectedText():
            self.interrupt.emit()
            return
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

    def event(self, event) -> bool:
        # Tab would otherwise move the focus before keyPressEvent sees it.
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Tab:
            self.keyPressEvent(event)
            return True
        return super().event(event)


class _CopyOrInterrupt(QObject):
    """Ctrl+C in the transcript: copy a selection, else interrupt."""

    def __init__(self, transcript: QPlainTextEdit, interrupt) -> None:
        super().__init__(transcript)
        self._transcript = transcript
        self._interrupt = interrupt

    def eventFilter(self, obj, event) -> bool:        # noqa: N802 (Qt API)
        if event.type() == QEvent.KeyPress and event.matches(
                QKeySequence.Copy) \
                and not self._transcript.textCursor().hasSelection():
            self._interrupt()
            return True
        return False


class ConsoleWidget(QWidget):
    """Transcript plus prompt."""

    #: Something ran; the workspace browser listens for this.
    executed = Signal(object)              # Result
    #: User code started (True) or finished (False) running.
    running_changed = Signal(bool)
    #: Stop, or Ctrl+C while something runs.
    stop_requested = Signal()

    def __init__(self, interpreter: Interpreter | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.interpreter = interpreter or Interpreter()
        self._history_index = 0
        self._pending: list[str] = []
        #: Where ``.m`` files are completed from; the script's folder.
        self.folder: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._transcript = QPlainTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setFont(theme.data_font(10))
        self._transcript.setMaximumBlockCount(5000)
        self._transcript.installEventFilter(
            _CopyOrInterrupt(self._transcript, self._interrupt))
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
        self._input.interrupt.connect(self._interrupt)
        self._completer = CompletionController(self._input, self.request)
        row.addWidget(self._input, stretch=1)
        # Sized by its label, like the workspace's "Clear all": a pixel cap
        # does not know the button font is the wide uppercase sign face.
        stop = QPushButton("Stop")
        stop.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        stop.setToolTip("Interrupt what is running (Ctrl+C here with "
                        "nothing selected, or Shift+F5)")
        stop.setEnabled(False)
        stop.clicked.connect(self.stop_requested)
        row.addWidget(stop)
        self._stop_button = stop
        clear = QPushButton("Clear")
        clear.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        clear.clicked.connect(self.clear_transcript)
        row.addWidget(clear)
        self._clear_button = clear
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

    @property
    def busy(self) -> bool:
        """User code is running and not paused: the prompt must wait."""
        tracer = self.interpreter.tracer
        return tracer.running and tracer.paused is None

    @contextmanager
    def running(self):
        """Mark a run, for the Stop button and anyone listening."""
        outermost = not self.interpreter.tracer.running
        if outermost:
            self._stop_button.setEnabled(True)
            self.running_changed.emit(True)
        try:
            yield
        finally:
            if outermost:
                self._stop_button.setEnabled(False)
                self.running_changed.emit(False)

    def _interrupt(self) -> None:
        if self.interpreter.tracer.running:
            self.stop_requested.emit()

    def set_debugging(self, paused: bool) -> None:
        """The ``K>>`` prompt while the debugger holds a paused frame."""
        if not self._pending:
            self._prompt.setText(DEBUG_PROMPT if paused else PROMPT)
        self._stop_button.setEnabled(self.interpreter.tracer.running)

    def _busy_note(self) -> None:
        self.note("Busy — Stop (or Ctrl+C) interrupts what is running.")

    def _submit(self, text: str) -> None:
        if self.busy:
            self._busy_note()
            return
        self._input.clear()
        if self._pending:
            self._pending.append(text)
            source = "\n".join(self._pending)
            self._pending = []
            self._prompt.setText(DEBUG_PROMPT if self.interpreter.tracer.paused
                                 else PROMPT)
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
        """
        Run a command and show what it produced.

        While a script is paused in the debugger, the command runs in the
        paused scope. While something runs (and is not paused) it is refused:
        the event loop turns during a run, so Return can arrive mid-script.
        """
        if self.busy:
            self._busy_note()
            return Result(source, error="Busy: something is already running.")
        paused = self.interpreter.tracer.paused is not None
        if not self._pending:
            self._echo((DEBUG_PROMPT if paused else PROMPT) + source,
                       "prompt")
        with self.running():
            result = self.interpreter.run(source)
        shown = result.display()
        if shown:
            self._echo(shown, "error" if result.error else "output")
        self._history_index = len(self.interpreter.history)
        self.executed.emit(result)
        return result

    def run_script(self, source: str, language: str = "auto", *,
                   debuggable: bool = False) -> list[Result]:
        """
        Run a whole script, echoing each statement as it finishes — not at
        the end, so a long run shows its progress (and what Stop cut short).
        """
        if self.busy:
            self._busy_note()
            return []

        def show(result: Result) -> None:
            self._echo(PROMPT + result.source.strip("\n").splitlines()[0]
                       + (" …" if "\n" in result.source.strip("\n") else ""),
                       "prompt")
            shown = result.display()
            if shown:
                self._echo(shown, "error" if result.error else "output")

        with self.running():
            results = self.interpreter.run_script(
                source, language, on_result=show, debuggable=debuggable)
        self.executed.emit(results[-1] if results else None)
        return results

    def show_output(self, text: str) -> None:
        """Printed output from code that has not finished (a paused run)."""
        if text.strip():
            self._echo(text.rstrip("\n"), "output")

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

    def note(self, text: str) -> None:
        """A muted line from the app itself, not from anything that ran."""
        self._echo(text, "note")

    def _banner(self) -> None:
        self._echo(
            "Evans console — Python with MATLAB's vocabulary.\n"
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

    def candidates(self, prefix: str) -> list[str]:
        """What Tab offers for ``prefix`` at this prompt."""
        return completion_candidates(prefix, self.interpreter,
                                     folder=self.folder, language="console")

    def request(self, before: str):
        """What the popup offers after ``before``: Python, MATLAB's names."""
        return code_request(before, "console", self.interpreter, self.folder)

    @property
    def completer(self) -> CompletionController:
        return self._completer

    def _complete(self) -> None:
        """
        One match is filled in; several open a popup to choose from. With
        no word before the cursor, Tab indents (a block's body, say).
        """
        if not self._completer.complete():
            self._input.insert("    ")

    def focus_input(self) -> None:
        self._input.setFocus()

    def set_input(self, text: str) -> None:
        """Put ``text`` at the prompt, cursor at its end, without running it."""
        self._input.setText(text)
        self._input.setCursorPosition(len(text))
        self._history_index = len(self.interpreter.history)

    def input_text(self) -> str:
        return self._input.text()


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
