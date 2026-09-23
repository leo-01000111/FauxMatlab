"""
Undoable edits to a :class:`~fakematlab.sim.model.SimModel`.

Every command mutates only the model and then asks the canvas to rebuild from
it, so undo can never leave the drawing and the model disagreeing. Commands
are coarse on purpose: rebuilding a diagram of a few dozen blocks is
instantaneous, and the alternative — surgically undoing item-level changes —
is where diagram editors accumulate their subtlest bugs.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QUndoCommand

from ...sim.model import Connection, ModelError


class _ModelCommand(QUndoCommand):
    """Base: snapshot the whole model, restore it on undo."""

    def __init__(self, canvas, text: str) -> None:
        super().__init__(text)
        self.canvas = canvas
        self._before: dict[str, Any] | None = None
        self._after: dict[str, Any] | None = None

    # Subclasses implement apply(); the snapshots are handled here.
    def apply(self) -> None:
        raise NotImplementedError

    def redo(self) -> None:
        if self._after is not None:
            self.canvas.restore_model(self._after)
            return
        self._before = self.canvas.model.to_dict()
        self.apply()
        self._after = self.canvas.model.to_dict()
        self.canvas.rebuild()

    def undo(self) -> None:
        if self._before is not None:
            self.canvas.restore_model(self._before)


class AddBlock(_ModelCommand):
    def __init__(self, canvas, type_name: str, x: float, y: float) -> None:
        super().__init__(canvas, f"add {type_name}")
        self.type_name, self.x, self.y = type_name, x, y
        self.block_id: str | None = None

    def apply(self) -> None:
        block = self.canvas.model.add(self.type_name, x=self.x, y=self.y)
        self.block_id = block.block_id


class DeleteSelection(_ModelCommand):
    def __init__(self, canvas, block_ids: list[str],
                 connections: list[Connection]) -> None:
        n = len(block_ids) + len(connections)
        super().__init__(canvas, f"delete {n} item{'s' if n != 1 else ''}")
        self.block_ids = list(block_ids)
        self.connections = list(connections)

    def apply(self) -> None:
        for conn in self.connections:
            self.canvas.model.disconnect(conn)
        for bid in self.block_ids:
            self.canvas.model.remove(bid)


class Connect(_ModelCommand):
    def __init__(self, canvas, src: str, dst: str) -> None:
        super().__init__(canvas, f"connect {src} → {dst}")
        self.src, self.dst = src, dst

    def apply(self) -> None:
        self.canvas.model.connect(self.src, self.dst)


class MoveBlock(_ModelCommand):
    def __init__(self, canvas, block_id: str, x: float, y: float) -> None:
        super().__init__(canvas, f"move {block_id}")
        self.block_id, self.x, self.y = block_id, x, y

    def apply(self) -> None:
        self.canvas.model.move(self.block_id, self.x, self.y)

    def id(self) -> int:
        return 1001

    def mergeWith(self, other: QUndoCommand) -> bool:
        """Collapse a drag into one undo step rather than one per pixel."""
        if not isinstance(other, MoveBlock) or other.block_id != self.block_id:
            return False
        self.x, self.y = other.x, other.y
        self._after = other._after
        return True


class SetParams(_ModelCommand):
    def __init__(self, canvas, block_id: str, params: dict[str, Any]) -> None:
        super().__init__(canvas, f"edit {block_id}")
        self.block_id, self.params = block_id, dict(params)

    def apply(self) -> None:
        block = self.canvas.model.block(self.block_id)
        for name, value in self.params.items():
            block.set_param(name, value)


class PasteBlocks(_ModelCommand):
    def __init__(self, canvas, payload: dict[str, Any],
                 dx: float, dy: float) -> None:
        n = len(payload.get("blocks", []))
        super().__init__(canvas, f"paste {n} block{'s' if n != 1 else ''}")
        self.payload, self.dx, self.dy = payload, dx, dy
        self.new_ids: dict[str, str] = {}

    def apply(self) -> None:
        model = self.canvas.model
        self.new_ids = {}
        for entry in self.payload.get("blocks", []):
            block = model.add(entry["type"],
                              x=entry.get("x", 0.0) + self.dx,
                              y=entry.get("y", 0.0) + self.dy,
                              **entry.get("params", {}))
            self.new_ids[entry["id"]] = block.block_id
        # Only wires wholly inside the pasted selection are reproduced;
        # a wire to a block that was not copied has nothing to attach to.
        for entry in self.payload.get("connections", []):
            src_block, _, src_port = entry["src"].partition(".")
            dst_block, _, dst_port = entry["dst"].partition(".")
            if src_block in self.new_ids and dst_block in self.new_ids:
                try:
                    model.connect(f"{self.new_ids[src_block]}.{src_port}",
                                  f"{self.new_ids[dst_block]}.{dst_port}")
                except ModelError:
                    pass
