"""
The workspace browser: what is currently defined, and what it is.
"""

from __future__ import annotations

from typing import Any

import control as ctl
import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ...console.interpreter import Interpreter


class WorkspaceWidget(QWidget):
    """
    A table of the user's variables.

    Only *user* variables: the fifty-odd command names the API installs are
    filtered out, so the list shows what you made rather than what came with
    the tool. Double-clicking a system opens it in the analysis tabs, which is
    the console's main route back into the rest of the app.
    """

    #: A system was double-clicked and should be analysed.
    open_system = Signal(str, object)      # name, system
    #: A Simulink model was double-clicked.
    open_model = Signal(str, object)

    def __init__(self, interpreter: Interpreter, parent=None) -> None:
        super().__init__(parent)
        self.interpreter = interpreter

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        row = QHBoxLayout()
        row.addWidget(QLabel("Workspace"))
        row.addStretch()
        clear = QPushButton("Clear all")
        clear.setMaximumWidth(80)
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        layout.addLayout(row)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Type", "Value"])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table, stretch=1)

        self._hint = QLabel("Double-click a system to analyse it.")
        self._hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._hint)

        self.refresh()

    # ── contents ────────────────────────────────────────────────

    def refresh(self, *_ignored) -> None:
        variables = self.interpreter.variables()
        names = sorted(variables, key=lambda n: (n == "ans", n.lower()))
        self._table.setRowCount(len(names))
        for row, name in enumerate(names):
            value = variables[name]
            self._table.setItem(row, 0, _item(name))
            self._table.setItem(row, 1, _item(_type_name(value)))
            self._table.setItem(row, 2, _item(_summary(value)))
        self._hint.setText(
            f"{len(names)} variable{'s' if len(names) != 1 else ''} — "
            f"double-click a system to analyse it.")

    def _clear(self) -> None:
        self.interpreter.clear()
        self.refresh()

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        name_item = self._table.item(item.row(), 0)
        if name_item is None:
            return
        name = name_item.text()
        value = self.interpreter.namespace.get(name)

        if isinstance(value, (ctl.TransferFunction, ctl.StateSpace)):
            self.open_system.emit(name, value)
            return
        try:
            from ...sim.model import SimModel
            if isinstance(value, SimModel):
                self.open_model.emit(name, value)
                return
        except ImportError:
            pass
        self._hint.setText(
            f"'{name}' is a {_type_name(value)} — only systems and Simulink "
            f"models can be opened.")


# ──────────────────────────────────────────────────────────────
#  Rendering values
# ──────────────────────────────────────────────────────────────

def _type_name(value: Any) -> str:
    if isinstance(value, ctl.TransferFunction):
        return "tf (discrete)" if getattr(value, "dt", 0) else "tf"
    if isinstance(value, ctl.StateSpace):
        return "ss (discrete)" if getattr(value, "dt", 0) else "ss"
    if isinstance(value, np.ndarray):
        return f"array {'×'.join(str(d) for d in value.shape)}"
    return type(value).__name__


def _summary(value: Any) -> str:
    """
    One line describing a value.

    Systems are described by order and poles rather than by their full
    printed form — a transfer function's repr is six lines of ASCII art,
    which is unreadable in a table cell.
    """
    if isinstance(value, (ctl.TransferFunction, ctl.StateSpace)):
        try:
            poles = np.atleast_1d(ctl.poles(value))
            order = len(poles)
            stable = ("stable" if np.all(_decay(value, poles))
                      else "UNSTABLE")
            return (f"order {order}, {stable}, poles "
                    f"{np.array2string(poles, precision=3, max_line_width=90)}")
        except Exception:                                  # noqa: BLE001
            return type(value).__name__
    if isinstance(value, np.ndarray):
        if value.size <= 12:
            return np.array2string(value, precision=4, suppress_small=True,
                                   max_line_width=120)
        return f"{value.size} elements, {value.dtype}"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, dict):
        return "{" + ", ".join(list(value)[:6]) + ("…}" if len(value) > 6
                                                   else "}")
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "…"


def _decay(sys, poles) -> np.ndarray:
    """Stability test in the right plane for the system's timebase."""
    if getattr(sys, "dt", 0):
        return np.abs(poles) < 1.0
    return np.real(poles) < 0.0


def _item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    return item
