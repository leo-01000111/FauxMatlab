"""
Discontinuous blocks.

Every block here has a kink or a jump in its input/output map. Each declares
:meth:`~evans.sim.block.Block.zero_crossings` so the solver can stop
exactly on the discontinuity: integrating straight through one makes the
local error estimate meaningless, which shows up as a step size that collapses
towards zero, or — worse — a plausible-looking answer that changes when you
change the tolerance.

Most of them also have **modes** (see :class:`~evans.sim.block.ModeLatch`):
the region, on/off or engaged state is computed by ``_fresh_mode`` from the
input, latched by the solver between crossings, and every evaluation goes
through the latched value. Each ``_fresh_mode`` tests its zero-crossing values
as ``z >= 0``, the convention the solver uses for a value of exactly zero.
"""

from __future__ import annotations

import numpy as np

from ..block import Block, BlockError, ModeLatch, ParamSpec, register

_CAT = "Discontinuities"


@register
class Saturation(ModeLatch, Block):
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

    def _fresh_mode(self, v):
        # +1 on the upper limit, -1 on the lower, 0 in between.
        p = self.params
        return np.where(v - p["upper"] >= 0, 1.0,
                        np.where(v - p["lower"] < 0, -1.0, 0.0))

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        mode = self._mode_or(self._fresh_mode(v))
        return [np.where(mode > 0, self.params["upper"],
                         np.where(mode < 0, self.params["lower"], v))]

    def zero_crossings(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        return np.concatenate([v - self.params["upper"],
                               v - self.params["lower"]])

    def n_zero_crossings(self, input_widths):
        return 2 * input_widths[0]

    def update_modes(self, t, x, xd, u):
        return self._latch(self._fresh_mode(np.atleast_1d(u[0])))

    def label(self):
        return "sat"


@register
class DeadZone(ModeLatch, Block):
    type_name = "DeadZone"
    category = _CAT
    description = "Zero output inside a band — stiction, backlash, valve overlap."
    params_spec = (
        ParamSpec("start", "Dead zone start", -0.1),
        ParamSpec("end", "Dead zone end", 0.1),
    )

    def _fresh_mode(self, v):
        # +1 above the band, -1 below it, 0 inside.
        p = self.params
        return np.where(v - p["end"] >= 0, 1.0,
                        np.where(v - p["start"] < 0, -1.0, 0.0))

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        lo, hi = self.params["start"], self.params["end"]
        mode = self._mode_or(self._fresh_mode(v))
        return [np.where(mode > 0, v - hi, np.where(mode < 0, v - lo, 0.0))]

    def zero_crossings(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        return np.concatenate([v - self.params["start"],
                               v - self.params["end"]])

    def n_zero_crossings(self, input_widths):
        return 2 * input_widths[0]

    def update_modes(self, t, x, xd, u):
        return self._latch(self._fresh_mode(np.atleast_1d(u[0])))

    def label(self):
        return "dead\nzone"


@register
class Relay(ModeLatch, Block):
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
        # The relay's initial on/off memory. Hysteresis means the output
        # depends on history, not just on the present input. During a run the
        # memory is the latched mode: nothing clocks a discrete update for a
        # block with sample time 0, so a memory kept here never moved, and
        # the relay switched off again at the switch-*on* point.
        return 1

    @property
    def sample_time(self) -> float:
        # Driven by zero crossings, not by a clock.
        return 0.0

    def _switched(self, on: bool, u) -> bool:
        """The memory ``on`` after seeing input ``u``."""
        z_on, z_off = self.zero_crossings(0.0, None, None, u)
        if z_on >= 0:
            return True
        if z_off >= 0:
            return False
        return on

    def _memory(self, xd) -> bool:
        if self._mode is not None:
            return bool(self._mode[0] > 0.5)
        return bool(xd is not None and len(xd) and xd[0] > 0.5)

    def output(self, t, x, xd, u):
        p = self.params
        on = self._memory(xd)
        if not self._latched:
            on = self._switched(on, u)
        return [np.array([p["on_value"] if on else p["off_value"]])]

    def update(self, t, x, xd, u):
        return np.array([1.0 if self._switched(self._memory(xd), u) else 0.0])

    def zero_crossings(self, t, x, xd, u):
        # Both written so that ``>= 0`` means "switch": on at or above the
        # on-point, off at or below the off-point.
        v = float(np.atleast_1d(u[0])[0]) if u else 0.0
        return np.array([v - self.params["on_point"],
                         self.params["off_point"] - v])

    def n_zero_crossings(self, input_widths):
        return 2

    def init_modes(self, t, x, xd, u):
        self._mode = None
        on = bool(len(xd) and xd[0] > 0.5)
        self._latch([1.0 if self._switched(on, u) else 0.0])

    def update_modes(self, t, x, xd, u):
        return self._latch(
            [1.0 if self._switched(self._memory(xd), u) else 0.0])

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
class Switch(ModeLatch, Block):
    type_name = "Switch"
    category = _CAT
    description = "Pass input 1 or input 3 depending on the control input 2."
    default_inputs = ("in1", "control", "in3")
    params_spec = (
        ParamSpec("threshold", "Threshold", 0.0),
        ParamSpec("condition", "Pass in1 when control", ">=", kind="choice",
                  choices=(">=", ">", "~=0")),
    )

    def _fresh_mode(self, u) -> np.ndarray:
        # 1 passes in1, 0 passes in3 — read off the zero-crossing values, so
        # the tie at the threshold falls the way the condition says.
        z = self.zero_crossings(0.0, None, None, u)
        cond = self.params["condition"]
        if cond == ">=":
            first = z[0] >= 0                       # c − thr ≥ 0
        elif cond == ">":
            first = not z[0] >= 0                   # thr − c ≥ 0 means in3
        else:
            first = not (z[0] >= 0 and z[1] >= 0)   # both ≥ 0 only at c = 0
        return np.array([1.0 if first else 0.0])

    def output(self, t, x, xd, u):
        mode = self._mode_or(self._fresh_mode(u))
        return [np.atleast_1d(u[0] if mode[0] > 0.5 else u[2])]

    def output_widths(self, input_widths):
        return [max(input_widths[0], input_widths[2])] if len(input_widths) == 3 \
            else [1]

    def zero_crossings(self, t, x, xd, u):
        c = float(np.atleast_1d(u[1])[0])
        cond, thr = self.params["condition"], self.params["threshold"]
        if cond == ">=":
            return np.array([c - thr])
        if cond == ">":
            return np.array([thr - c])
        # "~=0" changes mode when c leaves zero in *either* direction, and a
        # single value can only flag one of them when c sits exactly at 0.
        return np.array([c, -c])

    def n_zero_crossings(self, input_widths):
        return 2 if self.params["condition"] == "~=0" else 1

    def update_modes(self, t, x, xd, u):
        return self._latch(self._fresh_mode(u))

    def label(self):
        return "switch"


@register
class CoulombFriction(ModeLatch, Block):
    type_name = "CoulombFriction"
    category = _CAT
    description = "Coulomb + viscous friction: offset·sign(u) + gain·u."
    params_spec = (
        ParamSpec("offset", "Coulomb offset", 0.1),
        ParamSpec("gain", "Viscous gain", 1.0),
    )

    def _fresh_mode(self, v):
        # Slipping forward (+1), backward (−1), or stuck (0). Stuck needs both
        # values ≥ 0, i.e. v exactly 0: a mass at rest stays at rest until
        # its velocity actually leaves zero, in either direction.
        return np.where(-v < 0, 1.0, np.where(v < 0, -1.0, 0.0))

    def output(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        p = self.params
        mode = self._mode_or(self._fresh_mode(v))
        return [p["offset"] * mode + p["gain"] * v]

    def zero_crossings(self, t, x, xd, u):
        v = np.atleast_1d(u[0])
        return np.concatenate([v, -v])

    def n_zero_crossings(self, input_widths):
        return 2 * input_widths[0]

    def update_modes(self, t, x, xd, u):
        return self._latch(self._fresh_mode(np.atleast_1d(u[0])))

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
class Backlash(ModeLatch, Block):
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

    def _fresh_mode(self, x, u):
        # +1 driven by the upper face, −1 by the lower, 0 free in the slack.
        z_up, z_down = self.zero_crossings(0.0, x, None, u)
        return np.array([1.0 if z_up >= 0 else -1.0 if z_down >= 0 else 0.0])

    def derivative(self, t, x, xd, u):
        # The output follows the input only while pressed against one side of
        # the slack; inside the band the gear is free and nothing moves.
        half = self.params["width"] / 2.0
        uu = float(np.atleast_1d(u[0])[0]) if u else 0.0
        mode = self._mode_or(self._fresh_mode(x, u))[0]
        if mode > 0:
            return np.array([(uu - half - x[0]) * 1e3])
        if mode < 0:
            return np.array([(uu + half - x[0]) * 1e3])
        return np.zeros(1)

    def zero_crossings(self, t, x, xd, u):
        half = self.params["width"] / 2.0
        uu = float(np.atleast_1d(u[0])[0]) if u else 0.0
        return np.array([uu - x[0] - half, x[0] - uu - half])

    def n_zero_crossings(self, input_widths):
        return 2

    def update_modes(self, t, x, xd, u):
        return self._latch(self._fresh_mode(x, u))

    def label(self):
        return "backlash"
