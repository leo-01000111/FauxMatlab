"""
Hierarchy: subsystems, and the ports that define their boundary.

A :class:`Subsystem` holds a nested model. It is never simulated as a block —
:func:`fakematlab.sim.compile.flatten` splices its contents into the parent
before anything runs, so the engine only ever sees a flat graph and needs no
notion of hierarchy at all.

Flattening rather than recursive evaluation matters for more than tidiness:
the algebraic-loop detector, the execution sort and the state layout all work
on the whole graph at once. A loop that runs *through* a subsystem is a real
algebraic loop, and only a flat view can see it.
"""

from __future__ import annotations

import numpy as np

from ..block import Block, BlockError, ParamSpec, register

_CAT = "Hierarchy"


@register
class Inport(Block):
    type_name = "Inport"
    category = _CAT
    description = "An input of the enclosing subsystem."
    default_inputs = ()
    params_spec = (
        ParamSpec("port_name", "Port name", "in", kind="str"),
        ParamSpec("order", "Port order", 1, kind="int"),
    )

    @property
    def direct_feedthrough(self) -> bool:
        return False

    def output(self, t, x, xd, u):
        # Only reached if an Inport is left at the top level, where there is
        # no enclosing subsystem to supply a value.
        return [np.zeros(1)]

    def label(self):
        return f"▸ {self.params['port_name']}"


@register
class Outport(Block):
    type_name = "Outport"
    category = _CAT
    description = "An output of the enclosing subsystem."
    default_outputs = ()
    params_spec = (
        ParamSpec("port_name", "Port name", "out", kind="str"),
        ParamSpec("order", "Port order", 1, kind="int"),
    )

    def output_widths(self, input_widths):
        return []

    def output(self, t, x, xd, u):
        return []

    def label(self):
        return f"{self.params['port_name']} ▸"


@register
class Subsystem(Block):
    """
    A block containing another model.

    Its ports are named by the ``Inport``/``Outport`` blocks inside, ordered by
    their ``order`` parameter, so rearranging the inside changes the outside
    predictably.
    """

    type_name = "Subsystem"
    category = _CAT
    description = "A group of blocks, edited as its own diagram."
    default_inputs = ()
    default_outputs = ()
    params_spec = (
        ParamSpec("name", "Name", "Subsystem", kind="str"),
        ParamSpec("model", "Contents", None, kind="model",
                  help="The nested model, edited by double-clicking."),
    )

    def configure(self) -> None:
        self.inputs = [name for name, _ in self._boundary("Inport")]
        self.outputs = [name for name, _ in self._boundary("Outport")]

    # ── contents ────────────────────────────────────────────────

    def inner_dict(self) -> dict:
        """The nested model as a plain dict (possibly empty)."""
        data = self.params.get("model")
        if not data:
            from ..model import SimModel
            return SimModel(self.params.get("name", "Subsystem")).to_dict()
        return data

    def inner_model(self):
        from ..model import SimModel
        return SimModel.from_dict(self.inner_dict())

    def set_inner(self, model) -> None:
        self.set_param("model", model.to_dict())

    def _boundary(self, type_name: str) -> list[tuple[str, str]]:
        """``[(port name, block id)]`` for the boundary blocks, in order."""
        data = self.params.get("model")
        if not data:
            return []
        entries = [e for e in data.get("blocks", [])
                   if e.get("type") == type_name]
        entries.sort(key=lambda e: (e.get("params", {}).get("order", 1),
                                    e.get("id", "")))
        seen: dict[str, str] = {}
        for entry in entries:
            name = entry.get("params", {}).get("port_name") or entry["id"]
            # Two ports with the same name would make the outside ambiguous.
            if name in seen:
                name = f"{name}_{entry['id']}"
            seen[name] = entry["id"]
        return list(seen.items())

    def inport_ids(self) -> dict[str, str]:
        return dict(self._boundary("Inport"))

    def outport_ids(self) -> dict[str, str]:
        return dict(self._boundary("Outport"))

    # ── never simulated directly ────────────────────────────────

    def output(self, t, x, xd, u):
        raise BlockError(
            f"Subsystem {self.block_id!r} reached the solver. Subsystems are "
            f"spliced into the parent by compile.flatten() before a run; this "
            f"means flattening was skipped."
        )

    def label(self):
        # A brand-new subsystem has model=None until something is put in it,
        # so this must survive an empty one — it is drawn before it is filled.
        data = self.params.get("model") or {}
        n = len(data.get("blocks", []))
        return f"{self.params['name']}\n({n} block{'s' if n != 1 else ''})"
