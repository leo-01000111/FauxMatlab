"""
Syntax highlighting for MATLAB (and the Python the Script tab also takes).

The lexing is a pure function, :func:`tokenize_line`, so it can be tested
without a document; :class:`MatlabHighlighter` only maps its spans to
formats. The one subtle rule is MATLAB's ``'``: it is a *transpose* straight
after a value (``A'``, ``x(1)'``, ``b.'``) and the start of a string anywhere
else (``disp('hi')``, ``[a 'b']``) — the same test MATLAB's own lexer makes.

Colours come from the theme tokens, so they follow Day and Night:
keywords in ``edge`` (bold), strings in ``lamp_go``, numbers in the amber
plot highlight, comments in ``ink_muted`` (italic), ``%%`` section titles in
bold ink.
"""

from __future__ import annotations

import keyword
import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from .. import theme

#: MATLAB's reserved words (with the Octave spellings the translator takes).
MATLAB_KEYWORDS = frozenset({
    "break", "case", "catch", "classdef", "continue", "else", "elseif", "end",
    "for", "function", "global", "if", "otherwise", "parfor", "persistent",
    "return", "spmd", "switch", "try", "while", "endif", "endfor",
    "endwhile", "endfunction", "endswitch", "end_try_catch",
})

PYTHON_KEYWORDS = frozenset(keyword.kwlist) | {"match", "case"}

#: Block-comment state carried from one line to the next.
NORMAL, BLOCK_COMMENT = 0, 1

_NUMBER = re.compile(
    r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[ij]?")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_SECTION = re.compile(r"^\s*(%%|#\s*%%)(?=\s|$)")

#: After one of these, MATLAB's ``'`` transposes rather than quotes.
_VALUE_END = set("_)]}.'") | {chr(c) for c in range(48, 58)}


def is_section_header(text: str) -> bool:
    """``%%`` at the start of a line (``# %%`` in Python) opens a section."""
    return bool(_SECTION.match(text))


def tokenize_line(text: str, state: int = NORMAL,
                  language: str = "matlab") -> tuple[list[tuple[int, int, str]],
                                                     int]:
    """
    Split one line into ``(start, length, kind)`` spans.

    ``kind`` is ``keyword``, ``string``, ``number``, ``comment`` or
    ``section``; plain text gets no span. Returns the spans and the state the
    next line starts in (``BLOCK_COMMENT`` inside ``%{ … %}``).
    """
    if language == "python":
        return _tokenize_python(text), NORMAL

    stripped = text.strip()
    if state == BLOCK_COMMENT:
        return [(0, len(text), "comment")], \
            NORMAL if stripped == "%}" else BLOCK_COMMENT
    if stripped == "%{":
        return [(0, len(text), "comment")], BLOCK_COMMENT
    if is_section_header(text):
        return [(0, len(text), "section")], NORMAL

    spans: list[tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "%":
            spans.append((i, n - i, "comment"))
            break
        if text.startswith("...", i):
            spans.append((i, n - i, "comment"))   # the rest is ignored
            break
        if c == '"' or (c == "'" and not _transposes(text, i)):
            end = _string_end(text, i, c)
            spans.append((i, end - i, "string"))
            i = end
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            if i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"):
                m = _NUMBER.match(text, i)
                if m:
                    spans.append((i, m.end() - i, "number"))
                    i = m.end()
                    continue
        m = _IDENT.match(text, i)
        if m:
            if m.group() in MATLAB_KEYWORDS and not _is_field(text, i):
                spans.append((i, m.end() - i, "keyword"))
            i = m.end()
            continue
        i += 1
    return spans, NORMAL


def _transposes(text: str, i: int) -> bool:
    """Is the ``'`` at ``i`` a transpose? Only straight after a value."""
    if i == 0:
        return False
    prev = text[i - 1]
    if prev.isalpha() or prev in _VALUE_END:
        # ``case 'a'`` / ``disp 'x'``: a keyword is not a value.
        j = i
        while j > 0 and (text[j - 1].isalnum() or text[j - 1] == "_"):
            j -= 1
        return text[j:i] not in MATLAB_KEYWORDS
    return False


def _string_end(text: str, i: int, quote: str) -> int:
    """Index just past the closing quote (doubled quotes escape)."""
    j = i + 1
    while j < len(text):
        if text[j] == quote:
            if j + 1 < len(text) and text[j + 1] == quote:
                j += 2
                continue
            return j + 1
        j += 1
    return len(text)


def _is_field(text: str, i: int) -> bool:
    """``s.end`` is a field, not the keyword."""
    return i > 0 and text[i - 1] == "." and not (i > 1 and text[i - 2] == ".")


def _tokenize_python(text: str) -> list[tuple[int, int, str]]:
    if is_section_header(text):
        return [(0, len(text), "section")]
    spans: list[tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "#":
            spans.append((i, n - i, "comment"))
            break
        if c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            end = min(j + 1, n)
            spans.append((i, end - i, "string"))
            i = end
            continue
        if c.isdigit() and (i == 0 or not (text[i - 1].isalnum()
                                           or text[i - 1] == "_")):
            m = _NUMBER.match(text, i)
            if m:
                spans.append((i, m.end() - i, "number"))
                i = m.end()
                continue
        m = _IDENT.match(text, i)
        if m:
            if m.group() in PYTHON_KEYWORDS:
                spans.append((i, m.end() - i, "keyword"))
            i = m.end()
            continue
        i += 1
    return spans


def syntax_formats(tokens: theme.Tokens | None = None) -> dict[
        str, QTextCharFormat]:
    """The character format for each span kind, in the given theme."""
    t = tokens or theme.tokens()
    amber = "#f5c518" if t.is_night else "#b8900a"

    def fmt(colour: str, bold: bool = False,
            italic: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(QColor(colour))
        if bold:
            f.setFontWeight(QFont.Bold)
        f.setFontItalic(italic)
        return f

    return {
        "keyword": fmt(t.edge, bold=True),
        "string":  fmt(t.lamp_go),
        "number":  fmt(amber),
        "comment": fmt(t.ink_muted, italic=True),
        "section": fmt(t.ink, bold=True),
    }


class MatlabHighlighter(QSyntaxHighlighter):
    """
    Highlights a document as MATLAB (or Python: :attr:`language`).

    Follows the theme by itself: a Day/Night switch re-reads the formats and
    rehighlights.
    """

    def __init__(self, document, language: str = "matlab") -> None:
        super().__init__(document)
        self._language = language
        self._formats = syntax_formats()
        theme.notifier().changed.connect(self._retheme)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        if language != self._language:
            self._language = language
            self.rehighlight()

    def _retheme(self, *_args) -> None:
        self._formats = syntax_formats()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:       # noqa: N802 (Qt API)
        previous = self.previousBlockState()
        spans, state = tokenize_line(
            text, BLOCK_COMMENT if previous == BLOCK_COMMENT else NORMAL,
            self._language)
        for start, length, kind in spans:
            self.setFormat(start, length, self._formats[kind])
        self.setCurrentBlockState(state)
