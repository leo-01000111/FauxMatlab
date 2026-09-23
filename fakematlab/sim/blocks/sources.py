"""Source blocks — signals that drive a model."""

from __future__ import annotations

import numpy as np

from ..block import Block, BlockError, ParamSpec, register

_CAT = "Sources"


@register
class Constant(Block):
    type_name = "Constant"
    category = _CAT
    description = "A fixed value."
    default_inputs = ()
    params_spec = (
        ParamSpec("value", "Value", 1.0, help="Constant output."),
    )

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output_widths(self, input_widths):
        return [np.atleast_1d(np.asarray(self.params["value"])).size]

    def output(self, t, x, xd, u):
        return [np.atleast_1d(np.asarray(self.params["value"], dtype=float))]

    def label(self):
        return f"{self.params['value']:g}"


@register
class Step(Block):
    type_name = "Step"
    category = _CAT
    description = "Step from an initial to a final value at a given time."
    default_inputs = ()
    params_spec = (
        ParamSpec("step_time", "Step time", 1.0),
        ParamSpec("initial", "Initial value", 0.0),
        ParamSpec("final", "Final value", 1.0),
    )

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        p = self.params
        value = p["final"] if t >= p["step_time"] else p["initial"]
        return [np.array([float(value)])]

    def zero_crossings(self, t, x, xd, u):
        # Let the solver land exactly on the step instead of straddling it,
        # which would otherwise smear the discontinuity over one step and
        # make the response depend on the step size.
        return np.array([t - self.params["step_time"]])

    def label(self):
        return "Step"


@register
class Ramp(Block):
    type_name = "Ramp"
    category = _CAT
    description = "Constant slope after a start time."
    default_inputs = ()
    params_spec = (
        ParamSpec("slope", "Slope", 1.0),
        ParamSpec("start_time", "Start time", 0.0),
        ParamSpec("initial", "Initial output", 0.0),
    )

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        p = self.params
        dt = max(t - p["start_time"], 0.0)
        return [np.array([p["initial"] + p["slope"] * dt])]


@register
class Sine(Block):
    type_name = "Sine"
    category = _CAT
    description = "A · sin(ω t + φ) + bias."
    default_inputs = ()
    params_spec = (
        ParamSpec("amplitude", "Amplitude", 1.0),
        ParamSpec("frequency", "Frequency (rad/s)", 1.0),
        ParamSpec("phase", "Phase (rad)", 0.0),
        ParamSpec("bias", "Bias", 0.0),
    )

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        p = self.params
        return [np.array([p["bias"] + p["amplitude"] *
                          np.sin(p["frequency"] * t + p["phase"])])]


@register
class Chirp(Block):
    type_name = "Chirp"
    category = _CAT
    description = "Sine sweeping linearly in frequency — one run gives a Bode plot."
    default_inputs = ()
    params_spec = (
        ParamSpec("amplitude", "Amplitude", 1.0),
        ParamSpec("f_start", "Start freq (rad/s)", 0.1),
        ParamSpec("f_end", "End freq (rad/s)", 10.0),
        ParamSpec("sweep_time", "Sweep time (s)", 10.0),
    )

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        p = self.params
        rate = (p["f_end"] - p["f_start"]) / max(p["sweep_time"], 1e-12)
        # Phase is the integral of the instantaneous frequency.
        phase = p["f_start"] * t + 0.5 * rate * t * t
        return [np.array([p["amplitude"] * np.sin(phase)])]


@register
class Pulse(Block):
    type_name = "Pulse"
    category = _CAT
    description = "Periodic rectangular pulse."
    default_inputs = ()
    params_spec = (
        ParamSpec("amplitude", "Amplitude", 1.0),
        ParamSpec("period", "Period (s)", 2.0),
        ParamSpec("duty", "Duty cycle (0–1)", 0.5),
        ParamSpec("delay", "Start delay (s)", 0.0),
    )

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def _phase(self, t: float) -> float:
        p = self.params
        return (t - p["delay"]) % max(p["period"], 1e-12)

    def output(self, t, x, xd, u):
        p = self.params
        if t < p["delay"]:
            return [np.array([0.0])]
        on = self._phase(t) < p["duty"] * p["period"]
        return [np.array([p["amplitude"] if on else 0.0])]

    def zero_crossings(self, t, x, xd, u):
        p = self.params
        phase = self._phase(t)
        return np.array([phase - p["duty"] * p["period"]])


@register
class Clock(Block):
    type_name = "Clock"
    category = _CAT
    description = "Simulation time."
    default_inputs = ()

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        return [np.array([float(t)])]


@register
class BandLimitedNoise(Block):
    type_name = "Noise"
    category = _CAT
    description = "Band-limited white noise, held over a sample period."
    default_inputs = ()
    params_spec = (
        ParamSpec("power", "Noise power", 0.01),
        ParamSpec("sample_time", "Sample time (s)", 0.05),
        ParamSpec("seed", "Seed", 0, kind="int"),
    )

    def configure(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._rng = np.random.default_rng(int(self.params["seed"]))
        self._cache: dict[int, float] = {}

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        ts = max(self.params["sample_time"], 1e-12)
        # Key on the sample index, not on t: the ODE solver evaluates the same
        # instant repeatedly within a step, and a fresh draw each time would
        # make the "signal" depend on the solver's internal stages.
        k = int(np.floor(t / ts))
        if k not in self._cache:
            sigma = np.sqrt(max(self.params["power"], 0.0) / ts)
            self._cache[k] = float(self._rng.normal(0.0, sigma))
        return [np.array([self._cache[k]])]


@register
class PRBS(Block):
    type_name = "PRBS"
    category = _CAT
    description = "Pseudo-random binary sequence — the standard identification input."
    default_inputs = ()
    params_spec = (
        ParamSpec("amplitude", "Amplitude", 1.0),
        ParamSpec("sample_time", "Bit period (s)", 0.1),
        ParamSpec("seed", "Seed", 1, kind="int"),
    )

    def configure(self) -> None:
        if self.params["sample_time"] <= 0:
            raise BlockError("PRBS needs a positive bit period")
        self.reset()

    def reset(self) -> None:
        self._rng = np.random.default_rng(int(self.params["seed"]))
        self._cache: dict[int, float] = {}

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        ts = self.params["sample_time"]
        # Keyed on the bit index so every solver stage within one bit sees the
        # same value — a fresh draw per evaluation is noise, not a signal.
        k = int(np.floor(max(t, 0.0) / ts))
        if k not in self._cache:
            self._cache[k] = float(self._rng.choice([-1.0, 1.0]))
        return [np.array([self.params["amplitude"] * self._cache[k]])]

    def label(self):
        return "PRBS"
