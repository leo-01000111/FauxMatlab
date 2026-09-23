"""
The simulation half of FakeMatlab — a working Simulink.

A :class:`~fakematlab.sim.model.SimModel` is a graph of blocks with typed
ports. :mod:`fakematlab.sim.compile` flattens and sorts it,
:mod:`fakematlab.sim.solver` integrates it, and
:mod:`fakematlab.sim.linearize` hands the result back to the classical and
modern analysis tabs as a transfer function or a state-space model.

Why a custom engine rather than ``control.interconnect``
--------------------------------------------------------
``interconnect`` handles pure-continuous nonlinear models well, but it raises
``ValueError: Systems have incompatible timebases`` the moment a continuous
plant meets a discrete controller. A Simulink that cannot run a sampled
controller against a continuous plant is not a Simulink. It is still used as
an oracle in the tests, for the continuous-only cases where it does apply.
"""

# Importing the package registers the whole block library, so any entry point
# into fakematlab.sim finds a populated palette. Without this, importing only
# `sim.model` gave an empty registry and every block type was "unknown".
from . import blocks  # noqa: E402,F401
from .block import block_types, by_category, create  # noqa: E402,F401
from .compile import CompileError, compile_model  # noqa: E402,F401
from .model import SimModel  # noqa: E402,F401
from .solver import SimulationError, simulate  # noqa: E402,F401

__all__ = [
    "SimModel", "simulate", "compile_model", "create",
    "block_types", "by_category", "CompileError", "SimulationError",
]
