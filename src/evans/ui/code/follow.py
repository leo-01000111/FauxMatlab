"""
Hover for a function's syntax, Ctrl+click to go to it.

One controller for the script tabs, the live-script cells, the console
prompt and its transcript. Resting the mouse on a function name shows how
it is called; holding Ctrl over one that can be followed underlines it, and
Ctrl+click follows it:

* a function defined in the same script (a local function) — to its line;
* a function in a ``.m`` file in the current folder or on the path — that
  file, in a script tab, at the function;
* a built-in with a help page — the page.

What a name means is decided the way MATLAB decides it: a variable is not a
function, a local function comes before a file, and a file before a
built-in. :func:`resolve` does that without Qt, so it is tested on its own.

The popup for a built-in is its help page's *Syntax* section and summary;
one without a page falls back to the signature table
(:mod:`.signatures`), then to the Python signature. For a function you
wrote, it is the ``function`` line and the comment line under it, which is
what MATLAB's ``help`` shows first.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QCursor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QToolTip,
)

from .. import theme
from .signatures import SIGNATURES

#: A MATLAB identifier.
_NAME = re.compile(r"[A-Za-z_]\w*")

#: ``function [a, b] = name(x, y)``, ``function name``, and the rest.
_FUNCTION = re.compile(
    r"^\s*function\s+(?:(?:\[[^\]]*\]|\w+)\s*=\s*)?(?P<name>[A-Za-z_]\w*)")

#: Words that are never followed: the language's own.
_KEYWORDS = frozenset((
    "if", "elseif", "else", "end", "for", "while", "switch", "case",
    "otherwise", "function", "return", "break", "continue", "try", "catch",
    "global", "persistent"))

#: What a :class:`Target` is.
LOCAL, FILE, HELP, SIGNATURE = "local", "file", "help", "signature"


@dataclass
class Target:
    """Where a name leads, and what its popup says."""
    name:     str
    kind:     str                       # LOCAL, FILE, HELP or SIGNATURE
    #: How it is called, one form per line.
    syntax:   list[str] = field(default_factory=list)
    summary:  str = ""
    path:     Path | None = None        # FILE: the .m file
    line:     int | None = None         # LOCAL / FILE: the function line

    @property
    def followable(self) -> bool:
        """Whether Ctrl+click goes somewhere: not for a bare signature."""
        return self.kind != SIGNATURE


@dataclass
class Context:
    """
    What :func:`resolve` may consult, all optional.

    ``text`` is the script the name is in (for its local functions);
    ``find_file(name)`` returns the ``.m`` file defining it, if any;
    ``is_variable(name)`` says the workspace holds a value of that name;
    ``python(name)`` returns the object a name means in Python, for the
    last fallback.
    """
    text:        str = ""
    find_file:   Callable[[str], Path | None] | None = None
    is_variable: Callable[[str], bool] | None = None
    python:      Callable[[str], object] | None = None


# ── the name under a position ───────────────────────────────────

def name_at(line: str, column: int) -> tuple[int, int] | None:
    """The identifier ``line[column]`` is in, as (start, end), or None."""
    for match in _NAME.finditer(line):
        if match.start() <= column < match.end():
            if _in_string_or_comment(line, match.start()):
                return None
            return match.span()
    return None


def _in_string_or_comment(line: str, column: int) -> bool:
    """
    Whether ``column`` is inside a quoted string or after a ``%``. A rough
    reading — a ``'`` after a name or ``)`` is a transpose — that only has
    to keep text that is not code from being followed.
    """
    quote = None
    for i, ch in enumerate(line[:column]):
        if quote:
            if ch == quote:
                quote = None
        elif ch == "%" or ch == "#":
            return True
        elif ch == '"':
            quote = ch
        elif ch == "'":
            before = line[:i].rstrip()
            if not before or not (before[-1].isalnum()
                                  or before[-1] in "_)]}.'"):
                quote = ch
    return quote is not None


# ── what a name means ───────────────────────────────────────────

def resolve(name: str, context: Context | None = None) -> Target | None:
    """Where ``name`` leads, in MATLAB's order; None if nowhere."""
    context = context or Context()
    if not _NAME.fullmatch(name) or name in _KEYWORDS:
        return None
    if context.is_variable is not None and context.is_variable(name):
        return None
    local = _local_function(name, context.text)
    if local is not None:
        return local
    if context.find_file is not None:
        path = context.find_file(name)
        if path is not None:
            return _file_function(name, Path(path))
    page = _help_target(name)
    if page is not None:
        return page
    return _signature_target(name, context.python)


def _local_function(name: str, text: str) -> Target | None:
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        match = _FUNCTION.match(line)
        if match and match["name"] == name:
            return Target(name, LOCAL, [_signature_of(line)],
                          _h1(lines, number), line=number)
    return None


def _file_function(name: str, path: Path) -> Target:
    """A function file: its first ``function`` line, else a script."""
    try:
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines()
    except OSError:
        lines = []
    for number, line in enumerate(lines, 1):
        if _FUNCTION.match(line):
            return Target(name, FILE, [_signature_of(line)],
                          _h1(lines, number), path=path, line=number)
    first = next((ln.strip().lstrip("%").strip() for ln in lines
                  if ln.strip().startswith("%")), "")
    return Target(name, FILE, [name], first or f"Script {path.name}",
                  path=path, line=1)


def _signature_of(line: str) -> str:
    """A ``function`` line as it is called: no keyword, no trailing comment."""
    text = line.strip()[len("function"):].strip()
    return text.split("%", 1)[0].rstrip(" ;")


def _h1(lines: list[str], number: int) -> str:
    """The first comment line under line ``number``, MATLAB's H1 line."""
    for line in lines[number:]:
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.lstrip("%").strip() if stripped.startswith("%") \
            else ""
    return ""


def _help_target(name: str) -> Target | None:
    from ... import help as pages
    try:
        page = pages.load(name)
    except (pages.PageError, OSError, UnicodeDecodeError):
        return None
    if page is None:
        return None
    syntax = [form for kind, source in page.section("Syntax")
              if kind == "code" for form in source.splitlines()
              if form.strip()]
    return Target(name, HELP, syntax, page.summary)


def _signature_target(name: str, python) -> Target | None:
    known = SIGNATURES.get(name)
    if known is not None:
        signature, description = known
        return Target(name, SIGNATURE, [signature or name], description)
    if python is None:
        return None
    obj = python(name)
    if obj is None or not callable(obj):
        return None
    from .completion import first_line, python_signature
    return Target(name, SIGNATURE, [python_signature(name, obj)],
                  first_line(getattr(obj, "__doc__", None)))


def popup_html(target: Target) -> str:
    """The hover popup: the forms in the code font, then the summary."""
    forms = "<br>".join(html.escape(form) for form in target.syntax)
    summary = html.escape(_plain(target.summary))
    where = ""
    if target.kind == FILE and target.path is not None:
        where = f"<br><i>{html.escape(target.path.name)}</i>"
    hint = ("<br><small>Ctrl+click for the help page</small>"
            if target.kind == HELP else
            "<br><small>Ctrl+click to go to it</small>"
            if target.followable else "")
    body = f"<code>{forms}</code>"
    if summary:
        body += f"<br>{summary}"
    return f"<p style='white-space:pre'>{body}{where}{hint}</p>"


def _plain(markup: str) -> str:
    """A page's summary without its markup: links and backticks."""
    markup = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", markup)
    return markup.replace("`", "").replace("**", "")


# ── the controller ──────────────────────────────────────────────

class FollowController(QObject):
    """
    Hover and Ctrl+click on one text widget: a ``QPlainTextEdit``, a
    ``QTextEdit`` or a ``QLineEdit``.

    ``context()`` is asked afresh at each hover or click, since the script,
    the folder and the workspace all change; ``follow(target, widget)``
    does the going.
    """

    def __init__(self, widget, context: Callable[[], Context],
                 follow: Callable[[Target, object], None]) -> None:
        super().__init__(widget)
        self._widget = widget
        self._context = context
        self._follow = follow
        self._underlined: tuple[int, int] | None = None
        self._line_edit = isinstance(widget, QLineEdit)
        self._surface = widget if self._line_edit else widget.viewport()
        self._surface.setMouseTracking(True)
        self._surface.installEventFilter(self)
        widget.installEventFilter(self)          # Ctrl released

    # ── what is under the mouse ─────────────────────────────────

    def target_at(self, pos) -> tuple[Target, tuple[int, int]] | None:
        """The target under ``pos`` (in the surface's coordinates)."""
        found = self._name_at(pos)
        if found is None:
            return None
        name, span = found
        context = self._context()
        if not self._line_edit and not context.text:
            context.text = self._widget.toPlainText()
        target = resolve(name, context)
        return (target, span) if target is not None else None

    def _name_at(self, pos) -> tuple[str, tuple[int, int]] | None:
        if self._line_edit:
            text = self._widget.text()
            column = self._widget.cursorPositionAt(pos)
            # cursorPositionAt rounds to the nearest gap: look either side.
            span = name_at(text, column) or name_at(text, column - 1)
            if span is None:
                return None
            return text[span[0]:span[1]], span
        cursor = self._widget.cursorForPosition(pos)
        block = cursor.block()
        column = cursor.positionInBlock()
        rect = self._widget.cursorRect(cursor)
        if pos.x() < rect.left():         # the left half of a character
            column -= 1
        span = name_at(block.text(), column) \
            or name_at(block.text(), cursor.positionInBlock())
        if span is None:
            return None
        start = block.position()
        return (block.text()[span[0]:span[1]],
                (start + span[0], start + span[1]))

    # ── events ──────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        kind = event.type()
        if obj is self._surface:
            if kind == QEvent.ToolTip:
                return self._hover(event)
            if kind == QEvent.MouseMove:
                self._track(event.position().toPoint(),
                            event.modifiers() & Qt.ControlModifier)
            elif kind == QEvent.Leave:
                self._clear()
            elif kind == QEvent.MouseButtonPress \
                    and event.button() == Qt.LeftButton \
                    and event.modifiers() & Qt.ControlModifier:
                return self._click(event.position().toPoint())
        elif kind == QEvent.KeyRelease and event.key() == Qt.Key_Control:
            self._clear()
        elif kind == QEvent.KeyPress and event.key() == Qt.Key_Control:
            pos = self._surface.mapFromGlobal(QCursor.pos())
            if self._surface.rect().contains(pos):
                self._track(pos, True)
        return False

    def _hover(self, event) -> bool:
        found = self.target_at(event.pos())
        if found is None:
            QToolTip.hideText()
            event.ignore()
            return True
        QToolTip.showText(event.globalPos(), popup_html(found[0]),
                          self._surface)
        return True

    def _track(self, pos, ctrl) -> None:
        found = self.target_at(pos) if ctrl else None
        if found is None or not found[0].followable:
            self._clear()
            return
        self._underline(found[1])

    def _click(self, pos) -> bool:
        found = self.target_at(pos)
        if found is None or not found[0].followable:
            return False
        self._clear()
        QToolTip.hideText()
        self._follow(found[0], self._widget)
        return True

    # ── the underline ───────────────────────────────────────────

    def _underline(self, span: tuple[int, int]) -> None:
        if span == self._underlined:
            return
        self._clear()
        self._underlined = span
        self._surface.setCursor(Qt.PointingHandCursor)
        if self._line_edit:
            return
        selection = QTextEdit.ExtraSelection()
        cursor = QTextCursor(self._widget.document())
        cursor.setPosition(span[0])
        cursor.setPosition(span[1], QTextCursor.KeepAnchor)
        selection.cursor = cursor
        fmt = QTextCharFormat()
        fmt.setFontUnderline(True)
        fmt.setForeground(QColor(theme.tokens().edge))
        selection.format = fmt
        self._widget.setExtraSelections(
            [*self._others(), selection])

    def _clear(self) -> None:
        if self._underlined is None:
            return
        self._underlined = None
        self._surface.unsetCursor()
        if isinstance(self._widget, QPlainTextEdit):
            # The editor's I-beam, as Qt sets it on the viewport.
            self._surface.setCursor(Qt.IBeamCursor)
        if not self._line_edit:
            self._widget.setExtraSelections(self._others())

    def _others(self) -> list:
        """The widget's own selections (an error line, a paused line)."""
        return [s for s in self._widget.extraSelections()
                if not s.format.fontUnderline()]
