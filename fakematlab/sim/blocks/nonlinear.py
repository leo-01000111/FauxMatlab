"""
Discontinuous blocks.

Every block here has a kink or a jump in its input/output map. Each declares
:meth:`~fakematlab.sim.block.Block.zero_crossings` so the solver can land a
step exactly on the discontinuity: integrating straight through one makes the
local error estimate meaningless, which shows up as a step size that collapses
towards zero, or — worse — a plausible-looking answer that changes when you
change the tolerance.
"""

from __future__ import annotations

import numpy as np

from ..block import Block, BlockError, ParamSpec, register

_CAT = "Discontinuities"


@register
class Saturation(Block):
    type_name = "Saturation"
    category = _CAT
    description = "Clip between an upper and a lower limit — an actuator limit."
    params_spec = (
        ParamSpec("upper", "Upper limit", 1.0),
        ParamSpec("lower", "Lower limit", -1.0),
    )

    def configure(self) -> None:
        if self.params["upper"] <= self.params["lower"]:
            raise BlockError(
                f"Saturation {self.block_id!r}: upper limit "
                f"({self.params['upper']}) must exceed the lower "
                f"({self.params['lower']})"
            )

    def output(self, t, x, xd, u):
        return [np.clip(np.atleast_1d(u[0]),
                        self.params["lower"], self.params["upper"])]

    def zero_crossings(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        return np.concatenate([v - self.params["upper"],
                               v - self.params["lower"]])

    def label(self):
        return "sat"


@register
class DeadZone(Block):
    type_name = "DeadZone"
    category = _CAT
    description = "Zero output inside a band — stiction, backlash, valve overlap."
    params_spec = (
        ParamSpec("start", "Dead zone start", -0.1),
        ParamSpec("end", "Dead zone end", 0.1),
    )

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        lo, hi = self.params["start"], self.params["end"]
        return [np.where(v > hi, v - hi, np.where(v < lo, v - lo, 0.0))]

    def zero_crossings(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        return np.concatenate([v - self.params["start"],
                               v - self.params["end"]])

    def label(self):
        return "dead\nzone"


@register
class Relay(Block):
    type_name = "Relay"
    category = _CAT
    description = "On/off with hysteresis — the relay-feedback experiment."
    params_spec = (
        ParamSpec("on_point", "Switch-on point", 0.1),
        ParamSpec("off_point", "Switch-off point", -0.1),
        ParamSpec("on_value", "Output when on", 1.0),
        ParamSpec("off_value", "Output when off", -1.0),
    )

    def configure(self) -> None:
        if self.params["on_point"] < self.params["off_point"]:
            raise BlockError(
                f"Relay {self.block_id!r}: the switch-on point must not be "
                f"below the switch-off point (that would invert the "
                f"hysteresis loop)"
            )

    @property
    def n_dstates(self) -> int:
        # The relay's own on/off memory. Hysteresis means the output depends
        # on history, not just on the present input.
        return 1

    @property
    def sample_time(self) -> float:
        # Driven by zero crossings, not by a clock.
        return 0.0

    def output(self, t, x, xd, u):
        p = self.params
        v = float(np.atleast_1d(u[0])[0]) if u else 0.0
        on = bool(xd[0] > 0.5)
        if v >= p["on_point"]:
            on = True
        elif v <= p["off_point"]:
            on = False
        return [np.array([p["on_value"] if on else p["off_value"]])]

    def update(self, t, x, xd, u):
        p = self.params
        v = float(np.atleast_1d(u[0])[0]) if u else 0.0
        on = bool(xd[0] > 0.5)
        if v >= p["on_point"]:
            on = True
        elif v <= p["off_point"]:
            on = False
        return np.array([1.0 if on else 0.0])

    def zero_crossings(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        return np.concatenate([v - self.params["on_point"],
                               v - self.params["off_point"]])

    def label(self):
        return "relay"


@register
class RateLimiter(Block):
    type_name = "RateLimiter"
    category = _CAT
    description = "Limit how fast the output may change — a slew-rate limit."
    params_spec = (
        ParamSpec("rising", "Max rising slope", 1.0),
        ParamSpec("falling", "Max falling slope", -1.0),
    )

    @property
    def n_states(self) -> int:
        return 1

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        return [x.copy()]

    def derivative(self, t, x, xd, u):
        # Implemented as a high-gain tracking integrator with a clamped rate:
        # the state chases the input as fast as the limits allow.
        uu = float(np.atleast_1d(u[0])[0]) if u else 0.0
        demand = (uu - x[0]) * 1e3
        return np.array([np.clip(demand, self.params["falling"],
                                 self.params["rising"])])

    def label(self):
        return "rate\nlimit"


@register
class Quantizer(Block):
    type_name = "Quantizer"
    category = _CAT
    description = "Round to a multiple of the step — an ADC or encoder."
    params_spec = (ParamSpec("interval", "Quantisation interval", 0.1),)

    def configure(self) -> None:
        if self.params["interval"] <= 0:
            raise BlockError("Quantizer interval must be positive")

    def output(self, t, x, xd, u):
        q = self.params["interval"]
        return [q * np.round(np.atleast_1d(u[0]) / q)]

    def label(self):
        return "quant"


@register
class Switch(Block):
    type_name = "Switch"
    category = _CAT
    description = "Pass input 1 or input 3 depending on the control input 2."
    default_inputs = ("in1", "control", "in3")
    params_spec = (
        ParamSpec("threshold", "Threshold", 0.0),
        ParamSpec("condition", "Pass in1 when control", ">=", kind="choice",
                  choices=(">=", ">", "~=0")),
    )

    def _take_first(self, c: float) -> bool:
        cond, thr = self.params["condition"], self.params["threshold"]
        if cond == ">=":
            return c >= thr
        if cond == ">":
            return c > thr
        return abs(c) > 1e-12

    def output(self, t, x, xd, u):
        c = float(np.atleast_1d(u[1])[0])
        return [np.atleast_1d(u[0] if self._take_first(c) else u[2])]

    def output_widths(self, input_widths):
        return [max(input_widths[0], input_widths[2])] if len(input_widths) == 3 \
            else [1]

    def zero_crossings(self, t, x, xd, u):
        return np.atleast_1d(u[1]) - self.params["threshold"]

    def label(self):
        return "switch"


@register
class CoulombFriction(Block):
    type_name = "CoulombFriction"
    category = _CAT
    description = "Coulomb + viscous friction: offset·sign(u) + gain·u."
    params_spec = (
        ParamSpec("offset", "Coulomb offset", 0.1),
        ParamSpec("gain", "Viscous gain", 1.0),
    )

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        p = self.params
        return [np.where(np.abs(v) < 1e-12, 0.0,
                         p["offset"] * np.sign(v) + p["gain"] * v)]

    def zero_crossings(self, t, x, xd, u):
        return np.atleast_1d(u[0]).copy()

    def label(self):
        return "friction"


@register
class Lookup1D(Block):
    type_name = "Lookup1D"
    category = _CAT
    description = "Piecewise-linear table, interpolated and clamped at the ends."
    params_spec = (
        ParamSpec("x_table", "Input breakpoints", "-1, 0, 1", kind="vector"),
        ParamSpec("y_table", "Output values", "-1, 0, 1", kind="vector"),
    )

    def configure(self) -> None:
        from .continuous import _parse_vector
        self._x = _parse_vector(self.params["x_table"])
        self._y = _parse_vector(self.params["y_table"])
        if len(self._x) != len(self._y):
            raise BlockError(
                f"Lookup1D {self.block_id!r}: {len(self._x)} breakpoints but "
                f"{len(self._y)} output values"
            )
        if np.any(np.diff(self._x) <= 0):
            raise BlockError(
                f"Lookup1D {self.block_id!r}: breakpoints must increase "
                f"strictly, so the table can be inverted for interpolation"
            )

    def output(self, t, x, xd, u):
        return [np.interp(np.atleast_1d(u[0]), self._x, self._y)]

    def label(self):
        return "lookup"


@register
class Backlash(Block):
    type_name = "Backlash"
    category = _CAT
    description = "Mechanical play: the output only moves once the slack is taken up."
    params_spec = (
        ParamSpec("width", "Deadband width", 0.1),
        ParamSpec("x0", "Initial output", 0.0),
    )

    def configure(self) -> None:
        if self.params["width"] < 0:
            raise BlockError("Backlash width cannot be negative")

    @property
    def n_states(self) -> int:
        return 1

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def initial_continuous_state(self):
        return np.array([float(self.params["x0"])])

    def output(self, t, x, xd, u):
        return [x.copy()]

    def derivative(self, t, x, xd, u):
        # The output follows the input only while pressed against one side of
        # the slack; inside the band the gear is free and nothing moves.
        half = self.params["width"] / 2.0
        uu = float(np.atleast_1d(u[0])[0]) if u else 0.0
        if uu - x[0] > half:
            return np.array([(uu - half - x[0]) * 1e3])
        if x[0] - uu > half:
            return np.array([(uu + half - x[0]) * 1e3])
        return np.zeros(1)

    def zero_crossings(self, t, x, xd, u):
        half = self.params["width"] / 2.0
        uu = float(np.atleast_1d(u[0])[0]) if u else 0.0
        return np.array([uu - x[0] - half, x[0] - uu - half])

    def label(self):
        return "backlash"
