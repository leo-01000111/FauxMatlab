"""
Sources: what Cedric is asked about, and where his edits go.

A source builds the narrow :class:`~evans.assistant.context.Context` for one
question from the widget it wraps, and applies an edit back to that widget.
The panel never reads an editor itself, so a new kind of editor is a new
source rather than a change to the panel.

* :class:`EditorSource` — a script tab or a live-script cell (any
  ``QPlainTextEdit``/``QTextEdit``, or a callable that returns the one
  showing now).
* :class:`ConsoleSource` — the console: the prompt line (typed, not run) is
  the code, and a selection in the transcript goes along as output.
* :class:`SwitchSource` — whichever of several sources is showing.

Qt counts positions in UTF-16 units and Python in characters; they differ
past the first 65 536 code points (an emoji in a comment), so every position
crossing the boundary goes through :func:`to_qt` / :func:`from_qt`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit

from ...assistant import context as ctx
from ...assistant import protocol
from ...assistant.context import Context
from ...assistant.protocol import Edit, StaleEdit

Variables = Callable[[], Mapping[str, Any]]


class Source:
    """
    Whatever a question is about. Subclasses fill in the two methods.

    ``context()`` is called once per question, on the GUI thread.
    ``apply(context, edit)`` replaces the code that ``context`` was built
    from, or raises :class:`StaleEdit`.
    """

    def resolve(self) -> Source:
        """
        This source pinned to what it reads *now*: the tab showing, the
        cell current. A question keeps the resolved source, so an edit lands
        where its code came from even after the user switches tabs.
        """
        return self

    def context(self) -> Context:
        raise NotImplementedError

    def apply(self, context: Context, edit: Edit) -> None:
        raise StaleEdit("This place cannot be edited.")


class EditorSource(Source):
    """
    A script tab or a live-script cell.

    ``editor`` is the text widget, or a callable returning the one in use
    now (the showing script tab, the current live cell), or ``None``.
    ``whole`` sends the editor's whole text when nothing is selected — a
    live cell is one unit, as a ``%%`` section is in a script. ``variables``
    and ``last_error`` are read at question time, never held.
    """

    def __init__(self, editor: QPlainTextEdit | QTextEdit
                 | Callable[[], QPlainTextEdit | QTextEdit | None], *,
                 where: str, language: str | Callable[[], str] = "python",
                 variables: Variables = dict,
                 last_error: Callable[[], str] = str,
                 whole: str | None = None) -> None:
        self._editor = editor
        self.where = where
        self._language = language
        self._variables = variables
        self._last_error = last_error
        self._whole = whole

    @property
    def editor(self) -> QPlainTextEdit | QTextEdit | None:
        if isinstance(self._editor, QPlainTextEdit | QTextEdit):
            return self._editor
        return self._editor() if callable(self._editor) else None

    def resolve(self) -> EditorSource:
        if isinstance(self._editor, QPlainTextEdit | QTextEdit):
            return self
        editor = self.editor
        return EditorSource(editor if editor is not None else (lambda: None),
                            where=self.where, language=self._language,
                            variables=self._variables,
                            last_error=self._last_error, whole=self._whole)

    def context(self) -> Context:
        language = self._language() if callable(self._language) else self._language
        editor = self.editor
        if editor is None:
            return ctx.build(self.where, language=language,
                             variables=self._variables(),
                             last_error=self._last_error())
        text = editor.toPlainText()
        cursor = editor.textCursor()
        return ctx.build(
            self.where, language=language, text=text,
            cursor=from_qt(text, cursor.position()),
            sel_start=from_qt(text, cursor.selectionStart()),
            sel_end=from_qt(text, cursor.selectionEnd()),
            variables=self._variables(), last_error=self._last_error(),
            whole=self._whole)

    def apply(self, context: Context, edit: Edit) -> None:
        editor = self.editor
        if editor is None:
            raise StaleEdit("The code this edit was for is no longer open.")
        text = editor.toPlainText()
        protocol.apply_edit(text, context, edit)          # raises if stale
        region = context.region
        cursor = QTextCursor(editor.document())
        cursor.beginEditBlock()                           # one undo step
        cursor.setPosition(to_qt(text, region.start))
        cursor.setPosition(to_qt(text, region.end), QTextCursor.KeepAnchor)
        cursor.insertText(edit.code)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)


class ConsoleSource(Source):
    """
    The console: what is typed at the prompt, and what is picked out above.

    The prompt's text, typed but not run, always goes along (its selection,
    if part of it is selected), and an edit replaces it — it still runs only
    when the user presses Enter. A selection in the transcript is sent as
    output to explain, errors included, and is never edited.
    """

    def __init__(self, prompt: QLineEdit, transcript: QPlainTextEdit, *,
                 language: str | Callable[[], str] = "matlab",
                 variables: Variables = dict,
                 last_error: Callable[[], str] = str) -> None:
        self.prompt = prompt
        self.transcript = transcript
        self._language = language
        self._variables = variables
        self._last_error = last_error

    def context(self) -> Context:
        text = self.prompt.text()
        start = end = None
        if self.prompt.hasSelectedText():
            start = from_qt(text, self.prompt.selectionStart())
            end = from_qt(text, self.prompt.selectionEnd())
        selected = self.transcript.textCursor().selectedText()
        language = self._language() if callable(self._language) else self._language
        return ctx.build(
            "console", language=language, text=text,
            cursor=from_qt(text, self.prompt.cursorPosition()),
            sel_start=start, sel_end=end, whole="prompt",
            variables=self._variables(), last_error=self._last_error(),
            # Qt hands a selection's line breaks back as U+2029.
            attachment=selected.replace(" ", "\n"))

    def apply(self, context: Context, edit: Edit) -> None:
        if "\n" in edit.code.strip("\n"):
            raise StaleEdit("This edit runs to several lines and the prompt "
                            "holds one. Copy it into a script instead.")
        text = self.prompt.text()
        protocol.apply_edit(text, context, edit)          # raises if stale
        region = context.region
        start, end = to_qt(text, region.start), to_qt(text, region.end)
        # Select, then type over it: the prompt's own undo takes it back.
        self.prompt.setSelection(start, end - start)
        self.prompt.insert(edit.code.strip("\n"))
        self.prompt.setFocus()


class SwitchSource(Source):
    """Whichever source ``pick()`` names now: the showing Console tab."""

    def __init__(self, pick: Callable[[], Source]) -> None:
        self._pick = pick

    def resolve(self) -> Source:
        return self._pick().resolve()

    def context(self) -> Context:
        return self._pick().context()

    def apply(self, context: Context, edit: Edit) -> None:
        self._pick().apply(context, edit)


def to_qt(text: str, index: int) -> int:
    """A Python string index as a Qt position (Qt counts UTF-16 units)."""
    return len(text[:index].encode("utf-16-le")) // 2


def from_qt(text: str, position: int) -> int:
    """A Qt position as a Python string index."""
    units = 0
    for i, ch in enumerate(text):
        if units >= position:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)
