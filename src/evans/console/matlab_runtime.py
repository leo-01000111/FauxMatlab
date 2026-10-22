"""
What translated MATLAB runs against.
====================================
:mod:`.matlab` turns a script into Python that calls this module for every
operation whose MATLAB meaning differs from Python's. One :class:`Runtime`
lives in a console namespace as ``__ml__``.

Representation
--------------
* A **row vector** is a 1-D numpy array — that is what ``tf``, ``step`` and
  ``linspace`` take and return, so a vector built in MATLAB passes straight
  into the control layer. A column is ``(n, 1)``; a matrix is 2-D.
* A **scalar** is a Python number. Indexing one element out of an array gives
  a number back, not a 1×1 array, so it mixes freely with transfer functions.
* A **cell** is :class:`Cell` (a list); a **struct** is :class:`Struct` (a
  dict with attribute access); a struct array is :class:`StructArray`.
* ``end`` inside an index is a :class:`Deferred` — a value waiting for the
  length of the dimension it indexes.

Plots
-----
While a script runs, figures are collected rather than drawn, so ``hold on``,
``title`` and ``legend`` can amend the figure a plot command already made.
They are handed to the real figure sink when the script finishes.
"""

from __future__ import annotations

import math
import os
import re
import struct
import sys
import time
import types
from collections.abc import Callable, Mapping
from typing import Any

import control as ctl
import numpy as np

from . import api
from .figures import FigureSpec

# ──────────────────────────────────────────────────────────────
#  Errors and control flow
# ──────────────────────────────────────────────────────────────

class MatlabError(Exception):
    """An ``error(...)`` raised by the script, or a MATLAB-style failure."""


class ScriptReturn(Exception):
    """``return`` at the top level of a script: stop, quietly."""


class MException:
    """What ``catch err`` binds: ``err.message`` and ``err.identifier``."""

    def __init__(self, message: str, identifier: str = "") -> None:
        self.message = message
        self.identifier = identifier

    @classmethod
    def wrap(cls, exc: BaseException) -> MException:
        return cls(str(exc), type(exc).__name__)

    def __repr__(self) -> str:
        return f"MException: {self.message}"


# ──────────────────────────────────────────────────────────────
#  Containers
# ──────────────────────────────────────────────────────────────

class Cell(list):
    """A MATLAB cell array (always a row here)."""

    def __repr__(self) -> str:
        inner = "    ".join(_brief(v) for v in self)
        return f"1×{len(self)} cell array\n    {{{inner}}}"


class Struct(dict):
    """A struct: a dict whose fields are also attributes."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"Unrecognized field name \"{name}\".") from None

    def __setattr__(self, name: str, value) -> None:
        self[name] = value

    def __repr__(self) -> str:
        if not self:
            return "struct with no fields."
        width = max(len(k) for k in self)
        return "\n".join(f"    {k:>{width}}: {_brief(v)}"
                         for k, v in self.items())


class StructArray(list):
    """``info(k) = stepinfo(...)`` builds one of these."""

    def __repr__(self) -> str:
        fields = list(self[0]) if self else []
        lines = [f"1×{len(self)} struct array with fields:", ""]
        lines += [f"    {f}" for f in fields]
        return "\n".join(lines)


class Table:
    """What ``struct2table`` returns: rows of named columns, displayed."""

    def __init__(self, rows: list[Mapping]) -> None:
        self.rows = rows
        self.columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in self.columns:
                    self.columns.append(key)

    def __repr__(self) -> str:
        if not self.rows:
            return "0×0 empty table"
        cells = [[_table_cell(r.get(c)) for c in self.columns]
                 for r in self.rows]
        widths = [max(len(c), *(len(row[k]) for row in cells))
                  for k, c in enumerate(self.columns)]
        # A wide table is split into blocks of columns that fit the console,
        # so no row wraps onto a second line.
        blocks, current, used = [], [], 0
        for k, w in enumerate(widths):
            if current and used + w + 3 > TABLE_WIDTH:
                blocks.append(current)
                current, used = [], 0
            current.append(k)
            used += w + 3
        blocks.append(current)
        out: list[str] = []
        for block in blocks:
            if out:
                out.append("")
            out.append("   " + "   ".join(
                self.columns[k].center(widths[k]) for k in block))
            out.append("   " + "   ".join("_" * widths[k] for k in block))
            out += ["   " + "   ".join(row[k].rjust(widths[k]) for k in block)
                    for row in cells]
        return "\n".join(out)


#: Characters a table row may use before its columns wrap into a new block.
TABLE_WIDTH = 84


def _table_cell(value) -> str:
    if isinstance(value, (int, float, np.floating, np.integer)):
        return _number(float(value))
    return _brief(value)


class PlotOptions:
    """
    ``bodeoptions`` and friends. Property names are case-insensitive, as
    MATLAB's are — ``opts.PhaseMatchingvalue`` sets ``PhaseMatchingValue``.
    """

    def __init__(self, kind: str, defaults: dict[str, Any]) -> None:
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_values", dict(defaults))

    def _key(self, name: str) -> str:
        for key in self._values:
            if key.lower() == name.lower():
                return key
        return name

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        key = self._key(name)
        if key not in self._values:
            raise AttributeError(f"There is no {name} property on "
                                 f"{self._kind} options.")
        return self._values[key]

    def __setattr__(self, name: str, value) -> None:
        self._values[self._key(name)] = value

    def get(self, name: str, default=None):
        return self._values.get(self._key(name), default)

    def __repr__(self) -> str:
        width = max(len(k) for k in self._values)
        return "\n".join(f"    {k:>{width}}: {_brief(v)}"
                         for k, v in self._values.items())


_BODE_DEFAULTS = {
    "Title": "Bode Diagram", "XLabel": "Frequency", "YLabel": "",
    "Grid": "off", "FreqUnits": "rad/s", "FreqScale": "log",
    "MagUnits": "dB", "MagScale": "linear", "MagVisible": "on",
    "PhaseUnits": "deg", "PhaseVisible": "on", "PhaseWrapping": "off",
    "PhaseMatching": "off", "PhaseMatchingFreq": 0.0,
    "PhaseMatchingValue": 0.0, "XLim": None, "YLim": None,
}
_TIME_DEFAULTS = {"Title": "Step Response", "XLabel": "Time",
                  "YLabel": "Amplitude", "Grid": "off", "XLim": None,
                  "YLim": None}


# ──────────────────────────────────────────────────────────────
#  end, :, and deferred values
# ──────────────────────────────────────────────────────────────

class _Colon:
    def __repr__(self) -> str:
        return ":"


COLON = _Colon()


class Deferred:
    """A value that depends on the length of the dimension being indexed."""

    def __init__(self, fn: Callable[[int], Any]) -> None:
        self.fn = fn

    def resolve(self, n: int):
        return self.fn(n)

    def _combine(self, other, op, reverse=False):
        def fn(n):
            a, b = self.resolve(n), _resolve(other, n)
            return op(b, a) if reverse else op(a, b)
        return Deferred(fn)

    def __add__(self, o):  return self._combine(o, lambda a, b: a + b)
    def __radd__(self, o): return self._combine(o, lambda a, b: a + b, True)
    def __sub__(self, o):  return self._combine(o, lambda a, b: a - b)
    def __rsub__(self, o): return self._combine(o, lambda a, b: a - b, True)
    def __mul__(self, o):  return self._combine(o, lambda a, b: a * b)
    def __rmul__(self, o): return self._combine(o, lambda a, b: a * b, True)
    def __truediv__(self, o):
        return self._combine(o, lambda a, b: a / b)
    def __rtruediv__(self, o):
        return self._combine(o, lambda a, b: a / b, True)
    def __neg__(self):     return Deferred(lambda n: -self.resolve(n))


def End(_k: int = 0, _n: int = 1) -> Deferred:
    return Deferred(lambda n: n)


def _resolve(value, n: int):
    return value.resolve(n) if isinstance(value, Deferred) else value


def _any_deferred(*values) -> bool:
    return any(isinstance(v, Deferred) for v in values)


def _defer(fn, *values):
    return Deferred(lambda n: fn(*(_resolve(v, n) for v in values)))


# ──────────────────────────────────────────────────────────────
#  Shape helpers
# ──────────────────────────────────────────────────────────────

def _is_lti(x) -> bool:
    return isinstance(x, ctl.LTI)


def _is_number(x) -> bool:
    return isinstance(x, (int, float, complex, bool, np.number, np.bool_))


def _as_array(x) -> np.ndarray:
    if isinstance(x, np.ndarray):
        return x
    if x is None:
        return np.zeros((0, 0))
    return np.asarray(x)


def _as2d(x) -> np.ndarray:
    a = _as_array(x)
    if a.ndim == 0:
        return a.reshape(1, 1)
    if a.ndim == 1:
        return a.reshape(1, -1)
    return a


def _normalise(a):
    """MATLAB-shaped result: 1×1 → scalar, 1×n → row (1-D)."""
    if not isinstance(a, np.ndarray):
        return a
    if a.ndim == 0 or a.size == 1 and a.ndim <= 2:
        return a.reshape(-1)[0].item() if a.size == 1 else a
    if a.ndim == 2 and a.shape[0] == 1:
        return a.reshape(-1)
    return a


def _shape(x) -> tuple[int, int]:
    if x is None:
        return (0, 0)
    if isinstance(x, str):
        return (1 if x else 0, len(x))
    if isinstance(x, (Cell, StructArray)):
        return (1 if len(x) else 0, len(x))
    if isinstance(x, (Struct, PlotOptions, Table)):
        return (len(x.rows), len(x.columns)) if isinstance(x, Table) \
            else (1, 1)
    if _is_lti(x):
        return (x.noutputs, x.ninputs)
    a = _as_array(x)
    if a.ndim == 0:
        return (1, 1)
    if a.ndim == 1:
        return (1 if a.size else 0, a.size) if a.size else (0, 0)
    return (a.shape[0], a.shape[1])


def _numel(x) -> int:
    r, c = _shape(x)
    return r * c


def _scalar(value):
    """A numpy scalar → a plain Python number; integral floats → int."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    return value


def _float_array(values) -> np.ndarray:
    a = np.asarray(values)
    if a.dtype == bool:
        return a
    if np.iscomplexobj(a):
        return a.astype(complex)
    return a.astype(float)


def _is_function(x) -> bool:
    return isinstance(x, (types.FunctionType, types.BuiltinFunctionType,
                          types.MethodType, np.ufunc)) \
        or getattr(x, "_ml_function", False)


# ──────────────────────────────────────────────────────────────
#  Display
# ──────────────────────────────────────────────────────────────

_FORMAT = {"long": False}


def _number(v) -> str:
    if isinstance(v, (bool, np.bool_)):
        return "1" if v else "0"
    if isinstance(v, complex) or isinstance(v, np.complexfloating):
        re_, im = v.real, v.imag
        sign = "+" if im >= 0 else "-"
        return f"{_number(re_)} {sign} {_number(abs(im))}i"
    v = float(v)
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Inf" if v > 0 else "-Inf"
    if v.is_integer() and abs(v) < 1e10:
        return str(int(v))
    if _FORMAT["long"]:
        return f"{v:.15g}"
    if 1e-3 <= abs(v) < 1e5:
        return f"{v:.4f}"
    return f"{v:.4e}"


def _brief(v) -> str:
    """One-line description, for cells, structs and tables."""
    if isinstance(v, str):
        return f"'{v}'"
    if _is_number(v):
        return _number(v)
    if v is None:
        return "[]"
    if isinstance(v, np.ndarray):
        if v.size <= 6:
            return "[" + " ".join(_number(x) for x in v.ravel()) + "]"
        r, c = _shape(v)
        return f"[{r}×{c} double]"
    if _is_lti(v):
        kind = "tf" if isinstance(v, ctl.TransferFunction) else "ss"
        return f"[1×1 {kind}]"
    if isinstance(v, Struct):
        return "[1×1 struct]"
    if isinstance(v, Cell):
        return f"{{1×{len(v)} cell}}"
    return type(v).__name__


def display(value) -> str:
    """How MATLAB shows a value after ``name =``."""
    if isinstance(value, str):
        return f"'{value}'"
    if _is_number(value):
        return _number(value)
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return "[]"
        return _matrix_text(value)
    if value is None:
        return "[]"
    return repr(value) if not _is_lti(value) else _system_text(value)


def _matrix_text(a: np.ndarray, max_columns: int = 10) -> str:
    """
    Columns of right-aligned numbers, the way MATLAB lays out a matrix.

    A long row wraps into blocks headed ``Columns 1 through 10``, as MATLAB
    does; very long vectors show their ends with a count in between, since a
    thousand-element time vector helps nobody.
    """
    m = _as2d(a)
    if m.dtype == bool:
        m = m.astype(int)
    rows, cols = m.shape
    shown_cols = list(range(cols))
    elided = None
    if rows * cols > 200:
        if rows == 1:
            shown_cols = list(range(5)) + list(range(cols - 5, cols))
            elided = cols - 10
        elif cols == 1:
            m = np.vstack([m[:5], m[-5:]])
            elided = rows - 10
            rows = m.shape[0]
    cells = [[_number(m[r, c]) for c in shown_cols] for r in range(rows)]
    width = max(len(x) for row in cells for x in row) + 3
    lines = []
    if rows == 1 and elided:
        head = "".join(x.rjust(width) for x in cells[0][:5])
        tail = "".join(x.rjust(width) for x in cells[0][5:])
        return f"{head}   … {elided} more …{tail}\n\n  (1×{cols} double)"
    if elided:
        body = ["".join(x.rjust(width) for x in row) for row in cells]
        return "\n".join(body[:5] + [f"   … {elided} more …"] + body[5:]
                         + ["", f"  ({rows + elided}×1 double)"])
    for start in range(0, len(shown_cols), max_columns):
        block = range(start, min(start + max_columns, len(shown_cols)))
        if len(shown_cols) > max_columns:
            last = block[-1] + 1
            label = (f"Column {last}" if len(block) == 1 else
                     f"Columns {block[0] + 1} through {last}")
            lines += [f"  {label}", ""]
        lines += ["".join(cells[r][c].rjust(width) for c in block)
                  for r in range(rows)]
        if start + max_columns < len(shown_cols):
            lines.append("")
    return "\n".join(lines)


def _system_text(sys) -> str:
    """A system as MATLAB prints it: the model, then what kind it is."""
    lines = [line for line in str(sys).splitlines()
             if not line.startswith("<")
             and not re.match(r"\s*(Inputs|Outputs|States) \(", line)]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    dt = getattr(sys, "dt", 0)
    kind = ("transfer function" if isinstance(sys, ctl.TransferFunction)
            else "state-space model")
    if dt:
        footer = [f"Sample time: {_number(dt)} seconds",
                  f"Discrete-time {kind}."]
    else:
        footer = [f"Continuous-time {kind}."]
    return "\n".join(lines + [""] + footer)


# ──────────────────────────────────────────────────────────────
#  Figures
# ──────────────────────────────────────────────────────────────

class Figures:
    """
    Plot requests made during one script run, open to amendment.

    ``subplot`` makes a figure of kind ``"subplot"`` whose
    ``extra["panes"]`` lists the axes laid out in it — each a dict of the
    grid it was placed on (``rows``, ``cols``), the cells it covers
    (``cells``, 1-based like MATLAB's ``p``) and the ordinary
    :class:`FigureSpec` drawn there (``spec``). While a pane is selected, a
    plot command lands in it rather than opening a figure of its own.
    """

    def __init__(self) -> None:
        self.specs: list[FigureSpec] = []
        self.current: FigureSpec | None = None
        self.hold = False
        self.close_requested = False
        self.grid: FigureSpec | None = None
        self.pane: dict | None = None

    def collect(self, spec: FigureSpec) -> FigureSpec:
        cur = self.current
        if self.hold and cur is not None and (
                cur.kind == spec.kind or not cur.traces):
            if not cur.traces:
                cur.kind, cur.title = spec.kind, cur.title or spec.title
                cur.xlabel = cur.xlabel or spec.xlabel
                cur.ylabel = cur.ylabel or spec.ylabel
            cur.traces.extend(spec.traces)
            for key, value in spec.extra.items():
                if isinstance(value, list):
                    cur.extra.setdefault(key, []).extend(value)
                else:
                    cur.extra.setdefault(key, value)
            return cur
        if self.pane is not None:
            # A new plot in a subplot replaces what that axes showed.
            self.pane["spec"] = spec
        else:
            self.specs.append(spec)
        self.current = spec
        return spec

    def ensure(self) -> FigureSpec:
        if self.current is None:
            self.collect(FigureSpec("xy", "", "", ""))
        return self.current

    def new(self) -> None:
        self.current = None
        self.hold = False
        self.grid = None
        self.pane = None

    def subplot(self, rows: int, cols: int, cells: tuple[int, ...]) -> None:
        """Select (or add) the axes at ``cells`` of a rows × cols grid."""
        if self.pane is not None:
            self.pane["hold"] = self.hold
        if self.grid is None:
            self.grid = FigureSpec("subplot")
            self.grid.extra["panes"] = []
            self.specs.append(self.grid)
        panes = self.grid.extra["panes"]
        for pane in panes:
            if (pane["rows"], pane["cols"], pane["cells"]) == (rows, cols,
                                                               cells):
                break
        else:
            pane = {"rows": rows, "cols": cols, "cells": cells,
                    "spec": None, "hold": False}
            panes.append(pane)
        self.pane = pane
        self.current = pane["spec"]
        self.hold = pane["hold"]

    def figure(self) -> FigureSpec | None:
        """The current figure: a subplot grid, or the current plot."""
        return self.grid if self.grid is not None else self.current

    def drawable(self) -> list[FigureSpec]:
        """The figures worth drawing: those with something on them."""
        return [s for s in self.specs if s.traces or any(
            p["spec"] is not None and p["spec"].traces
            for p in s.extra.get("panes", ()))]


# ──────────────────────────────────────────────────────────────
#  The runtime
# ──────────────────────────────────────────────────────────────

class Runtime:
    """Bound to one console namespace as ``__ml__``."""

    COLON = COLON
    End = staticmethod(End)
    MException = MException
    ScriptReturn = ScriptReturn

    def __init__(self, namespace: dict, base: dict | None = None,
                 clear: Callable[..., None] | None = None) -> None:
        self.ns = namespace
        self.base = base or {}
        self._clear = clear
        self.figures = Figures()
        self.script_functions: set[str] = set()
        self._tic = time.perf_counter()
        #: The running script's folder; ``cd`` moves away from it.
        self.script_folder: str | None = None
        self._cwd: str | None = None
        #: Folders added with ``addpath``, searched after the current one.
        self.path: list[str] = []
        self._listing: dict[str, set[str]] = {}
        self._files: dict[str, tuple[int, Callable]] = {}
        #: Set once "no audio output" has been said, so it is said once.
        self._quiet = False
        self.lib = _Library(self)

    # ── names ───────────────────────────────────────────────────

    def lookup(self, name: str, glob: dict, loc: dict):
        """
        Resolve a name the script never assigns.

        A variable from the console wins; then a function file ``name.m``
        in the current folder or on the path, as in MATLAB; then the MATLAB
        library (whose ``zeros(3)`` is 3×3, unlike numpy's); then the
        console's commands.
        """
        if loc is not glob and name in loc:
            return loc[name]
        if name in glob:
            value = glob[name]
            if not (name in self.lib.names
                    and value is self.base.get(name, object())):
                return value
        path = self.find_file(name)
        if path is not None:
            return self._file_function(name, path)
        if name in self.lib.names:
            return getattr(self.lib, _lib_attr(name))
        # The folder may have gained the file since it was last listed.
        path = self.find_file(name, refresh=True)
        if path is not None:
            return self._file_function(name, path)
        if name == "syms":
            raise MatlabError(
                "syms (symbolic maths) is not supported. For transfer "
                "functions use  s = tf('s').")
        raise MatlabError(f"Unrecognized function or variable '{name}'.")

    def existing(self, name: str, scope: dict):
        """
        The current value of a variable about to be indexed into.

        The console's presets — ``s``, ``pi``, the commands — are not
        variables the script made: ``s.name = 'x'`` builds a new struct, as
        it would in a fresh MATLAB workspace.
        """
        value = scope.get(name)
        if value is not None and value is self.base.get(name, object()):
            return None
        return value

    # ── the current folder and the path ─────────────────────────

    @property
    def folder(self) -> str:
        """MATLAB's current folder: ``cd``'s, else the script's, else ours."""
        return self._cwd or self.script_folder or os.getcwd()

    def resolve(self, name) -> str:
        """A file name as a script wrote it, made absolute."""
        name = _as_text(name)
        if os.sep == "/":
            name = name.replace("\\", "/")     # "data\x.wav" written on Windows
        name = os.path.expanduser(name)
        return os.path.normpath(name if os.path.isabs(name)
                                else os.path.join(self.folder, name))

    def cd(self, folder) -> None:
        target = self.resolve(folder)
        if not os.path.isdir(target):
            raise MatlabError(f"Cannot CD to {_as_text(folder)} (Name is "
                              f"nonexistent or not a folder).")
        self._cwd = target

    def find_file(self, name: str, refresh: bool = False) -> str | None:
        """
        ``name.m`` in the current folder, then on the path.

        Folders are listed once per run (and again on a miss), so a loop
        calling ``zeros`` does not touch the disk every time round.
        """
        for folder in [self.folder, *self.path]:
            names = None if refresh else self._listing.get(folder)
            if names is None:
                try:
                    names = {e.name[:-2] for e in os.scandir(folder)
                             if e.name.endswith(".m") and e.is_file()}
                except OSError:
                    names = set()
                self._listing[folder] = names
            if name in names:
                return os.path.join(folder, name + ".m")
        return None

    def _file_function(self, name: str, path: str):
        """
        Load a function file as a callable, cached until the file changes.

        A file that starts with ``function`` defines its first function
        under the file's name, with the rest as its local functions; they
        run in a namespace of their own, so they see none of the caller's
        variables. Any other file is a script, run in the workspace.
        """
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            raise MatlabError(f"Unrecognized function or variable "
                              f"'{name}'.") from None
        cached = self._files.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        from .matlab import MatlabSyntaxError, translate
        with open(path, "rb") as fh:
            raw = fh.read()
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            source = raw.decode("cp1252", errors="replace")
        try:
            chunks = translate(source)
        except MatlabSyntaxError as exc:
            raise MatlabError(f"{name}.m, line {exc.line}: "
                              f"{exc.message}") from None
        functions = [c for c in chunks if c.function]
        filename = f"<{name}.m>"
        if functions and min(c.first for c in functions) == min(
                c.first for c in chunks):
            scope = dict(self.base)
            scope["__ml__"] = self
            for chunk in functions:
                exec(compile(chunk.python, filename, "exec"), scope)
            main = min(functions, key=lambda c: c.first)
            fn = scope[re.search(r"^def (\w+)\(", main.python, re.M).group(1)]
        else:
            codes = [compile(c.python, filename, "exec") for c in chunks]

            def fn(*_args, nargout=0):
                for code in codes:
                    exec(code, self.ns)

            fn._ml_function = fn._ml_nargout = True
            fn.__name__ = name
        self._files[path] = (stamp, fn)
        return fn

    def value(self, x):
        """A bare function name in an expression calls it with no inputs."""
        if _is_function(x):
            return self.call(x, (), nargout=1)
        return x

    def function(self, fn):
        """Decorator for a script's local functions."""
        fn._ml_function = True
        fn._ml_nargout = True
        self.script_functions.add(fn.__name__)
        return fn

    @staticmethod
    def outputs(values: tuple, nargout: int):
        if nargout <= 1:
            return values[0] if values else None
        return values[:nargout]

    # ── calls and indexing ──────────────────────────────────────

    def call(self, f, args: tuple, nargout: int = 1, names=None):
        if _is_function(f) or (callable(f) and not _is_lti(f)
                               and not isinstance(f, (np.ndarray, str,
                                                      Mapping, list))):
            if any(isinstance(a, Deferred) for a in args):
                raise MatlabError("'end' can only be used inside an index.")
            args = tuple(None if a is COLON else a for a in args)
            kwargs = {}
            if getattr(f, "_ml_nargout", False):
                kwargs["nargout"] = nargout
            if names is not None and getattr(f, "_ml_names", False):
                kwargs["names"] = names
            result = f(*args, **kwargs)
            if (nargout == 1 and not getattr(f, "_ml_nargout", False)
                    and type(result) is tuple):
                return result[0]
            if isinstance(result, np.ndarray) and result.ndim == 2 \
                    and result.shape[0] == 1:
                return _normalise(result)     # a 1×n row is a row vector here
            return result
        return self.index(f, args)

    def unpack(self, value, n: int) -> tuple:
        if n == 1:
            return (value,)
        if isinstance(value, (tuple, list)) and not isinstance(
                value, (Cell, StructArray)):
            if len(value) < n:
                raise MatlabError("Too many output arguments.")
            return tuple(value[:n])
        raise MatlabError("Too many output arguments.")

    def index(self, x, args: tuple):
        if not args:
            return x
        if _is_lti(x):
            raise MatlabError("Indexing into a system is not supported; "
                              "use evalfr(G, s) to evaluate it.")
        if isinstance(x, (Cell, StructArray)):
            picked = self._pick_list(x, args)
            if isinstance(picked, list) and len(picked) == 1 \
                    and isinstance(x, StructArray):
                return picked[0]
            return type(x)(picked) if isinstance(picked, list) else picked
        if isinstance(x, Struct) and all(_resolve(a, 1) in (1, COLON)
                                         for a in args):
            return x
        if isinstance(x, str):
            chars = np.array(list(x))
            picked = self.index(chars, args)
            return "".join(np.atleast_1d(picked)) if isinstance(
                picked, np.ndarray) else str(picked)
        a = _as_array(x)
        if a.ndim == 0:
            a = a.reshape(1)
        if len(args) == 1:
            arg = args[0]
            if arg is COLON:
                return _normalise(a.reshape(-1, 1, order="F")) \
                    if a.ndim == 2 else a.reshape(-1, 1)
            flat = a.reshape(-1, order="F") if a.ndim == 2 else a
            idx = self._indices(arg, flat.size)
            out = flat[idx]
            if np.isscalar(idx) or np.ndim(idx) == 0:
                return _scalar(out)
            if a.ndim == 2 and a.shape[1] == 1 and a.shape[0] > 1:
                return out.reshape(-1, 1)
            return out
        a2 = _as2d(a)
        if len(args) > 2:
            extra = args[2:]
            if any(_resolve(e, 1) not in (1, COLON) for e in extra):
                raise MatlabError("Index exceeds the array dimensions.")
        rows = self._indices(args[0], a2.shape[0])
        cols = self._indices(args[1], a2.shape[1])
        out = a2[np.ix_(np.atleast_1d(rows), np.atleast_1d(cols))]
        return _normalise(out)

    def _pick_list(self, items: list, args: tuple):
        idx = self._indices(args[-1], len(items))
        if np.ndim(idx) == 0:
            return [items[int(idx)]]
        return [items[int(i)] for i in idx]

    def _indices(self, arg, n: int):
        """1-based MATLAB index → 0-based numpy index, checked."""
        if arg is COLON:
            return np.arange(n)
        arg = _resolve(arg, n)
        if isinstance(arg, Deferred):
            arg = arg.resolve(n)
        a = np.asarray(arg)
        if a.dtype == bool:
            if a.size > n:
                raise MatlabError("The logical index is longer than the "
                                  "array.")
            return np.nonzero(a.reshape(-1, order="F"))[0]
        if a.size and not np.all(np.isreal(a)):
            raise MatlabError("Array indices must be positive integers.")
        a = a.real if np.iscomplexobj(a) else a
        if a.size and (np.any(a < 1) or np.any(a != np.round(a))):
            bad = a.reshape(-1)[0]
            raise MatlabError(f"Index in position 1 is invalid. Array "
                              f"indices must be positive integers "
                              f"(got {_number(bad)}).")
        if a.size and np.max(a) > n:
            raise MatlabError(f"Index exceeds the number of array elements. "
                              f"Index must not exceed {n}.")
        out = a.astype(int) - 1
        return int(out) if out.ndim == 0 else out.reshape(-1)

    def cell_index(self, c, args: tuple):
        if isinstance(c, (Cell, list)):
            picked = self._pick_list(c, args)
            return picked[0] if len(picked) == 1 else tuple(picked)
        raise MatlabError("Brace indexing is only for cell arrays; use "
                          "() for this value.")

    def field(self, obj, name):
        if isinstance(obj, StructArray):
            if len(obj) == 1:
                obj = obj[0]
            else:
                return tuple(o.get(name) for o in obj)
        if isinstance(obj, Mapping):
            if name in obj:
                return obj[name]
            raise MatlabError(f"Unrecognized field name \"{name}\".")
        if isinstance(obj, MException):
            return getattr(obj, name)
        try:
            return getattr(obj, name)
        except AttributeError:
            raise MatlabError(f"Unrecognized property or field "
                              f"\"{name}\".") from None

    # ── assignment ──────────────────────────────────────────────

    def assign(self, obj, path: list, value):
        if not path:
            return value
        (kind, key), rest = path[0], path[1:]
        if kind == ".":
            if obj is None or (isinstance(obj, np.ndarray) and obj.size == 0):
                obj = Struct()
            if isinstance(obj, StructArray) and len(obj) == 1:
                obj = obj[0]
            if isinstance(obj, Mapping):
                current = obj.get(key)
                obj[key] = self.assign(current, rest, value)
                return obj
            if isinstance(obj, PlotOptions):
                current = obj.get(key)
                setattr(obj, key, self.assign(current, rest, value))
                return obj
            raise MatlabError(f"Cannot set field '{key}' on a "
                              f"{type(obj).__name__}.")
        if kind == "{}":
            cell = Cell() if obj is None else obj
            if not isinstance(cell, list):
                raise MatlabError("Brace assignment needs a cell array.")
            k = self._grow_index(key[-1], len(cell))
            while len(cell) <= k:
                cell.append(np.zeros((0, 0)))
            cell[k] = self.assign(cell[k] if rest else None, rest, value)
            return cell
        # ()
        if rest or isinstance(value, Mapping) or isinstance(
                obj, StructArray):
            array = StructArray() if obj is None else obj
            if isinstance(array, Struct):
                array = StructArray([array])
            if not isinstance(array, StructArray):
                raise MatlabError("Cannot index into this value with "
                                  "a field.")
            k = self._grow_index(key[-1], len(array))
            template = array[0] if array else (value if isinstance(
                value, Mapping) else {})
            while len(array) <= k:
                array.append(Struct({f: np.zeros((0, 0)) for f in template}))
            element = array[k]
            array[k] = (self.assign(element, rest, value) if rest
                        else Struct(value))
            return array
        if isinstance(obj, Cell):
            k = self._grow_index(key[-1], len(obj))
            while len(obj) <= k:
                obj.append(np.zeros((0, 0)))
            obj[k] = value[0] if isinstance(value, Cell) and len(value) == 1 \
                else value
            return obj
        return self._assign_array(obj, key, value)

    def _grow_index(self, arg, n: int) -> int:
        k = _resolve(arg, n)
        k = _scalar(np.asarray(k).reshape(-1)[0]) if not isinstance(
            k, (int, float)) else k
        if k < 1 or int(k) != k:
            raise MatlabError("Array indices must be positive integers.")
        return int(k) - 1

    def _assign_array(self, obj, key: tuple, value):
        was_row = obj is None or (isinstance(obj, np.ndarray) and obj.ndim
                                  == 1) or _is_number(obj)
        if obj is None:
            a = np.zeros(0)
        elif _is_number(obj):
            a = np.array([obj])
        else:
            a = np.array(obj, copy=True)
        v = value
        delete = isinstance(v, np.ndarray) and v.size == 0
        if not delete:
            v = np.asarray(v)
            if np.iscomplexobj(v) and not np.iscomplexobj(a):
                a = a.astype(complex)
            elif a.dtype == bool and v.dtype != bool:
                a = a.astype(float)
            elif a.dtype.kind in "iu":
                a = a.astype(float)
        if len(key) == 1:
            arg = key[0]
            if a.ndim == 2 and min(a.shape) > 1:
                flat = a.reshape(-1, order="F")
                idx = self._indices(arg, flat.size) if not delete else \
                    self._indices(arg, flat.size)
                if delete:
                    return np.delete(flat, idx)
                flat[idx] = v.reshape(-1) if v.size > 1 else v
                return flat.reshape(a.shape, order="F")
            column = a.ndim == 2 and a.shape[1] == 1 and a.shape[0] > 1
            flat = a.reshape(-1)
            if arg is COLON:
                idx = np.arange(flat.size)
            else:
                raw = _resolve(arg, flat.size)
                r = np.asarray(raw)
                if r.dtype == bool:
                    idx = np.nonzero(r.reshape(-1))[0]
                else:
                    if r.size and (np.any(r < 1) or np.any(r != np.round(r))):
                        raise MatlabError("Array indices must be positive "
                                          "integers.")
                    idx = r.astype(int).reshape(-1) - 1 if r.ndim else \
                        int(r) - 1
            if delete:
                out = np.delete(flat, idx)
                return out.reshape(-1, 1) if column else out
            top = int(np.max(idx)) + 1 if np.size(idx) else 0
            if top > flat.size:
                grown = np.zeros(top, dtype=flat.dtype)
                grown[:flat.size] = flat
                flat = grown
            flat[idx] = v.reshape(-1) if v.size > 1 else v
            return flat.reshape(-1, 1) if column else flat
        a2 = _as2d(a) if a.size else np.zeros((0, 0), dtype=a.dtype)
        r_arg, c_arg = key[0], key[1]
        vr, vc = _shape(value)

        def dim_index(arg, n, other_len):
            if arg is COLON:
                return np.arange(n if n else other_len)
            raw = np.asarray(_resolve(arg, n))
            if raw.dtype == bool:
                return np.nonzero(raw.reshape(-1))[0]
            if raw.size and (np.any(raw < 1) or np.any(raw != np.round(raw))):
                raise MatlabError("Array indices must be positive integers.")
            return np.atleast_1d(raw.astype(int).reshape(-1) - 1)

        rows = dim_index(r_arg, a2.shape[0], vr)
        cols = dim_index(c_arg, a2.shape[1], vc)
        if delete:
            if r_arg is COLON:
                out = np.delete(a2, cols, axis=1)
            elif c_arg is COLON:
                out = np.delete(a2, rows, axis=0)
            else:
                raise MatlabError("A null assignment can delete only whole "
                                  "rows or columns.")
            return _normalise_row(out, was_row)
        need_r = max(a2.shape[0], int(rows.max()) + 1 if rows.size else 0)
        need_c = max(a2.shape[1], int(cols.max()) + 1 if cols.size else 0)
        if (need_r, need_c) != a2.shape:
            grown = np.zeros((need_r, need_c), dtype=a2.dtype)
            grown[:a2.shape[0], :a2.shape[1]] = a2
            a2 = grown
        block = v if v.size <= 1 else v.reshape(len(rows), len(cols))
        a2[np.ix_(rows, cols)] = block
        return _normalise_row(a2, was_row)

    # ── construction ────────────────────────────────────────────

    def concat(self, rows: list[list]):
        flat = [x for row in rows for x in row]
        if any(isinstance(x, Deferred) for x in flat):
            return Deferred(lambda n: self.concat(
                [[_resolve(x, n) for x in row] for row in rows]))
        if not flat:
            return np.zeros((0, 0))
        if any(_is_lti(x) for x in flat):
            if len(flat) == 1:
                return flat[0]
            raise MatlabError("Concatenating systems into a MIMO model is "
                              "not supported.")
        if any(isinstance(x, (Cell,)) for x in flat):
            out = Cell()
            for x in flat:
                out.extend(x if isinstance(x, Cell) else [x])
            return out
        if any(isinstance(x, (Struct, StructArray)) for x in flat):
            out = StructArray()
            for x in flat:
                out.extend(x if isinstance(x, StructArray) else [x])
            return out
        if any(isinstance(x, str) for x in flat):
            texts = ["".join(_as_text(x) for x in row) for row in rows if row]
            return texts[0] if len(texts) == 1 else Cell(texts)
        blocks = []
        for row in rows:
            parts = [_as2d(x) for x in row if _numel(x) > 0]
            if not parts:
                continue
            try:
                blocks.append(np.hstack(parts))
            except ValueError:
                raise MatlabError("Dimensions of arrays being concatenated "
                                  "are not consistent.") from None
        if not blocks:
            return np.zeros((0, 0))
        try:
            out = np.vstack(blocks)
        except ValueError:
            raise MatlabError("Dimensions of arrays being concatenated are "
                              "not consistent.") from None
        out = _float_array(out)
        if out.shape[0] == 1:
            return out.reshape(-1)
        return out

    @staticmethod
    def cell(rows: list[list]) -> Cell:
        return Cell(x for row in rows for x in row)

    def colon(self, start, step, stop):
        if _any_deferred(start, step, stop):
            return _defer(self.colon, start, step, stop)
        start, step, stop = (_scalar_of(start), _scalar_of(step),
                             _scalar_of(stop))
        if step == 0 or (step > 0 and start > stop) or (step < 0
                                                        and start < stop):
            return np.zeros(0)
        n = int(math.floor((stop - start) / step + 1e-10)) + 1
        return start + step * np.arange(n, dtype=float)

    # ── statements ──────────────────────────────────────────────

    def show(self, name: str, value) -> None:
        text = display(value)
        if "\n" in text or (isinstance(value, np.ndarray) and value.size > 1) \
                or _is_lti(value):
            body = "\n".join("    " + line for line in text.splitlines())
            print(f"{name} =\n\n{body}\n")
        else:
            print(f"{name} = {text}")

    def bare(self, name: str, glob: dict, loc: dict, echo: bool) -> None:
        """
        A name alone as a statement. A variable shows itself, ``x = 5``, as
        in MATLAB; a function runs and its result becomes ``ans``.
        """
        target = self.lookup(name, glob, loc)
        scope = loc if name in loc else glob
        if not _is_function(target) and scope.get(name) is target \
                and target is not self.base.get(name, object()):
            if echo:
                self.show(name, target)
            return
        if _is_function(target):
            self.statement(self.call(target, (), nargout=0), echo)
        else:
            self.statement(target, echo)

    def statement(self, value, echo: bool) -> None:
        if value is None:
            return
        self.ns["ans"] = value
        if echo:
            self.show("ans", value)

    @staticmethod
    def truth(x) -> bool:
        if x is None:
            return False
        if isinstance(x, str):
            return bool(x)
        if isinstance(x, np.ndarray):
            return bool(x.size) and bool(np.all(x != 0))
        if isinstance(x, (Cell, StructArray)):
            raise MatlabError("Conversion to logical from cell is not "
                              "possible.")
        return bool(x)

    @staticmethod
    def iterate(x):
        if x is None:
            return []
        if isinstance(x, np.ndarray):
            if x.ndim <= 1:
                return [_scalar(v) for v in x]
            if x.shape[0] == 1:
                return [_scalar(v) for v in x[0]]
            return [x[:, k:k + 1] for k in range(x.shape[1])]
        if isinstance(x, Cell):
            return [Cell([v]) for v in x]
        if isinstance(x, (StructArray, str)):
            return list(x)
        return [x]

    def case_matches(self, subject, value) -> bool:
        if isinstance(value, Cell):
            return any(self.case_matches(subject, v) for v in value)
        if isinstance(subject, str) or isinstance(value, str):
            return isinstance(subject, str) and isinstance(value, str) \
                and subject == value
        try:
            return bool(np.all(np.asarray(subject) == np.asarray(value)))
        except Exception:                                # noqa: BLE001
            return False

    # ── operators ───────────────────────────────────────────────

    def plus(self, a, b):
        return self._arith(a, b, lambda x, y: x + y)

    def minus(self, a, b):
        return self._arith(a, b, lambda x, y: x - y)

    def times(self, a, b):
        return self._arith(a, b, lambda x, y: x * y)

    def rdivide(self, a, b):
        return self._arith(a, b, _divide)

    def ldivide(self, a, b):
        return self._arith(a, b, lambda x, y: _divide(y, x))

    def power(self, a, b):
        return self._arith(a, b, _power)

    def mtimes(self, a, b):
        if _any_deferred(a, b):
            return _defer(self.mtimes, a, b)
        a, b = _coerce(a, b)
        if isinstance(a, np.ndarray) and isinstance(b, np.ndarray) \
                and a.size > 1 and b.size > 1:
            A, B = _as2d(a), _as2d(b)
            if A.shape[1] != B.shape[0]:
                raise MatlabError(
                    f"Incorrect dimensions for matrix multiplication: "
                    f"{A.shape[0]}×{A.shape[1]} * {B.shape[0]}×{B.shape[1]}. "
                    f"Use .* for elementwise multiplication.")
            return _normalise(A @ B)
        return a * b

    def mrdivide(self, a, b):
        if _any_deferred(a, b):
            return _defer(self.mrdivide, a, b)
        a, b = _coerce(a, b)
        if isinstance(b, np.ndarray) and b.size > 1:
            A, B = _as2d(a), _as2d(b)
            x = np.linalg.lstsq(B.T, A.T, rcond=None)[0].T
            return _normalise(x)
        return _divide(a, b)

    def mldivide(self, a, b):
        a, b = _coerce(a, b)
        if isinstance(a, np.ndarray) and a.size > 1:
            A, B = _as2d(a), _as2d(b)
            if B.shape[0] == 1 and A.shape[0] > 1:
                B = B.T
            if A.shape[0] == A.shape[1]:
                x = np.linalg.solve(A, B)
            else:
                x = np.linalg.lstsq(A, B, rcond=None)[0]
            return _normalise(x)
        return _divide(b, a)

    def mpower(self, a, b):
        if _any_deferred(a, b):
            return _defer(self.mpower, a, b)
        a, b = _coerce(a, b)
        if _is_lti(a):
            if float(b) != int(b):
                raise MatlabError("A system can only be raised to an "
                                  "integer power.")
            return a ** int(b)
        if isinstance(a, np.ndarray) and a.size > 1:
            A = _as2d(a)
            if A.shape[0] != A.shape[1]:
                raise MatlabError("For a vector, use .^ for elementwise "
                                  "power.")
            if float(b) == int(b):
                return np.linalg.matrix_power(A, int(b))
            vals, vecs = np.linalg.eig(A)
            return vecs @ np.diag(vals ** b) @ np.linalg.inv(vecs)
        return _power(a, b)

    def _arith(self, a, b, op):
        if _any_deferred(a, b):
            return _defer(lambda x, y: op(x, y), a, b)
        a, b = _coerce(a, b)
        if isinstance(a, np.ndarray) and isinstance(b, np.ndarray) \
                and a.size > 1 and b.size > 1 and _shape(a) != _shape(b):
            sa, sb = _shape(a), _shape(b)
            compatible = all(x == y or x == 1 or y == 1
                             for x, y in zip(sa, sb))
            if not compatible:
                raise MatlabError(f"Arrays have incompatible sizes for this "
                                  f"operation: {sa[0]}×{sa[1]} and "
                                  f"{sb[0]}×{sb[1]}.")
            return _normalise(op(_as2d(a), _as2d(b)))
        with np.errstate(divide="ignore", invalid="ignore"):
            return op(a, b)

    def _compare(self, a, b, op):
        a, b = _coerce(a, b)
        if isinstance(a, str) and isinstance(b, str):
            if len(a) != len(b) and len(a) != 1 and len(b) != 1:
                raise MatlabError("Arrays have incompatible sizes; use "
                                  "strcmp to compare text.")
            a, b = np.array([ord(c) for c in a]), np.array([ord(c) for c in b])
        out = op(a, b)
        return bool(out) if isinstance(out, (bool, np.bool_)) else out

    def eq(self, a, b):
        return self._compare(a, b, lambda x, y: x == y)

    def ne(self, a, b):
        return self._compare(a, b, lambda x, y: x != y)

    def lt(self, a, b):
        return self._compare(a, b, lambda x, y: x < y)

    def le(self, a, b):
        return self._compare(a, b, lambda x, y: x <= y)

    def gt(self, a, b):
        return self._compare(a, b, lambda x, y: x > y)

    def ge(self, a, b):
        return self._compare(a, b, lambda x, y: x >= y)

    @staticmethod
    def logical_and(a, b):
        out = np.logical_and(a, b)
        return bool(out) if np.ndim(out) == 0 else out

    @staticmethod
    def logical_or(a, b):
        out = np.logical_or(a, b)
        return bool(out) if np.ndim(out) == 0 else out

    @staticmethod
    def logical_not(a):
        out = np.logical_not(a)
        return bool(out) if np.ndim(out) == 0 else out

    def uminus(self, a):
        if isinstance(a, Deferred):
            return -a
        return -a

    @staticmethod
    def uplus(a):
        return a

    @staticmethod
    def transpose(a):
        if isinstance(a, np.ndarray):
            if a.ndim == 1:
                return a.reshape(-1, 1)
            if a.ndim == 2 and a.shape[1] == 1:
                return a.reshape(-1)
            return a.T
        return a

    def ctranspose(self, a):
        out = self.transpose(a)
        if isinstance(out, np.ndarray) and np.iscomplexobj(out):
            return out.conj()
        if isinstance(out, complex):
            return out.conjugate()
        return out

    # ── running a script ────────────────────────────────────────

    def begin(self, folder: str | None = None) -> None:
        self.figures = Figures()
        self.script_folder = folder
        self._cwd = None
        self._listing.clear()

    def clear(self, names: tuple[str, ...]) -> None:
        keep = self.script_functions
        if self._clear is None:
            return
        if names and names[0] not in ("all", "-all", "variables", "-v"):
            self._clear(*(n for n in names if n not in keep))
            return
        saved = {n: self.ns[n] for n in keep if n in self.ns}
        self._clear()
        self.ns.update(saved)

    def workspace(self) -> dict[str, Any]:
        """The script's variables, as ``save`` and ``whos`` see them."""
        return {
            name: value for name, value in self.ns.items()
            if not name.startswith("_")
            and value is not self.base.get(name, object())
            and (value is None or _is_number(value) or isinstance(
                value, (str, np.ndarray, Struct, StructArray, Cell)))
        }


def _normalise_row(a: np.ndarray, was_row: bool):
    if was_row and a.ndim == 2 and a.shape[0] == 1:
        return a.reshape(-1)
    return a


def _scalar_of(x):
    if isinstance(x, np.ndarray):
        if x.size == 0:
            raise MatlabError("The colon operator needs non-empty bounds.")
        x = x.reshape(-1)[0]
    if isinstance(x, np.generic):
        x = x.item()
    return x


def _coerce(a, b):
    """A one-element array meeting a system becomes a plain number."""
    def unbox(x):
        if isinstance(x, np.ndarray) and x.size == 1:
            return x.reshape(-1)[0].item()
        if isinstance(x, (bool, np.bool_)):
            return int(x)
        return x
    if _is_lti(a) or _is_lti(b):
        return unbox(a), unbox(b)
    if isinstance(a, np.ndarray) and a.size == 1 and not isinstance(
            b, np.ndarray):
        a = a.reshape(-1)[0].item()
    if isinstance(b, np.ndarray) and b.size == 1 and not isinstance(
            a, np.ndarray):
        b = b.reshape(-1)[0].item()
    return a, b


def _divide(a, b):
    if _is_number(a) and _is_number(b):
        try:
            return a / b
        except ZeroDivisionError:
            with np.errstate(divide="ignore", invalid="ignore"):
                return float(np.true_divide(float(np.real(a)), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return a / b


def _power(a, b):
    if _is_lti(a):
        return a ** int(b)
    if _is_number(a) and _is_number(b):
        try:
            out = a ** b
        except ZeroDivisionError:
            return math.inf
        return out
    a_arr = np.asarray(a)
    b_arr = np.asarray(b)
    if a_arr.dtype.kind in "iub":
        a_arr = a_arr.astype(float)
    if np.any(np.real(a_arr) < 0) and np.any(b_arr != np.round(b_arr)):
        a_arr = a_arr.astype(complex)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return np.power(a_arr, b_arr)


def _as_text(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, np.ndarray):
        return "".join(chr(int(v)) for v in x.reshape(-1))
    if _is_number(x):
        return chr(int(x))
    return str(x)


def _lib_attr(name: str) -> str:
    return f"f_{name}"


# ──────────────────────────────────────────────────────────────
#  The MATLAB library
# ──────────────────────────────────────────────────────────────

def _nargout(fn):
    fn._ml_nargout = True
    fn._ml_function = True
    return fn


def _named(fn):
    fn._ml_names = True
    return fn


_LINESPEC = re.compile(r"^(-|--|:|-\.)?[rgbcmykw]?[.o+*xsd^v<>ph]?(-|--|:|-\.)?"
                       r"[rgbcmykw]?$")


def _is_linespec(x) -> bool:
    return isinstance(x, str) and bool(x) and bool(_LINESPEC.match(x))


class _Library:
    """MATLAB's own functions, with MATLAB's shapes and argument rules."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.names = {n[2:] for n in dir(self) if n.startswith("f_")}

    # ── constants ───────────────────────────────────────────────

    f_pi = math.pi
    f_Inf = f_inf = math.inf
    f_NaN = f_nan = math.nan
    f_eps = float(np.finfo(float).eps)
    f_i = f_j = 1j
    f_true = True
    f_false = False
    f_realmax = float(np.finfo(float).max)
    f_realmin = float(np.finfo(float).tiny)

    # ── workspace and session ───────────────────────────────────

    def f_clc(self, *_):
        return None

    def f_clear(self, *names):
        self.rt.clear(tuple(n for n in names if isinstance(n, str)))

    f_clearvars = f_clear

    def f_close(self, *args):
        self.rt.figures = Figures()
        self.rt.figures.close_requested = True

    def f_clf(self, *_):
        figs = self.rt.figures
        if figs.figure() in figs.specs:
            figs.specs.remove(figs.figure())
        figs.new()

    @_nargout
    def f_figure(self, *_, nargout=0):
        figs = self.rt.figures
        figs.new()
        # A handle is the figure's number: the one its next plot will get.
        return len(figs.specs) + 1 if nargout else None

    @_nargout
    def f_gcf(self, nargout=1):
        figs = self.rt.figures
        current = figs.figure()
        return (figs.specs.index(current) + 1 if current in figs.specs
                else len(figs.specs) + 1)

    f_gca = f_gcf

    def f_subplot(self, m, n=None, p=None, *_):
        if n is None:                      # subplot(211)
            digits = str(int(m))
            if len(digits) != 3:
                raise MatlabError("subplot needs subplot(m, n, p).")
            m, n, p = (int(d) for d in digits)
        rows, cols = int(m), int(n)
        cells = tuple(sorted(int(c) for c in np.atleast_1d(p).reshape(-1)))
        if not cells or cells[0] < 1 or cells[-1] > rows * cols:
            raise MatlabError(f"Index exceeds number of subplots "
                              f"({rows * cols}).")
        self.rt.figures.subplot(rows, cols, cells)

    def f_sgtitle(self, text, *_):
        figs = self.rt.figures
        (figs.grid or figs.ensure()).title = _as_text(text)

    def f_hold(self, state=None):
        figs = self.rt.figures
        figs.hold = (not figs.hold) if state is None else \
            str(state).lower() in ("on", "all")
        if figs.pane is not None:
            figs.pane["hold"] = figs.hold

    def f_grid(self, *args):
        figs = self.rt.figures
        if figs.current is not None:
            figs.current.extra["grid"] = (args[0] if args else "on")

    def f_box(self, *_):
        return None

    f_sgrid = f_zgrid = f_drawnow = f_box
    f_more = f_pkg = f_beep = f_shg = f_box

    def f_format(self, *args):
        _FORMAT["long"] = bool(args) and str(args[0]).lower().startswith(
            "long")

    def f_pause(self, seconds=None, *_):
        """``pause(t)`` waits t seconds; a bare ``pause`` waits for no key."""
        if seconds is None or isinstance(seconds, str):
            return None
        t = float(np.real(_scalar_of(seconds)))
        if math.isfinite(t) and t > 0:
            _pause_for(t)

    def f_tic(self):
        self.rt._tic = time.perf_counter()

    @_nargout
    def f_toc(self, nargout=1):
        elapsed = time.perf_counter() - self.rt._tic
        if nargout == 0:
            print(f"Elapsed time is {elapsed:.6f} seconds.")
            return None
        return elapsed

    def f_exist(self, name, *_):
        if name in self.rt.ns:
            return 1
        if self.rt.find_file(name, refresh=True) is not None \
                or os.path.isfile(self.rt.resolve(name)):
            return 2
        if os.path.isdir(self.rt.resolve(name)):
            return 7
        return 5 if name in self.names else 0

    # ── files and folders ───────────────────────────────────────

    @_nargout
    def f_cd(self, folder=None, nargout=0):
        if folder is not None:
            self.rt.cd(folder)
            return None
        if nargout:
            return self.rt.folder
        print(self.rt.folder)
        return None

    def f_pwd(self):
        return self.rt.folder

    def f_addpath(self, *folders):
        at_end = any(str(f).lower() == "-end" for f in folders)
        added = [self.rt.resolve(p) for f in folders
                 if not str(f).startswith("-")
                 for p in _as_text(f).split(os.pathsep) if p]
        path = [p for p in self.rt.path if p not in added]
        self.rt.path = path + added if at_end else added + path

    def f_rmpath(self, *folders):
        gone = {self.rt.resolve(f) for f in folders}
        self.rt.path = [p for p in self.rt.path if p not in gone]

    def f_fullfile(self, *parts):
        return os.path.join(*(_as_text(p) for p in parts)) if parts else ""

    @_nargout
    def f_fileparts(self, name, nargout=1):
        name = _as_text(name)
        folder, base = os.path.split(name)
        stem, ext = os.path.splitext(base)
        return (folder, stem, ext)[:nargout] if nargout >= 2 else folder

    def f_isfile(self, name):
        return os.path.isfile(self.rt.resolve(name))

    def f_isfolder(self, name):
        return os.path.isdir(self.rt.resolve(name))

    f_isdir = f_isfolder

    def f_mkdir(self, *parts):
        os.makedirs(self.rt.resolve(os.path.join(*map(_as_text, parts))),
                    exist_ok=True)
        return True

    def f_input(self, *_):
        raise MatlabError("input() needs a keyboard; scripts here run "
                          "unattended. Set the value in the script instead.")

    f_keyboard = f_input

    def f_error(self, message="", *args):
        text = self.f_sprintf(message, *args) if args else str(message)
        raise MatlabError(text)

    def f_warning(self, message="", *args):
        if str(message).lower() in ("on", "off", "query"):
            return None
        print("Warning: " + (self.f_sprintf(message, *args) if args
                             else str(message)))

    def f_assert(self, cond, message="Assertion failed.", *args):
        if not Runtime.truth(cond):
            self.f_error(message, *args)

    # ── text ────────────────────────────────────────────────────

    def f_disp(self, x):
        if isinstance(x, str):
            print(x)
        elif x is None or (isinstance(x, np.ndarray) and x.size == 0):
            return None
        else:
            print(display(x))

    f_display = f_disp

    def f_fprintf(self, fmt, *args):
        if isinstance(fmt, (int, float)) and fmt in (1, 2) and args:
            fmt, args = args[0], args[1:]      # fprintf(1, ...) → stdout
        print(self.f_sprintf(fmt, *args), end="")

    def f_sprintf(self, fmt, *args) -> str:
        return _sprintf(str(fmt), args)

    def f_num2str(self, x, spec=None) -> str:
        if isinstance(x, str):
            return x
        if isinstance(spec, str):
            return self.f_sprintf(spec, x)
        values = np.atleast_1d(np.asarray(x)).reshape(-1)
        return "  ".join(_num2str(v, spec) for v in values)

    def f_int2str(self, x) -> str:
        values = np.atleast_1d(np.round(np.asarray(x, float))).reshape(-1)
        return "  ".join(str(int(v)) for v in values)

    def f_mat2str(self, x, precision=15) -> str:
        if _is_number(x):
            return f"{x:.{precision}g}"
        a = _as2d(x)
        rows = [" ".join(f"{v:.{precision}g}" for v in row) for row in a]
        text = ";".join(rows)
        return text if a.size == 1 else f"[{text}]"

    def f_str2num(self, text):
        return float(text)

    f_str2double = f_str2num

    def f_strcat(self, *parts):
        return "".join(p.rstrip() if isinstance(p, str) else _as_text(p)
                       for p in parts)

    def f_strcmp(self, a, b):
        return isinstance(a, str) and isinstance(b, str) and a == b

    def f_strcmpi(self, a, b):
        return isinstance(a, str) and isinstance(b, str) and \
            a.lower() == b.lower()

    def f_upper(self, s):
        return s.upper()

    def f_lower(self, s):
        return s.lower()

    def f_strtrim(self, s):
        return s.strip()

    def f_strrep(self, s, old, new):
        return s.replace(old, new)

    def f_newline(self):
        return "\n"

    def f_char(self, x):
        return _as_text(x)

    f_string = f_char

    # ── types ───────────────────────────────────────────────────

    def f_class(self, x) -> str:
        if isinstance(x, str):
            return "char"
        if isinstance(x, (bool, np.bool_)) or (isinstance(x, np.ndarray)
                                               and x.dtype == bool):
            return "logical"
        if isinstance(x, Cell):
            return "cell"
        if isinstance(x, (Struct, StructArray)):
            return "struct"
        if isinstance(x, ctl.TransferFunction):
            return "tf"
        if isinstance(x, ctl.StateSpace):
            return "ss"
        if _is_function(x):
            return "function_handle"
        return "double"

    def f_isa(self, x, name):
        return self.f_class(x) == name or (name == "numeric"
                                           and self.f_class(x) == "double")

    def f_isnumeric(self, x):
        return self.f_class(x) == "double"

    def f_ischar(self, x):
        return isinstance(x, str)

    def f_iscell(self, x):
        return isinstance(x, Cell)

    def f_isstruct(self, x):
        return isinstance(x, (Struct, StructArray))

    def f_islogical(self, x):
        return self.f_class(x) == "logical"

    def f_isfield(self, s, name):
        return isinstance(s, Mapping) and name in s

    def f_fieldnames(self, s):
        if isinstance(s, StructArray):
            s = s[0] if s else {}
        return Cell(s.keys())

    def f_struct(self, *pairs):
        out = Struct()
        for k in range(0, len(pairs) - 1, 2):
            out[pairs[k]] = pairs[k + 1]
        return out

    def f_struct2table(self, s):
        rows = list(s) if isinstance(s, StructArray) else [s]
        return Table(rows)

    def f_cell(self, *dims):
        n = int(np.prod([int(d) for d in np.atleast_1d(dims)])) if dims else 0
        return Cell(np.zeros((0, 0)) for _ in range(n))

    def f_num2cell(self, x):
        return Cell(_scalar(v) for v in np.atleast_1d(x).reshape(-1))

    # ── sizes ───────────────────────────────────────────────────

    @_nargout
    def f_size(self, x, dim=None, nargout=1):
        r, c = _shape(x)
        if dim is not None:
            return (r, c, 1)[int(dim) - 1] if int(dim) <= 3 else 1
        if nargout >= 2:
            return (r, c) + (1,) * (nargout - 2)
        return np.array([r, c], dtype=float)

    def f_length(self, x):
        r, c = _shape(x)
        return 0 if r == 0 or c == 0 else max(r, c)

    def f_numel(self, x):
        return _numel(x)

    def f_ndims(self, x):
        return 2

    def f_isempty(self, x):
        return _numel(x) == 0

    def f_isscalar(self, x):
        return _numel(x) == 1

    def f_isvector(self, x):
        r, c = _shape(x)
        return (r == 1 or c == 1) and r * c >= 1

    def f_isrow(self, x):
        return _shape(x)[0] == 1

    def f_iscolumn(self, x):
        return _shape(x)[1] == 1

    # ── construction ────────────────────────────────────────────

    @staticmethod
    def _dims(dims) -> tuple[int, int]:
        if not dims:
            return (1, 1)
        if len(dims) == 1:
            d = np.atleast_1d(dims[0]).astype(int)
            return (int(d[0]), int(d[0])) if d.size == 1 else (int(d[0]),
                                                               int(d[1]))
        return (int(dims[0]), int(dims[1]))

    def _filled(self, fill, dims):
        dims = tuple(d for d in dims if not isinstance(d, str))
        r, c = self._dims(dims)
        return _normalise_row(fill((r, c)), True) if r == 1 else fill((r, c))

    def f_zeros(self, *dims):
        out = self._filled(np.zeros, dims)
        return _scalar(out[0]) if np.size(out) == 1 else out

    def f_ones(self, *dims):
        out = self._filled(np.ones, dims)
        return _scalar(out[0]) if np.size(out) == 1 else out

    def f_eye(self, *dims):
        r, c = self._dims(dims)
        return 1 if (r, c) == (1, 1) else np.eye(r, c)

    def f_rand(self, *dims):
        out = self._filled(lambda s: np.random.rand(*s), dims)
        return float(out[0]) if np.size(out) == 1 else out

    def f_randn(self, *dims):
        out = self._filled(lambda s: np.random.randn(*s), dims)
        return float(out[0]) if np.size(out) == 1 else out

    def f_linspace(self, a, b, n=100):
        return np.linspace(float(a), float(b), int(n))

    def f_logspace(self, a, b, n=50):
        return np.logspace(float(a), float(b), int(n))

    def f_repmat(self, x, m, n=None):
        if n is None:
            m, n = self._dims((m,))
        if isinstance(x, str):
            return x * int(n)
        return _normalise_row(np.tile(_as2d(x), (int(m), int(n))), True)

    def f_reshape(self, x, *dims):
        dims = [int(d) for d in (np.atleast_1d(dims[0]) if len(dims) == 1
                                 else dims)]
        out = _as2d(x).reshape(-1, order="F").reshape(dims, order="F")
        return _normalise_row(out, True)

    def f_diag(self, x, k=0):
        a = np.asarray(x)
        if a.ndim == 2 and min(a.shape) > 1:
            return np.diag(a, int(k)).reshape(-1, 1)
        return np.diag(a.reshape(-1), int(k))

    def f_horzcat(self, *xs):
        return self.rt.concat([list(xs)])

    def f_vertcat(self, *xs):
        return self.rt.concat([[x] for x in xs])

    def f_fliplr(self, x):
        a = np.asarray(x)
        return a[::-1] if a.ndim == 1 else a[:, ::-1]

    def f_flipud(self, x):
        a = np.asarray(x)
        return a if a.ndim == 1 else a[::-1, :]

    def f_flip(self, x):
        a = np.asarray(x)
        return a[::-1] if a.ndim == 1 or a.shape[0] == 1 else a[::-1, :]

    # ── elementwise maths ───────────────────────────────────────

    def _ew(fn):                               # noqa: N805 — helper
        def wrapper(self, *args):
            with np.errstate(divide="ignore", invalid="ignore"):
                out = fn(*args)
            return _scalar(out) if np.ndim(out) == 0 else out
        return wrapper

    f_abs = _ew(np.abs)
    f_sqrt = _ew(np.emath.sqrt)
    f_exp = _ew(np.exp)
    f_log = _ew(np.emath.log)
    f_log10 = _ew(np.emath.log10)
    f_log2 = _ew(np.emath.log2)
    f_sin = _ew(np.sin)
    f_cos = _ew(np.cos)
    f_tan = _ew(np.tan)
    f_asin = _ew(np.arcsin)
    f_acos = _ew(np.arccos)
    f_atan = _ew(np.arctan)
    f_atan2 = _ew(np.arctan2)
    f_sinh = _ew(np.sinh)
    f_cosh = _ew(np.cosh)
    f_tanh = _ew(np.tanh)
    f_floor = _ew(np.floor)
    f_ceil = _ew(np.ceil)
    f_fix = _ew(np.trunc)
    f_sign = _ew(np.sign)
    f_real = _ew(np.real)
    f_imag = _ew(np.imag)
    f_conj = _ew(np.conj)
    f_angle = _ew(np.angle)
    f_hypot = _ew(np.hypot)
    f_deg2rad = _ew(np.deg2rad)
    f_rad2deg = _ew(np.rad2deg)
    f_isnan = _ew(np.isnan)
    f_isinf = _ew(np.isinf)
    f_isfinite = _ew(np.isfinite)
    f_mod = _ew(lambda a, b: np.where(np.asarray(b) == 0, a, np.mod(a, b)))
    f_rem = _ew(lambda a, b: np.where(np.asarray(b) == 0, a, np.fmod(a, b)))
    f_mag2db = _ew(lambda m: 20 * np.log10(m))
    f_db = f_mag2db
    f_db2mag = _ew(lambda d: 10 ** (np.asarray(d) / 20))
    del _ew

    def f_round(self, x, digits=0):
        a = np.asarray(x, dtype=complex if np.iscomplexobj(x) else float)
        scale = 10.0 ** int(digits)
        out = np.sign(a.real) * np.floor(np.abs(a.real) * scale + 0.5) / scale
        return _scalar(out) if out.ndim == 0 else out

    def f_isreal(self, x):
        return not np.iscomplexobj(x) or bool(np.all(np.imag(x) == 0))

    # ── reductions ──────────────────────────────────────────────

    @staticmethod
    def _axis(a: np.ndarray, dim):
        if dim is not None:
            return int(dim) - 1
        if a.ndim == 1 or a.shape[0] == 1:
            return None
        return 0

    def _reduce(self, fn, x, dim=None):
        a = np.asarray(x)
        if a.size == 0:
            return fn(np.zeros(0))
        out = fn(a if a.ndim > 1 and dim is not None or a.ndim > 1 and
                 a.shape[0] > 1 else a.reshape(-1), axis=self._axis(a, dim))
        return _normalise(np.asarray(out)) if np.ndim(out) else _scalar(out)

    def f_sum(self, x, dim=None):
        return self._reduce(np.sum, x, dim)

    def f_prod(self, x, dim=None):
        return self._reduce(np.prod, x, dim)

    def f_mean(self, x, dim=None):
        return self._reduce(np.mean, x, dim)

    def f_median(self, x, dim=None):
        return self._reduce(np.median, x, dim)

    def f_std(self, x, w=0, dim=None):
        return self._reduce(lambda a, axis=None: np.std(a, axis=axis,
                                                        ddof=0 if w else 1),
                            x, dim)

    def f_cumsum(self, x, dim=None):
        a = np.asarray(x)
        return np.cumsum(a, axis=self._axis(a, dim) or 0) if a.ndim > 1 \
            else np.cumsum(a)

    def f_cumprod(self, x, dim=None):
        a = np.asarray(x)
        return np.cumprod(a, axis=self._axis(a, dim) or 0) if a.ndim > 1 \
            else np.cumprod(a)

    def f_diff(self, x, n=1):
        return np.diff(np.asarray(x), int(n), axis=0 if np.ndim(x) > 1
                       and np.shape(x)[0] > 1 else -1)

    def f_any(self, x, dim=None):
        return bool(np.any(x)) if dim is None else self._reduce(np.any, x,
                                                               dim)

    def f_all(self, x, dim=None):
        return bool(np.all(x)) if dim is None else self._reduce(np.all, x,
                                                               dim)

    def _extreme(self, pick, arg, x, other, dim, nargout):
        if other is not None and _numel(other) > 0:
            out = pick(np.asarray(x), np.asarray(other))
            return _scalar(out) if np.ndim(out) == 0 else out
        a = np.asarray(x)
        if a.size == 0:
            return np.zeros((0, 0))
        if np.iscomplexobj(a):
            key = np.abs(a)
        else:
            key = a
        if a.ndim == 1 or a.shape[0] == 1 and dim is None:
            flat, k = a.reshape(-1), key.reshape(-1)
            i = int(arg(np.where(np.isnan(k), -np.inf if arg is np.argmax
                                 else np.inf, k)))
            value = _scalar(flat[i])
            return (value, i + 1) if nargout >= 2 else value
        axis = self._axis(a, dim) or 0
        idx = arg(key, axis=axis)
        values = np.take_along_axis(a, np.expand_dims(idx, axis), axis)
        values = _normalise(values)
        return (values, _normalise(np.asarray(idx + 1, float))) \
            if nargout >= 2 else values

    @_nargout
    def f_max(self, x, other=None, dim=None, nargout=1):
        return self._extreme(np.maximum, np.argmax, x, other, dim, nargout)

    @_nargout
    def f_min(self, x, other=None, dim=None, nargout=1):
        return self._extreme(np.minimum, np.argmin, x, other, dim, nargout)

    @_nargout
    def f_sort(self, x, mode="ascend", nargout=1):
        a = np.asarray(x)
        flat = a.ndim == 1 or a.shape[0] == 1
        axis = -1 if flat else 0
        order = np.argsort(a, axis=axis, kind="stable")
        if str(mode).lower().startswith("desc"):
            order = np.flip(order, axis=axis)
        values = np.take_along_axis(a, order, axis)
        return (values, order + 1.0) if nargout >= 2 else values

    def f_unique(self, x):
        return np.unique(np.asarray(x))

    @_nargout
    def f_find(self, x, n=None, nargout=1):
        a = np.asarray(x)
        idx = np.nonzero(a.reshape(-1, order="F"))[0] + 1.0
        if n is not None:
            idx = idx[:int(n)]
        if a.ndim == 2 and a.shape[0] > 1:
            idx = idx.reshape(-1, 1)
        return idx

    @staticmethod
    def _integrand(x, y, dim):
        """``trapz``'s inputs: the samples, their spacing, and the axis."""
        if y is None:
            x, y = None, x
        Y = np.asarray(y)
        if Y.ndim == 2 and dim is None and Y.shape[0] == 1:
            Y = Y.reshape(-1)
        axis = (int(dim) - 1) if dim is not None and Y.ndim == 2 else (
            0 if Y.ndim == 2 and Y.shape[0] > 1 else -1)
        if x is None:
            return Y, {"dx": 1.0}, axis
        if _numel(x) == 1:
            return Y, {"dx": float(_scalar_of(x))}, axis
        return Y, {"x": np.asarray(x, float).reshape(-1)}, axis

    def f_trapz(self, x, y=None, dim=None):
        from scipy.integrate import trapezoid
        Y, step, axis = self._integrand(x, y, dim)
        out = trapezoid(Y, axis=axis, **step)
        return _normalise(np.asarray(out)) if np.ndim(out) else _scalar(out)

    def f_cumtrapz(self, x, y=None, dim=None):
        from scipy.integrate import cumulative_trapezoid
        Y, step, axis = self._integrand(x, y, dim)
        return cumulative_trapezoid(Y, axis=axis, initial=0, **step)

    def f_interp1(self, *args):
        """
        ``interp1(x, v, xq[, method][, extrapolation])`` or
        ``interp1(v, xq)``. Outside the samples the answer is NaN unless
        extrapolation is asked for — except for 'spline', 'pchip' and
        'makima', which extrapolate by default, as in MATLAB.
        """
        from scipy import interpolate
        first_text = next((k for k, a in enumerate(args)
                           if isinstance(a, str)), len(args))
        data, options = args[:first_text], args[first_text:]
        if len(data) == 2:
            v, xq = data
            r, c = _shape(v)
            x = np.arange(1.0, (r * c if 1 in (r, c) else r) + 1)
        elif len(data) >= 3:
            x, v, xq = data[:3]
            options = args[3:]
        else:
            raise MatlabError("interp1 needs sample points and values.")
        method = "linear"
        fill = math.nan
        extrapolate = None
        for opt in options:
            if isinstance(opt, str):
                word = opt.lower().lstrip("*")
                if word == "extrap":
                    extrapolate = True
                else:
                    method = word
            else:
                fill, extrapolate = float(_scalar_of(opt)), False
        if extrapolate is None:
            extrapolate = method in ("spline", "pchip", "cubic", "makima")
        x = np.asarray(x, float).reshape(-1)
        V = np.asarray(v)
        if V.ndim == 2 and 1 in V.shape:
            V = V.reshape(-1)
        order = np.argsort(x, kind="stable")
        x, V = x[order], V[order]
        q = np.asarray(xq, float)
        if method in ("spline",):
            f = interpolate.CubicSpline(x, V, axis=0)
        elif method in ("pchip", "cubic"):
            f = interpolate.PchipInterpolator(x, V, axis=0)
        elif method == "makima":
            f = interpolate.Akima1DInterpolator(x, V, axis=0, method="makima")
        elif method in ("linear", "nearest", "previous", "next"):
            f = interpolate.interp1d(x, V, kind=method, axis=0,
                                     bounds_error=False,
                                     fill_value="extrapolate" if extrapolate
                                     else fill, assume_sorted=True)
        else:
            raise MatlabError(f"Invalid interpolation method '{method}'.")
        flat = q.reshape(-1)
        out = np.asarray(f(flat))
        if not extrapolate:
            outside = (flat < x[0]) | (flat > x[-1])
            out[outside] = fill
        if V.ndim == 1:
            out = out.reshape(q.shape)
            return _scalar(out) if out.ndim == 0 else out
        return out

    # ── linear algebra and polynomials ──────────────────────────

    def f_inv(self, a):
        return _normalise(np.linalg.inv(_as2d(a)))

    def f_det(self, a):
        return float(np.real_if_close(np.linalg.det(_as2d(a))))

    def f_rank(self, a):
        return int(np.linalg.matrix_rank(_as2d(a)))

    def f_trace(self, a):
        return _scalar(np.trace(_as2d(a)))

    def f_norm(self, x, p=2):
        a = np.asarray(x)
        if isinstance(p, str):
            p = {"inf": np.inf, "fro": "fro"}.get(p.lower(), 2)
        return float(np.linalg.norm(a if a.ndim == 1 else a, p))

    @_nargout
    def f_eig(self, a, nargout=1):
        if _is_lti(a):
            return api.pole(a).reshape(-1, 1)
        vals, vecs = np.linalg.eig(_as2d(a))
        vals = np.real_if_close(vals)
        if nargout >= 2:
            return np.real_if_close(vecs), np.diag(vals)
        return vals.reshape(-1, 1)

    def f_kron(self, a, b):
        return _normalise(np.kron(_as2d(a), _as2d(b)))

    def f_roots(self, p):
        return np.roots(np.asarray(p, float).reshape(-1)).reshape(-1, 1)

    def f_poly(self, r):
        # A vector of roots, row or column (roots returns a column), or a
        # square matrix for its characteristic polynomial.
        r = np.asarray(r)
        if r.ndim != 2 or 1 in r.shape:
            r = r.reshape(-1)
        return np.real_if_close(np.poly(r))

    def f_polyval(self, p, x):
        out = np.polyval(np.asarray(p).reshape(-1), x)
        return _scalar(out) if np.ndim(out) == 0 else out

    def f_polyfit(self, x, y, n):
        return np.polyfit(np.asarray(x).reshape(-1),
                          np.asarray(y).reshape(-1), int(n))

    def f_conv(self, a, b, shape="full"):
        u = np.atleast_1d(np.asarray(a)).reshape(-1)
        v = np.atleast_1d(np.asarray(b)).reshape(-1)
        full = np.convolve(u, v)
        shape = str(shape).lower()
        if shape == "same":              # the central part, as long as u
            start = int(math.ceil((v.size - 1) / 2))
            out = full[start:start + u.size]
        elif shape == "valid":
            out = full[v.size - 1:u.size] if u.size >= v.size else \
                np.zeros(0)
        else:
            out = full
        # Shaped like the longer input (b on a tie), as MATLAB's conv.m
        # filters the longer one; 'same' is shaped like u.
        like = a if shape == "same" or u.size > v.size else b
        column = _shape(like)[1] == 1 and _numel(like) > 1
        return out.reshape(-1, 1) if column else out

    @_nargout
    def f_deconv(self, a, b, nargout=1):
        u = np.atleast_1d(np.asarray(a)).reshape(-1)
        q, r = np.polydiv(u, np.atleast_1d(np.asarray(b)).reshape(-1))
        # MATLAB's remainder is as long as the dividend, zeros in front.
        r = np.concatenate([np.zeros(max(u.size - r.size, 0)), r])
        return (q, r) if nargout >= 2 else q

    @_nargout
    def f_meshgrid(self, x, y=None, z=None, nargout=1):
        xv = np.asarray(x).reshape(-1)
        yv = xv if y is None else np.asarray(y).reshape(-1)
        X, Y = np.meshgrid(xv, yv)
        out = (_normalise(X), _normalise(Y))
        return out[:nargout] if nargout >= 2 else out[0]

    # ── signal processing ───────────────────────────────────────

    @staticmethod
    def _along(x, dim=None) -> tuple[np.ndarray, int]:
        """
        ``x`` as 2-D and the axis an operation runs along: ``dim``, else
        the first dimension that is not 1 — down the columns of a matrix,
        along a vector whichever way it lies.
        """
        A = _as2d(np.asarray(x))
        if dim is not None and _numel(dim):
            return A, int(_scalar_of(dim)) - 1
        return A, (0 if A.shape[0] != 1 or A.shape[1] == 1 else 1)

    @staticmethod
    def _length(n):
        return None if n is None or _numel(n) == 0 else int(_scalar_of(n))

    def f_fft(self, x, n=None, dim=None):
        A, axis = self._along(x, dim)
        if axis > 1:
            return x
        return _normalise(np.fft.fft(A, n=self._length(n), axis=axis))

    def f_ifft(self, x, *args):
        symmetric = any(str(a).lower() == "symmetric" for a in args
                        if isinstance(a, str))
        nums = [a for a in args if not isinstance(a, str)]
        A, axis = self._along(x, nums[1] if len(nums) > 1 else None)
        if axis > 1:
            return x
        n = self._length(nums[0] if nums else None) or A.shape[axis]
        # The spectrum actually transformed: x cut or zero-padded to n.
        if n <= A.shape[axis]:
            X = np.take(A, range(n), axis=axis)
        else:
            pad = [(0, 0), (0, 0)]
            pad[axis] = (0, n - A.shape[axis])
            X = np.pad(A, pad)
        if symmetric:
            half = np.take(X, range(n // 2 + 1), axis=axis)
            return _normalise(np.fft.irfft(half, n=n, axis=axis))
        out = np.fft.ifft(X, axis=axis)
        # MATLAB returns a real signal when the spectrum is exactly
        # conjugate-symmetric, as a real signal's always is.
        mirror = np.roll(np.flip(X, axis=axis), 1, axis=axis)
        if np.array_equal(X, np.conj(mirror)):
            out = out.real
        return _normalise(out)

    def _shift(self, fn, x, dim):
        a = np.asarray(x)
        if dim is not None:
            A = _as2d(a)
            return _normalise(fn(A, axes=int(_scalar_of(dim)) - 1))
        return fn(a)

    def f_fftshift(self, x, dim=None):
        return self._shift(np.fft.fftshift, x, dim)

    def f_ifftshift(self, x, dim=None):
        return self._shift(np.fft.ifftshift, x, dim)

    @_nargout
    def f_filter(self, b, a, x, zi=None, dim=None, nargout=1):
        from scipy.signal import lfilter
        bb = np.atleast_1d(np.asarray(b)).reshape(-1)
        aa = np.atleast_1d(np.asarray(a)).reshape(-1)
        if not aa.size or aa[0] == 0:
            raise MatlabError("First denominator filter coefficient must be "
                              "non-zero.")
        A, axis = self._along(x, dim)
        k = max(aa.size, bb.size) - 1
        z = None
        if zi is not None and _numel(zi):
            z = np.asarray(zi).reshape(k, -1)
            z = z if axis == 0 else z.T
        elif nargout >= 2:
            z = np.zeros((k, A.shape[1]) if axis == 0 else (A.shape[0], k))
        if z is None:
            y = lfilter(bb, aa, A, axis=axis)
        else:
            y, zf = lfilter(bb, aa, A, axis=axis, zi=z)
        y = y.reshape(-1) if np.ndim(x) <= 1 else y
        y = _scalar(y.reshape(-1)[0]) if np.ndim(x) == 0 else y
        if nargout >= 2:
            zf = zf if axis == 0 else zf.T
            return y, (zf.reshape(-1, 1) if 1 in zf.shape else zf)
        return y

    def _iir(self, design, n, edges, options, nargout, *ripple):
        """butter, cheby1, cheby2, ellip: MATLAB's argument order."""
        from scipy import signal
        wn = np.asarray(edges, float).reshape(-1)
        btype, analog = ("bandpass" if wn.size == 2 else "lowpass"), False
        for opt in options:
            word = str(opt).lower()
            if word == "s":
                analog = True
            elif word in ("low", "high", "bandpass", "stop", "bandstop"):
                btype = {"low": "lowpass", "high": "highpass",
                         "stop": "bandstop"}.get(word, word)
        output = {3: "zpk", 4: "ss"}.get(nargout, "ba")
        out = getattr(signal, design)(int(n), *ripple,
                                      wn if wn.size > 1 else float(wn[0]),
                                      btype=btype, analog=analog,
                                      output=output)
        if output == "zpk":
            z, p, k = out
            return z.reshape(-1, 1), p.reshape(-1, 1), float(k)
        if output == "ss":
            return tuple(_normalise(np.asarray(m)) for m in out)
        b, a = (np.real_if_close(np.asarray(c)) for c in out)
        return (b, a) if nargout >= 2 else b

    @_nargout
    def f_butter(self, n, wn, *options, nargout=1):
        return self._iir("butter", n, wn, options, nargout)

    @_nargout
    def f_cheby1(self, n, rp, wp, *options, nargout=1):
        return self._iir("cheby1", n, wp, options, nargout, float(rp))

    @_nargout
    def f_cheby2(self, n, rs, ws, *options, nargout=1):
        return self._iir("cheby2", n, ws, options, nargout, float(rs))

    @_nargout
    def f_ellip(self, n, rp, rs, wp, *options, nargout=1):
        return self._iir("ellip", n, wp, options, nargout, float(rp),
                         float(rs))

    @_nargout
    def f_freqz(self, b, a=1, n=512, *rest, nargout=1):
        """
        ``[h, w] = freqz(b, a, n)`` over [0, π) rad/sample, or
        ``[h, f] = freqz(b, a, n, fs)`` in Hz; ``n`` may be the frequencies
        themselves. With no outputs, magnitude over phase.
        """
        from scipy import signal
        whole = any(isinstance(r, str) and r.lower() == "whole"
                    for r in rest)
        numbers = [r for r in rest if not isinstance(r, str)]
        fs = float(_scalar_of(numbers[0])) if numbers else None
        grid = np.asarray(n, float).reshape(-1) if _numel(n) > 1 \
            else int(_scalar_of(n))
        w, h = signal.freqz(np.atleast_1d(np.asarray(b)).reshape(-1),
                            np.atleast_1d(np.asarray(a)).reshape(-1),
                            worN=grid, whole=whole,
                            fs=fs if fs else 2 * np.pi)
        if nargout == 0:
            figs = self.rt.figures
            figs.new()
            x = w if fs else w / np.pi
            label = "Frequency (Hz)" if fs else \
                "Normalized Frequency (×π rad/sample)"
            with np.errstate(divide="ignore"):
                magnitude = 20 * np.log10(np.abs(h))
            for k, (y, ylabel) in enumerate((
                    (magnitude, "Magnitude (dB)"),
                    (np.degrees(np.unwrap(np.angle(h))), "Phase (degrees)"))):
                figs.subplot(2, 1, (k + 1,))
                figs.collect(FigureSpec("xy", "", label, ylabel).add(x, y))
            figs.new()
            return None
        return (h.reshape(-1, 1), w.reshape(-1, 1))[:nargout] \
            if nargout >= 2 else h.reshape(-1, 1)

    @_nargout
    def f_findpeaks(self, y, *args, nargout=1):
        """
        Local maxima, the way MATLAB's findpeaks finds and filters them:
        a plateau counts once (at its left edge), the ends never count,
        then MinPeakHeight, Threshold, MinPeakProminence, MinPeakDistance,
        SortStr and NPeaks, in that order.
        """
        rest = list(args)
        data = np.asarray(y, float)
        flat = data.reshape(-1)
        x = np.arange(1.0, flat.size + 1)
        if rest and not isinstance(rest[0], str):
            given = rest.pop(0)
            if _numel(given) == 1:                 # findpeaks(y, Fs)
                x = np.arange(flat.size) / float(_scalar_of(given))
            else:
                x = np.asarray(given, float).reshape(-1)
        opts = {str(rest[k]).lower(): rest[k + 1]
                for k in range(0, len(rest) - 1, 2)}

        def opt(name, default):
            value = opts.get(name.lower())
            return default if value is None or (
                not isinstance(value, str) and _numel(value) == 0) else value

        padded = np.concatenate([[np.nan], flat, [np.nan]])
        index = np.arange(padded.size)
        finite = ~np.isnan(padded)
        keep = np.concatenate([[True], (padded[:-1] != padded[1:])
                               & (finite[:-1] | finite[1:])])
        index = index[keep]
        with np.errstate(invalid="ignore"):
            slope = np.sign(np.diff(padded[index]))
            peaks = index[1 + np.nonzero(np.diff(slope) < 0)[0]] - 1
        peaks = peaks[flat[peaks] > float(opt("MinPeakHeight", -np.inf))]
        threshold = float(opt("Threshold", 0.0))
        if threshold > 0 and peaks.size:
            base = np.maximum(flat[peaks - 1], flat[peaks + 1])
            peaks = peaks[flat[peaks] - base >= threshold]
        prominence = None
        if peaks.size and (nargout >= 4 or "minpeakprominence" in opts):
            from scipy.signal import peak_prominences
            prominence = peak_prominences(flat, peaks)[0]
            keep = prominence >= float(opt("MinPeakProminence", 0.0))
            peaks, prominence = peaks[keep], prominence[keep]
        distance = float(opt("MinPeakDistance", 0.0))
        if distance > 0 and peaks.size > 1:
            locs = x[peaks]
            delete = np.zeros(peaks.size, bool)
            for i in np.argsort(-flat[peaks], kind="stable"):
                if not delete[i]:
                    delete |= (locs >= locs[i] - distance) & (
                        locs <= locs[i] + distance)
                    delete[i] = False
            if prominence is not None:
                prominence = prominence[~delete]
            peaks = peaks[~delete]
        order = np.arange(peaks.size)
        sort = str(opt("SortStr", "none")).lower()
        if sort.startswith("desc"):
            order = np.argsort(-flat[peaks], kind="stable")
        elif sort.startswith("asc"):
            order = np.argsort(flat[peaks], kind="stable")
        npeaks = opt("NPeaks", None)
        if npeaks is not None:
            order = order[:int(_scalar_of(npeaks))]
        peaks = peaks[order]
        pks, locs = flat[peaks], x[peaks]
        if nargout == 0:
            spec = FigureSpec("xy").add(x, flat)
            spec.add(locs, pks, style="scatter")
            self.rt.figures.collect(spec)
            return None
        outputs = [pks, locs]
        if nargout >= 3:
            from scipy.signal import peak_widths
            widths = peak_widths(flat, peaks, rel_height=0.5)
            left = np.interp(widths[2], np.arange(flat.size), x)
            right = np.interp(widths[3], np.arange(flat.size), x)
            outputs.append(right - left)
            outputs.append(prominence[order] if prominence is not None
                           else np.zeros(peaks.size))
        column = data.ndim == 2 and data.shape[0] > 1
        outputs = [v.reshape(-1, 1) if column else v for v in outputs]
        return tuple(outputs[:nargout]) if nargout >= 2 else outputs[0]

    # ── differential equations and optimisation ─────────────────

    def f_odeset(self, *pairs):
        if pairs and isinstance(pairs[0], Mapping):
            out = Struct(pairs[0])
            pairs = pairs[1:]
        else:
            out = Struct()
        for k in range(0, len(pairs) - 1, 2):
            out[str(pairs[k])] = pairs[k + 1]
        return out

    f_optimset = f_odeset

    @staticmethod
    def _option(options, name, default):
        if isinstance(options, Mapping):
            for key, value in options.items():
                if key.lower() == name.lower() and _numel(value):
                    return value
        return default

    def _ode(self, solver, method, refine, f, tspan, y0, options, nargout):
        """
        Solve ``y' = f(t, y)`` with scipy's solver of the same family.

        With a two-element ``tspan`` the output is the solver's own steps,
        each refined with interpolated points (four for ode45, as MATLAB's
        Refine does); with more, the solution at exactly those times.
        """
        from scipy.integrate import solve_ivp
        ts = np.asarray(tspan, float).reshape(-1)
        if ts.size < 2:
            raise MatlabError("The time span must have at least two "
                              "elements.")
        start = np.asarray(y0).reshape(-1)
        start = start.astype(complex if np.iscomplexobj(start) else float)
        n = start.size

        def rhs(t, y):
            state = _scalar(y[0]) if n == 1 else y.reshape(-1, 1).copy()
            out = self.rt.call(f, (float(t), state), nargout=1)
            return np.asarray(out, dtype=y.dtype).reshape(-1)

        kwargs = {"rtol": float(_scalar_of(self._option(options, "RelTol",
                                                          1e-3))),
                  "atol": np.asarray(self._option(options, "AbsTol", 1e-6),
                                     float).reshape(-1)}
        if kwargs["atol"].size == 1:
            kwargs["atol"] = float(kwargs["atol"][0])
        for name, key in (("MaxStep", "max_step"),
                          ("InitialStep", "first_step")):
            value = self._option(options, name, None)
            if value is not None:
                kwargs[key] = float(_scalar_of(value))
        sol = solve_ivp(rhs, (ts[0], ts[-1]), start, method=method,
                        dense_output=True, **kwargs)
        if sol.status < 0:
            print(f"Warning: {solver}: {sol.message}")
        if ts.size > 2:
            t = ts
        else:
            steps = sol.t
            fractions = np.arange(1, refine + 1) / refine
            t = np.concatenate([steps[:1], (steps[:-1, None] + np.diff(
                steps)[:, None] * fractions).reshape(-1)])
        Y = sol.sol(t) if t.size else np.zeros((n, 0))
        if ts.size == 2:
            Y[:, ::refine] = sol.y          # the steps themselves, exactly
        Y = np.real_if_close(Y)
        if nargout == 0:
            spec = FigureSpec("xy", "", "t", "y")
            for row in Y:
                spec.add(t, np.real(row))
            self.rt.figures.collect(spec)
            return None
        if nargout == 1:
            return Struct(solver=solver, x=sol.t,
                          y=_normalise(np.asarray(sol.y)))
        return t.reshape(-1, 1), Y.T

    @_nargout
    def f_ode45(self, f, tspan, y0, options=None, *_, nargout=1):
        return self._ode("ode45", "RK45", 4, f, tspan, y0, options, nargout)

    @_nargout
    def f_ode23(self, f, tspan, y0, options=None, *_, nargout=1):
        return self._ode("ode23", "RK23", 1, f, tspan, y0, options, nargout)

    @_nargout
    def f_ode15s(self, f, tspan, y0, options=None, *_, nargout=1):
        return self._ode("ode15s", "BDF", 1, f, tspan, y0, options, nargout)

    @_nargout
    def f_ode23s(self, f, tspan, y0, options=None, *_, nargout=1):
        return self._ode("ode23s", "Radau", 1, f, tspan, y0, options,
                         nargout)

    def _scalar_fn(self, f):
        def g(x):
            out = self.rt.call(f, (_scalar(x),), nargout=1)
            return float(np.real(_scalar_of(out)))
        return g

    @_nargout
    def f_fzero(self, f, x0, options=None, nargout=1):
        """
        A root of ``f``: in the bracket ``[a b]``, or near ``x0`` — found
        by widening an interval around it by √2 each step until the sign
        changes, as MATLAB does, then Brent's method.
        """
        from scipy.optimize import brentq
        g = self._scalar_fn(f)
        start = np.asarray(x0, float).reshape(-1)
        if start.size >= 2:
            a, b = float(start[0]), float(start[1])
            fa, fb = g(a), g(b)
            if np.sign(fa) * np.sign(fb) > 0:
                raise MatlabError("The function values at the interval "
                                  "endpoints must differ in sign.")
        else:
            x = float(start[0])
            fx = g(x)
            a = b = x
            fa = fb = fx
            if fx != 0:
                dx = x / 50 if x else 1 / 50
                for _ in range(4000):
                    dx *= math.sqrt(2)
                    a, b = x - dx, x + dx
                    fa, fb = g(a), g(b)
                    if not (math.isfinite(fa) and math.isfinite(fb)):
                        raise MatlabError(
                            "Exiting fzero: aborting search for an interval "
                            "containing a sign change because NaN or Inf "
                            "function value encountered during search.")
                    if np.sign(fa) * np.sign(fb) <= 0:
                        break
                else:
                    raise MatlabError("Exiting fzero: aborting search for "
                                      "an interval containing a sign "
                                      "change.")
        if fa == 0:
            root = a
        elif fb == 0:
            root = b
        else:
            root = brentq(g, a, b, xtol=1e-300, rtol=4 * np.finfo(float).eps,
                          maxiter=500)
        out = (_scalar(root), g(root), 1,
               Struct(algorithm="bisection, interpolation"))
        return out[:nargout] if nargout >= 2 else out[0]

    @_nargout
    def f_fminsearch(self, f, x0, options=None, *_, nargout=1):
        """
        Nelder–Mead from ``x0``: scipy's, which starts from the same
        simplex MATLAB's does (5% steps, 0.00025 for zero components) and
        stops on the same TolX / TolFun tests.
        """
        from scipy.optimize import minimize
        start = np.asarray(x0, float)
        shape = start.shape

        def g(v):
            arg = _scalar(v[0]) if v.size == 1 else v.reshape(shape).copy()
            return float(np.real(_scalar_of(self.rt.call(f, (arg,),
                                                         nargout=1))))

        n = start.size
        limit = 200 * n
        res = minimize(g, start.reshape(-1), method="Nelder-Mead", options={
            "xatol": float(self._option(options, "TolX", 1e-4)),
            "fatol": float(self._option(options, "TolFun", 1e-4)),
            "maxiter": int(self._option(options, "MaxIter", limit)),
            "maxfev": int(self._option(options, "MaxFunEvals", limit))})
        x = res.x.reshape(shape) if n > 1 else _scalar(res.x[0])
        out = (x, float(res.fun), 1 if res.success else 0,
               Struct(iterations=int(res.nit), funcCount=int(res.nfev),
                      algorithm="Nelder-Mead simplex direct search"))
        return out[:nargout] if nargout >= 2 else out[0]

    @_nargout
    def f_fminbnd(self, f, a, b, options=None, nargout=1):
        from scipy.optimize import minimize_scalar
        res = minimize_scalar(self._scalar_fn(f), method="bounded",
                              bounds=(float(a), float(b)), options={
                                  "xatol": float(self._option(
                                      options, "TolX", 1e-4))})
        out = (_scalar(res.x), float(res.fun), 1 if res.success else 0)
        return out[:nargout] if nargout >= 2 else out[0]

    # ── audio ───────────────────────────────────────────────────

    def _audio_path(self, filename) -> str:
        path = self.rt.resolve(filename)
        if not os.path.isfile(path):
            raise MatlabError(f"The filename specified was not found in the "
                              f"MATLAB path: {_as_text(filename)}")
        return path

    @_nargout
    def f_audioread(self, filename, *args, nargout=1):
        """``[y, fs] = audioread(file[, [start stop]][, 'native'])``."""
        path = self._audio_path(filename)
        native = any(isinstance(a, str) and a.lower() == "native"
                     for a in args)
        y, fs, info = _read_audio(path, native)
        span = next((a for a in args if not isinstance(a, str)), None)
        if span is not None and _numel(span):
            lo, hi = np.asarray(span, float).reshape(-1)[:2]
            hi = y.shape[0] if math.isinf(hi) else int(hi)
            y = y[int(lo) - 1:hi]
        return (y, fs)[:nargout] if nargout >= 2 else y

    def f_audiowrite(self, filename, y, fs, *options):
        path = self.rt.resolve(filename)
        opts = {str(options[k]).lower(): options[k + 1]
                for k in range(0, len(options) - 1, 2)}
        bits = int(_scalar_of(opts.get("bitspersample", 16)))
        data = np.real(np.asarray(y))
        data = data.reshape(-1, 1) if data.ndim <= 1 else data
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        _write_audio(path, data, int(round(float(_scalar_of(fs)))), bits)

    def f_audioinfo(self, filename):
        path = self._audio_path(filename)
        info = _audio_info(path)
        frames, rate = info["frames"], info["rate"]
        out = Struct(Filename=path, CompressionMethod="Uncompressed",
                     NumChannels=info["channels"], SampleRate=rate,
                     TotalSamples=frames, Duration=frames / rate,
                     Title=np.zeros((0, 0)), Comment=np.zeros((0, 0)),
                     Artist=np.zeros((0, 0)),
                     BitsPerSample=info["bits"])
        return out

    def _play(self, y, fs) -> None:
        data = np.real(np.asarray(y, dtype=complex if np.iscomplexobj(y)
                                  else float))
        data = data.reshape(-1, 1) if data.ndim <= 1 else data
        if data.shape[1] > 2 and data.shape[0] <= 2:
            data = data.T                     # one row per channel
        data = np.clip(np.nan_to_num(data), -1.0, 1.0)
        if not _play(data, float(_scalar_of(fs))) and not self.rt._quiet:
            self.rt._quiet = True
            print("Warning: No audio output is available; sound() and "
                  "soundsc() will be silent.")

    def f_sound(self, y, fs=8192, *_):
        self._play(y, fs)

    def f_soundsc(self, y, fs=8192, *_):
        a = np.real(np.asarray(y, dtype=complex if np.iscomplexobj(y)
                               else float))
        peak = float(np.max(np.abs(a))) if a.size else 0.0
        self._play(a / peak if peak else a, fs)

    # ── workspace files ─────────────────────────────────────────

    def f_save(self, *args):
        import fnmatch

        import scipy.io
        words = [_as_text(a) for a in args]
        flags = {w.lower() for w in words if w.startswith("-")}
        names = [w for w in words if not w.startswith("-")]
        path = self.rt.resolve(names[0] if names else "matlab.mat")
        ascii_ = "-ascii" in flags
        if not os.path.splitext(path)[1] and not ascii_:
            path += ".mat"
        workspace = self.rt.workspace()
        chosen: dict[str, Any] = {}
        for pattern in names[1:] or ["*"]:
            hits = [k for k in workspace if fnmatch.fnmatchcase(k, pattern)]
            if not hits and not any(c in pattern for c in "*?["):
                raise MatlabError(f"Variable '{pattern}' not found.")
            chosen.update((k, workspace[k]) for k in hits)
        if ascii_:
            rows = [np.atleast_2d(np.asarray(v, float)) for v in
                    chosen.values()]
            np.savetxt(path, np.vstack(rows) if rows else np.zeros((0, 0)),
                       fmt="%.7e", delimiter="   ")
            return None
        data = {k: _to_mat(v) for k, v in chosen.items()}
        if "-append" in flags and os.path.isfile(path):
            old = scipy.io.loadmat(path)
            data = {**{k: v for k, v in old.items()
                       if not k.startswith("__")}, **data}
        scipy.io.savemat(path, data, oned_as="row", long_field_names=True)
        return None

    @_nargout
    def f_load(self, filename="matlab.mat", *names, nargout=0):
        import fnmatch

        import scipy.io
        path = self.rt.resolve(filename)
        if not os.path.isfile(path) and os.path.isfile(path + ".mat"):
            path += ".mat"
        if not os.path.isfile(path):
            raise MatlabError(f"Unable to find file or directory "
                              f"'{_as_text(filename)}'.")
        if path.lower().endswith(".mat"):
            raw = scipy.io.loadmat(path, squeeze_me=False,
                                   struct_as_record=False,
                                   chars_as_strings=True)
            values = {k: _from_mat(v) for k, v in raw.items()
                      if not k.startswith("__")}
        else:                                  # a text file of numbers
            matrix = _normalise(np.loadtxt(path, ndmin=2))
            if nargout:
                return matrix
            stem = re.sub(r"\W", "_", os.path.splitext(
                os.path.basename(path))[0])
            values = {stem: matrix}
        patterns = [n for n in map(_as_text, names) if not n.startswith("-")]
        if patterns:
            values = {k: v for k, v in values.items()
                      if any(fnmatch.fnmatchcase(k, p) for p in patterns)}
        if nargout:
            return Struct(values)
        self.rt.ns.update(values)
        return None

    # ── systems ─────────────────────────────────────────────────

    def f_tf(self, *args):
        if len(args) >= 2 and not isinstance(args[0], str):
            num, den = args[0], args[1]
            rest = [a for a in args[2:] if not isinstance(a, str)]
            return api.tf(_poly_arg(num), _poly_arg(den),
                          rest[0] if rest else None)
        if len(args) == 1 and _is_lti(args[0]):
            return ctl.tf(args[0])
        return api.tf(*args)

    def f_zpk(self, z, p=None, k=None, *rest):
        if _is_lti(z) and p is None:
            return z
        return api.zpk(np.atleast_1d(np.asarray(z, complex)).reshape(-1),
                       np.atleast_1d(np.asarray(p, complex)).reshape(-1),
                       float(k))

    def f_ss(self, *args):
        return api.ss(*args)

    @_nargout
    def f_tfdata(self, sys, form=None, nargout=1):
        G = ctl.tf(sys)
        num, den = G.num[0][0], G.den[0][0]
        # MATLAB pads the numerator with leading zeros to the denominator's
        # length: the coefficients of a common power of s (or z).
        num = np.concatenate([np.zeros(max(len(den) - len(num), 0)), num])
        if form == "v":
            out = (np.asarray(num, float), np.asarray(den, float))
        else:
            out = (Cell([np.asarray(num, float)]),
                   Cell([np.asarray(den, float)]))
        return out[:max(nargout, 1)] if nargout >= 2 else out[0]

    @_nargout
    def f_zpkdata(self, sys, form=None, nargout=1):
        z, p = api.zero(sys), api.pole(sys)
        k = _zpk_gain(sys)
        out = (z.reshape(-1, 1), p.reshape(-1, 1), k)
        if form != "v":
            out = (Cell([out[0]]), Cell([out[1]]), k)
        return out[:nargout] if nargout >= 2 else out[0]

    @_nargout
    def f_ssdata(self, sys, nargout=1):
        S = ctl.ss(sys)
        out = (np.asarray(S.A), np.asarray(S.B), np.asarray(S.C),
               np.asarray(S.D))
        return tuple(_normalise(m) for m in out[:nargout]) if nargout >= 2 \
            else out[0]

    def f_evalfr(self, sys, x):
        return _scalar(complex(sys(x)))

    def f_freqresp(self, sys, w):
        w = np.atleast_1d(np.asarray(w, float))
        return np.array([complex(sys(1j * x)) for x in w])

    def f_isstable(self, sys):
        poles = api.pole(sys)
        if getattr(sys, "dt", 0):
            return bool(np.all(np.abs(poles) < 1))
        return bool(np.all(np.real(poles) < 0))

    @_nargout
    def f_pade(self, T, n=1, nargout=1):
        G = api.pade(T, int(n))
        if nargout >= 2:
            G = ctl.tf(G)
            return (np.asarray(G.num[0][0], float),
                    np.asarray(G.den[0][0], float))
        return G

    def f_stepinfo(self, sys, *args):
        if isinstance(sys, np.ndarray):
            t = np.asarray(args[0] if args else np.arange(len(sys)), float)
            y = np.asarray(sys, float).reshape(-1)
            info = Struct(api.stepinfo((t.reshape(-1), y)))
        else:
            # The plotting window is sized to frame the slowest pole; a zero
            # near the origin can make the response settle well after that.
            # MATLAB simulates until it has settled, so widen until it does.
            span = None
            for _ in range(6):
                info = Struct(api.stepinfo(sys, t=span))
                t, y = api.step(sys, t=span, plot=False)
                t, y = np.asarray(t, float), np.asarray(y, float).reshape(-1)
                settle = info.get("SettlingTime", np.nan)
                if not np.isfinite(info.get("SteadyState", np.nan)) or (
                        np.isfinite(settle) and settle < 0.9 * t[-1]):
                    break
                span = np.linspace(0.0, 2.0 * t[-1], 4000)
        return _matlab_stepinfo(info, t.reshape(-1), y)

    @_nargout
    def f_damp(self, sys, nargout=1):
        table = api.damp(sys)
        if nargout == 0:
            print(repr(table))
            return None
        wn, zeta, p = table
        out = (wn.reshape(-1, 1), zeta.reshape(-1, 1), p.reshape(-1, 1))
        return out[:nargout] if nargout >= 2 else out[0]

    # ── plot options ────────────────────────────────────────────

    def f_bodeoptions(self, *_):
        return PlotOptions("bode", _BODE_DEFAULTS)

    def f_nyquistoptions(self, *_):
        return PlotOptions("nyquist", {"Grid": "off", "ShowFullContour":
                                       "on"})

    def f_timeoptions(self, *_):
        return PlotOptions("time", _TIME_DEFAULTS)

    f_stepDataOptions = f_timeoptions

    def f_pzoptions(self, *_):
        return PlotOptions("pz", {"Grid": "off"})

    # ── response plots ──────────────────────────────────────────

    def _systems(self, args, names):
        """Split a plot command's inputs: systems, grid, options, names."""
        systems, labels, rest, options = [], [], [], None
        names = names or (None,) * len(args)
        for value, name in zip(args, names):
            if _is_lti(value):
                systems.append(value)
                labels.append(name)
            elif isinstance(value, PlotOptions):
                options = value
            elif isinstance(value, str):
                continue
            else:
                rest.append(value)
        return systems, labels, rest, options

    def _label(self, spec: FigureSpec, labels) -> None:
        named = [t for t in spec.traces if t.label]
        for trace, label in zip(named, labels):
            if label:
                trace.label = label
        for k, entry in enumerate(spec.extra.get("phase", [])):
            if k < len(labels) and labels[k]:
                spec.extra["phase"][k] = (entry[0], entry[1], labels[k])

    def _time_plot(self, fn, args, nargout, names, title):
        systems, labels, rest, options = self._systems(args, names)
        if not systems:
            raise MatlabError(f"{title.split()[0].lower()} needs a system.")
        t = rest[0] if rest else None
        if nargout == 0:
            if t is None and len(systems) > 1:
                # One time axis for every curve, long enough for the slowest.
                end = max(float(fn(g, plot=False)[0][-1]) for g in systems)
                t = np.linspace(0.0, end, 2000)
            fn(*systems, t=t)
            spec = self.rt.figures.current
            if spec is not None:
                self._label(spec, labels)
                if options is not None:
                    _apply_options(spec, options)
            return None
        if len(systems) > 1:
            raise MatlabError("Ask for outputs one system at a time.")
        t_out, y = fn(systems[0], t=t, plot=False)
        y = np.asarray(y).reshape(-1, 1)
        t_col = np.asarray(t_out).reshape(-1, 1)
        return (y, t_col)[:nargout] if nargout >= 2 else y

    @_named
    @_nargout
    def f_step(self, *args, nargout=1, names=None):
        return self._time_plot(api.step, args, nargout, names,
                               "Step Response")

    f_stepplot = f_step

    @_named
    @_nargout
    def f_impulse(self, *args, nargout=1, names=None):
        return self._time_plot(api.impulse, args, nargout, names,
                               "Impulse Response")

    f_impulseplot = f_impulse

    @_nargout
    def f_lsim(self, sys, u, t, x0=None, *_, nargout=1):
        out = api.lsim(sys, u, t, x0=x0, plot=(nargout == 0))
        if nargout == 0:
            return None
        t_out, y = out
        return (np.asarray(y).reshape(-1, 1),
                np.asarray(t_out).reshape(-1, 1))[:nargout] \
            if nargout >= 2 else np.asarray(y).reshape(-1, 1)

    @_nargout
    def f_initial(self, sys, x0, t=None, nargout=1):
        out = api.initial(sys, np.asarray(x0).reshape(-1), t=t,
                          plot=(nargout == 0))
        if nargout == 0:
            return None
        t_out, y = out
        return (np.asarray(y).reshape(-1, 1),
                np.asarray(t_out).reshape(-1, 1))[:nargout] \
            if nargout >= 2 else np.asarray(y).reshape(-1, 1)

    @staticmethod
    def _freq_grid(rest):
        if not rest:
            return None
        w = rest[0]
        if isinstance(w, (Cell, list, tuple)) and len(w) == 2:
            lo, hi = float(np.real(w[0])), float(np.real(w[1]))
            return np.logspace(np.log10(lo), np.log10(hi), 500)
        return w

    @_named
    @_nargout
    def f_bode(self, *args, nargout=1, names=None):
        systems, labels, rest, options = self._systems(args, names)
        if not systems:
            raise MatlabError("bode needs a system.")
        w = self._freq_grid(rest)
        if nargout == 0:
            if w is None and len(systems) > 1:
                # One frequency axis spanning every system's own range.
                grids = [np.asarray(api.bode(g, plot=False)[2])
                         for g in systems]
                lo = min(float(g[0]) for g in grids)
                hi = max(float(g[-1]) for g in grids)
                w = np.logspace(np.log10(lo), np.log10(hi), 800)
            api.bode(*systems, w=w)
            spec = self.rt.figures.current
            if spec is not None:
                # MATLAB's bode draws no margin markers; margin(G) does.
                spec.extra.pop("margins", None)
                if options is not None:
                    _apply_options(spec, options, systems)
                self._label(spec, labels)
            return None
        mag, phase, omega = api.bode(systems[0], w=w, plot=False)
        if options is not None and str(options.get(
                "PhaseMatching", "off")).lower() == "on":
            phase = _match_phase(systems[0], omega, phase, options)
        out = (np.asarray(mag), np.asarray(phase), np.asarray(omega))
        return out[:nargout] if nargout >= 2 else out[0]

    f_bodeplot = f_bode

    @_named
    @_nargout
    def f_margin(self, *args, nargout=1, names=None):
        systems, labels, _rest, _ = self._systems(args, names)
        if not systems:
            raise MatlabError("margin needs a system.")
        gm, pm, wcg, wcp = api.margin(systems[0])
        if nargout >= 1:
            return (gm, pm, wcg, wcp)[:nargout] if nargout >= 2 else gm
        api.bode(systems[0])
        spec = self.rt.figures.current
        gm_db = 20 * math.log10(gm) if gm and np.isfinite(gm) else math.inf
        title = (f"Gm = {_number(gm_db)} dB (at {_number(wcg)} rad/s), "
                 f"Pm = {_number(pm)} deg (at {_number(wcp)} rad/s)")
        if spec is not None:
            spec.title = title
            self._label(spec, labels)
        print(title)
        return None

    @_named
    @_nargout
    def f_nyquist(self, *args, nargout=1, names=None):
        systems, labels, rest, _ = self._systems(args, names)
        w = self._freq_grid(rest)
        if nargout == 0:
            api.nyquist(*systems, w=w)
            if self.rt.figures.current is not None:
                self._label(self.rt.figures.current, labels)
            return None
        data = api.nyquist(systems[0], w=w, plot=False)
        out = (data.H_pos.real, data.H_pos.imag, data.omega)
        return out[:nargout] if nargout >= 2 else out[0]

    f_nyquistplot = f_nyquist

    @_named
    @_nargout
    def f_nichols(self, *args, nargout=1, names=None):
        systems, labels, rest, _ = self._systems(args, names)
        api.nichols(*systems, w=self._freq_grid(rest), plot=(nargout == 0))
        return None

    @_named
    @_nargout
    def f_pzmap(self, *args, nargout=1, names=None):
        systems, labels, _rest, _ = self._systems(args, names)
        if nargout == 0:
            api.pzmap(*systems)
            return None
        out = (api.pole(systems[0]).reshape(-1, 1),
               api.zero(systems[0]).reshape(-1, 1))
        return out[:nargout] if nargout >= 2 else out[0]

    f_pzplot = f_pzmap

    @_named
    @_nargout
    def f_rlocus(self, *args, nargout=1, names=None):
        systems, labels, rest, _ = self._systems(args, names)
        k = rest[0] if rest else None
        if nargout == 0:
            api.rlocus(systems[0], k)
            return None
        roots, gains = api.rlocus(systems[0], k, plot=False)
        out = (np.asarray(roots).T, np.asarray(gains))
        return out[:nargout] if nargout >= 2 else out[0]

    f_rlocusplot = f_rlocus

    # ── generic plots ───────────────────────────────────────────

    def _xy(self, args, kind_extra: dict | None = None,
            style: str | None = None):
        spec = FigureSpec("xy", "", "", "")
        spec.extra.update(kind_extra or {})
        values = list(args)
        k = 0
        series = []
        while k < len(values):
            v = values[k]
            if isinstance(v, str):
                if _is_linespec(v):
                    if series:
                        series[-1][2] = v
                    k += 1
                else:
                    k += 2                    # a name–value pair
                continue
            nxt = values[k + 1] if k + 1 < len(values) else None
            if nxt is not None and not isinstance(nxt, str):
                series.append([v, nxt, ""])
                k += 2
            else:
                y = np.asarray(v)
                if np.iscomplexobj(y):
                    series.append([y.real, y.imag, ""])
                else:
                    n = y.shape[0] if y.ndim == 2 and y.shape[0] > 1 \
                        else y.size
                    series.append([np.arange(1, n + 1), y, ""])
                k += 1
        warned = False
        for x, y, linespec in series:
            x, y = np.asarray(x), np.asarray(y)
            if np.iscomplexobj(x) or np.iscomplexobj(y):
                if not warned:
                    print("Warning: Imaginary parts of complex X and/or Y "
                          "arguments ignored.")
                    warned = True
                x, y = x.real, y.real
            x = np.asarray(x, float)
            y = np.asarray(y, float)
            columns = [y] if y.ndim == 1 or 1 in y.shape else (
                [y[:, c] for c in range(y.shape[1])]
                if y.shape[0] == x.size else [y[r] for r in range(y.shape[0])])
            for col in columns:
                xs, ys = x.reshape(-1), np.asarray(col).reshape(-1)
                kind = style or _style(linespec)
                if kind == "stairs":           # hold each value to the next x
                    xs, ys = np.repeat(xs, 2)[1:], np.repeat(ys, 2)[:-1]
                    kind = "line"
                spec.add(xs, ys, "", style=kind)
        self.rt.figures.collect(spec)

    def f_plot(self, *args):
        self._xy(args)

    def f_stem(self, *args):
        self._xy(args, style="stem")

    def f_stairs(self, *args):
        self._xy(args, style="stairs")

    def f_bar(self, *args):
        """
        Bars, ``bar(y)`` or ``bar(x, y[, width])``; a matrix's columns are
        drawn as groups of bars side by side.
        """
        numbers = [a for a in args if not isinstance(a, str)]
        if len(numbers) == 1:
            y = _as2d(numbers[0])
            x = None
        else:
            x, y = numbers[0], _as2d(numbers[1])
        y = y.T if y.shape[0] == 1 else y
        x = np.arange(1.0, y.shape[0] + 1) if x is None else \
            np.asarray(x, float).reshape(-1)
        width = float(_scalar_of(numbers[2])) if len(numbers) > 2 else 0.8
        step = float(np.min(np.diff(np.sort(x)))) if x.size > 1 else 1.0
        groups = y.shape[1]
        spec = FigureSpec("xy")
        spec.extra["bar_width"] = width * step / groups
        for k in range(groups):
            offset = (k - (groups - 1) / 2) * width * step / groups
            spec.add(x + offset, np.real(y[:, k]), style="bar")
        self.rt.figures.collect(spec)

    f_barh = f_bar

    @_nargout
    def f_histogram(self, x, bins=None, *_, nargout=1):
        """Counts in bins drawn as bars; returns Values and BinEdges."""
        data = np.asarray(x, float).reshape(-1)
        data = data[np.isfinite(data)]
        edges = _bin_edges(data, bins)
        counts, _edges = np.histogram(data, bins=edges)
        centres = (edges[:-1] + edges[1:]) / 2
        spec = FigureSpec("xy")
        spec.extra["bar_width"] = float(np.min(np.diff(edges))) if \
            edges.size > 1 else 1.0
        spec.add(centres, counts, style="bar")
        self.rt.figures.collect(spec)
        return Struct(Values=counts.astype(float), BinEdges=edges,
                      NumBins=int(counts.size),
                      BinWidth=float(spec.extra["bar_width"]),
                      Data=data) if nargout else None

    @_nargout
    def f_histcounts(self, x, bins=None, *_, nargout=1):
        data = np.asarray(x, float).reshape(-1)
        data = data[np.isfinite(data)]
        edges = _bin_edges(data, bins)
        counts = np.histogram(data, bins=edges)[0].astype(float)
        return (counts, edges)[:nargout] if nargout >= 2 else counts

    @_nargout
    def f_hist(self, y, bins=10, *_, nargout=1):
        """The old ``hist``: equal bins over the data's range, by centre."""
        data = np.asarray(y, float).reshape(-1)
        if _numel(bins) > 1:
            centres = np.asarray(bins, float).reshape(-1)
            mids = (centres[:-1] + centres[1:]) / 2
            edges = np.concatenate([[-np.inf], mids, [np.inf]])
        else:
            lo, hi = (float(np.min(data)), float(np.max(data))) \
                if data.size else (0.0, 1.0)
            if lo == hi:
                lo, hi = lo - 0.5, hi + 0.5
            edges = np.linspace(lo, hi, int(_scalar_of(bins)) + 1)
            centres = (edges[:-1] + edges[1:]) / 2
            edges[0], edges[-1] = -np.inf, np.inf
        counts = np.histogram(data, bins=edges)[0].astype(float)
        if nargout == 0:
            self._xy((centres, counts), style="bar")
            self.rt.figures.current.extra["bar_width"] = float(
                np.min(np.diff(centres))) if centres.size > 1 else 1.0
            return None
        return (counts, centres)[:nargout] if nargout >= 2 else counts

    # ── saving figures ──────────────────────────────────────────

    def _figure_for(self, handle) -> FigureSpec:
        figs = self.rt.figures
        spec = None
        if _is_number(handle) and 1 <= int(handle) <= len(figs.specs):
            spec = figs.specs[int(handle) - 1]
        spec = spec or figs.figure()
        if spec is None or spec not in figs.drawable():
            raise MatlabError("There is no figure to save.")
        return spec

    def f_saveas(self, fig, filename, fmt=None):
        path = self.rt.resolve(filename)
        if not os.path.splitext(path)[1]:
            ext = str(fmt or "png").lower().lstrip(".")
            path += "." + ("png" if ext == "fig" else ext)
        _export_figure(self._figure_for(fig), path)

    f_exportgraphics = f_saveas

    def f_print(self, *args):
        fmt, filename, handle = "png", None, None
        for a in args:
            if isinstance(a, str) and a.startswith("-d"):
                fmt = a[2:].lower()
            elif isinstance(a, str) and a.startswith("-"):
                continue                       # -r300, -painters, …
            elif isinstance(a, str):
                filename = a
            else:
                handle = a
        if filename is None:
            raise MatlabError("Printing to a printer is not supported; give "
                              "print a file name.")
        path = self.rt.resolve(filename)
        if not os.path.splitext(path)[1]:
            path += {"jpeg": ".jpg", "tiff": ".tif", "tiffn": ".tif",
                     "epsc": ".eps", "meta": ".emf"}.get(fmt, "." + fmt)
        _export_figure(self._figure_for(handle), path)

    def f_semilogx(self, *args):
        self._xy(args, {"logx": True})

    def f_semilogy(self, *args):
        self._xy(args, {"logy": True})

    def f_loglog(self, *args):
        self._xy(args, {"logx": True, "logy": True})

    # ── annotation ──────────────────────────────────────────────

    def f_title(self, text, *_):
        self.rt.figures.ensure().title = _as_text(text) if not isinstance(
            text, Cell) else " ".join(text)

    def f_xlabel(self, text, *_):
        self.rt.figures.ensure().xlabel = _as_text(text)

    def f_ylabel(self, text, *_):
        self.rt.figures.ensure().ylabel = _as_text(text)

    def f_legend(self, *args):
        labels: list[str] = []
        skip = False
        for a in args:
            if skip:
                skip = False
                continue
            if isinstance(a, Cell):
                labels.extend(str(x) for x in a)
            elif isinstance(a, str):
                if a.lower() in ("location", "orientation", "box", "fontsize",
                                 "numcolumns", "interpreter", "autoupdate",
                                 "textcolor"):
                    skip = True
                elif a.lower() in ("show", "off", "hide", "boxoff", "boxon",
                                   "toggle"):
                    continue
                else:
                    labels.append(a)
        spec = self.rt.figures.current
        if spec is None or not labels:
            return None
        named = [t for t in spec.traces if t.label] or spec.traces
        for trace, label in zip(named, labels):
            trace.label = label
        for k, entry in enumerate(spec.extra.get("phase", [])):
            if k < len(labels):
                spec.extra["phase"][k] = (entry[0], entry[1], labels[k])
        return None

    def f_axis(self, *args):
        if args and not isinstance(args[0], str):
            lims = np.asarray(args[0], float).reshape(-1)
            spec = self.rt.figures.ensure()
            spec.extra["xlim"] = (lims[0], lims[1])
            if lims.size >= 4:
                spec.extra["ylim"] = (lims[2], lims[3])

    def f_xlim(self, lims, *_):
        if not isinstance(lims, str):
            lims = np.asarray(lims, float).reshape(-1)
            self.rt.figures.ensure().extra["xlim"] = (lims[0], lims[1])

    def f_ylim(self, lims, *_):
        if not isinstance(lims, str):
            lims = np.asarray(lims, float).reshape(-1)
            self.rt.figures.ensure().extra["ylim"] = (lims[0], lims[1])


# ──────────────────────────────────────────────────────────────
#  Helpers for the library
# ──────────────────────────────────────────────────────────────

def _pause_for(seconds: float) -> None:
    """What ``pause(t)`` waits with — a seam the tests replace."""
    time.sleep(seconds)


def _bin_edges(data: np.ndarray, bins) -> np.ndarray:
    """
    ``histogram``'s bin edges: the edges given; ``n`` equal bins over the
    data; or, by default, Scott's rule rounded to a 1-2-3-5 width with
    edges on multiples of it — MATLAB's ``binpicker``.
    """
    if bins is not None and _numel(bins) > 1:
        return np.asarray(bins, float).reshape(-1)
    lo, hi = (float(np.min(data)), float(np.max(data))) if data.size \
        else (0.0, 1.0)
    if bins is not None:
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        return np.linspace(lo, hi, int(_scalar_of(bins)) + 1)
    spread = float(np.std(data)) if data.size > 1 else 0.0
    raw = 3.5 * spread / max(data.size, 1) ** (1 / 3) if spread else 1.0
    if hi > lo:
        raw = max(raw, (hi - lo) / 1e6)
    power = 10.0 ** math.floor(math.log10(raw))
    rel = raw / power
    width = power * (1 if rel < 1.5 else 2 if rel < 2.5 else 3 if rel < 4
                     else 5 if rel < 7.5 else 10)
    left = min(width * math.floor(lo / width), lo)
    count = max(1, math.ceil((hi - left) / width))
    edges = left + width * np.arange(count + 1)
    edges[-1] = max(edges[-1], hi)
    return edges


# ── audio files ──────────────────────────────────────────────────

_SUBTYPE_BITS = {"PCM_U8": 8, "PCM_S8": 8, "PCM_16": 16, "PCM_24": 24,
                 "PCM_32": 32, "FLOAT": 32, "DOUBLE": 64}


def _soundfile():
    try:
        import soundfile
    except Exception:                                    # noqa: BLE001
        return None
    return soundfile


def _wav_header(path: str) -> dict:
    """The ``fmt `` and ``data`` chunks of a RIFF WAVE file."""
    info: dict = {}
    with open(path, "rb") as fh:
        riff = fh.read(12)
        if len(riff) < 12 or riff[:4] != b"RIFF" or riff[8:] != b"WAVE":
            raise MatlabError(f"{os.path.basename(path)} is not a WAVE "
                              f"file this reader understands.")
        while True:
            head = fh.read(8)
            if len(head) < 8:
                break
            chunk, size = head[:4], struct.unpack("<I", head[4:])[0]
            if chunk == b"fmt ":
                body = fh.read(size)
                tag, channels, rate, _, align, bits = struct.unpack(
                    "<HHIIHH", body[:16])
                if tag == 0xFFFE and len(body) >= 26:     # extensible
                    tag = struct.unpack("<H", body[24:26])[0]
                info.update(tag=tag, channels=channels, rate=rate,
                            align=align, bits=bits)
                fh.seek(size & 1, 1)
            elif chunk == b"data":
                info.update(offset=fh.tell(), size=size)
                fh.seek(size + (size & 1), 1)
            else:
                fh.seek(size + (size & 1), 1)
    if "tag" not in info or "offset" not in info:
        raise MatlabError(f"{os.path.basename(path)} has no audio data.")
    info["frames"] = info["size"] // max(info["align"], 1)
    return info


def _audio_info(path: str) -> dict:
    sf = _soundfile()
    if sf is not None:
        try:
            i = sf.info(path)
            return {"channels": i.channels, "rate": int(i.samplerate),
                    "frames": int(i.frames),
                    "bits": _SUBTYPE_BITS.get(i.subtype, 16)}
        except Exception:                                # noqa: BLE001
            pass
    h = _wav_header(path)
    return {k: h[k] for k in ("channels", "rate", "frames", "bits")}


def _read_audio(path: str, native: bool = False):
    """Samples as a frames × channels array (doubles in [-1, 1])."""
    sf = _soundfile()
    if sf is not None and not native:
        try:
            y, rate = sf.read(path, dtype="float64", always_2d=True)
            return y, int(rate), _audio_info(path)
        except Exception:                                # noqa: BLE001
            pass
    h = _wav_header(path)
    with open(path, "rb") as fh:
        fh.seek(h["offset"])
        raw = fh.read(h["frames"] * h["align"])
    bits, tag = h["bits"], h["tag"]
    if tag == 3:
        y = np.frombuffer(raw, "<f4" if bits == 32 else "<f8").astype(float)
        ints = None
    elif tag == 1 and bits in (8, 16, 24, 32):
        if bits == 24:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
            ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        else:
            ints = np.frombuffer(raw, {8: np.uint8, 16: "<i2",
                                       32: "<i4"}[bits])
        y = (ints.astype(float) - 128) / 128 if bits == 8 else \
            ints.astype(float) / 2.0 ** (bits - 1)
    else:
        raise MatlabError(f"{os.path.basename(path)}: {bits}-bit audio "
                          f"(format {tag}) is not supported.")
    shape = (-1, h["channels"])
    if native and ints is not None:
        y = ints                       # uint8, int16 or int32, as MATLAB's
    return y.reshape(shape), int(h["rate"]), {
        k: h[k] for k in ("channels", "rate", "frames", "bits")}


def _write_audio(path: str, data: np.ndarray, rate: int, bits: int) -> None:
    """
    Write frames × channels samples. Integer depths clip to [-1, 1) and
    scale by 2^(bits-1), as MATLAB does; 32 and 64 bits write floats.
    """
    if bits not in (8, 16, 24, 32, 64):
        raise MatlabError("BitsPerSample must be 8, 16, 24, 32 or 64.")
    data = np.asarray(data, float)
    if not path.lower().endswith(".wav"):
        sf = _soundfile()
        if sf is None:
            raise MatlabError("Only .wav files can be written here "
                              "(install the soundfile package for others).")
        subtype = {8: "PCM_U8", 16: "PCM_16", 24: "PCM_24", 32: "FLOAT",
                   64: "DOUBLE"}[bits]
        sf.write(path, data, rate, subtype=subtype)
        return
    channels = data.shape[1]
    if bits >= 32:
        payload = data.astype("<f4" if bits == 32 else "<f8").tobytes()
        tag = 3
    else:
        scale = 2.0 ** (bits - 1)
        ints = np.clip(np.round(data * scale), -scale, scale - 1)
        if bits == 8:
            payload = (ints + 128).astype(np.uint8).tobytes()
        elif bits == 16:
            payload = ints.astype("<i2").tobytes()
        else:
            payload = ints.astype("<i4").view(np.uint8).reshape(
                -1, 4)[:, :3].tobytes()
        tag = 1
    align = channels * bits // 8
    fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * align, align,
                      bits)
    chunks = [b"fmt ", struct.pack("<I", len(fmt)), fmt]
    if tag == 3:                     # float files carry a sample count
        chunks += [b"fact", struct.pack("<II", 4, data.shape[0])]
    chunks += [b"data", struct.pack("<I", len(payload)), payload]
    if len(payload) & 1:
        chunks.append(b"\0")
    body = b"".join(chunks)
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)


_PLAYERS: list = []


def _play(data: np.ndarray, rate: float) -> bool:
    """
    Start playing frames × channels samples in [-1, 1] and return at once;
    False when there is nothing to play them on. sounddevice if it is
    installed, else Qt Multimedia (which ships with PySide6).
    """
    try:
        import sounddevice
        sounddevice.play(data, int(round(rate)))
        return True
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QIODevice
        from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices
        if QCoreApplication.instance() is None:
            return False
        device = QMediaDevices.defaultAudioOutput()
        fmt = QAudioFormat()
        fmt.setSampleRate(int(round(rate)))
        fmt.setChannelCount(int(data.shape[1]))
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if device.isNull() or not device.isFormatSupported(fmt):
            return False
        buffer = QBuffer()
        buffer.setData(QByteArray((data * 32767).astype("<i2").tobytes()))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        sink = QAudioSink(device, fmt)
        sink.start(buffer)
        # Keep each player alive until it has finished.
        _PLAYERS[:] = [p for p in _PLAYERS
                       if p[0].state() == QAudio.State.ActiveState]
        _PLAYERS.append((sink, buffer))
        return True
    except Exception:                                    # noqa: BLE001
        pass
    return _play_winsound(data, rate) or _play_afplay(data, rate)


def _sound_file(data: np.ndarray, rate: float) -> str:
    """
    A .wav of ``data`` that lives until Evans exits: both last resorts play
    asynchronously, so the file has to outlive the call.
    """
    import atexit
    import tempfile

    handle, path = tempfile.mkstemp(prefix="evans-sound-", suffix=".wav")
    os.close(handle)
    if not _SOUND_FILES:
        atexit.register(_remove_sound_files)
    _SOUND_FILES.append(path)
    _write_audio(path, data, int(round(rate)), 16)
    return path


def _play_afplay(data: np.ndarray, rate: float) -> bool:
    """
    The last resort on a Mac: ``afplay``, which every macOS ships in
    /usr/bin. The packaged app has no Qt Multimedia there either.
    """
    if sys.platform != "darwin":
        return False
    import subprocess

    try:
        subprocess.Popen(["/usr/bin/afplay", _sound_file(data, rate)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _play_winsound(data: np.ndarray, rate: float) -> bool:
    """
    The last resort on Windows: the standard library's winsound.

    The packaged app has neither sounddevice (not a dependency) nor Qt
    Multimedia (left out of the bundle for its size), so sound() was silent
    there. winsound plays a .wav file asynchronously and lets Windows
    resample any rate. The file must outlive the call, so each sound gets
    its own temporary file, removed when Evans exits.
    """
    if sys.platform != "win32":
        return False
    try:
        import winsound
    except ImportError:
        return False
    try:
        winsound.PlaySound(_sound_file(data, rate),
                           winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


_SOUND_FILES: list[str] = []


def _remove_sound_files() -> None:
    try:
        import winsound
        winsound.PlaySound(None, 0)               # stop, release the file
    except Exception:                               # noqa: BLE001
        pass
    for path in _SOUND_FILES:
        try:
            os.remove(path)
        except OSError:
            pass


# ── .mat files ───────────────────────────────────────────────────

def _to_mat(value):
    """A workspace value in the form ``scipy.io.savemat`` writes."""
    if isinstance(value, Struct):
        return {k: _to_mat(v) for k, v in value.items()}
    if isinstance(value, (Cell, StructArray)):
        out = np.empty((1, len(value)), dtype=object)
        for k, v in enumerate(value):
            out[0, k] = _to_mat(v)
        return out
    if value is None:
        return np.zeros((0, 0))
    return value


def _from_mat(value):
    """What ``scipy.io.loadmat`` read, as the runtime represents it."""
    from scipy.io.matlab import mat_struct
    if isinstance(value, mat_struct):
        return Struct({f: _from_mat(getattr(value, f))
                       for f in value._fieldnames})
    if isinstance(value, str):
        return value
    a = np.asarray(value)
    if a.dtype.kind == "U":
        texts = [str(s) for s in a.reshape(-1)]
        return texts[0] if len(texts) == 1 else ("" if not texts
                                                 else Cell(texts))
    if a.dtype == object:
        items = [_from_mat(v) for v in a.reshape(-1, order="F")]
        if items and all(isinstance(v, Struct) for v in items):
            return items[0] if len(items) == 1 else StructArray(items)
        return Cell(items)
    if a.size == 0:
        return np.zeros((0, 0))
    if a.dtype.kind in "iu":
        a = a.astype(float)
    return _normalise(a)


# ── saving figures ───────────────────────────────────────────────

def _export_figure(spec: FigureSpec, path: str) -> None:
    """
    Draw a figure off-screen and write it to ``path``.

    The figure UI's own ``export_figure(view, path)`` does the writing when
    it has one (it knows the vector formats); otherwise the drawn widget is
    grabbed as an image, the way the figure dock's Save does.
    """
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
    try:
        from PySide6.QtWidgets import QApplication

        from ..ui.console import figure_view
    except ImportError as exc:
        raise MatlabError(f"Saving a figure needs the Qt interface "
                          f"({exc}).") from None
    _app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    view = figure_view.FigureView(spec)
    view.resize(800, 600)
    try:
        export = getattr(figure_view, "export_figure", None)
        if export is not None:
            export(view, path)
        elif not view.grab().save(path):
            raise MatlabError(f"Could not write the figure to {path} (is "
                              f"'{os.path.splitext(path)[1]}' an image "
                              f"format?).")
    finally:
        view.deleteLater()


def _matlab_stepinfo(info: Struct, t: np.ndarray, y: np.ndarray) -> Struct:
    """
    Align two fields with MATLAB's definitions.

    MATLAB's ``PeakTime`` is when ``|y|`` peaks even with no overshoot, and
    ``SettlingMin`` / ``SettlingMax`` are taken *after* the rise — not over
    the whole response, whose minimum is the zero it starts from.
    """
    if not y.size:
        return info
    k = int(np.argmax(np.abs(y)))
    if not np.isfinite(info.get("PeakTime", np.nan)):
        info["PeakTime"] = float(t[k])
        info["Peak"] = float(abs(y[k]))
    final = info.get("SteadyState", y[-1])
    if np.isfinite(final) and final != 0:
        # Signed: an undershoot heading the wrong way has not "risen".
        risen = np.nonzero(y * np.sign(final) >= 0.9 * abs(final))[0]
        if risen.size:
            tail = y[risen[0]:]
            info["SettlingMin"] = float(np.min(tail))
            info["SettlingMax"] = float(np.max(tail))
    return info


def _poly_arg(x):
    if _is_number(x):
        return [x]
    return np.asarray(x).reshape(-1)


def _zpk_gain(sys) -> float:
    G = ctl.tf(sys)
    num = np.trim_zeros(np.asarray(G.num[0][0], float), "f")
    den = np.trim_zeros(np.asarray(G.den[0][0], float), "f")
    return float(num[0] / den[0]) if num.size and den.size else 0.0


def _style(linespec: str) -> str:
    if not linespec:
        return "line"
    if any(s in linespec for s in ("--", ":", "-.")):
        return "dashed"
    if not re.search(r"-", linespec) and re.search(r"[.o+*xsd^v<>ph]",
                                                  linespec):
        return "scatter"
    return "line"


def _apply_options(spec: FigureSpec, options: PlotOptions,
                   systems=None) -> None:
    title = options.get("Title")
    if isinstance(title, str) and title and title not in (
            "Bode Diagram", "Step Response"):
        spec.title = title
    if systems and spec.kind == "bode" and str(
            options.get("PhaseMatching", "off")).lower() == "on":
        phases = spec.extra.get("phase", [])
        for k, (omega, degrees, label) in enumerate(phases):
            if k < len(systems):
                phases[k] = (omega, _match_phase(systems[k], omega, degrees,
                                                 options), label)
    for key in ("XLim", "YLim"):
        value = options.get(key)
        if value is not None and _numel(value) >= 2:
            lims = np.asarray(value, float).reshape(-1)
            spec.extra[key.lower()] = (lims[0], lims[1])


def _match_phase(sys, omega, degrees, options: PlotOptions) -> np.ndarray:
    """
    MATLAB's PhaseMatching: shift the phase curve by whole turns so that at
    ``PhaseMatchingFreq`` it lies closest to ``PhaseMatchingValue``.

    The phase at that frequency is found by continuing the curve down to it
    — not by evaluating ``angle(G(jw))`` there, which would be wrapped and
    could sit a turn away from the curve actually drawn.
    """
    omega = np.asarray(omega, float)
    degrees = np.asarray(degrees, float)
    w0 = float(options.get("PhaseMatchingFreq", 0.0) or 0.0)
    target = float(options.get("PhaseMatchingValue", 0.0) or 0.0)
    if not omega.size:
        return degrees
    if w0 <= 0:
        w0 = float(omega[0])
    lo = min(w0, float(omega[0]))
    bridge = np.logspace(np.log10(lo), np.log10(float(omega[0])), 200)
    response = np.array([complex(sys(1j * w)) for w in bridge])
    path = np.degrees(np.unwrap(np.angle(response)))
    # Join the bridge onto the plotted curve at its first point.
    path += degrees[0] - path[-1]
    at_w0 = float(np.interp(np.log10(w0), np.log10(bridge), path)) \
        if w0 < omega[0] else float(np.interp(np.log10(w0), np.log10(omega),
                                              degrees))
    turns = round((target - at_w0) / 360.0)
    return degrees + 360.0 * turns


_SPEC = re.compile(r"%(?P<flags>[-+ 0#]*)(?P<width>\d+|\*)?"
                   r"(?:\.(?P<prec>\d+|\*))?(?P<conv>[diouxXfeEgGcs%])")
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "r": "\r", "a": "\a",
            "b": "\b", "f": "\f", "v": "\v", "'": "'", '"': '"'}


def _escapes(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1),
                                                   "\\" + m.group(1)), text)


def _sprintf(fmt: str, args: tuple) -> str:
    """MATLAB's sprintf: escapes, vector arguments, and format recycling."""
    fmt = _escapes(fmt)
    values: list = []
    for a in args:
        if isinstance(a, str):
            values.append(a)
        elif isinstance(a, (Cell, list, tuple)):
            values.extend(a)
        elif isinstance(a, np.ndarray):
            values.extend(_scalar(v) for v in a.reshape(-1, order="F"))
        else:
            values.append(_scalar(a) if isinstance(a, (float, np.generic))
                          else a)
    specs = [m for m in _SPEC.finditer(fmt) if m.group("conv") != "%"]
    if not specs:
        return fmt.replace("%%", "%")
    out: list[str] = []
    pos = 0
    first = True
    while first or pos < len(values):
        first = False
        last = 0
        for m in _SPEC.finditer(fmt):
            out.append(fmt[last:m.start()])
            last = m.end()
            if m.group("conv") == "%":
                out.append("%")
                continue
            if pos >= len(values):
                if values or pos > 0:
                    return "".join(out)
                last = len(fmt)     # no data at all: print literal text only
                out.append("")
                break
            out.append(_convert(m, values[pos]))
            pos += 1
        else:
            out.append(fmt[last:])
            continue
    return "".join(out)


def _convert(m: re.Match, value) -> str:
    flags = m.group("flags") or ""
    width = m.group("width") or ""
    prec = m.group("prec")
    conv = m.group("conv")
    head = "%" + flags + width
    if conv == "s":
        text = value if isinstance(value, str) else _num2str(value, None)
        return (head + (f".{prec}" if prec else "") + "s") % text
    if conv == "c":
        text = value if isinstance(value, str) else chr(int(value))
        return (head + "s") % text
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        value = int(value)
    if isinstance(value, complex):
        value = value.real
    if conv in "diouxX":
        if float(value).is_integer() and math.isfinite(value):
            code = "d" if conv in "diu" else conv
            return (head + code) % int(value)
        return (head + (f".{prec}" if prec else "") + "e") % float(value)
    return (head + (f".{prec}" if prec else "") + conv) % float(value)


def _num2str(v, spec) -> str:
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, str):
        return v
    if isinstance(v, (bool,)):
        return "1" if v else "0"
    if isinstance(v, complex):
        sign = "+" if v.imag >= 0 else "-"
        return f"{_num2str(v.real, spec)}{sign}{_num2str(abs(v.imag), spec)}i"
    v = float(v)
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Inf" if v > 0 else "-Inf"
    if spec is not None:
        return f"{v:.{int(spec)}g}"
    if v.is_integer():
        return str(int(v))
    digits = max(int(math.floor(math.log10(abs(v)))) + 5, 5) if v else 5
    return f"{v:.{digits}g}"
