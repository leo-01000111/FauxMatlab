"""
The text-cell dialect: a small Markdown with LaTeX math and placeholders.

Blocks are separated by blank lines:

* a paragraph — its lines are joined, as Markdown joins them;
* a list — every line starts ``- `` (bulleted) or ``1. `` (numbered);
* display math — a block that is a single ``$$ ... $$``.

Inline: ``**bold**``, ``*italic*``, `` `code` ``, ``<u>underline</u>``,
``[text](url)``, ``$math$``, ``$$math$$`` and ``{{expr}}``. A backslash
before punctuation makes it literal (``\\$5``, ``\\*``).

Parsed into a small tree of :class:`Node` so that the one parse feeds three
renderers: HTML for the editor and the HTML report, LaTeX for the report, and
the run lists the ``.mlx`` writer needs.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PUNCTUATION = set("\\`*_{}[]()#+-.!$|<>~^&%\"'")


@dataclass
class Node:
    """
    ``kind`` is one of: text, math, code, interp, bold, italic, underline,
    link. Leaves carry ``text`` (math: the LaTeX; interp: the expression);
    containers carry ``children``. ``display`` marks ``$$`` math.
    """
    kind:     str
    text:     str = ""
    children: list[Node] = field(default_factory=list)
    url:      str = ""
    display:  bool = False


@dataclass
class Block:
    """``kind``: paragraph, ul, ol or math. ``items`` holds a list's items."""
    kind:  str
    nodes: list[Node] = field(default_factory=list)
    items: list[list[Node]] = field(default_factory=list)
    math:  str = ""


_BULLET = re.compile(r"^\s*[-*+]\s+")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+")


def parse_blocks(source: str) -> list[Block]:
    """Split a text cell into blocks and parse each one's inline markup."""
    blocks: list[Block] = []
    for chunk in re.split(r"\n\s*\n", source.strip("\n")):
        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        joined = " ".join(line.strip() for line in lines)
        if (joined.startswith("$$") and joined.endswith("$$")
                and len(joined) > 4 and "$$" not in joined[2:-2]):
            blocks.append(Block("math", math=joined[2:-2].strip()))
        elif all(_BULLET.match(line) for line in lines):
            blocks.append(Block("ul", items=[
                parse_inline(_BULLET.sub("", line)) for line in lines]))
        elif all(_NUMBER.match(line) for line in lines):
            blocks.append(Block("ol", items=[
                parse_inline(_NUMBER.sub("", line)) for line in lines]))
        else:
            blocks.append(Block("paragraph", parse_inline(joined)))
    return blocks


# ── inline ──────────────────────────────────────────────────────

def _skip(s: str, i: int) -> int:
    """From ``s[i]``, past one atom that may not be split: escape, code, math."""
    c = s[i]
    if c == "\\" and i + 1 < len(s):
        return i + 2
    if c == "`":
        end = s.find("`", i + 1)
        return end + 1 if end > 0 else i + 1
    if c == "$":
        if s.startswith("$$", i):
            end = s.find("$$", i + 2)
            return end + 2 if end > 0 else i + 2
        end = _math_end(s, i + 1)
        return end + 1 if end > 0 else i + 1
    if s.startswith("{{", i):
        end = s.find("}}", i + 2)
        return end + 2 if end > 0 else i + 2
    return i + 1


def _math_end(s: str, i: int) -> int:
    """The closing ``$`` of inline math opened before ``i``, or -1."""
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "$":
            return i
        i += 1
    return -1


def _find(s: str, i: int, delim: str) -> int:
    """The next unescaped ``delim`` at or after ``i``, skipping atoms."""
    while i < len(s):
        if s.startswith(delim, i):
            # A single * must not be half of a **.
            if delim == "*" and s.startswith("**", i):
                i += 2
                continue
            return i
        i = _skip(s, i)
    return -1


def parse_inline(s: str) -> list[Node]:
    nodes: list[Node] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            nodes.append(Node("text", "".join(buf)))
            buf.clear()

    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in PUNCTUATION:
            buf.append(s[i + 1])
            i += 2
            continue
        if s.startswith("{{", i):
            end = s.find("}}", i + 2)
            if end > 0:
                flush()
                nodes.append(Node("interp", s[i + 2:end].strip()))
                i = end + 2
                continue
        if s.startswith("$$", i):
            end = s.find("$$", i + 2)
            if end > 0:
                flush()
                nodes.append(Node("math", s[i + 2:end].strip(), display=True))
                i = end + 2
                continue
        if c == "$":
            end = _math_end(s, i + 1)
            if end > i + 1:
                flush()
                nodes.append(Node("math", s[i + 1:end]))
                i = end + 1
                continue
        if c == "`":
            end = s.find("`", i + 1)
            if end > 0:
                flush()
                nodes.append(Node("code", s[i + 1:end]))
                i = end + 1
                continue
        if s.startswith("**", i):
            end = _find(s, i + 2, "**")
            if end > i + 2:
                flush()
                nodes.append(Node("bold", children=parse_inline(s[i + 2:end])))
                i = end + 2
                continue
        if c == "*":
            end = _find(s, i + 1, "*")
            if end > i + 1:
                flush()
                nodes.append(Node("italic",
                                  children=parse_inline(s[i + 1:end])))
                i = end + 1
                continue
        if s.startswith("<u>", i):
            end = _find(s, i + 3, "</u>")
            if end > 0:
                flush()
                nodes.append(Node("underline",
                                  children=parse_inline(s[i + 3:end])))
                i = end + 4
                continue
        if c == "[":
            m = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)").match(s, i)
            if m:
                flush()
                nodes.append(Node("link", children=parse_inline(m.group(1)),
                                  url=m.group(2)))
                i = m.end()
                continue
        buf.append(c)
        i += 1
    flush()
    return nodes


def escape_markdown(text: str) -> str:
    """Plain text made literal in this dialect (for imported prose)."""
    text = text.replace("\\", "\\\\")
    for ch in "*$`[":
        text = text.replace(ch, "\\" + ch)
    return text.replace("{{", "{\\{").replace("<u>", "\\<u>")


def plain_text(nodes: list[Node]) -> str:
    """The text with markup dropped — for titles and headings."""
    out = []
    for n in nodes:
        if n.kind in ("text", "code"):
            out.append(n.text)
        elif n.kind == "math":
            out.append(n.text)
        elif n.kind == "interp":
            out.append("{{" + n.text + "}}")
        else:
            out.append(plain_text(n.children))
    return "".join(out)


# ──────────────────────────────────────────────────────────────
#  Placeholder values
# ──────────────────────────────────────────────────────────────

Evaluator = Callable[[str], Any]


def resolve(expr: str, evaluate: Evaluator | None) -> Node:
    """
    One ``{{expr}}``, evaluated: a text node — or a math node for a transfer
    function, which reads far better as a fraction than as ASCII art. A
    failure shows in place, marked, rather than stopping the render.
    """
    from .document import format_value
    if evaluate is None:
        return Node("text", "{{" + expr + "}}")
    try:
        value = evaluate(expr)
    except Exception as exc:                               # noqa: BLE001
        message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return Node("code", f"{{{{{expr}}}}}: {message}")
    latex = value_latex(value)
    if latex is not None:
        return Node("math", latex)
    return Node("text", format_value(value))


def value_latex(value: Any) -> str | None:
    """A SISO transfer function as ``\\frac{num}{den}``; None for others."""
    try:
        import control as ctl
    except ImportError:                                    # pragma: no cover
        return None
    if not isinstance(value, ctl.TransferFunction):
        return None
    if value.ninputs != 1 or value.noutputs != 1:
        return None
    var = "z" if value.dt else "s"
    num = _poly_latex(value.num[0][0], var)
    den = _poly_latex(value.den[0][0], var)
    return num if den == "1" else rf"\frac{{{num}}}{{{den}}}"


def _poly_latex(coefs, var: str) -> str:
    from .document import format_value
    coefs = [float(c) for c in coefs]
    while len(coefs) > 1 and coefs[0] == 0:
        coefs.pop(0)
    terms = []
    order = len(coefs) - 1
    for k, c in enumerate(coefs):
        power = order - k
        if c == 0:
            continue
        magnitude = format_value(abs(c))
        if power and magnitude == "1":
            magnitude = ""
        x = "" if power == 0 else var if power == 1 else f"{var}^{{{power}}}"
        sign = "-" if c < 0 else "+"
        terms.append((sign, f"{magnitude}{' ' if magnitude and x else ''}{x}"))
    if not terms:
        return "0"
    text = ("-" if terms[0][0] == "-" else "") + terms[0][1]
    for sign, body in terms[1:]:
        text += f" {sign} {body}"
    return text


# ──────────────────────────────────────────────────────────────
#  HTML
# ──────────────────────────────────────────────────────────────

#: (latex, display) → an <img> tag, or None to show the source instead.
MathImage = Callable[[str, bool], str | None]


def to_html(source: str, *, evaluate: Evaluator | None = None,
            math_image: MathImage | None = None) -> str:
    """A text cell's prose as HTML. Math goes through ``math_image``."""
    out = []
    for block in parse_blocks(source):
        if block.kind == "math":
            out.append(f'<p align="center">'
                       f'{_math_html(block.math, True, math_image)}</p>')
        elif block.kind in ("ul", "ol"):
            items = "".join(
                f"<li>{_inline_html(item, evaluate, math_image)}</li>"
                for item in block.items)
            out.append(f"<{block.kind}>{items}</{block.kind}>")
        else:
            out.append(f"<p>{_inline_html(block.nodes, evaluate, math_image)}"
                       f"</p>")
    return "\n".join(out)


def inline_html(source: str, *, evaluate: Evaluator | None = None,
                math_image: MathImage | None = None) -> str:
    """One line of markup (a heading) as HTML, without a <p>."""
    return _inline_html(parse_inline(source.replace("\n", " ")), evaluate,
                        math_image)


def _math_html(latex: str, display: bool, math_image: MathImage | None) -> str:
    tag = math_image(latex, display) if math_image else None
    if tag:
        return tag
    delim = "$$" if display else "$"
    return f"<code>{html.escape(delim + latex + delim)}</code>"


def _inline_html(nodes: list[Node], evaluate, math_image) -> str:
    out = []
    for n in nodes:
        if n.kind == "interp":
            n = resolve(n.text, evaluate)
        if n.kind == "text":
            out.append(html.escape(n.text).replace("\n", "<br>"))
        elif n.kind == "code":
            out.append(f"<code>{html.escape(n.text)}</code>")
        elif n.kind == "math":
            out.append(_math_html(n.text, n.display, math_image))
        elif n.kind == "link":
            out.append(f'<a href="{html.escape(n.url, quote=True)}">'
                       f"{_inline_html(n.children, evaluate, math_image)}</a>")
        else:
            tag = {"bold": "b", "italic": "i", "underline": "u"}[n.kind]
            out.append(f"<{tag}>{_inline_html(n.children, evaluate, math_image)}"
                       f"</{tag}>")
    return "".join(out)


# ──────────────────────────────────────────────────────────────
#  LaTeX
# ──────────────────────────────────────────────────────────────

_TEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def escape_tex(text: str) -> str:
    return "".join(_TEX_ESCAPES.get(c, c) for c in text)


def to_latex(source: str, *, evaluate: Evaluator | None = None) -> str:
    """A text cell's prose as LaTeX; math is passed through untouched."""
    out = []
    for block in parse_blocks(source):
        if block.kind == "math":
            out.append(f"\\[\n{block.math}\n\\]")
        elif block.kind in ("ul", "ol"):
            env = "itemize" if block.kind == "ul" else "enumerate"
            items = "\n".join(f"  \\item {_inline_tex(item, evaluate)}"
                              for item in block.items)
            out.append(f"\\begin{{{env}}}\n{items}\n\\end{{{env}}}")
        else:
            out.append(_inline_tex(block.nodes, evaluate))
    return "\n\n".join(out)


def inline_latex(source: str, *, evaluate: Evaluator | None = None) -> str:
    return _inline_tex(parse_inline(source.replace("\n", " ")), evaluate)


def _inline_tex(nodes: list[Node], evaluate) -> str:
    out = []
    for n in nodes:
        if n.kind == "interp":
            n = resolve(n.text, evaluate)
        if n.kind == "text":
            out.append(escape_tex(n.text))
        elif n.kind == "code":
            out.append(f"\\texttt{{{escape_tex(n.text)}}}")
        elif n.kind == "math":
            out.append(f"\\[{n.text}\\]" if n.display else f"${n.text}$")
        elif n.kind == "link":
            url = n.url.replace("%", r"\%").replace("#", r"\#")
            out.append(f"\\href{{{url}}}{{{_inline_tex(n.children, evaluate)}}}")
        else:
            command = {"bold": "textbf", "italic": "emph",
                       "underline": "underline"}[n.kind]
            out.append(f"\\{command}{{{_inline_tex(n.children, evaluate)}}}")
    return "".join(out)
