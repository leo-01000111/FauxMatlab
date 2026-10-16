"""
Tab completion, for the script editor and the console prompt alike.

:func:`completion_candidates` decides *what* to offer — workspace variables
first, then keywords, the MATLAB library and the console's commands, then
``.m`` files in the current folder (a script is run by its name). It is a
plain function so it can be tested without a widget.

:class:`Completer` decides *how*: one match is inserted at once; several
fill in their common prefix and open a popup to pick from; no word before
the cursor returns ``False`` so the widget can indent instead.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QStringListModel, Qt
from PySide6.QtWidgets import QCompleter, QLineEdit, QPlainTextEdit

from .. import theme
from .highlighter import MATLAB_KEYWORDS, PYTHON_KEYWORDS

#: Characters that make up the word Tab completes.
WORD_CHARS = "_."


@functools.cache
def matlab_builtins() -> frozenset[str]:
    """The MATLAB library's function and constant names (``zeros``, ``pi``…)."""
    from ...console.matlab_runtime import Runtime
    return frozenset(Runtime({}).lib.names)


def word_before(text: str) -> str:
    """The identifier (dots included) that ends ``text``."""
    i = len(text)
    while i > 0 and (text[i - 1].isalnum() or text[i - 1] in WORD_CHARS):
        i -= 1
    return text[i:]


def completion_candidates(prefix: str, interpreter=None, *,
                          folder: str | Path | None = None,
                          language: str = "matlab") -> list[str]:
    """
    Every completion of ``prefix``, best first, without duplicates.

    ``interpreter`` supplies the workspace (the paused scope while
    debugging) and the console's commands; ``a.b`` completes attributes of
    ``a``. ``folder`` is where ``.m`` files are looked for (the current
    directory by default).
    """
    if not prefix:
        return []
    if "." in prefix:
        return interpreter.completions(prefix) if interpreter else []

    groups: list[Iterable[str]] = []
    if interpreter is not None:
        groups.append(sorted(n for n in interpreter.variables()
                             if n.startswith(prefix)))
    keywords = MATLAB_KEYWORDS if language == "matlab" else PYTHON_KEYWORDS
    groups.append(sorted(k for k in keywords if k.startswith(prefix)))
    names = set(n for n in matlab_builtins() if n.startswith(prefix))
    if interpreter is not None:
        names.update(interpreter.completions(prefix))
    groups.append(sorted(names, key=lambda n: (n.lower(), n)))
    groups.append(m_files(prefix, folder))

    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for name in group:
            if name not in seen and not name.startswith("_"):
                seen.add(name)
                out.append(name)
    return out


def m_files(prefix: str, folder: str | Path | None = None) -> list[str]:
    """Names of ``.m`` files in ``folder`` starting with ``prefix``."""
    try:
        entries = os.listdir(folder or os.getcwd())
    except OSError:
        return []
    return sorted(e[:-2] for e in entries
                  if e.endswith(".m") and e.startswith(prefix))


def common_prefix(items: list[str]) -> str:
    first = items[0]
    for i, char in enumerate(first):
        if any(len(other) <= i or other[i] != char for other in items[1:]):
            return first[:i]
    return first


class Completer(QObject):
    """
    Tab completion attached to a ``QPlainTextEdit`` or a ``QLineEdit``.

    The widget calls :meth:`complete` on Tab, and, while :meth:`is_open`,
    leaves Return, Tab and Escape to the popup (``event.ignore()``).
    """

    def __init__(self, widget: QPlainTextEdit | QLineEdit,
                 source: Callable[[str], list[str]]) -> None:
        super().__init__(widget)
        self._widget = widget
        self._source = source
        self._prefix = ""
        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setWidget(widget)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitive)
        self._completer.setMaxVisibleItems(12)
        self._completer.activated[str].connect(self._insert)
        popup = self._completer.popup()
        popup.setFont(theme.data_font(9))
        self._restyle()
        theme.notifier().changed.connect(self._restyle)

    def _restyle(self, *_args) -> None:
        t = theme.tokens()
        self._completer.popup().setStyleSheet(
            f"QListView {{ background: {t.surface}; color: {t.ink};"
            f" border: 2px solid {t.ink_muted}; }}"
            f"QListView::item:selected {{ background: {t.signal};"
            f" color: {t.on_signal}; }}")

    # ── the widget, either kind ─────────────────────────────────

    def _text_before_cursor(self) -> str:
        w = self._widget
        if isinstance(w, QLineEdit):
            return w.text()[:w.cursorPosition()]
        cursor = w.textCursor()
        return cursor.block().text()[:cursor.positionInBlock()]

    def _replace_word(self, length: int, text: str) -> None:
        w = self._widget
        if isinstance(w, QLineEdit):
            pos = w.cursorPosition()
            full = w.text()
            w.setText(full[:pos - length] + text + full[pos:])
            w.setCursorPosition(pos - length + len(text))
            return
        cursor = w.textCursor()
        cursor.movePosition(cursor.MoveOperation.Left,
                            cursor.MoveMode.KeepAnchor, length)
        cursor.insertText(text)
        w.setTextCursor(cursor)

    def _cursor_rect(self) -> QRect:
        rect = self._widget.cursorRect()
        rect.setWidth(max(240, self._completer.popup().sizeHintForColumn(0)
                          + 30))
        return rect

    # ── completing ──────────────────────────────────────────────

    def is_open(self) -> bool:
        return self._completer.popup().isVisible()

    def candidates(self) -> list[str]:
        """What Tab would offer now."""
        return self._source(word_before(self._text_before_cursor()))

    def complete(self) -> bool:
        """
        Complete the word before the cursor.

        Returns ``False`` when there is no word there — the caller then
        indents — and ``True`` otherwise, even if nothing matched.
        """
        prefix = word_before(self._text_before_cursor())
        if not prefix:
            return False
        matches = self._source(prefix)
        if not matches:
            return True
        if len(matches) == 1:
            self._replace_word(len(prefix), matches[0])
            return True
        shared = common_prefix(matches)
        if len(shared) > len(prefix):
            self._replace_word(len(prefix), shared)
            prefix = shared
        self._prefix = prefix
        self._model.setStringList(matches[:200])
        self._completer.setCompletionPrefix("")
        popup = self._completer.popup()
        popup.setCurrentIndex(self._model.index(0, 0))
        self._completer.complete(self._cursor_rect())
        return True

    def _insert(self, text: str) -> None:
        self._replace_word(len(self._prefix), text)
        self._completer.popup().hide()

    def accept_current(self) -> None:
        """Insert the popup's highlighted entry (as Return/Tab would)."""
        index = self._completer.popup().currentIndex()
        if index.isValid():
            self._insert(index.data())
