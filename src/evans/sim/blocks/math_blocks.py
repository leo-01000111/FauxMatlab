"""Arithmetic, routing and sink blocks."""

from __future__ import annotations

import numpy as np

from ..block import Block, BlockError, ParamSpec, as_array, register

_MATH = "Math"
_ROUTE = "Routing"
_SINK = "Sinks"


# ──────────────────────────────────────────────────────────────
#  Math
# ──────────────────────────────────────────────────────────────

@register
class Gain(Block):
    type_name = "Gain"
    category = _MATH
    description = "Multiply by a constant."
    params_spec = (ParamSpec("gain", "Gain", 1.0),)

    def output(self, t, x, xd, u):
        return [self.params["gain"] * np.atleast_1d(u[0])]

    def label(self):
        return f"{self.params['gain']:g}"


@register
class Sum(Block):
    type_name = "Sum"
    category = _MATH
    description = "Signed sum of its inputs; the signs string sets the ports."
    params_spec = (
        ParamSpec("signs", "Signs", "+-", kind="str",
                  help="One character per input, '+' or '-'. '+-' is the "
                       "classic error junction."),
    )

    def configure(self) -> None:
        signs = str(self.params["signs"]).strip()
        if not signs or any(c not in "+-" for c in signs):
            raise BlockError(
                f"Sum signs must be a string of '+' and '-' "
                f"(got {self.params['signs']!r})"
            )
        self._signs = np.array([1.0 if c == "+" else -1.0 for c in signs])
        self.inputs = [f"in{i + 1}" for i in range(len(signs))]

    def output(self, t, x, xd, u):
        width = max((len(np.atleast_1d(v)) for v in u), default=1)
        total = np.zeros(width)
        for sign, value in zip(self._signs, u):
            total = total + sign * as_array(value, width)
        return [total]

    def label(self):
        return str(self.params["signs"])


@register
class Product(Block):
    type_name = "Product"
    category = _MATH
    description = "Elementwise product or quotient of two inputs."
    default_inputs = ("in1", "in2")
    params_spec = (
        ParamSpec("operation", "Operation", "*", kind="choice",
                  choices=("*", "/")),
    )

    def output(self, t, x, xd, u):
        a, b = np.atleast_1d(u[0]), np.atleast_1d(u[1])
        if self.params["operation"] == "/":
            # A hard zero would raise or produce inf and poison the solver;
            # clamping the magnitude keeps the step finite so the run
            # continues and the user can see where it went wrong.
            safe = np.where(np.abs(b) < 1e-300, np.sign(b) * 1e-300 + 1e-300, b)
            return [a / safe]
        return [a * b]

    def label(self):
        return "×" if self.params["operation"] == "*" else "÷"


@register
class Abs(Block):
    type_name = "Abs"
    category = _MATH
    description = "|u|."

    def output(self, t, x, xd, u):
        return [np.abs(np.atleast_1d(u[0]))]

    def zero_crossings(self, t, x, xd, u):
        return np.atleast_1d(u[0]).copy()

    def label(self):
        return "|u|"


@register
class Sign(Block):
    type_name = "Sign"
    category = _MATH
    description = "sign(u)."

    def output(self, t, x, xd, u):
        return [np.sign(np.atleast_1d(u[0]))]

    def zero_crossings(self, t, x, xd, u):
        return np.atleast_1d(u[0]).copy()


@register
class Trig(Block):
    type_name = "Trig"
    category = _MATH
    description = "Trigonometric function of the input."
    params_spec = (
        ParamSpec("function", "Function", "sin", kind="choice",
                  choices=("sin", "cos", "tan", "asin", "acos", "atan")),
    )

    def output(self, t, x, xd, u):
        fn = getattr(np, self.params["function"])
        return [fn(np.atleast_1d(u[0]))]

    def label(self):
        return self.params["function"]


@register
class MathFunction(Block):
    type_name = "MathFunction"
    category = _MATH
    description = "square, sqrt, exp, log, reciprocal."
    params_spec = (
        ParamSpec("function", "Function", "square", kind="choice",
                  choices=("square", "sqrt", "exp", "log", "reciprocal")),
    )

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        fn = self.params["function"]
        if fn == "square":
            return [v ** 2]
        if fn == "sqrt":
            return [np.sqrt(np.maximum(v, 0.0))]
        if fn == "exp":
            return [np.exp(np.clip(v, -700, 700))]
        if fn == "log":
            return [np.log(np.maximum(v, 1e-300))]
        return [1.0 / np.where(np.abs(v) < 1e-300, 1e-300, v)]

    def label(self):
        return self.params["function"]


@register
class MinMax(Block):
    type_name = "MinMax"
    category = _MATH
    description = "Elementwise min or max of two inputs."
    default_inputs = ("in1", "in2")
    params_spec = (
        ParamSpec("operation", "Operation", "max", kind="choice",
                  choices=("min", "max")),
    )

    def output(self, t, x, xd, u):
        a, b = np.atleast_1d(u[0]), np.atleast_1d(u[1])
        fn = np.maximum if self.params["operation"] == "max" else np.minimum
        return [fn(a, b)]

    def zero_crossings(self, t, x, xd, u):
        return np.atleast_1d(u[0]) - np.atleast_1d(u[1])

    def label(self):
        return self.params["operation"]


# ──────────────────────────────────────────────────────────────
#  Routing
# ──────────────────────────────────────────────────────────────

@register
class Mux(Block):
    type_name = "Mux"
    category = _ROUTE
    description = "Combine several signals into one vector."
    params_spec = (ParamSpec("n_inputs", "Number of inputs", 2, kind="int"),)

    def configure(self) -> None:
        n = int(self.params["n_inputs"])
        if n < 1:
            raise BlockError("Mux needs at least one input")
        self.inputs = [f"in{i + 1}" for i in range(n)]

    def output_widths(self, input_widths):
        return [int(sum(input_widths))] if input_widths else [1]

    def output(self, t, x, xd, u):
        return [np.concatenate([np.atleast_1d(v) for v in u])] if u \
            else [np.zeros(1)]

    def label(self):
        return "Mux"


@register
class Demux(Block):
    type_name = "Demux"
    category = _ROUTE
    description = "Split a vector into scalar signals."
    params_spec = (ParamSpec("n_outputs", "Number of outputs", 2, kind="int"),)

    def configure(self) -> None:
        n = int(self.params["n_outputs"])
        if n < 1:
            raise BlockError("Demux needs at least one output")
        self.outputs = [f"out{i + 1}" for i in range(n)]

    def output_widths(self, input_widths):
        n = len(self.outputs)
        width = input_widths[0] if input_widths else n
        if width % n:
            raise BlockError(
                f"Demux {self.block_id!r} cannot split a width-{width} signal "
                f"into {n} equal outputs"
            )
        return [width // n] * n

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        n = len(self.outputs)
        if len(v) % n:
            raise BlockError(
                f"Demux {self.block_id!r} got width {len(v)}, not divisible "
                f"by {n}"
            )
        return list(np.split(v, n))

    def label(self):
        return "Demux"


@register
class Selector(Block):
    type_name = "Selector"
    category = _ROUTE
    description = "Pick one element out of a vector signal."
    params_spec = (ParamSpec("index", "Index (0-based)", 0, kind="int"),)

    def output_widths(self, input_widths):
        return [1]

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        i = int(self.params["index"])
        if not 0 <= i < len(v):
            raise BlockError(
                f"Selector {self.block_id!r}: index {i} is outside a "
                f"width-{len(v)} signal"
            )
        return [np.array([v[i]])]

    def label(self):
        return f"[{self.params['index']}]"


# ──────────────────────────────────────────────────────────────
#  Sinks
# ──────────────────────────────────────────────────────────────

@register
class Scope(Block):
    type_name = "Scope"
    category = _SINK
    description = "Record a signal for plotting."
    default_outputs = ()
    params_spec = (
        ParamSpec("n_inputs", "Number of channels", 1, kind="int"),
        ParamSpec("title", "Title", "Scope", kind="str"),
    )

    def configure(self) -> None:
        n = int(self.params["n_inputs"])
        self.inputs = [f"in{i + 1}" for i in range(max(n, 1))]

    def output_widths(self, input_widths):
        return []

    def output(self, t, x, xd, u):
        return []

    def label(self):
        return str(self.params["title"])


@register
class ToWorkspace(Block):
    type_name = "ToWorkspace"
    category = _SINK
    description = "Record a signal under a name, for later use."
    default_outputs = ()
    params_spec = (ParamSpec("name", "Variable name", "y", kind="str"),)

    def output_widths(self, input_widths):
        return []

    def output(self, t, x, xd, u):
        return []

    def label(self):
        return f"→ {self.params['name']}"


@register
class Display(Block):
    type_name = "Display"
    category = _SINK
    description = "Show the final value of a signal."
    default_outputs = ()

    def output_widths(self, input_widths):
        return []

    def output(self, t, x, xd, u):
        return []

    def label(self):
        return "Display"


@register
class Terminator(Block):
    type_name = "Terminator"
    category = _SINK
    description = "Discard a signal, so an unused output is not an error."
    default_outputs = ()

    def output_widths(self, input_widths):
        return []

    def output(self, t, x, xd, u):
        return []


@register
class StopSimulation(Block):
    type_name = "StopSimulation"
    category = _SINK
    description = "End the run when the input becomes non-zero."
    default_outputs = ()

    def output_widths(self, input_widths):
        return []

    def output(self, t, x, xd, u):
        return []

    def should_stop(self, u) -> bool:
        return bool(np.any(np.abs(np.atleast_1d(u[0])) > 1e-12)) if u else False

    def label(self):
        return "STOP"
