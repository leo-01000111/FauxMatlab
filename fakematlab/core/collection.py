"""
Named collections of systems, and snapshots of the architecture.
=================================================================

Two small things the "apps" all need:

**A collection** — an ordered, named set of systems with a visible flag. The
LTI Viewer is a collection plus a response kind; the designer's before/after
overlay is a collection of two.

**A snapshot** — the four block transfer functions of a
:class:`~fakematlab.core.architecture.CourseArchitecture`, frozen.

Snapshots store *coefficients*, not transfer-function objects. A snapshot
holding a reference to a live block would be a snapshot of whatever that block
becomes later, which is the opposite of the point; storing coefficients also
means a snapshot can be written to a session file, and compared for equality.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

import control as ctl
import numpy as np

from .architecture import BLOCK_IDS, CourseArchitecture
from .tf_utils import from_coefficients

#: How many snapshots a store keeps before dropping the oldest. A comparison
#: plot with fifteen curves on it is not a comparison.
MAX_SNAPSHOTS = 8


# ──────────────────────────────────────────────────────────────
#  Collection
# ──────────────────────────────────────────────────────────────

@dataclass
class Entry:
    """One named system in a collection."""

    name: str
    system: Any                      # TransferFunction or StateSpace
    visible: bool = True
    note: str = ""
    #: Index into the plot palette, assigned on insertion and kept for the
    #: entry's lifetime — so hiding one curve does not recolour the others.
    colour: int = 0

    @property
    def tf(self) -> ctl.TransferFunction:
        """The entry as a transfer function, converting a state space."""
        if isinstance(self.system, ctl.TransferFunction):
            return self.system
        return ctl.ss2tf(self.system)


class SystemCollection:
    """
    An ordered set of named systems.

    Names are unique: adding a name that is taken appends a numeric suffix
    rather than replacing the existing entry, because in the viewer the two
    are meant to be compared, not substituted.
    """

    def __init__(self, entries: list[Entry] | None = None) -> None:
        self._entries: list[Entry] = list(entries or [])
        self._next_colour = len(self._entries)

    # ── building ────────────────────────────────────────────────

    def add(self, name: str, system: Any, note: str = "") -> Entry:
        entry = Entry(name=self._unique(name), system=system, note=note,
                      colour=self._next_colour)
        self._next_colour += 1
        self._entries.append(entry)
        return entry

    def extend(self, systems: dict[str, Any]) -> list[Entry]:
        return [self.add(name, sys) for name, sys in systems.items()]

    def remove(self, name: str) -> None:
        self._entries = [e for e in self._entries if e.name != name]

    def clear(self) -> None:
        self._entries.clear()
        self._next_colour = 0

    def rename(self, old: str, new: str) -> Entry:
        entry = self.get(old)
        renamed = replace(entry, name=self._unique(new, exclude=old))
        self._entries[self._entries.index(entry)] = renamed
        return renamed

    def _unique(self, name: str, exclude: str | None = None) -> str:
        name = (name or "system").strip() or "system"
        taken = {e.name for e in self._entries if e.name != exclude}
        if name not in taken:
            return name
        n = 2
        while f"{name} ({n})" in taken:
            n += 1
        return f"{name} ({n})"

    # ── reading ─────────────────────────────────────────────────

    def get(self, name: str) -> Entry:
        for entry in self._entries:
            if entry.name == name:
                return entry
        raise KeyError(f"no system named {name!r} "
                       f"(have: {', '.join(self.names) or 'none'})")

    def set_visible(self, name: str, visible: bool) -> None:
        entry = self.get(name)
        self._entries[self._entries.index(entry)] = replace(entry,
                                                            visible=visible)

    @property
    def names(self) -> list[str]:
        return [e.name for e in self._entries]

    @property
    def visible(self) -> list[Entry]:
        return [e for e in self._entries if e.visible]

    def __iter__(self) -> Iterator[Entry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __repr__(self) -> str:
        shown = sum(1 for e in self._entries if e.visible)
        return (f"<SystemCollection: {len(self._entries)} systems, "
                f"{shown} shown — {', '.join(self.names)}>")


# ──────────────────────────────────────────────────────────────
#  Snapshots
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Snapshot:
    """
    The four block transfer functions of an architecture, frozen.

    Coefficient tuples rather than ``TransferFunction`` objects: a snapshot is
    a record of a past state, so it must not be able to change when the
    architecture does.
    """

    label: str
    blocks: dict[str, tuple[tuple[float, ...], tuple[float, ...]]]
    note: str = ""

    def tf(self, block_id: str) -> ctl.TransferFunction:
        num, den = self.blocks[block_id]
        return from_coefficients(list(num), list(den))

    def architecture(self) -> CourseArchitecture:
        """Rebuild an architecture, so the exact closed loops can be derived."""
        return CourseArchitecture(**{bid: self.tf(bid)
                                     for bid in self.blocks})

    def loop_tf(self) -> ctl.TransferFunction:
        return self.architecture().loop_tf()

    def closed_loop_tf(self, input_sig: str = "r",
                       output_sig: str = "y") -> ctl.TransferFunction:
        return self.architecture().get_closed_loop_tf(input_sig, output_sig)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "note": self.note,
            "blocks": {bid: {"num": list(num), "den": list(den)}
                       for bid, (num, den) in self.blocks.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        blocks = {
            bid: (tuple(float(c) for c in entry["num"]),
                  tuple(float(c) for c in entry["den"]))
            for bid, entry in data.get("blocks", {}).items()
        }
        if not blocks:
            raise ValueError("snapshot has no blocks")
        return cls(label=str(data.get("label", "snapshot")),
                   blocks=blocks, note=str(data.get("note", "")))

    def __repr__(self) -> str:
        return f"<Snapshot {self.label!r}: {', '.join(self.blocks)}>"


def take_snapshot(arch: CourseArchitecture, label: str,
                  note: str = "") -> Snapshot:
    """Freeze an architecture's four blocks under ``label``."""
    return Snapshot(
        label=label,
        blocks={
            bid: (tuple(float(c) for c in
                        np.atleast_1d(arch.block_tf(bid).num[0][0])),
                  tuple(float(c) for c in
                        np.atleast_1d(arch.block_tf(bid).den[0][0])))
            for bid in BLOCK_IDS
        },
        note=note,
    )


def restore_snapshot(arch: CourseArchitecture, snapshot: Snapshot) -> None:
    """
    Put a snapshot's blocks back, in place.

    Every block is rebuilt before any is applied, so a malformed snapshot
    leaves the architecture untouched rather than half-restored — the same
    rule :mod:`fakematlab.core.session` follows for files.
    """
    rebuilt = {bid: snapshot.tf(bid) for bid in snapshot.blocks
               if bid in BLOCK_IDS}
    if not rebuilt:
        raise ValueError(f"snapshot {snapshot.label!r} has no usable blocks")
    for bid, tf in rebuilt.items():
        arch.set_block(bid, tf)


@dataclass
class SnapshotStore:
    """A bounded, ordered list of snapshots with unique labels."""

    limit: int = MAX_SNAPSHOTS
    _items: list[Snapshot] = field(default_factory=list)

    def take(self, arch: CourseArchitecture, label: str = "",
             note: str = "") -> Snapshot:
        label = self._unique(label or f"Snapshot {len(self._items) + 1}")
        snapshot = take_snapshot(arch, label, note)
        self._items.append(snapshot)
        del self._items[:-self.limit]
        return snapshot

    def _unique(self, label: str) -> str:
        taken = {s.label for s in self._items}
        if label not in taken:
            return label
        n = 2
        while f"{label} ({n})" in taken:
            n += 1
        return f"{label} ({n})"

    def get(self, label: str) -> Snapshot:
        for snapshot in self._items:
            if snapshot.label == label:
                return snapshot
        raise KeyError(f"no snapshot named {label!r}")

    def remove(self, label: str) -> None:
        self._items = [s for s in self._items if s.label != label]

    def clear(self) -> None:
        self._items.clear()

    def collection(self, input_sig: str = "r",
                   output_sig: str = "y") -> SystemCollection:
        """The stored snapshots as closed-loop systems, ready to plot."""
        collection = SystemCollection()
        for snapshot in self._items:
            collection.add(snapshot.label,
                           snapshot.closed_loop_tf(input_sig, output_sig),
                           note=snapshot.note)
        return collection

    @property
    def labels(self) -> list[str]:
        return [s.label for s in self._items]

    def __iter__(self) -> Iterator[Snapshot]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
