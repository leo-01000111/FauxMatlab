"""
The REPL engine.
================
Executes a line (or a block) against a persistent namespace and reports what
happened: printed output, the value of a trailing expression, or a traceback.

Deliberately separate from any widget, so the same engine runs the console,
the script editor and the tests.

MATLAB habits that are tolerated
--------------------------------
* ``%`` as a comment — rewritten to ``#`` when the line is not valid Python.
* A trailing ``;`` — stripped, and taken to mean "do not echo the value",
  exactly as MATLAB uses it.
* ``ans`` — bound to the last unassigned result.

Habits that are **not** silently accepted are the ones where guessing would
change the meaning: ``[1 2 3]`` without commas, ``^`` for powers, ``end`` in
an index. Each produces a message saying what to write instead. Quietly
rewriting those would make the console a dialect that works until it doesn't.
"""

from __future__ import annotations

import ast
import io
import re
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import Any

from .api import build_namespace, command_names


@dataclass
class Result:
    """What one execution produced."""
    source:    str
    output:    str = ""
    value:     Any = None
    has_value: bool = False
    error:     str = ""
    hint:      str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def display(self) -> str:
        """Everything to show, in the order a console shows it."""
        parts = []
        if self.output:
            parts.append(self.output.rstrip("\n"))
        if self.has_value and self.value is not None:
            parts.append(format_value(self.value))
        if self.error:
            parts.append(self.error.rstrip("\n"))
        if self.hint:
            parts.append(self.hint)
        return "\n".join(p for p in parts if p)


class Interpreter:
    """A persistent Python session with the MATLAB vocabulary loaded."""

    def __init__(self, extra: dict[str, Any] | None = None) -> None:
        self.namespace = build_namespace(extra)
        self._commands = command_names()
        self.history: list[str] = []

    # ── execution ───────────────────────────────────────────────

    def run(self, source: str) -> Result:
        """Execute one statement or block."""
        source = source.rstrip()
        if not source.strip():
            return Result(source)
        self.history.append(source)

        prepared, echo = self._prepare(source)
        result = Result(source)

        try:
            tree = ast.parse(prepared, mode="exec")
        except SyntaxError as exc:
            result.error = f"SyntaxError: {exc.msg}"
            result.hint = _syntax_hint(source, exc)
            return result

        # A trailing bare expression is evaluated separately so its value can
        # be echoed and bound to `ans`, the way a REPL does.
        body, tail = tree.body, None
        if body and isinstance(body[-1], ast.Expr):
            tail = body.pop()

        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                if body:
                    exec(compile(ast.Module(body, []), "<console>", "exec"),
                         self.namespace)
                if tail is not None:
                    value = eval(
                        compile(ast.Expression(tail.value), "<console>",
                                "eval"),
                        self.namespace)
                    if value is not None:
                        self.namespace["ans"] = value
                    result.value = value
                    result.has_value = echo
        except SystemExit:
            raise
        except BaseException as exc:                        # noqa: BLE001
            result.output = buffer.getvalue()
            result.error = _format_exception(exc)
            result.hint = _runtime_hint(exc, self.namespace)
            return result

        result.output = buffer.getvalue()
        return result

    def run_script(self, source: str) -> list[Result]:
        """
        Run a whole script, one top-level statement at a time.

        Statement by statement rather than in one block so that output appears
        in order and a failure reports *which* line stopped it — running the
        file as a single exec gives one traceback and no partial results.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            result = Result(source, error=f"SyntaxError: {exc.msg}",
                            hint=_syntax_hint(source, exc))
            return [result]

        lines = source.splitlines()
        results: list[Result] = []
        for node in tree.body:
            end = getattr(node, "end_lineno", node.lineno)
            chunk = "\n".join(lines[node.lineno - 1:end])
            outcome = self.run(chunk)
            results.append(outcome)
            if outcome.error:
                break
        return results

    # ── namespace ───────────────────────────────────────────────

    def variables(self) -> dict[str, Any]:
        """User variables — the commands and modules are filtered out."""
        return {
            name: value for name, value in self.namespace.items()
            if not name.startswith("_")
            and name not in self._commands
            and not _is_module(value)
        }

    def clear(self, *names: str) -> None:
        """``clear()`` empties the workspace; ``clear('G')`` removes one."""
        if names:
            for name in names:
                self.namespace.pop(name, None)
            return
        for name in list(self.variables()):
            self.namespace.pop(name, None)

    def completions(self, prefix: str) -> list[str]:
        """Names starting with ``prefix``, commands last."""
        if "." in prefix:
            head, _, tail = prefix.rpartition(".")
            try:
                obj = eval(head, self.namespace)          # noqa: S307
            except Exception:                              # noqa: BLE001
                return []
            return sorted(f"{head}.{a}" for a in dir(obj)
                          if a.startswith(tail) and not a.startswith("_"))
        user = sorted(n for n in self.variables() if n.startswith(prefix))
        commands = sorted(n for n in self._commands if n.startswith(prefix))
        return user + [c for c in commands if c not in user]

    # ── input munging ───────────────────────────────────────────

    def _prepare(self, source: str) -> tuple[str, bool]:
        """
        Apply the two safe MATLAB accommodations.

        Both are unambiguous: a trailing semicolon cannot mean anything else
        in Python, and ``%`` is only rewritten when the text does not already
        parse — so a modulo expression is left alone.
        """
        echo = True
        stripped = source.rstrip()
        if stripped.endswith(";"):
            source, echo = stripped[:-1], False

        if "%" in source and not _parses(source):
            candidate = re.sub(r"(?<![%\w'\"])%(?!\s*[)\]}])", "#", source)
            if _parses(candidate):
                source = candidate
        return source, echo


# ──────────────────────────────────────────────────────────────
#  Formatting and diagnostics
# ──────────────────────────────────────────────────────────────

def format_value(value: Any) -> str:
    """How a result is echoed."""
    import numpy as np

    if isinstance(value, np.ndarray):
        return np.array2string(value, precision=5, suppress_small=True)
    if isinstance(value, dict) and value and all(
            isinstance(k, str) for k in value):
        width = max(len(k) for k in value)
        return "\n".join(f"  {k:<{width}} : {_short(v)}"
                         for k, v in value.items())
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _short(value: Any) -> str:
    import numpy as np

    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, np.ndarray):
        return np.array2string(value, precision=4, suppress_small=True)
    return str(value)


def _format_exception(exc: BaseException) -> str:
    lines = traceback.format_exception_only(type(exc), exc)
    return "".join(lines).strip()


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


#: MATLAB spellings that are *not* rewritten, with what to write instead.
#: Guessing at these would change meaning, so the console explains rather
#: than translates.
_SYNTAX_HINTS = (
    (re.compile(r"\[\s*[-+.\d]+(\s+[-+.\d]+)+\s*\]"),
     "In Python a list needs commas: write [1, 2, 3] rather than [1 2 3]."),
    (re.compile(r"\w\s*\^\s*\w"),
     "Python uses ** for powers: s**2, not s^2. (^ is bitwise XOR here.)"),
    (re.compile(r"\bend\b\s*\]"),
     "Python has no 'end' in an index; use [-1] for the last element."),
    (re.compile(r"^\s*(function|endfunction)\b"),
     "Define a function with 'def name(args):' and an indented body."),
    (re.compile(r"~="),
     "Python writes 'not equal' as !=."),
)


def _syntax_hint(source: str, exc: SyntaxError) -> str:
    for pattern, message in _SYNTAX_HINTS:
        if pattern.search(source):
            return "  → " + message
    return ""


def _runtime_hint(exc: BaseException, namespace: dict[str, Any]) -> str:
    """Point at the likely fix for the mistakes this console invites."""
    if isinstance(exc, NameError):
        missing = re.search(r"name '([^']+)'", str(exc))
        if missing:
            name = missing.group(1)
            close = [n for n in namespace
                     if n.lower() == name.lower() and n != name]
            if close:
                return f"  → did you mean '{close[0]}'? Names are case-sensitive."
            return (f"  → '{name}' is not defined. help_fm() lists the "
                    f"available commands.")
    if isinstance(exc, TypeError):
        message = str(exc)
        if "not callable" in message:
            return ("  → Python indexes with [] and calls with (); "
                    "x[0], not x(0).")
        if "^" in message:
            # ``s^2`` is *valid* Python — bitwise XOR — so it fails at run
            # time, not parse time, and the syntax hints never see it.
            return "  → Python uses ** for powers: s**2, not s^2."
    return ""


def _is_module(value: Any) -> bool:
    import types
    return isinstance(value, types.ModuleType)
