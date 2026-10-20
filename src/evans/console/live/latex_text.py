"""
Text cells as LaTeX.

With the report template's ``latex_text`` on (the default), a text cell is
LaTeX: commands, environments, ``\\[ … \\]``, ``\\ref`` and ``\\cite`` reach
the .tex untouched. The Markdown marks keep working, since the editor renders
them and older scripts use them — ``**bold**``, ``*italic*``, `` `code` ``,
``[text](url)``, ``<u>…</u>``, ``- `` / ``1. `` lists, ``$$…$$`` — and so do
``{{expr}}`` placeholders, filled from the workspace.

Prose is forgiven the characters that are always an error in LaTeX text: a
bare ``_``, ``#``, ``^`` or ``&`` (outside an environment) is escaped, and so
is a ``%`` written straight after a word or number ("50%"); a ``%`` after a
space or at the start of a line is a LaTeX comment, to the end of its line.
The arguments of a command (``\\includegraphics[width=…]{my_plot.png}``) are
left exactly as written.
"""

from __future__ import annotations

import re

from .markup import (
    _BULLET,
    _NUMBER,
    _TEX_ESCAPES,
    Evaluator,
    _find,
    _math_end,
    escape_tex,
    resolve,
)

_COMMAND = re.compile(r"\\([A-Za-z@]+)\*?")
_BEGIN = re.compile(r"\\begin\s*\{([^}]*)\}")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
_PLACEHOLDER = re.compile(r"\{\{(.+?)\}\}")


def latex_text(source: str, *, evaluate: Evaluator | None = None) -> str:
    """A text cell, written as LaTeX, ready for the .tex."""
    s = source.strip("\n")
    out: list[str] = []
    prose_start = i = 0
    while i < len(s):
        if s.startswith("\\begin", i):
            m = _BEGIN.match(s, i)
            end = _environment_end(s, i, m.group(1)) if m else -1
            if end > 0:
                out.append(_prose(s[prose_start:i], evaluate))
                out.append(_fill(s[i:end], evaluate))
                i = prose_start = end
                continue
        i += 2 if s[i] == "\\" else 1
    out.append(_prose(s[prose_start:], evaluate))
    return "".join(out)


def inline_latex_text(s: str, *, evaluate: Evaluator | None = None,
                      keep_lines: bool = False) -> str:
    """
    One run of LaTeX prose with the Markdown marks converted: a heading, a
    caption, a list item, or a paragraph (``keep_lines`` keeps its line
    breaks, so a ``%`` comment ends where its line does).
    """
    if not keep_lines:
        s = s.replace("\n", " ")
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i = _backslash(s, i, out, evaluate)
            continue
        if s.startswith("{{", i):
            end = s.find("}}", i + 2)
            if end > 0:
                out.append(_value(s[i + 2:end].strip(), evaluate, math=False))
                i = end + 2
                continue
        if s.startswith("$$", i):
            end = s.find("$$", i + 2)
            if end > 0:
                out.append(f"\\[{_fill(s[i + 2:end].strip(), evaluate)}\\]")
                i = end + 2
                continue
        if c == "$":
            end = _math_end(s, i + 1)
            if end > i + 1:
                out.append(f"${_fill(s[i + 1:end], evaluate)}$")
                i = end + 1
                continue
        if c == "`":
            end = s.find("`", i + 1)
            if end > 0:
                out.append(f"\\texttt{{{escape_tex(s[i + 1:end])}}}")
                i = end + 1
                continue
        marked = _emphasis(s, i, evaluate)
        if marked is not None:
            text, i = marked
            out.append(text)
            continue
        if c == "[":
            m = _LINK.match(s, i)
            if m:
                url = m.group(2).replace("%", r"\%").replace("#", r"\#")
                inner = inline_latex_text(m.group(1), evaluate=evaluate)
                out.append(f"\\href{{{url}}}{{{inner}}}")
                i = m.end()
                continue
        if c == "%":
            if i > 0 and not s[i - 1].isspace():
                out.append(r"\%")              # "50%": a percent sign
                i += 1
                continue
            end = s.find("\n", i)              # a comment, to the line's end
            end = n if end < 0 else end
            out.append(s[i:end])
            i = end
            continue
        out.append(_TEX_ESCAPES[c] if c in "_#^&" else c)
        i += 1
    return "".join(out)


# ── pieces ──────────────────────────────────────────────────────

def _prose(text: str, evaluate) -> str:
    """Prose between environments: blocks (lists, display math) and inline."""
    parts = re.split(r"(\n[ \t]*\n\s*)", text)
    out = []
    for k, chunk in enumerate(parts):
        if k % 2:                          # a blank-line separator, as is
            out.append(chunk)
            continue
        lines = [line for line in chunk.splitlines() if line.strip()]
        stripped = chunk.strip()
        # Whitespace around a block is kept: an environment may sit right
        # against it, and its line break is what separates the two.
        lead = chunk[:len(chunk) - len(chunk.lstrip())]
        trail = chunk[len(chunk.rstrip()):]
        if (stripped.startswith("$$") and stripped.endswith("$$")
                and len(stripped) > 4 and "$$" not in stripped[2:-2]):
            block = f"\\[\n{_fill(stripped[2:-2].strip(), evaluate)}\n\\]"
        elif lines and all(_BULLET.match(line) for line in lines):
            block = _list("itemize", _BULLET, lines, evaluate)
        elif lines and all(_NUMBER.match(line) for line in lines):
            block = _list("enumerate", _NUMBER, lines, evaluate)
        else:
            out.append(inline_latex_text(chunk, evaluate=evaluate,
                                         keep_lines=True))
            continue
        out.append(lead + block + trail)
    return "".join(out)


def _list(env: str, marker, lines: list[str], evaluate) -> str:
    items = "\n".join(
        f"  \\item {inline_latex_text(marker.sub('', line), evaluate=evaluate)}"
        for line in lines)
    return f"\\begin{{{env}}}\n{items}\n\\end{{{env}}}"


def _backslash(s: str, i: int, out: list[str], evaluate) -> int:
    """A command with its arguments, ``\\[…\\]``, or an escape; returns the
    index after it."""
    n = len(s)
    m = _COMMAND.match(s, i)
    if m:
        out.append(m.group(0))
        i = m.end()
        while i < n and s[i] in "[{":          # [optional] and {required}
            end = _group_end(s, i, s[i], "]" if s[i] == "[" else "}")
            if end < 0:
                break
            out.append(_fill(s[i:end], evaluate, math=False))
            i = end
        return i
    if s.startswith(("\\[", "\\("), i):
        close = "\\]" if s[i + 1] == "[" else "\\)"
        end = s.find(close, i + 2)
        if end > 0:
            out.append(_fill(s[i:end + 2], evaluate))
            return end + 2
    if i + 1 < n and s[i + 1] in "*<":         # Markdown-only escapes
        out.append(s[i + 1])
        return i + 2
    out.append(s[i:i + 2])                     # \$ \% \& \\ \, …
    return i + 2


def _emphasis(s: str, i: int, evaluate) -> tuple[str, int] | None:
    for open_, close, command in (("**", "**", "textbf"), ("*", "*", "emph"),
                                  ("<u>", "</u>", "underline")):
        if not s.startswith(open_, i):
            continue
        start = i + len(open_)
        end = _find(s, start, close)
        if end > start:
            inner = inline_latex_text(s[start:end], evaluate=evaluate)
            return f"\\{command}{{{inner}}}", end + len(close)
        if open_ == "**":
            continue                            # maybe a single * then
        return None
    return None


def _group_end(s: str, i: int, open_: str, close: str) -> int:
    """Index just past the group opened by ``s[i] == open_``, or -1."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def _environment_end(s: str, i: int, name: str) -> int:
    """Index past the ``\\end{name}`` matching the ``\\begin{name}`` at i."""
    begin = re.compile(r"\\begin\s*\{" + re.escape(name) + r"\}")
    end = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
    depth = 0
    j = i
    while True:
        b, e = begin.search(s, j), end.search(s, j)
        if e is None:
            return -1
        if b is not None and b.start() < e.start():
            depth += 1
            j = b.end()
        else:
            depth -= 1
            j = e.end()
            if depth == 0:
                return j


def _value(expr: str, evaluate: Evaluator | None, math: bool) -> str:
    """A placeholder's value as LaTeX — bare inside math, ``$…$`` outside."""
    node = resolve(expr, evaluate)
    if node.kind == "math":
        return node.text if math else f"${node.text}$"
    if node.kind == "code":
        return f"\\texttt{{{escape_tex(node.text)}}}"
    return escape_tex(node.text)


def _fill(raw: str, evaluate: Evaluator | None, math: bool = True) -> str:
    """Placeholders inside raw LaTeX (an environment, math, an argument)."""
    return _PLACEHOLDER.sub(
        lambda m: _value(m.group(1).strip(), evaluate, math), raw)
