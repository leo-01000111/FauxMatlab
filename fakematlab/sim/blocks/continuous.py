"""Continuous-time blocks: transfer functions, state space, integrators, PID."""

from __future__ import annotations

import control as ctl
import numpy as np

from ..block import Block, BlockError, ParamSpec, as_array, register

_CAT = "Continuous"


def _parse_vector(value) -> np.ndarray:
    """Accept a list, tuple, array or comma-separated string of numbers."""
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
        value = [float(p) for p in parts if p]
    arr = np.atleast_1d(np.asarray(value, dtype=float)).ravel()
    if arr.size == 0:
        raise BlockError("empty coefficient list")
    return arr


class _StateSpaceBlock(Block):
    """
    Shared machinery for blocks defined by ``(A, B, C, D)``.

    Subclasses set ``self._A/_B/_C/_D`` in :meth:`configure`. Keeping the
    realisation here means the transfer-function, zero-pole and state-space
    blocks share one tested integration path.
    """

    _A: np.ndarray
    _B: np.ndarray
    _C: np.ndarray
    _D: np.ndarray

    @property
    def n_states(self) -> int:
        return int(self._A.shape[0])

    @property
    def direct_feedthrough(self) -> bool:
        return bool(np.any(np.abs(self._D) > 1e-15))

    def validate_widths(self, input_widths):
        if input_widths and input_widths[0] != self._B.shape[1]:
            raise BlockError(
                f"{self.type_name} {self.block_id!r} takes a width-"
                f"{self._B.shape[1]} input, got {input_widths[0]}"
            )

    def output_widths(self, input_widths):
        return [int(self._C.shape[0])]

    def initial_continuous_state(self) -> np.ndarray:
        x0 = self.params.get("x0", 0.0)
        return as_array(x0, self.n_states) if self.n_states else np.zeros(0)

    def output(self, t, x, xd, u):
        uu = u[0] if u else np.zeros(self._B.shape[1])
        y = self._C @ x + self._D @ uu
        return [np.atleast_1d(y)]

    def derivative(self, t, x, xd, u):
        uu = u[0] if u else np.zeros(self._B.shape[1])
        return self._A @ x + self._B @ uu


@register
class TransferFcn(_StateSpaceBlock):
    type_name = "TransferFcn"
    category = _CAT
    description = "num(s)/den(s), realised in controllable canonical form."
    params_spec = (
        ParamSpec("num", "Numerator", "1", kind="vector",
                  help="Coefficients, highest power first."),
        ParamSpec("den", "Denominator", "1, 1", kind="vector"),
        ParamSpec("x0", "Initial state", 0.0),
    )

    def configure(self) -> None:
        num = _parse_vector(self.params["num"])
        den = _parse_vector(self.params["den"])
        if len(num) > len(den):
            raise BlockError(
                f"TransferFcn {self.block_id!r} is improper "
                f"(numerator degree {len(num) - 1} > denominator degree "
                f"{len(den) - 1}). A block that differentiates its input "
                f"cannot be simulated; add poles or use a Derivative block."
            )
        self.tf = ctl.TransferFunction(num, den)
        ss = ctl.tf2ss(self.tf)
        self._A = np.atleast_2d(np.asarray(ss.A, dtype=float))
        self._B = np.atleast_2d(np.asarray(ss.B, dtype=float)).reshape(-1, 1)
        self._C = np.atleast_2d(np.asarray(ss.C, dtype=float)).reshape(1, -1)
        self._D = np.atleast_2d(np.asarray(ss.D, dtype=float)).reshape(1, 1)
        if self._A.size == 0:                      # pure gain
            self._A = np.zeros((0, 0))
            self._B = np.zeros((0, 1))
            self._C = np.zeros((1, 0))

    def label(self):
        from ...core.tf_utils import factored_str
        return factored_str(self.tf)


@register
class StateSpace(_StateSpaceBlock):
    type_name = "StateSpace"
    category = _CAT
    description = "ẋ = Ax + Bu,  y = Cx + Du."
    params_spec = (
        ParamSpec("A", "A", "0", kind="matrix"),
        ParamSpec("B", "B", "1", kind="matrix"),
        ParamSpec("C", "C", "1", kind="matrix"),
        ParamSpec("D", "D", "0", kind="matrix"),
        ParamSpec("x0", "Initial state", 0.0),
    )

    def configure(self) -> None:
        self._A = _as_matrix(self.params["A"])
        n = self._A.shape[0]
        self._B = _as_matrix(self.params["B"]).reshape(n, -1) if n else np.zeros((0, 1))
        self._C = _as_matrix(self.params["C"]).reshape(-1, n) if n else np.zeros((1, 0))
        self._D = _as_matrix(self.params["D"]).reshape(
            self._C.shape[0], self._B.shape[1])


def _as_matrix(value) -> np.ndarray:
    if isinstance(value, str):
        rows = [r for r in value.replace("\n", ";").split(";") if r.strip()]
        value = [[float(v) for v in r.replace(",", " ").split()] for r in rows]
    return np.atleast_2d(np.asarray(value, dtype=float))


@register
class Integrator(Block):
    type_name = "Integrator"
    category = _CAT
    description = "1/s, optionally saturating — the windup demonstration."
    params_spec = (
        ParamSpec("x0", "Initial condition", 0.0),
        ParamSpec("limit", "Limit output", False, kind="bool"),
        ParamSpec("upper", "Upper limit", 1.0),
        ParamSpec("lower", "Lower limit", -1.0),
    )

    @property
    def n_states(self) -> int:
        return 1

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def initial_continuous_state(self):
        return np.array([float(self.params["x0"])])

    def output(self, t, x, xd, u):
        return [self._clamp(x.copy())]

    def _clamp(self, x):
        if not self.params["limit"]:
            return x
        return np.clip(x, self.params["lower"], self.params["upper"])

    def derivative(self, t, x, xd, u):
        rate = np.atleast_1d(u[0])[:1] if u else np.zeros(1)
        if not self.params["limit"]:
            return rate
        # Anti-windup: hold the state at the limit while the input pushes
        # further out, so the integrator does not accumulate a charge it must
        # later discharge. Without this, a saturating loop overshoots wildly
        # long after the error has changed sign.
        lo, hi = self.params["lower"], self.params["upper"]
        held = ((x[0] >= hi) and rate[0] > 0) or ((x[0] <= lo) and rate[0] < 0)
        return np.zeros(1) if held else rate

    def zero_crossings(self, t, x, xd, u):
        if not self.params["limit"]:
            return np.zeros(0)
        return np.array([x[0] - self.params["upper"],
                         x[0] - self.params["lower"]])

    def label(self):
        return "1/s"


@register
class Derivative(Block):
    type_name = "Derivative"
    category = _CAT
    description = "Filtered derivative  s/(Tf·s + 1)."
    params_spec = (
        ParamSpec("Tf", "Filter time constant", 0.01,
                  help="An ideal derivative cannot be simulated; this is the "
                       "filtered form every real implementation uses."),
    )

    def configure(self) -> None:
        if self.params["Tf"] <= 0:
            raise BlockError(
                "Derivative needs Tf > 0. An ideal derivative has infinite "
                "high-frequency gain and no state-space realisation; pick a "
                "filter constant well below your fastest time constant."
            )

    @property
    def n_states(self) -> int:
        return 1

    def output(self, t, x, xd, u):
        Tf = self.params["Tf"]
        uu = np.atleast_1d(u[0])[0] if u else 0.0
        return [np.array([(uu - x[0]) / Tf])]

    def derivative(self, t, x, xd, u):
        Tf = self.params["Tf"]
        uu = np.atleast_1d(u[0])[0] if u else 0.0
        return np.array([(uu - x[0]) / Tf])

    def label(self):
        return "du/dt"


@register
class PID(Block):
    type_name = "PID"
    category = _CAT
    description = "Kp + Ki/s + Kd·s/(Tf·s+1), with anti-windup clamping."
    params_spec = (
        ParamSpec("Kp", "Kp", 1.0),
        ParamSpec("Ki", "Ki", 0.0),
        ParamSpec("Kd", "Kd", 0.0),
        ParamSpec("Tf", "Derivative filter Tf", 0.01),
        ParamSpec("limit", "Limit output", False, kind="bool"),
        ParamSpec("upper", "Upper limit", 1.0),
        ParamSpec("lower", "Lower limit", -1.0),
    )

    @property
    def n_states(self) -> int:
        # One integrator state, one derivative-filter state.
        return 2

    def _unclamped(self, x, uu):
        p = self.params
        d_term = p["Kd"] * (uu - x[1]) / max(p["Tf"], 1e-12)
        return p["Kp"] * uu + p["Ki"] * x[0] + d_term

    def output(self, t, x, xd, u):
        uu = np.atleast_1d(u[0])[0] if u else 0.0
        v = self._unclamped(x, uu)
        if self.params["limit"]:
            v = float(np.clip(v, self.params["lower"], self.params["upper"]))
        return [np.array([v])]

    def derivative(self, t, x, xd, u):
        p = self.params
        uu = np.atleast_1d(u[0])[0] if u else 0.0
        di = uu
        if p["limit"]:
            # Conditional integration: stop charging the integrator while the
            # output is saturated and the error would push it further out.
            v = self._unclamped(x, uu)
            if (v > p["upper"] and uu > 0) or (v < p["lower"] and uu < 0):
                di = 0.0
        return np.array([di, (uu - x[1]) / max(p["Tf"], 1e-12)])

    def zero_crossings(self, t, x, xd, u):
        if not self.params["limit"]:
            return np.zeros(0)
        uu = np.atleast_1d(u[0])[0] if u else 0.0
        v = self._unclamped(x, uu)
        return np.array([v - self.params["upper"], v - self.params["lower"]])

    def label(self):
        p = self.params
        parts = [f"Kp={p['Kp']:g}"]
        if p["Ki"]:
            parts.append(f"Ki={p['Ki']:g}")
        if p["Kd"]:
            parts.append(f"Kd={p['Kd']:g}")
        return "PID\n" + " ".join(parts)


@register
class TransportDelay(Block):
    type_name = "TransportDelay"
    category = _CAT
    description = "True delay y(t) = u(t − T), by interpolating the input history."
    params_spec = (
        ParamSpec("delay", "Delay (s)", 0.1),
        ParamSpec("initial", "Output before t = T", 0.0),
    )

    def configure(self) -> None:
        if self.params["delay"] < 0:
            raise BlockError("TransportDelay needs a non-negative delay")
        self.reset()

    def reset(self) -> None:
        self._times: list[float] = []
        self._values: list[np.ndarray] = []

    @property
    def direct_feedthrough(self) -> bool:
        # With a positive delay the output depends only on the *past*, never
        # on the present input, so it breaks algebraic loops — which is the
        # usual reason to reach for this block.
        return self.params["delay"] <= 0.0

    def record(self, t: float, value: np.ndarray) -> None:
        """
        Append an accepted solver step to the history.

        Called by the solver only for accepted steps: recording every internal
        stage would fill the buffer with points the trajectory never visited.
        """
        if self._times and t <= self._times[-1]:
            return
        self._times.append(float(t))
        self._values.append(np.array(value, dtype=float))

    def output(self, t, x, xd, u):
        delay = self.params["delay"]
        if delay <= 0:
            return [np.atleast_1d(u[0]) if u else np.zeros(1)]
        target = t - delay
        if not self._times or target <= self._times[0]:
            width = len(np.atleast_1d(u[0])) if u else 1
            return [np.full(width, float(self.params["initial"]))]
        times = np.asarray(self._times)
        values = np.asarray(self._values)
        out = np.array([np.interp(target, times, values[:, i])
                        for i in range(values.shape[1])])
        return [out]

    def label(self):
        return f"e^(−{self.params['delay']:g}s)"


@register
class ZeroPole(_StateSpaceBlock):
    type_name = "ZeroPole"
    category = _CAT
    description = "K·Π(s−zᵢ) / Π(s−pⱼ) — the form the course speaks in."
    params_spec = (
        ParamSpec("zeros", "Zeros", "", kind="vector",
                  help="Comma-separated; leave empty for none."),
        ParamSpec("poles", "Poles", "-1", kind="vector"),
        ParamSpec("gain", "Gain K", 1.0),
        ParamSpec("x0", "Initial state", 0.0),
    )

    def configure(self) -> None:
        zeros = _parse_optional_vector(self.params["zeros"])
        poles = _parse_optional_vector(self.params["poles"])
        if len(zeros) > len(poles):
            raise BlockError(
                f"ZeroPole {self.block_id!r} has more zeros ({len(zeros)}) "
                f"than poles ({len(poles)}), which is improper and cannot be "
                f"simulated."
            )
        num = np.atleast_1d(self.params["gain"] * np.poly(zeros)) if len(zeros) \
            else np.array([float(self.params["gain"])])
        den = np.poly(poles) if len(poles) else np.array([1.0])
        self.tf = ctl.TransferFunction(np.real(num), np.real(den))
        ss = ctl.tf2ss(self.tf)
        self._A = np.atleast_2d(np.asarray(ss.A, dtype=float))
        self._B = np.atleast_2d(np.asarray(ss.B, dtype=float)).reshape(-1, 1)
        self._C = np.atleast_2d(np.asarray(ss.C, dtype=float)).reshape(1, -1)
        self._D = np.atleast_2d(np.asarray(ss.D, dtype=float)).reshape(1, 1)
        if self._A.size == 0:
            self._A = np.zeros((0, 0))
            self._B = np.zeros((0, 1))
            self._C = np.zeros((1, 0))

    def label(self):
        from ...core.tf_utils import factored_str
        return factored_str(self.tf)


def _parse_optional_vector(value) -> np.ndarray:
    """Like :func:`_parse_vector` but an empty string means "none"."""
    if value is None:
        return np.zeros(0)
    if isinstance(value, str) and not value.strip():
        return np.zeros(0)
    if isinstance(value, (list, tuple, np.ndarray)) and len(value) == 0:
        return np.zeros(0)
    return _parse_vector(value)
