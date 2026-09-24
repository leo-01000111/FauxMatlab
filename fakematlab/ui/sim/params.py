"""
Block parameter editing, built from the block's own ``params_spec``.

Nothing here knows about any particular block: the widget for each parameter
follows from its declared ``kind``, so a new block gets a working editor with
no UI changes. Values are validated by handing them to a throwaway copy of the
block before the dialog closes — if the block would reject them, the dialog
says so instead of letting a broken model reach the canvas.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...sim.block import Block, BlockError, create


class ParamForm(QWidget):
    """
    The editors for one block's parameters, without any container.

    Shared by the modal dialog and the docked inspector so there is one
    implementation of "what widget does a `matrix` parameter get?" — the
    reason a new block type still needs no UI changes.
    """

    def __init__(self, block: Block, parent=None) -> None:
        super().__init__(parent)
        self.block = block

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QLabel(block.description)
        header.setWordWrap(True)
        header.setStyleSheet("color: palette(mid);")
        root.addWidget(header)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._editors: dict[str, Any] = {}
        for spec in block.params_spec:
            widget = self._make_editor(spec, block.params[spec.name])
            if spec.help:
                widget.setToolTip(spec.help)
            widget.setAccessibleName(spec.label)
            self._editors[spec.name] = widget
            form.addRow(spec.label + ":", widget)
        root.addLayout(form)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: #C0392B;")
        self._error.hide()
        root.addWidget(self._error)

    # ── editors ─────────────────────────────────────────────────

    @staticmethod
    def _make_editor(spec, value):
        if spec.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            return w
        if spec.kind == "int":
            w = QSpinBox()
            w.setRange(-10_000_000, 10_000_000)
            w.setValue(int(value))
            return w
        if spec.kind == "choice":
            w = QComboBox()
            w.addItems([str(c) for c in spec.choices])
            idx = w.findText(str(value))
            w.setCurrentIndex(max(idx, 0))
            return w
        if spec.kind == "matrix":
            w = QPlainTextEdit(str(value))
            w.setMaximumHeight(72)
            w.setPlaceholderText("rows separated by ';', e.g. 0 1; -2 -3")
            return w
        if spec.kind in ("vector", "str"):
            return QLineEdit(str(value))
        w = QDoubleSpinBox()
        w.setRange(-1e12, 1e12)
        w.setDecimals(6)
        w.setValue(float(value))
        return w

    def _value(self, name: str) -> Any:
        widget = self._editors[name]
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        return widget.text()

    # ── validation ──────────────────────────────────────────────

    def commit(self) -> dict[str, Any] | None:
        """
        The changed parameters, or ``None`` if they would be rejected.

        Validated on a throwaway instance: the live block keeps its old
        parameters until the undo command applies the new ones, so a rejected
        edit cannot leave a half-configured block behind.
        """
        values = {spec.name: self._value(spec.name)
                  for spec in self.block.params_spec}
        try:
            create(self.block.type_name, "__validate__", **values)
        except (BlockError, ValueError) as exc:
            self._error.setText(str(exc))
            self._error.show()
            return None

        self._error.hide()
        return {k: v for k, v in values.items()
                if v != self.block.params[k]}


class ParamDialog(QDialog):
    """Edit one block's parameters, modally."""

    def __init__(self, block: Block, parent=None) -> None:
        super().__init__(parent)
        self.block = block
        self.changes: dict[str, Any] = {}
        self.setWindowTitle(f"{block.type_name} — {block.block_id}")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        self.form = ParamForm(block)
        root.addWidget(self.form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept(self) -> None:
        changes = self.form.commit()
        if changes is None:
            self.adjustSize()
            return
        self.changes = changes
        self.accept()
