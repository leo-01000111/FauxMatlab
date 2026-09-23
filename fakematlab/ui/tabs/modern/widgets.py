"""Small shared widgets for the modern-control views."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QPlainTextEdit,
                               QPushButton, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)


def make_table(headers: list[str], max_height: int | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    if max_height:
        table.setMaximumHeight(max_height)
    return table


def table_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)
    return item


def fill_table(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            table.setItem(r, c, table_item(str(text)))


def matrix_text(M) -> str:
    """A matrix as rows of numbers, one row per line."""
    M = np.atleast_2d(np.asarray(M, dtype=float))
    return "\n".join(" ".join(f"{v:g}" for v in row) for row in M)


def parse_matrix(text: str) -> np.ndarray:
    """
    Rows separated by newlines or semicolons, entries by spaces or commas.

    Accepts both because both are natural: MATLAB users type ``0 1; -2 -3``
    and everyone else types one row per line.
    """
    rows = [r for r in text.replace(";", "\n").splitlines() if r.strip()]
    if not rows:
        raise ValueError("the matrix is empty")
    parsed = []
    for i, row in enumerate(rows):
        try:
            parsed.append([float(v) for v in row.replace(",", " ").split()])
        except ValueError as exc:
            raise ValueError(f"row {i + 1} ({row.strip()!r}): {exc}") from exc
    widths = {len(r) for r in parsed}
    if len(widths) > 1:
        raise ValueError(
            f"rows have different lengths ({sorted(widths)}); every row of a "
            f"matrix must have the same number of entries")
    return np.array(parsed, dtype=float)


class MatrixEditor(QWidget):
    """
    Four text boxes for A, B, C, D, with one Apply button.

    Emits the **raw text**, not parsed arrays. Parsing has to happen inside
    the view's ``@guard`` so a typo lands in the panel's error banner like
    every other failure; parsing here would raise out of a Qt slot, where
    nothing catches it.
    """

    applied = Signal(str, str, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._boxes: dict[str, QPlainTextEdit] = {}
        for name, height in (("A", 84), ("B", 60), ("C", 46), ("D", 34)):
            box = QPlainTextEdit()
            box.setMaximumHeight(height)
            box.setFont(QFont("Consolas", 9))
            box.setPlaceholderText("rows on separate lines, or 0 1; -2 -3")
            self._boxes[name] = box
            form.addRow(f"{name}:", box)
        layout.addLayout(form)

        row = QHBoxLayout()
        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(self._emit)
        row.addWidget(apply_button)
        revert = QPushButton("Revert")
        revert.clicked.connect(self._revert)
        row.addWidget(revert)
        layout.addLayout(row)

        self._last: tuple | None = None

    def set_matrices(self, A, B, C, D) -> None:
        self._last = (A, B, C, D)
        for name, M in zip("ABCD", (A, B, C, D)):
            self._boxes[name].setPlainText(matrix_text(M))

    def _revert(self) -> None:
        if self._last is not None:
            self.set_matrices(*self._last)

    def _emit(self) -> None:
        self.applied.emit(*(self._boxes[name].toPlainText() for name in "ABCD"))


def frame_poles(plot, values, pad: float = 0.15) -> None:
    """
    Give a pole plot a sensible view range.

    Autoscaling an eigenvalue plot fails badly for a system whose poles are
    real: ``np.linalg.eigvals`` splits a repeated real root into a cluster
    with imaginary parts around 1e-6, and the view then zooms into that
    numerical noise — three coincident poles appear spread across the whole
    height of the plot, which reads as a design result rather than round-off.

    The imaginary range is therefore floored at a fraction of the real range.
    """
    values = [complex(v) for v in np.atleast_1d(values)]
    if not values:
        return

    real = [v.real for v in values]
    imag = [v.imag for v in values]
    x_lo, x_hi = min(real + [0.0]), max(real + [0.0])
    x_span = max(x_hi - x_lo, 1e-9)
    margin = pad * x_span

    y_needed = max(abs(v) for v in imag) if imag else 0.0
    y_span = max(y_needed, 0.25 * x_span)

    plot.setXRange(x_lo - margin, x_hi + margin, padding=0)
    plot.setYRange(-y_span * (1 + pad), y_span * (1 + pad), padding=0)
