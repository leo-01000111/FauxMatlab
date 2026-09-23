"""
A Simulink model: blocks, connections, and the ``.fmdl`` file format.
=====================================================================
Deliberately separate from :class:`fakematlab.core.model.Model`, which is the
single-port LTI graph the analysis half uses. A simulation block has several
typed ports and need not be linear, so it needs its own container —
:mod:`fakematlab.sim.linearize` is the bridge between the two.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .block import Block, BlockError, create

FORMAT = "fakematlab-model"
VERSION = 1


@dataclass(frozen=True)
class PortRef:
    """One end of a wire: a block and one of its ports, by name."""
    block: str
    port: str

    def __str__(self) -> str:
        return f"{self.block}.{self.port}"


@dataclass(frozen=True)
class Connection:
    """A wire from an output port to an input port."""
    src: PortRef
    dst: PortRef

    def __str__(self) -> str:
        return f"{self.src} → {self.dst}"


@dataclass
class BlockPlacement:
    """Where a block sits on the canvas. Ignored by the solver."""
    x: float = 0.0
    y: float = 0.0


class ModelError(Exception):
    """The model is structurally invalid."""


class SimModel:
    """
    A block diagram that can be simulated.

    One input port takes at most one wire — fan-*in* is what a ``Sum`` block is
    for, and silently adding two signals together because they happened to
    land on the same port is the kind of thing that costs an afternoon. Fan-out
    is unrestricted: one output may drive any number of inputs.
    """

    def __init__(self, name: str = "untitled") -> None:
        self.name = name
        self._blocks: dict[str, Block] = {}
        self._placements: dict[str, BlockPlacement] = {}
        self._connections: list[Connection] = []

    # ── blocks ──────────────────────────────────────────────────

    def add(self, type_name: str, block_id: str | None = None,
            x: float = 0.0, y: float = 0.0, **params: Any) -> Block:
        """Create and add a block, returning it."""
        block_id = block_id or self._unique_id(type_name)
        if block_id in self._blocks:
            raise ModelError(f"duplicate block id {block_id!r}")
        block = create(type_name, block_id, **params)
        self._blocks[block_id] = block
        self._placements[block_id] = BlockPlacement(x, y)
        return block

    def add_block(self, block: Block, x: float = 0.0, y: float = 0.0) -> Block:
        if block.block_id in self._blocks:
            raise ModelError(f"duplicate block id {block.block_id!r}")
        self._blocks[block.block_id] = block
        self._placements[block.block_id] = BlockPlacement(x, y)
        return block

    def remove(self, block_id: str) -> None:
        """Delete a block and every wire touching it."""
        if block_id not in self._blocks:
            raise ModelError(f"no block {block_id!r}")
        del self._blocks[block_id]
        self._placements.pop(block_id, None)
        self._connections = [
            c for c in self._connections
            if c.src.block != block_id and c.dst.block != block_id
        ]

    def _unique_id(self, type_name: str) -> str:
        i = 1
        while f"{type_name}{i}" in self._blocks:
            i += 1
        return f"{type_name}{i}"

    # ── connections ─────────────────────────────────────────────

    def connect(self, src: str, dst: str) -> Connection:
        """
        Wire ``"block.port"`` to ``"block.port"``.

        The port may be omitted when the block has exactly one of that kind,
        so ``connect("Step1", "Gain1")`` works for the common case.
        """
        src_ref = self._resolve(src, kind="output")
        dst_ref = self._resolve(dst, kind="input")

        existing = self.connection_into(dst_ref)
        if existing is not None:
            raise ModelError(
                f"{dst_ref} already has a wire from {existing.src}. "
                f"An input port takes one signal — use a Sum block to "
                f"combine two."
            )
        conn = Connection(src_ref, dst_ref)
        self._connections.append(conn)
        return conn

    def disconnect(self, conn: Connection) -> None:
        self._connections = [c for c in self._connections if c != conn]

    def _resolve(self, spec: str, kind: str) -> PortRef:
        if "." in spec:
            block_id, port = spec.split(".", 1)
        else:
            block_id, port = spec, None

        block = self._blocks.get(block_id)
        if block is None:
            raise ModelError(
                f"no block {block_id!r}. Have: "
                f"{', '.join(sorted(self._blocks)) or '(none)'}"
            )
        ports = block.outputs if kind == "output" else block.inputs
        if port is None:
            if len(ports) != 1:
                raise ModelError(
                    f"{block_id} has {len(ports)} {kind} ports "
                    f"({', '.join(ports) or 'none'}); name one explicitly, "
                    f"e.g. '{block_id}.{ports[0] if ports else 'port'}'"
                )
            port = ports[0]
        elif port not in ports:
            raise ModelError(
                f"{block_id} has no {kind} port {port!r}; "
                f"valid: {', '.join(ports) or '(none)'}"
            )
        return PortRef(block_id, port)

    def connection_into(self, ref: PortRef) -> Connection | None:
        for c in self._connections:
            if c.dst == ref:
                return c
        return None

    def connections_from(self, ref: PortRef) -> list[Connection]:
        return [c for c in self._connections if c.src == ref]

    # ── introspection ───────────────────────────────────────────

    @property
    def blocks(self) -> dict[str, Block]:
        return dict(self._blocks)

    @property
    def connections(self) -> list[Connection]:
        return list(self._connections)

    def block(self, block_id: str) -> Block:
        try:
            return self._blocks[block_id]
        except KeyError:
            raise ModelError(f"no block {block_id!r}") from None

    def placement(self, block_id: str) -> BlockPlacement:
        return self._placements.get(block_id, BlockPlacement())

    def move(self, block_id: str, x: float, y: float) -> None:
        self._placements[block_id] = BlockPlacement(x, y)

    def blocks_of_type(self, type_name: str) -> list[Block]:
        return [b for b in self._blocks.values() if b.type_name == type_name]

    def unconnected_inputs(self) -> list[PortRef]:
        """Input ports with no wire — they read zero, which is worth a warning."""
        missing = []
        for block in self._blocks.values():
            for port in block.inputs:
                ref = PortRef(block.block_id, port)
                if self.connection_into(ref) is None:
                    missing.append(ref)
        return missing

    def __iter__(self) -> Iterator[Block]:
        return iter(self._blocks.values())

    def __len__(self) -> int:
        return len(self._blocks)

    def __repr__(self) -> str:
        return (f"<SimModel {self.name!r}: {len(self._blocks)} blocks, "
                f"{len(self._connections)} connections>")

    # ── persistence ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": VERSION,
            "name": self.name,
            "blocks": [
                {
                    "id": b.block_id,
                    "type": b.type_name,
                    "params": _jsonable(b.params),
                    "x": self.placement(b.block_id).x,
                    "y": self.placement(b.block_id).y,
                }
                for b in self._blocks.values()
            ],
            "connections": [
                {"src": str(c.src), "dst": str(c.dst)} for c in self._connections
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimModel:
        if data.get("format") != FORMAT:
            raise ModelError(
                f"not a FakeMatlab model file (format={data.get('format')!r})")
        if data.get("version", 1) > VERSION:
            raise ModelError(
                f"model was written by a newer version "
                f"(file format {data['version']}, this build reads {VERSION})")

        model = cls(data.get("name", "untitled"))
        for entry in data.get("blocks", []):
            try:
                model.add(entry["type"], entry["id"],
                          x=entry.get("x", 0.0), y=entry.get("y", 0.0),
                          **entry.get("params", {}))
            except (BlockError, KeyError) as exc:
                raise ModelError(
                    f"could not load block {entry.get('id', '?')!r} "
                    f"of type {entry.get('type', '?')!r}: {exc}"
                ) from exc
        for entry in data.get("connections", []):
            try:
                model.connect(entry["src"], entry["dst"])
            except (ModelError, KeyError) as exc:
                raise ModelError(
                    f"could not connect {entry.get('src')} → "
                    f"{entry.get('dst')}: {exc}"
                ) from exc
        return model

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2),
                              encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> SimModel:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def copy(self) -> SimModel:
        return SimModel.from_dict(self.to_dict())


def _jsonable(params: dict[str, Any]) -> dict[str, Any]:
    """Convert numpy values to plain Python so the model round-trips as JSON."""
    import numpy as np

    out: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, np.ndarray):
            out[key] = value.tolist()
        elif isinstance(value, (np.floating, np.integer)):
            out[key] = value.item()
        else:
            out[key] = value
    return out
