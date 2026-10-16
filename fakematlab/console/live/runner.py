"""
Running cells against the console's interpreter — the shared workspace.

Each code cell runs as a MATLAB script of its own. Its printed output and
its figures are captured onto the cell instead of going to the console's
transcript and figure area: a live script's output belongs under its code.

While a cell runs, the **current folder** is the live script's own folder,
so ``audioread('musique.wav')`` and a function file saved beside the script
resolve the way they do in MATLAB. The folder is restored afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ..figures import FigureSpec, set_figure_sink
from .document import Cell, CellOutput, LiveDocument


@contextmanager
def current_folder(folder: str | Path | None) -> Iterator[None]:
    """Run with ``folder`` as the working directory, then go back."""
    if folder is None or not Path(folder).is_dir():
        yield
        return
    before = os.getcwd()
    os.chdir(folder)
    try:
        yield
    finally:
        os.chdir(before)


class LiveRunner:
    """Runs a document's code cells, one at a time or in sequence."""

    def __init__(self, interpreter) -> None:
        self.interpreter = interpreter
        #: Called after each cell runs — the editor redraws that cell's output.
        self.on_cell_done: Callable[[Cell], None] | None = None

    def run_cell(self, cell: Cell, folder: str | Path | None = None) -> CellOutput:
        """Run one code cell and store what it produced on it."""
        if not cell.is_code:
            return CellOutput()
        figures: list[FigureSpec] = []
        interpreter = self.interpreter
        previous_sink = set_figure_sink(figures.append)
        # `close all` in a cell closes the figures this cell has drawn.
        previous_close = interpreter.close_figures
        interpreter.close_figures = figures.clear
        try:
            with current_folder(folder):
                results = interpreter.run_script(cell.source, "matlab")
        finally:
            set_figure_sink(previous_sink)
            interpreter.close_figures = previous_close
        text = "\n".join(t for t in (r.display() if not r.error else
                                     _without_error(r) for r in results) if t)
        errors = [r for r in results if r.error]
        error = ""
        if errors:
            error = "\n".join(p for p in (errors[-1].error, errors[-1].hint) if p)
        cell.output = CellOutput(text=text, error=error, figures=figures)
        if self.on_cell_done is not None:
            self.on_cell_done(cell)
        return cell.output

    def run_cells(self, document: LiveDocument, cells: list[Cell],
                  *, stop_on_error: bool = True) -> bool:
        """Run the given cells in document order; False if one failed."""
        for cell in cells:
            if not cell.is_code:
                continue
            output = self.run_cell(cell, document.folder)
            if stop_on_error and not output.ok:
                return False
        return True

    def run_all(self, document: LiveDocument) -> bool:
        return self.run_cells(document, document.cells)

    def run_to(self, document: LiveDocument, cell: Cell) -> bool:
        """Every code cell from the top down to and including ``cell``."""
        index = document.index(cell)
        return self.run_cells(document, document.cells[:index + 1])


def _without_error(result) -> str:
    """A failed statement's output, without the error (shown separately)."""
    return (result.output or "").rstrip("\n")
