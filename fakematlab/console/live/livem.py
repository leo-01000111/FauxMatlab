"""
MATLAB's plain-text live script: a ``.m`` file with ``%[text]`` markup.

Introduced in R2025a as an alternative to ``.mlx``. The syntax, as
documented by MathWorks ("Plain Text File Format for Live Scripts",
https://www.mathworks.com/help/matlab/matlab_prog/plain-text-file-format-for-live-scripts.html):

* Every line that does not start with markup — blank lines included — is
  **code**. ``%%`` alone on a line is a **section break**.
* ``%[text]`` starts one paragraph of formatted text. ``# `` makes it the
  title and ``## `` a heading (deeper levels add a ``#``); ``**bold**``,
  ``*italic*``, `` `mono` ``, ``<u>underline</u>`` and ``[link](url)`` as in
  Markdown. ``- `` and ``1. `` lines are list items, the last of a list
  ending in a backslash.
* A JSON attribute may follow the marker: ``%[text]{"align":"center"}``.
* **Equations** are LaTeX between ``$``. Inside the line, a backslash escapes
  Markdown, so a LaTeX command is written with two: ``$\\\\frac{1}{s}$``
  is ``\\frac{1}{s}``, and ``\\_`` is ``_``. A centred paragraph holding only
  an equation is a display equation.
* ``%[output:id]`` after a code line refers to stored output;
  ``%[control:…]`` and ``%[task:…]`` to controls and tasks.
* The file ends with an appendix — a blank line, ``%[appendix]{"version":"1.0"}``,
  ``%---``, then entries (``%[output:id]``, ``%[metadata:view]`` …), each a
  ``%   data: {json}`` line closed by ``%---``.

This is FauxMatlab's **native** format: it carries everything the document
model holds, stays readable and diffable, and MATLAB R2025a+ opens it. Outputs
are not stored — they come back by running the script.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .document import Cell, CellKind, LiveDocument

_TEXT = re.compile(r"^%\[text(?::([\w:-]+))?\]\s?(\{[^}]*\})?\s?(.*)$")
_MARKER = re.compile(r"^%\[(output|control|task|appendix|metadata)\b")
_TRAILING = re.compile(r"\s*%\[(output|control|task):[^\]]*\](\{[^}]*\})?\s*$")
_SECTION = re.compile(r"^%%(\s.*)?$")
_LIST = re.compile(r"^(-|\d+[.)])\s")
_HEADING = {1: CellKind.TITLE, 2: CellKind.HEADING, 3: CellKind.HEADING2,
            4: CellKind.HEADING3}
_PREFIX = {v: "#" * k for k, v in _HEADING.items()}

APPENDIX = ('%[appendix]{"version":"1.0"}\n'
            "%---\n"
            "%[metadata:view]\n"
            '%   data: {"layout":"inline"}\n'
            "%---\n")


def is_live_text(text: str) -> bool:
    """Does this ``.m`` use live-script markup, or is it an ordinary script?"""
    return any(_TEXT.match(line) or line.startswith("%[appendix]")
               for line in text.splitlines())


# ──────────────────────────────────────────────────────────────
#  Reading
# ──────────────────────────────────────────────────────────────

def read_live_m(path: str | Path) -> LiveDocument:
    path = Path(path)
    return LiveDocument(parse_live_m(path.read_text(encoding="utf-8")), path)


def parse_live_m(text: str) -> list[Cell]:
    """
    The cells of a plain-text live script — or of an ordinary script, whose
    ``%% Title`` section lines become headings over its code.
    """
    cells: list[Cell] = []
    code: list[str] = []
    pending_break = False
    lines = text.splitlines()
    i = 0

    def flush_code() -> None:
        nonlocal pending_break
        while code and not code[-1].strip():
            code.pop()
        while code and not code[0].strip():
            code.pop(0)
        if code:
            cells.append(Cell.code("\n".join(code),
                                   section_break=pending_break))
            pending_break = False
        code.clear()

    def add_text(kind: CellKind, body: str) -> None:
        nonlocal pending_break
        flush_code()
        previous = cells[-1] if cells else None
        if (kind is CellKind.TEXT and previous is not None
                and previous.kind is CellKind.TEXT and not pending_break):
            last = previous.source.splitlines()[-1]
            joint = "\n" if _LIST.match(last) and _LIST.match(body) \
                else "\n\n"
            previous.source += joint + body
            return
        cells.append(Cell.text(body, kind, section_break=pending_break))
        pending_break = False

    while i < len(lines):
        line = lines[i]
        i += 1
        if line.startswith("%[appendix]"):
            break
        section = _SECTION.match(line)
        if section:
            flush_code()
            pending_break = bool(cells)
            title = (section.group(1) or "").strip()
            if title:
                add_text(CellKind.HEADING, title)
            continue
        match = _TEXT.match(line)
        if match:
            sub, attrs, body = match.groups()
            if sub == "table":
                # A table runs to the next %[text:table]; keep its rows as text.
                rows = []
                while i < len(lines) and not lines[i].startswith(
                        "%[text:table]"):
                    row = re.sub(r"^%(\[text\])?", "", lines[i]).strip()
                    if row and not set(row) <= set("|-: "):
                        rows.append(" · ".join(
                            c.strip() for c in row.strip("|").split("|")))
                    i += 1
                i += 1
                if rows:
                    add_text(CellKind.TEXT, "\n".join("- " + r for r in rows))
                continue
            if sub:                      # anchors, contents, images …
                continue
            _add_paragraph(add_text, body, _attributes(attrs))
            continue
        if _MARKER.match(line):
            continue
        code.append(_TRAILING.sub("", line))
    flush_code()
    return cells


def _attributes(attrs: str | None) -> dict:
    if not attrs:
        return {}
    try:
        value = json.loads(attrs)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _add_paragraph(add_text, body: str, attrs: dict) -> None:
    body = body.rstrip()
    heading = re.match(r"^(#{1,4})\s+(.*)$", body)
    if heading:
        level = len(heading.group(1))
        add_text(_HEADING[level], unescape_math(heading.group(2).strip()))
        return
    if _LIST.match(body) and body.endswith("\\") and not body.endswith("\\\\"):
        body = body[:-1].rstrip()
    body = unescape_math(body)
    if attrs.get("align") == "center":
        lone = re.fullmatch(r"\$\$?(.+?)\$?\$", body.strip(), re.S)
        if lone and "$" not in lone.group(1):
            body = f"$${lone.group(1).strip()}$$"
    add_text(CellKind.TEXT, body)


def _math_spans(text: str):
    """(start, end) of each ``$…$`` / ``$$…$$`` span's *inside*."""
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "$":
            width = 2 if text.startswith("$$", i) else 1
            j = i + width
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                if text.startswith("$" * width, j):
                    break
                j += 1
            if j >= len(text):
                return
            yield i + width, j
            i = j + width
            continue
        i += 1


def _map_math(text: str, fn) -> str:
    out, last = [], 0
    for start, end in _math_spans(text):
        out.append(text[last:start])
        out.append(fn(text[start:end]))
        last = end
    out.append(text[last:])
    return "".join(out)


def unescape_math(text: str) -> str:
    """Inside math, ``\\\\`` → ``\\`` and ``\\_`` → ``_``: Markdown escapes off."""
    return _map_math(text, lambda m: re.sub(
        r"\\([!-/:-@\[-`{-~])", r"\1", m))


def escape_math(text: str) -> str:
    """The inverse: LaTeX inside math written the way the file wants it."""
    return _map_math(text, lambda m: re.sub(r"([\\_*])", r"\\\1", m))


# ──────────────────────────────────────────────────────────────
#  Writing
# ──────────────────────────────────────────────────────────────

def write_live_m(document: LiveDocument, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(to_live_m(document), encoding="utf-8")
    return path


def to_live_m(document: LiveDocument) -> str:
    out: list[str] = []
    previous: Cell | None = None
    for cell in document.cells:
        # Two code cells in a row would read back as one: a break keeps them
        # apart, the way MATLAB itself separates them.
        if previous is not None and (
                cell.section_break or (cell.is_code and previous.is_code)):
            out.append("%%")
        if cell.is_code:
            out.extend(_code_lines(cell.source))
        elif cell.kind.is_heading:
            line = " ".join(cell.source.split())
            out.append(f"%[text] {_PREFIX[cell.kind]} {escape_math(line)}")
        else:
            out.extend(_text_lines(cell.source))
        previous = cell
    return "\n".join(out) + "\n\n" + APPENDIX


def _code_lines(source: str) -> list[str]:
    lines = source.strip("\n").splitlines()
    # A code line that looks like markup would be read back as markup.
    return [(" " + line if line.startswith("%[") else line) for line in lines]


def _text_lines(source: str) -> list[str]:
    out = []
    for chunk in re.split(r"\n\s*\n", source.strip("\n")):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        joined = " ".join(lines)
        if (joined.startswith("$$") and joined.endswith("$$")
                and len(joined) > 4 and "$$" not in joined[2:-2]):
            out.append('%[text]{"align":"center"} $'
                       + escape_math("$" + joined[2:-2].strip() + "$")[1:-1]
                       + "$")
        elif all(_LIST.match(line) or line.startswith(("* ", "+ "))
                 for line in lines):
            items = [re.sub(r"^[*+]\s", "- ", line) for line in lines]
            items[-1] += " \\"
            out.extend(f"%[text] {escape_math(item)}" for item in items)
        else:
            text = joined.replace("$$", "$")
            out.append(f"%[text] {escape_math(text)}")
    return out
