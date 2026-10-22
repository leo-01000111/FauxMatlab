"""
The REPL engine.
================
Executes a line (or a block) against a persistent namespace and reports what
happened: printed output, the value of a trailing expression, or a traceback.

Deliberately separate from any widget, so the same engine runs the console,
the script editor and the tests.

The prompt speaks MATLAB: :meth:`Interpreter.command` translates what is
typed, as the Script tab translates a script. Python still runs — a line only
Python means or only Python can read goes to :meth:`Interpreter.run`, which
is plain Python with two MATLAB habits tolerated:

* ``%`` as a comment — rewritten to ``#`` when the line is not valid Python.
* A trailing ``;`` — stripped, and taken to mean "do not echo the value",
  exactly as MATLAB uses it.

``ans`` is bound to the last unassigned result either way.
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
from .figures import set_figure_sink
from .tracer import Interrupted, Tracer, write_back


@dataclass
class Result:
    """What one execution produced."""
    source:    str
    output:    str = ""
    value:     Any = None
    has_value: bool = False
    error:     str = ""
    hint:      str = ""
    #: The line of the script (or command) an error or interrupt names.
    line:      int | None = None

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
        #: The presets, by identity — a MATLAB script may reuse their names.
        self._presets = dict(self.namespace)
        self._commands = command_names()
        self.history: list[str] = []
        #: Set by the UI: what ``close all`` in a MATLAB script calls.
        self.close_figures = None
        #: Set by the UI: the folder of the script being run. A MATLAB script
        #: finds its function files (``name.m``) and data files there.
        self.script_folder: str | None = None
        self._matlab = None
        #: Stops and pauses what runs; see :mod:`.tracer`.
        self.tracer = Tracer()
        #: Output of the statement now running, so far (see drain_output).
        self._buffers: list[io.StringIO] = []

    # ── execution ───────────────────────────────────────────────

    def run(self, source: str, *, first_line: int = 1,
            filename: str = "<console>", debuggable: bool = False) -> Result:
        """
        Execute one statement or block.

        ``first_line`` is where ``source`` starts in a script, so line
        numbers (errors, interrupts, breakpoints) are the script's own.
        While the debugger is paused, it runs in the paused frame's scope.
        """
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
            if exc.lineno:
                result.line = exc.lineno + first_line - 1
            return result
        if first_line > 1:
            ast.increment_lineno(tree, first_line - 1)

        # A trailing bare expression is evaluated separately so its value can
        # be echoed and bound to `ans`, the way a REPL does.
        body, tail = tree.body, None
        if body and isinstance(body[-1], ast.Expr):
            tail = body.pop()

        paused = self.tracer.paused
        glob = paused.frame.f_globals if paused else self.namespace
        loc = paused.scope if paused else glob
        # Decided now: reading f_locals again would refresh it from the
        # frame and lose what the command assigned before it is written back.
        in_function = loc is not glob
        buffer = io.StringIO()
        self._buffers.append(buffer)
        try:
            with self.tracer.active(self.namespace), \
                    redirect_stdout(buffer), redirect_stderr(buffer):
                if body:
                    code = compile(ast.Module(body, []), filename, "exec")
                    self.tracer.watch(code, debuggable=debuggable)
                    exec(code, glob, loc)
                if tail is not None:
                    code = compile(ast.Expression(tail.value), filename,
                                   "eval")
                    self.tracer.watch(code, debuggable=debuggable)
                    value = eval(code, glob, loc)
                    if value is not None:
                        loc["ans"] = value
                    result.value = value
                    result.has_value = echo
        except SystemExit:
            raise
        except Interrupted as exc:
            result.output = buffer.getvalue()
            result.error = str(exc)
            result.line = exc.line if exc.file is None else None
            return result
        except BaseException as exc:                        # noqa: BLE001
            result.output = buffer.getvalue()
            result.error = _format_exception(exc)
            result.hint = _runtime_hint(exc, self.namespace)
            result.line = _traceback_line(exc, filename)
            return result
        finally:
            self._buffers.remove(buffer)
            if in_function:
                write_back(paused.frame)

        result.output = buffer.getvalue()
        return result

    def command(self, source: str) -> Result:
        """
        Run what was typed at the prompt — MATLAB, as the Script tab runs it.

        Python still works: a line that is plainly Python (``import``,
        ``def``, ``**``), or that only Python can read (``x[0]``), runs as
        Python through :meth:`run`. What neither reads is reported in the
        language it looks like.
        """
        from .matlab import (
            MatlabSyntaxError,
            looks_like_matlab,
            plainly_python,
            translate,
        )
        source = source.rstrip()
        if not source.strip():
            return Result(source)
        if plainly_python(source):
            return self.run(source)
        try:
            chunks = translate(source)
        except MatlabSyntaxError as exc:
            if _parses(self._prepare(source)[0]) \
                    or not looks_like_matlab(source):
                return self.run(source)
            self.history.append(source)
            multi = "\n" in source
            return Result(source, error="Error: " + (str(exc) if multi
                                                     else exc.message),
                          line=exc.line)
        self.history.append(source)
        results: list[Result] = []
        with self.tracer.active(self.namespace):
            self._run_matlab(source, None, results.append, False,
                             chunks=chunks, prompt=True)
        merged = Result(source)
        merged.output = "".join(r.output for r in results)
        for r in results:
            if r.error:
                merged.error, merged.hint, merged.line = r.error, r.hint, \
                    r.line
        return merged

    def drain_output(self) -> str:
        """
        What the statement now running has printed so far, taken out of its
        result — so a pause can show it before the statement finishes.
        """
        if not self._buffers:
            return ""
        buffer = self._buffers[-1]
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return text

    def run_script(self, source: str, language: str = "auto",
                   folder: str | None = None, *, on_result=None,
                   debuggable: bool = False) -> list[Result]:
        """
        Run a whole script, one top-level statement at a time.

        ``language`` is ``"matlab"``, ``"python"`` or ``"auto"`` — which
        guesses from the text, so a pasted ``.m`` file just runs. ``folder``
        is the script's own folder (else :attr:`script_folder`, else the
        process's): a MATLAB script's current folder.

        Statement by statement rather than in one block so that output appears
        in order and a failure reports *which* line stopped it — running the
        file as a single exec gives one traceback and no partial results.

        ``on_result`` is called with each result as it is produced, so a long
        run shows its progress; ``debuggable`` lets the tracer's breakpoints
        apply (the script editor's runs, not the prompt's).
        """
        from .matlab import looks_like_matlab
        if language == "matlab" or (language == "auto"
                                    and looks_like_matlab(source)):
            return self.run_matlab(source, folder, on_result=on_result,
                                   debuggable=debuggable)
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            result = Result(source, error=f"SyntaxError: {exc.msg}",
                            hint=_syntax_hint(source, exc), line=exc.lineno)
            if on_result is not None:
                on_result(result)
            return [result]

        lines = source.splitlines()
        results: list[Result] = []
        with self.tracer.active(self.namespace):
            for node in tree.body:
                end = getattr(node, "end_lineno", node.lineno)
                chunk = "\n".join(lines[node.lineno - 1:end])
                outcome = self.run(chunk, first_line=node.lineno,
                                   filename="<script>", debuggable=debuggable)
                results.append(outcome)
                if on_result is not None:
                    on_result(outcome)
                if outcome.error:
                    break
        return results

    def run_matlab(self, source: str, folder: str | None = None, *,
                   on_result=None, debuggable: bool = False) -> list[Result]:
        """
        Translate a MATLAB script and run it, statement by statement.

        Figures are collected while it runs — so ``hold on``, ``title`` and
        ``legend`` can amend a plot already made — and drawn at the end, even
        if a statement fails part-way. Errors name the MATLAB line.
        """
        # One tracer session for the whole run, so a stop requested between
        # two statements still lands.
        with self.tracer.active(self.namespace):
            return self._run_matlab(source, folder, on_result, debuggable)

    def _run_matlab(self, source: str, folder: str | None, on_result,
                    debuggable: bool, *, chunks=None,
                    prompt: bool = False) -> list[Result]:
        """
        ``chunks`` is the translation when the caller has one already;
        ``prompt`` marks a typed command: it runs in the paused scope while
        the debugger holds one, and is already in the history.
        """
        from .matlab import MatlabSyntaxError, translate
        from .matlab_runtime import ScriptReturn

        try:
            if chunks is None:
                chunks = translate(source)
        except MatlabSyntaxError as exc:
            lines = source.splitlines()
            text = lines[exc.line - 1].strip() if 0 < exc.line <= len(
                lines) else ""
            result = Result(text or source,
                            error=f"Error: {exc.message} (line {exc.line})",
                            hint=f"  → line {exc.line}:  {text}" if text
                            else "", line=exc.line)
            if on_result is not None:
                on_result(result)
            return [result]

        runtime = self._matlab_runtime()
        runtime.begin(folder or self.script_folder)
        previous = set_figure_sink(lambda spec: runtime.figures.collect(spec))
        line_maps: dict[str, list[int]] = {}
        results: list[Result] = []
        paused = self.tracer.paused if prompt else None
        glob = paused.frame.f_globals if paused else self.namespace
        loc = paused.scope if paused else glob

        def done(result: Result) -> None:
            results.append(result)
            if on_result is not None:
                on_result(result)

        def where(line: int) -> str:
            # One typed line needs no line number; a script or block does.
            return "Error: " if prompt and "\n" not in source \
                else f"Error in line {line}: "

        try:
            for k, chunk in enumerate(chunks):
                filename = f"<matlab:{k}>"
                line_maps[filename] = chunk.lines
                result = Result(chunk.matlab)
                if not chunk.function and not prompt:
                    self.history.append(chunk.matlab)
                buffer = io.StringIO()
                self._buffers.append(buffer)
                try:
                    code = compile(chunk.python, filename, "exec")
                    self.tracer.watch(code, chunk.lines,
                                      debuggable=debuggable,
                                      quiet=chunk.function)
                    with self.tracer.active(self.namespace), \
                            redirect_stdout(buffer), redirect_stderr(buffer):
                        exec(code, glob, loc)
                except ScriptReturn:
                    result.output = buffer.getvalue()
                    done(result)
                    break
                except SystemExit:
                    raise
                except Interrupted as exc:
                    result.output = buffer.getvalue()
                    result.error = str(exc)
                    # A line of another file must not tint the script's.
                    result.line = exc.line if exc.file is None else None
                    done(result)
                    break
                except SyntaxError as exc:              # our bug, not theirs
                    result.output = buffer.getvalue()
                    result.error = (f"Error: this line could not be "
                                    f"translated ({exc.msg}).")
                    result.line = chunk.first
                    done(result)
                    break
                except BaseException as exc:            # noqa: BLE001
                    result.output = buffer.getvalue()
                    line = _matlab_line(exc, line_maps) or chunk.first
                    result.error = where(line) + _matlab_message(exc)
                    result.line = line
                    if not _is_matlab_error(exc):
                        result.hint = _runtime_hint(exc, self.namespace)
                    done(result)
                    break
                finally:
                    self._buffers.remove(buffer)
                    if paused is not None and loc is not glob:
                        write_back(paused.frame)
                result.output = buffer.getvalue()
                if not chunk.function:
                    done(result)
        finally:
            set_figure_sink(previous)
            figures = runtime.figures
            if figures.close_requested and self.close_figures is not None:
                self.close_figures()
            for spec in figures.drawable():
                previous(spec)
        return results

    def _matlab_runtime(self):
        from .matlab_runtime import Runtime
        if self._matlab is None or \
                self.namespace.get("__ml__") is not self._matlab:
            self._matlab = Runtime(self.namespace, base=self._presets,
                                   clear=self.clear)
            self._matlab.tracer = self.tracer
            self.namespace["__ml__"] = self._matlab
        return self._matlab

    # ── namespace ───────────────────────────────────────────────

    def variables(self) -> dict[str, Any]:
        """
        User variables — the commands and modules are filtered out.

        While the debugger is paused inside a function, that function's
        variables: the workspace shows the scope the prompt evaluates in.
        """
        paused = self.tracer.paused
        scope = paused.scope if paused is not None else self.namespace
        return {
            name: value for name, value in scope.items()
            if not name.startswith("_")
            and name not in self._commands
            and not _is_module(value)
            and not getattr(value, "_ml_function", False)
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
            return (f"  → '{name}' is not defined. help_fm lists the "
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


def _matlab_line(exc: BaseException,
                 line_maps: dict[str, list[int]]) -> int | None:
    """The MATLAB line behind the deepest translated frame of a traceback."""
    found = None
    tb = exc.__traceback__
    while tb is not None:
        name = tb.tb_frame.f_code.co_filename
        if name in line_maps:
            lines = line_maps[name]
            if 0 < tb.tb_lineno <= len(lines):
                found = lines[tb.tb_lineno - 1]
        tb = tb.tb_next
    return found


def _traceback_line(exc: BaseException, filename: str) -> int | None:
    """The line of the deepest frame compiled as ``filename``."""
    found = None
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == filename:
            found = tb.tb_lineno
        tb = tb.tb_next
    return found


def _is_matlab_error(exc: BaseException) -> bool:
    from .matlab_runtime import MatlabError
    return isinstance(exc, MatlabError)


def _matlab_message(exc: BaseException) -> str:
    if _is_matlab_error(exc):
        return str(exc)
    return _format_exception(exc)


def _is_module(value: Any) -> bool:
    import types
    return isinstance(value, types.ModuleType)
