"""
How the model is asked, and how its answer is read back.

Two kinds of proposal, each in its own fenced block so plain text, a
streamed half-reply and a model that ignores the format all degrade to
ordinary prose:

````text
```evans-edit
…the full replacement for the code that was sent…
```

```evans-run
…one console command…
```
````

An edit is a *replacement* of the code that was sent, not a diff. Small free
models write broken unified diffs (wrong line counts, missing context), but
copy a fifteen-line section back with one line changed reliably; the diff
the user reviews is computed here, by :func:`diff`. Since only the selection
or one section is ever sent, the replacement stays short.

The model never runs anything: an ``evans-run`` block is a proposal, which
runs only when the user presses Run.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .context import Context, render

#: Exchanges (a question and its answer) sent again for follow-ups.
HISTORY_EXCHANGES = 2

#: Code blocks in remembered answers are cut to this many lines: the model
#: needs to know what it proposed, not to read it all again.
HISTORY_CODE_LINES = 6

SYSTEM_PROMPT = """\
You are the coding assistant inside Evans, a MATLAB-like control-engineering \
workbench. Users write Python (numpy, scipy, python-control, with MATLAB-style \
commands such as tf, ss, step, bode, feedback) or MATLAB code.

You see only what the user sends: possibly a piece of code, the workspace \
variables by name, type and size (never their values), and the last error. \
Do not ask for the whole script.

Be brief. Explain in a few sentences, then propose.

To change the code that was sent, reply with ONE block:
```evans-edit
<the complete replacement for exactly the code that was sent>
```
It replaces that code entirely, so include the lines you keep, unchanged, \
and nothing outside it. Never propose an edit when no code was sent, or when \
the code was cut short.

To suggest a console command, use one block per command:
```evans-run
<one command>
```
The user decides whether to run it.

Use ordinary ```python or ```matlab blocks for examples that are neither."""


# ── the reply ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Edit:
    """A proposed replacement for the code that was sent."""
    code: str


@dataclass(frozen=True)
class Command:
    """A proposed console command; it runs only if the user says so."""
    code: str


Part = Text | Edit | Command

_FENCE = re.compile(r"^```[ \t]*(evans-edit|evans-run)[ \t]*\n(.*?)^```[ \t]*$",
                    re.MULTILINE | re.DOTALL)


def parse(reply: str) -> list[Part]:
    """
    The reply as prose, edits and commands, in order.

    Only closed ``evans-*`` blocks count; anything else, including an
    unclosed block from a reply that was cut off, stays text.
    """
    parts: list[Part] = []
    at = 0
    for match in _FENCE.finditer(reply):
        before = reply[at:match.start()].strip()
        if before:
            parts.append(Text(before))
        body = match.group(2)
        if body.endswith("\n"):
            body = body[:-1]
        if match.group(1) == "evans-edit":
            parts.append(Edit(body))
        elif body.strip():
            parts.append(Command(body.strip()))
        at = match.end()
    rest = reply[at:].strip()
    if rest:
        parts.append(Text(rest))
    return parts


def diff(original: str, replacement: str, *, label: str = "code") -> list[str]:
    """A unified diff of an edit, as lines without their newlines."""
    return list(difflib.unified_diff(
        original.split("\n"), replacement.split("\n"),
        fromfile=f"{label} (now)", tofile=f"{label} (proposed)",
        lineterm="", n=2))


def apply_edit(document: str, context: Context, edit: Edit) -> str:
    """
    ``document`` with the edit applied to the region it was proposed for.

    Raises :class:`StaleEdit` when that region no longer holds what was
    sent (the user typed in the meantime), or when the context had no
    editable region.
    """
    region = context.region
    if region is None or context.truncated:
        raise StaleEdit("This reply was not about a piece of code that can "
                        "be replaced.")
    if document[region.start:region.end] != region.text:
        raise StaleEdit("The code changed since the question was asked — "
                        "ask again to get an edit for the current code.")
    return document[:region.start] + edit.code + document[region.end:]


class StaleEdit(Exception):
    """An edit that no longer fits the document."""


# ── the request ────────────────────────────────────────────────────

@dataclass
class History:
    """
    The last few exchanges, for follow-up questions.

    Only the question as typed and the answer are kept — not the context
    that went with the question, which would be paid for again with every
    request. The newest context always goes with the newest question.
    """
    exchanges: list[tuple[str, str]] = field(default_factory=list)
    keep: int = HISTORY_EXCHANGES

    def add(self, question: str, answer: str) -> None:
        self.exchanges.append((question, answer))
        self.exchanges[:] = self.exchanges[-self.keep:] if self.keep else []

    def clear(self) -> None:
        self.exchanges.clear()

    def messages(self) -> list[dict[str, str]]:
        out = []
        for question, answer in self.exchanges:
            out.append({"role": "user", "content": question})
            out.append({"role": "assistant", "content": shorten_code(answer)})
        return out


_ANY_FENCE = re.compile(r"^(```[^\n]*\n)(.*?)(^```[ \t]*$)",
                        re.MULTILINE | re.DOTALL)


def shorten_code(text: str, keep: int = HISTORY_CODE_LINES) -> str:
    """Code blocks in ``text`` cut to their first ``keep`` lines."""
    def cut(match: re.Match) -> str:
        lines = match.group(2).split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if len(lines) <= keep:
            return match.group(0)
        hidden = len(lines) - keep
        body = "\n".join(lines[:keep]) + f"\n… ({hidden} more lines)\n"
        return match.group(1) + body + match.group(3)
    return _ANY_FENCE.sub(cut, text)


def messages(context: Context, question: str,
             history: History | None = None) -> list[dict[str, str]]:
    """The whole request: instructions, recent exchanges, context, question."""
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history is not None:
        out.extend(history.messages())
    out.append({"role": "user",
                "content": f"{render(context)}\n\n{question.strip()}"})
    return out
