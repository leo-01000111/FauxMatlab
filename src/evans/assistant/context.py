"""
What one request may carry, and nothing more.

Each request costs tokens and leaves the machine, so the context is narrow
by rule, not by habit:

* **the code at hand** — the selection, else the ``%%`` section around the
  cursor, else the cursor's line. Never the whole script. A live-script cell
  and the console's prompt line are sent whole: each is already one unit.
* **console output the user picked** — a selection in the transcript, with
  whatever error it shows; context only, never edited.
* **the workspace** — each variable's name, type and size. Never a value:
  a matrix of measured data, or a gain someone has not published, stays in
  Evans. :func:`describe` only ever looks at shape, order and length.
* **the last error** — the message the console printed, trimmed.

Everything is capped (:data:`MAX_CODE_CHARS` and friends), so even a huge
selection costs a bounded number of tokens.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: Caps, in characters (about four to a token).
MAX_CODE_CHARS = 6000
MAX_ERROR_CHARS = 1200
MAX_ATTACHMENT_CHARS = 4000
MAX_VARIABLES = 40

#: A cell divider: ``%%`` in MATLAB, ``# %%`` in Python. The same rule as
#: the editor's highlighter, so the section sent is the one the user sees.
SECTION = re.compile(r"^\s*(%%|#\s*%%)(?=\s|$)")


@dataclass(frozen=True)
class Variable:
    name: str
    type: str
    size: str


@dataclass(frozen=True)
class Region:
    """
    Where the code at hand sits in its document: characters ``start`` to
    ``end``, which held ``text`` when the request was made. An edit is only
    applied if they still do.
    """
    start: int
    end: int
    text: str


@dataclass
class Context:
    """One request's worth of context."""
    #: ``"console"``, ``"script"`` or ``"live"``.
    where: str
    #: ``"python"`` or ``"matlab"``.
    language: str = "python"
    #: The code at hand, or ``""`` (the console with nothing selected).
    code: str = ""
    #: What ``code`` is: ``"selection"``, ``"section"``, ``"line"``,
    #: ``"cell"`` (a live-script cell), ``"prompt"`` (the console's input
    #: line, typed but not run), ``"failed"`` (what raised the last error)
    #: or ``""``.
    origin: str = ""
    region: Region | None = None
    variables: list[Variable] = field(default_factory=list)
    #: How many variables there were before :data:`MAX_VARIABLES` cut in.
    variable_count: int = 0
    last_error: str = ""
    #: Console output the user selected and asked about; never edited.
    attachment: str = ""
    #: The code was longer than :data:`MAX_CODE_CHARS` and was cut, so an
    #: edit proposed for it cannot be applied.
    truncated: bool = False

    def summary(self) -> str:
        """What goes with the question, in a few words, for the panel."""
        parts = []
        if self.code:
            lines = self.code.count("\n") + 1
            what = {"prompt": "prompt line",
                    "failed": "failed code"}.get(self.origin, self.origin)
            parts.append(f"{what} ({lines} line{'s' if lines != 1 else ''}"
                         f"{', cut' if self.truncated else ''})")
        if self.attachment:
            lines = self.attachment.count("\n") + 1
            parts.append(f"console output ({lines} line{'s' if lines != 1 else ''})")
        if self.variable_count:
            parts.append(f"{self.variable_count} variable name"
                         f"{'s' if self.variable_count != 1 else ''}")
        if self.last_error:
            parts.append("last error")
        return ", ".join(parts) if parts else "no code or workspace"

    @property
    def editable(self) -> bool:
        return self.region is not None and not self.truncated


# ── the code at hand ──────────────────────────────────────────────

def code_at(text: str, cursor: int, sel_start: int | None = None,
            sel_end: int | None = None) -> tuple[str, Region]:
    """
    The code to send from a document, and where it sits.

    A non-empty selection wins. Otherwise the ``%%`` section holding the
    cursor, if the document has dividers; otherwise the cursor's line. The
    region covers the section's body, so the divider line itself (and its
    title) is never rewritten by an edit.
    """
    if sel_start is not None and sel_end is not None and sel_start != sel_end:
        a, b = sorted((sel_start, sel_end))
        return "selection", Region(a, b, text[a:b])

    starts = _line_starts(text)
    row = max(i for i, s in enumerate(starts) if s <= cursor) if starts else 0
    lines = text.split("\n")
    dividers = [i for i, line in enumerate(lines) if SECTION.match(line)]
    if dividers:
        above = [d for d in dividers if d <= row]
        below = [d for d in dividers if d > row]
        first = above[-1] + 1 if above else 0
        last = below[0] if below else len(lines)      # exclusive
        if first < last:
            a = starts[first]
            b = starts[last] - 1 if last < len(lines) else len(text)
            return "section", Region(a, b, text[a:b])
    a = starts[row]
    b = a + len(lines[row])
    return "line", Region(a, b, text[a:b])


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


# ── the workspace, without values ─────────────────────────────────

def describe(value: Any) -> tuple[str, str]:
    """
    A value's type and size, read from its structure only.

    Sizes are dimensions, orders and lengths; nothing returned here depends
    on what the numbers are. A transfer function's poles, a scalar's value
    or a string's contents never appear.
    """
    kind = type(value).__name__
    if _has(value, "num", "den") and _has(value, "ninputs", "noutputs"):
        order = _order(value)
        dt = " discrete" if getattr(value, "dt", 0) else ""
        return f"tf{dt}", f"{value.noutputs}×{value.ninputs}, order {order}"
    if _has(value, "A", "B", "C", "D") and _has(value, "ninputs", "noutputs"):
        dt = " discrete" if getattr(value, "dt", 0) else ""
        states = getattr(value, "nstates", "?")
        return f"ss{dt}", f"{value.noutputs}×{value.ninputs}, {states} states"
    shape = getattr(value, "shape", None)
    if isinstance(shape, tuple) and hasattr(value, "dtype"):
        dims = "×".join(str(d) for d in shape) if shape else "scalar"
        return f"array {value.dtype}", dims
    if isinstance(value, bool | int | float | complex):
        return kind, "scalar"
    if isinstance(value, str | bytes):
        return kind, f"{len(value)} chars"
    if isinstance(value, Mapping):
        return kind, f"{len(value)} keys"
    if isinstance(value, list | tuple | set | frozenset):
        return kind, f"{len(value)} items"
    if callable(value):
        return "function", "—"
    return kind, "—"


def _has(value: Any, *names: str) -> bool:
    return all(hasattr(value, n) for n in names)


def _order(sys: Any) -> int | str:
    try:
        den = sys.den[0][0]
        return max(len(den) - 1, 0)
    except (TypeError, IndexError, AttributeError):
        return "?"


def workspace(variables: Mapping[str, Any]) -> tuple[list[Variable], int]:
    """The described variables (``ans`` last, at most :data:`MAX_VARIABLES`)
    and how many there were in all."""
    names = sorted(variables, key=lambda n: (n == "ans", n.lower()))
    described = []
    for name in names[:MAX_VARIABLES]:
        try:
            kind, size = describe(variables[name])
        except Exception:                                  # noqa: BLE001
            kind, size = type(variables[name]).__name__, "—"
        described.append(Variable(name, kind, size))
    return described, len(names)


# ── putting it together ───────────────────────────────────────────

def build(where: str, *, language: str = "python", text: str = "",
          cursor: int = 0, sel_start: int | None = None,
          sel_end: int | None = None, variables: Mapping[str, Any] | None = None,
          last_error: str = "", whole: str | None = None,
          attachment: str = "") -> Context:
    """
    The context for one request from an editor or the console.

    ``text`` is the document; only the part :func:`code_at` picks out is
    kept. With ``whole`` (``"cell"``, ``"prompt"``) the whole text is the
    unit instead, unless something in it is selected.
    """
    origin, region = ("", None)
    code = ""
    selected = sel_start is not None and sel_end is not None \
        and sel_start != sel_end
    if whole and not selected:
        if text.strip():
            origin, region = whole, Region(0, len(text), text)
    elif text.strip():
        origin, region = code_at(text, cursor, sel_start, sel_end)
    if region is not None:
        code = region.text
        if not code.strip():
            origin, region, code = "", None, ""
    truncated = len(code) > MAX_CODE_CHARS
    if truncated:
        code = code[:MAX_CODE_CHARS]
    described, count = workspace(variables or {})
    error = last_error.strip()
    if len(error) > MAX_ERROR_CHARS:
        error = "…" + error[-MAX_ERROR_CHARS:]       # the end says what broke
    attachment = attachment.strip("\n")
    if len(attachment) > MAX_ATTACHMENT_CHARS:
        attachment = "…" + attachment[-MAX_ATTACHMENT_CHARS:]
    return Context(where=where, language=language, code=code, origin=origin,
                   region=region, variables=described, variable_count=count,
                   last_error=error, attachment=attachment,
                   truncated=truncated)


def render(context: Context) -> str:
    """The context as the text block that precedes the question."""
    place = {"console": "the console", "script": "a script",
             "live": "a live script"}.get(context.where, context.where)
    out = [f"[Evans: {place}, {context.language}]"]
    if context.code:
        what = {"selection": "Selected code", "section": "Current %% section",
                "line": "Current line", "cell": "Current live-script cell",
                "prompt": "Typed at the console prompt, not run yet "
                          "(one line: an edit must stay on one line)",
                "failed": "The code that failed (an edit replaces it; "
                          "in the console, keep it to one line)",
                }.get(context.origin, "Code")
        cut = " (cut short; do not propose an edit)" if context.truncated else ""
        out.append(f"{what}{cut}:\n```{context.language}\n{context.code}\n```")
    if context.attachment:
        out.append("Console output the user selected (do not edit it):\n"
                   f"```text\n{context.attachment}\n```")
    if context.variables:
        rows = [f"{v.name}: {v.type}, {v.size}" for v in context.variables]
        more = context.variable_count - len(context.variables)
        if more > 0:
            rows.append(f"… and {more} more")
        out.append("Workspace (names, types, sizes only):\n" + "\n".join(rows))
    if context.last_error:
        out.append(f"Last error:\n{context.last_error}")
    return "\n\n".join(out)
