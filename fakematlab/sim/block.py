"""
The block contract.
===================
Every block in the library implements this interface, and the compiler and
solver know nothing else about them. Adding a block means subclassing
:class:`Block` and registering it — no changes anywhere else.

The state model
---------------
A block may own **continuous** states (integrated by the ODE solver) and
**discrete** states (updated at its own sample times). Both are flat 1-D
arrays; the compiler concatenates every block's states into one global vector
and hands each block back its own slice.

Direct feedthrough
------------------
:attr:`Block.direct_feedthrough` says whether ``output()`` reads ``u``. This is
the single most important property for the compiler: it is what determines
execution order, and a cycle among feedthrough blocks is an algebraic loop.
Declaring it wrongly produces either a spurious algebraic loop (too eager) or
a block evaluated with stale inputs (too lazy), so the default is the safe
one — ``True``.

Signals
-------
Every signal is a 1-D ``numpy`` array. Most blocks are width-preserving and
elementwise; those that are not (``Mux``, ``Demux``, ``TransferFcn``) declare
their widths through :meth:`Block.output_widths`, which the compiler drives to
a fixed point.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np


class BlockError(Exception):
    """A block was configured or connected in a way it cannot support."""


@dataclass
class ParamSpec:
    """One editable parameter, for the canvas's parameter dialog."""
    name:    str
    label:   str
    default: Any
    kind:    str = "float"      # float | int | bool | str | vector | choice
    choices: tuple = ()
    help:    str = ""


# ──────────────────────────────────────────────────────────────
#  Block
# ──────────────────────────────────────────────────────────────

class Block(ABC):
    """Base class for every simulation block."""

    #: Library name, unique. Used in the palette and in saved models.
    type_name: ClassVar[str] = ""
    #: Palette grouping.
    category: ClassVar[str] = "Other"
    #: One-line description shown in the palette tooltip.
    description: ClassVar[str] = ""
    #: Editable parameters.
    params_spec: ClassVar[tuple[ParamSpec, ...]] = ()
    #: Default port names.
    default_inputs:  ClassVar[tuple[str, ...]] = ("in",)
    default_outputs: ClassVar[tuple[str, ...]] = ("out",)

    def __init__(self, block_id: str, **params: Any) -> None:
        self.block_id = block_id
        self.params: dict[str, Any] = {
            spec.name: spec.default for spec in self.params_spec
        }
        unknown = set(params) - set(self.params)
        if unknown:
            raise BlockError(
                f"{self.type_name} has no parameter(s) "
                f"{', '.join(sorted(unknown))}; "
                f"valid: {', '.join(sorted(self.params)) or '(none)'}"
            )
        self.params.update(params)
        self.inputs = list(self.default_inputs)
        self.outputs = list(self.default_outputs)
        self.configure()

    # ── configuration ───────────────────────────────────────────

    def configure(self) -> None:
        """
        Recompute anything derived from :attr:`params`.

        Called on construction and again whenever a parameter changes, so a
        block can validate and pre-compute (state-space matrices, for
        instance) in one place.
        """

    def set_param(self, name: str, value: Any) -> None:
        if name not in self.params:
            raise BlockError(f"{self.type_name} has no parameter {name!r}")
        self.params[name] = value
        self.configure()

    # ── structure ───────────────────────────────────────────────

    @property
    def n_states(self) -> int:
        """Number of continuous states."""
        return 0

    @property
    def n_dstates(self) -> int:
        """Number of discrete states."""
        return 0

    @property
    def sample_time(self) -> float:
        """``0`` for a continuous block, ``> 0`` for a discrete one."""
        return 0.0

    @property
    def direct_feedthrough(self) -> bool:
        """
        Whether :meth:`output` reads ``u``.

        Defaults to ``True``: over-declaring costs a possible false algebraic
        loop, which is reported and fixable, while under-declaring silently
        evaluates the block with stale inputs.
        """
        return True

    def output_widths(self, input_widths: list[int]) -> list[int]:
        """
        Width of each output port given the input widths.

        The default is elementwise: one output, as wide as the widest input
        (or 1 with no inputs).
        """
        width = max(input_widths) if input_widths else 1
        return [width] * len(self.outputs)

    def validate_widths(self, input_widths: list[int]) -> None:
        """Raise :class:`BlockError` if these input widths are unusable."""

    # ── behaviour ───────────────────────────────────────────────

    def initial_continuous_state(self) -> np.ndarray:
        return np.zeros(self.n_states)

    def initial_discrete_state(self) -> np.ndarray:
        return np.zeros(self.n_dstates)

    @abstractmethod
    def output(self, t: float, x: np.ndarray, xd: np.ndarray,
               u: list[np.ndarray]) -> list[np.ndarray]:
        """Outputs at time ``t``, one array per output port."""

    def derivative(self, t: float, x: np.ndarray, xd: np.ndarray,
                   u: list[np.ndarray]) -> np.ndarray:
        """``dx/dt`` for the continuous states."""
        return np.zeros(self.n_states)

    def update(self, t: float, x: np.ndarray, xd: np.ndarray,
               u: list[np.ndarray]) -> np.ndarray:
        """Next discrete state, evaluated at a sample hit."""
        return xd

    def zero_crossings(self, t: float, x: np.ndarray, xd: np.ndarray,
                       u: list[np.ndarray]) -> np.ndarray:
        """
        Values whose sign changes mark a discontinuity.

        The solver watches these and lands a step exactly on each crossing, so
        a saturation limit or a relay switch is hit precisely instead of being
        smeared across a step. Return an empty array for smooth blocks.
        """
        return np.zeros(0)

    def reset(self) -> None:
        """Clear any per-run internal caching before a simulation starts."""

    # ── presentation ────────────────────────────────────────────

    def label(self) -> str:
        """Text drawn inside the block on the canvas."""
        return self.type_name

    def __repr__(self) -> str:
        return f"<{self.type_name} {self.block_id!r} {self.params}>"


# ──────────────────────────────────────────────────────────────
#  Registry
# ──────────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[Block]] = {}


def register(cls: type[Block]) -> type[Block]:
    """Class decorator adding a block to the library."""
    if not cls.type_name:
        raise BlockError(f"{cls.__name__} must define a type_name")
    if cls.type_name in _REGISTRY:
        raise BlockError(f"duplicate block type {cls.type_name!r}")
    _REGISTRY[cls.type_name] = cls
    return cls


def block_types() -> dict[str, type[Block]]:
    """Every registered block, keyed by type name."""
    return dict(_REGISTRY)


def create(type_name: str, block_id: str, **params: Any) -> Block:
    """Instantiate a block by library name."""
    try:
        cls = _REGISTRY[type_name]
    except KeyError:
        raise BlockError(
            f"unknown block type {type_name!r}. "
            f"Available: {', '.join(sorted(_REGISTRY))}"
        ) from None
    return cls(block_id, **params)


def by_category() -> dict[str, list[type[Block]]]:
    """The library grouped for the palette."""
    grouped: dict[str, list[type[Block]]] = {}
    for cls in _REGISTRY.values():
        grouped.setdefault(cls.category, []).append(cls)
    for blocks in grouped.values():
        blocks.sort(key=lambda c: c.type_name)
    return dict(sorted(grouped.items()))


# ──────────────────────────────────────────────────────────────
#  Helpers for block authors
# ──────────────────────────────────────────────────────────────

def as_array(value, width: int = 1) -> np.ndarray:
    """Coerce a scalar or sequence to a 1-D array of the given width."""
    arr = np.atleast_1d(np.asarray(value, dtype=float)).ravel()
    if arr.size == width:
        return arr
    if arr.size == 1:
        return np.full(width, float(arr[0]))
    raise BlockError(f"cannot broadcast {arr.size} values to width {width}")
