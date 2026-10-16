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
import re
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
    """Plot requests made during one script run, open to amendment."""

    def __init__(self) -> None:
        self.specs: list[FigureSpec] = []
        self.current: FigureSpec | None = None
        self.hold = False
        self.close_requested = False

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
        self.lib = _Library(self)

    # ── names ───────────────────────────────────────────────────

    def lookup(self, name: str, glob: dict, loc: dict):
        """
        Resolve a name the script never assigns.

        A variable from the console wins; then the MATLAB library (whose
        ``zeros(3)`` is 3×3, unlike numpy's); then the console's commands.
        """
        if loc is not glob and name in loc:
            return loc[name]
        if name in glob:
            value = glob[name]
            if not (name in self.lib.names
                    and value is self.base.get(name, object())):
                return value
        if name in self.lib.names:
            return getattr(self.lib, _lib_attr(name))
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

    def begin(self) -> None:
        self.figures = Figures()

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
        if figs.current in figs.specs:
            figs.specs.remove(figs.current)
        figs.current = None

    def f_figure(self, *_):
        self.rt.figures.new()

    def f_subplot(self, *_):
        self.rt.figures.new()

    def f_hold(self, state=None):
        figs = self.rt.figures
        figs.hold = (not figs.hold) if state is None else \
            str(state).lower() in ("on", "all")

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

    def f_pause(self, *_):
        return None

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
        return 1 if name in self.rt.ns else (
            2 if name in self.names else 0)

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

    def f_trapz(self, x, y=None):
        if y is None:
            return float(np.trapz(np.asarray(x)))
        return float(np.trapz(np.asarray(y), np.asarray(x)))

    def f_interp1(self, x, y, xi, *_):
        out = np.interp(xi, np.asarray(x), np.asarray(y))
        return _scalar(out) if np.ndim(out) == 0 else out

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
        return np.real_if_close(np.poly(np.asarray(r)))

    def f_polyval(self, p, x):
        out = np.polyval(np.asarray(p).reshape(-1), x)
        return _scalar(out) if np.ndim(out) == 0 else out

    def f_polyfit(self, x, y, n):
        return np.polyfit(np.asarray(x).reshape(-1),
                          np.asarray(y).reshape(-1), int(n))

    def f_conv(self, a, b):
        return np.convolve(np.atleast_1d(a), np.atleast_1d(b))

    @_nargout
    def f_deconv(self, a, b, nargout=1):
        q, r = np.polydiv(np.atleast_1d(a), np.atleast_1d(b))
        return (q, r) if nargout >= 2 else q

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
        if form == "v":
            out = (np.asarray(num, float), np.asarray(den, float))
        else:
            out = (Cell([np.asarray(num, float)]),
                   Cell([np.asarray(den, float)]))
        return out[:max(nargout, 1)] if nargout >= 2 else out[0]

    @_nargout
    def f_zpkdata(self, sys, form=None, nargout=1):
        z, p = api.zero(sys), api.pole(sys)
        k = float(api.dcgain(sys)) if False else _zpk_gain(sys)
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

    def _xy(self, args, kind_extra: dict | None = None):
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
        for x, y, style in series:
            x = np.asarray(x, float)
            y = np.asarray(y, float)
            columns = [y] if y.ndim == 1 or 1 in y.shape else (
                [y[:, c] for c in range(y.shape[1])]
                if y.shape[0] == x.size else [y[r] for r in range(y.shape[0])])
            for col in columns:
                spec.add(x.reshape(-1), np.asarray(col).reshape(-1), "",
                         style=_style(style))
        self.rt.figures.collect(spec)

    def f_plot(self, *args):
        self._xy(args)

    def f_semilogx(self, *args):
        self._xy(args, {"logx": True})

    def f_semilogy(self, *args):
        self._xy(args, {"logy": True})

    def f_loglog(self, *args):
        self._xy(args, {"logx": True, "logy": True})

    f_stem = f_stairs = f_plot

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
