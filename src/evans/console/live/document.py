"""
The live script as data: an ordered list of cells.

A **code cell** holds MATLAB. A **text cell** is a title, a heading or prose;
prose is a small Markdown with LaTeX math (``$...$`` inline, ``$$...$$`` on
its own) and ``{{name}}`` or ``{{expr}}`` placeholders that are filled from
the shared workspace each time the cell is rendered.

Nothing here imports Qt. The editor widgets, the file formats and the report
writers all work on this model, so every one of them can be tested headless.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..figures import FigureSpec
from .template import ReportTemplate


class CellKind(str, Enum):
    CODE = "code"
    TITLE = "title"
    HEADING = "heading"          # level 1
    HEADING2 = "heading2"
    HEADING3 = "heading3"
    TEXT = "text"

    @property
    def is_code(self) -> bool:
        return self is CellKind.CODE

    @property
    def is_heading(self) -> bool:
        return self in (CellKind.TITLE, CellKind.HEADING, CellKind.HEADING2,
                        CellKind.HEADING3)

    @property
    def level(self) -> int:
        """0 for the title, 1–3 for headings, -1 for anything else."""
        return {CellKind.TITLE: 0, CellKind.HEADING: 1, CellKind.HEADING2: 2,
                CellKind.HEADING3: 3}.get(self, -1)


#: The kinds a text cell can be switched between, in menu order.
TEXT_KINDS = (CellKind.TEXT, CellKind.TITLE, CellKind.HEADING,
              CellKind.HEADING2, CellKind.HEADING3)


@dataclass
class CellOutput:
    """What running a code cell produced: printed text, an error, figures."""
    text:    str = ""
    error:   str = ""
    figures: list[FigureSpec] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def empty(self) -> bool:
        return not (self.text or self.error or self.figures)


@dataclass
class FigureMeta:
    """
    What the report says about one figure a code cell draws: its caption and
    its ``\\label``. Kept with the cell, by position among its figures, and
    saved with the live script — figures themselves come back by running it.
    An empty label means the automatic one, ``fig:<n>``.
    """
    caption: str = ""
    label:   str = ""

    @property
    def empty(self) -> bool:
        return not (self.caption.strip() or self.label.strip())


_ids = itertools.count(1)


@dataclass
class Cell:
    """
    One cell. ``section_break`` marks a section boundary *before* the cell —
    MATLAB's ``%%`` in a plain-text live script, ``<w:sectPr/>`` in an .mlx.
    """
    kind:          CellKind
    source:        str = ""
    section_break: bool = False
    output:        CellOutput | None = None
    id:            int = field(default_factory=lambda: next(_ids))
    #: Captions and labels of the figures this (code) cell draws, in order.
    figure_meta:   list[FigureMeta] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.kind = CellKind(self.kind)

    @classmethod
    def code(cls, source: str = "", **kw) -> Cell:
        return cls(CellKind.CODE, source, **kw)

    @classmethod
    def text(cls, source: str = "", kind: CellKind = CellKind.TEXT,
             **kw) -> Cell:
        return cls(kind, source, **kw)

    @property
    def is_code(self) -> bool:
        return self.kind.is_code

    def meta(self, index: int) -> FigureMeta:
        """The caption and label of figure ``index``, created if missing."""
        while len(self.figure_meta) <= index:
            self.figure_meta.append(FigureMeta())
        return self.figure_meta[index]

    def same_content(self, other: Cell) -> bool:
        """Equal kind, source and section break — what a file round trip keeps."""
        return (self.kind == other.kind
                and self.source.strip("\n") == other.source.strip("\n")
                and self.section_break == other.section_break)


class LiveDocument:
    """An ordered list of cells, and the file it came from."""

    def __init__(self, cells: list[Cell] | None = None,
                 path: str | Path | None = None,
                 template: ReportTemplate | None = None) -> None:
        self.cells: list[Cell] = list(cells or [])
        self.path: Path | None = Path(path) if path else None
        #: This document's own report template; None follows the user's.
        self.template: ReportTemplate | None = template

    # ── reading ─────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.cells)

    def __iter__(self):
        return iter(self.cells)

    def __getitem__(self, index: int) -> Cell:
        return self.cells[index]

    @property
    def title(self) -> str:
        """The first title cell's text, or the file name, or ``untitled``."""
        for cell in self.cells:
            if cell.kind is CellKind.TITLE and cell.source.strip():
                return cell.source.strip()
        return self.path.stem if self.path else "untitled"

    @property
    def folder(self) -> Path | None:
        """
        The folder the file lives in — the *current folder* while it runs,
        so relative paths and function files beside it resolve.
        """
        return self.path.parent if self.path else None

    def code_cells(self) -> list[Cell]:
        return [c for c in self.cells if c.is_code]

    def index(self, cell: Cell) -> int:
        for i, c in enumerate(self.cells):
            if c is cell:
                return i
        raise ValueError("cell is not in this document")

    def same_content(self, other: LiveDocument) -> bool:
        return len(self) == len(other) and all(
            a.same_content(b) for a, b in zip(self.cells, other.cells))

    # ── editing ─────────────────────────────────────────────────

    def insert(self, index: int, cell: Cell) -> Cell:
        index = max(0, min(index, len(self.cells)))
        self.cells.insert(index, cell)
        return cell

    def append(self, cell: Cell) -> Cell:
        self.cells.append(cell)
        return cell

    def remove(self, cell: Cell) -> int:
        """Remove a cell; returns the index it had."""
        index = self.index(cell)
        del self.cells[index]
        return index

    def move(self, cell: Cell, offset: int) -> int:
        """Move a cell up (negative) or down; returns its new index."""
        index = self.index(cell)
        target = max(0, min(index + offset, len(self.cells) - 1))
        if target != index:
            del self.cells[index]
            self.cells.insert(target, cell)
        return target

    def figure_labels(self) -> dict[tuple[int, int], str]:
        """
        (cell id, figure index) → the label each drawn figure gets in the
        report: its own, or ``fig:<n>`` counting the document's figures.
        """
        labels = {}
        n = 0
        for cell in self.code_cells():
            if cell.output is None:
                continue
            for i, _spec in enumerate(cell.output.figures):
                n += 1
                own = cell.figure_meta[i].label.strip()                     if i < len(cell.figure_meta) else ""
                labels[cell.id, i] = own or f"fig:{n}"
        return labels

    def clear_outputs(self) -> None:
        for cell in self.cells:
            cell.output = None

    def to_plain_script(self) -> str:
        """The code cells as one ordinary .m script, sections marked ``%%``."""
        parts = []
        for cell in self.code_cells():
            if parts and cell.section_break:
                parts.append("%%")
            parts.append(cell.source.strip("\n"))
        return "\n".join(parts) + "\n"


# ──────────────────────────────────────────────────────────────
#  Interpolation: {{name}} and {{expr}} in text cells
# ──────────────────────────────────────────────────────────────

class InterpolationError(Exception):
    """An ``{{expr}}`` could not be evaluated."""


_TEMP = "__live_value__"


def workspace_evaluator(interpreter):
    """
    An evaluator for :func:`render` and the report writers: MATLAB
    expressions against the interpreter's (shared) workspace.

    A bare variable name is looked up directly; anything else runs as one
    MATLAB assignment to a scratch variable, which is then removed again — so
    rendering a paragraph never leaves a trace in the workspace or history.
    """
    def evaluate(expr: str) -> Any:
        expr = expr.strip()
        namespace = interpreter.namespace
        if expr.isidentifier() and expr in namespace:
            return namespace[expr]
        history = len(interpreter.history)
        try:
            results = interpreter.run_matlab(f"{_TEMP} = {expr};")
        finally:
            del interpreter.history[history:]
        failed = [r for r in results if r.error]
        if failed or _TEMP not in namespace:
            message = failed[0].error if failed else "no value"
            raise InterpolationError(message)
        return namespace.pop(_TEMP)
    return evaluate


def format_value(value: Any) -> str:
    """
    A value as MATLAB would show it, folded onto one line for prose.

    ``pi`` reads ``3.1416``; a short vector reads ``[1 2 3]``; a matrix
    ``[1 2; 3 4]``; anything big is summarised as ``1×500 double``.
    Strings are shown without quotes, the way ``disp`` shows them.
    """
    import numpy as np

    from ..matlab_runtime import display

    if isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)) and all(
            isinstance(v, (int, float, complex, np.number)) for v in value):
        value = np.asarray(value)
    if isinstance(value, np.ndarray):
        if value.size == 1:
            return display(value.reshape(-1)[0].item())
        if value.size == 0:
            return "[]"
        shape = value.shape if value.ndim == 2 else (1, value.size)
        if value.ndim > 2 or value.size > 40:
            return "×".join(str(n) for n in shape) + " double"
        text = display(value.reshape(shape))
        rows = [" ".join(line.split()) for line in text.splitlines()
                if line.strip()]
        return "[" + "; ".join(rows) + "]"
    text = display(value)
    return " ".join(text.split()) if "\n" in text else text
