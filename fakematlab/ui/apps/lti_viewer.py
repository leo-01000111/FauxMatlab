"""
The LTI Viewer — every loaded system, any response, side by side.

The window is a renderer for :class:`~fakematlab.core.viewer.ViewerData` and
almost nothing else. Which systems, which response and which characteristics
are the only state it owns; every number on screen came out of the core
module, which is where they are checked.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from ...core.collection import SystemCollection
from ...core.viewer import (CHARACTERISTICS, Characteristic, ResponseKind,
                            ViewerData, compute)
from ..guard import GuardedPanel, guard
from ..plots import (COLORS, add_hline, add_marker, add_text_annotation,
                     add_vline, curve_pen, freq_marker, freq_text,
                     make_freq_plot, make_plot, plot_freq)


class LTIViewer(QWidget, GuardedPanel):
    """A collection of systems, drawn as whichever response is selected."""

    #: A system was double-clicked: analyse it in the main tabs.
    open_requested = Signal(str, object)

    def __init__(self, collection: SystemCollection | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LTI Viewer")
        self.resize(1080, 680)
        self.collection = collection or SystemCollection()
        self._kind = ResponseKind.STEP
        self._characteristics: set[Characteristic] = set()
        self._build_ui()
        self.refresh()

    # ── UI ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.install_error_banner(outer)

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, stretch=1)

        # ── left: the systems ──
        left = QWidget()
        left.setMaximumWidth(260)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(QLabel("Systems"))

        self._list = QListWidget()
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        left_lay.addWidget(self._list, stretch=1)

        buttons = QHBoxLayout()
        for label, slot in (("Rename…", self._rename),
                            ("Remove", self._remove),
                            ("Clear", self._clear)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        left_lay.addLayout(buttons)
        split.addWidget(left)

        # ── right: the plot ──
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        top.addWidget(QLabel("Response:"))
        self._kind_combo = QComboBox()
        for kind in ResponseKind:
            self._kind_combo.addItem(kind.value)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        top.addWidget(self._kind_combo)

        self._char_btn = QPushButton("Characteristics ▾")
        self._char_btn.setToolTip(
            "Add markers to every curve at once — the same menu the plot's "
            "right-click gives you.")
        self._char_btn.clicked.connect(self._show_characteristics_menu)
        top.addWidget(self._char_btn)
        top.addStretch()
        self._note = QLabel("")
        self._note.setStyleSheet("color: palette(mid);")
        top.addWidget(self._note)
        right_lay.addLayout(top)

        self._plot_host = QWidget()
        self._plot_lay = QVBoxLayout(self._plot_host)
        self._plot_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.addWidget(self._plot_host, stretch=1)

        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

    # ── collection management ───────────────────────────────────

    def add_system(self, name: str, system) -> None:
        self.collection.add(name, system)
        self.refresh()

    def set_collection(self, collection: SystemCollection) -> None:
        self.collection = collection
        self.refresh()

    def _selected_name(self) -> str | None:
        item = self._list.currentItem()
        return item.text() if item is not None else None

    def _rename(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        new, ok = QInputDialog.getText(self, "Rename", "Name:", text=name)
        if ok and new:
            self.collection.rename(name, new)
            self.refresh()

    def _remove(self) -> None:
        name = self._selected_name()
        if name is not None:
            self.collection.remove(name)
            self.refresh()

    def _clear(self) -> None:
        self.collection.clear()
        self.refresh()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        self.collection.set_visible(item.text(),
                                    item.checkState() == Qt.Checked)
        self._draw()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        entry = self.collection.get(item.text())
        self.open_requested.emit(entry.name, entry.system)

    # ── response kind and characteristics ───────────────────────

    def _on_kind_changed(self, index: int) -> None:
        # Rebuilt from the text rather than taken from `itemData`. Qt stores
        # item data in a QVariant, and a `str`-mixin enum goes in as an enum
        # member and comes back out as a plain `str` — which compares and
        # hashes equal to the member, so every dict lookup still works and the
        # only symptom is `.value` raising several calls later.
        self._kind = ResponseKind(self._kind_combo.itemText(index))
        # Drop the ones that do not apply to the new response, rather than
        # keeping them checked-but-ignored where they cannot be drawn.
        self._characteristics &= set(CHARACTERISTICS[self._kind])
        self._draw()

    def set_characteristic(self, characteristic: Characteristic,
                           on: bool) -> None:
        if on:
            self._characteristics.add(characteristic)
        else:
            self._characteristics.discard(characteristic)
        self._draw()

    def _show_characteristics_menu(self) -> None:
        menu = self._characteristics_menu()
        menu.exec(self._char_btn.mapToGlobal(
            self._char_btn.rect().bottomLeft()))

    def _characteristics_menu(self) -> QMenu:
        menu = QMenu(self)
        available = CHARACTERISTICS[self._kind]
        if not available:
            menu.addAction(QAction(
                f"{self._kind.value} has no characteristics", self,
                enabled=False))
            return menu
        for characteristic in available:
            action = QAction(characteristic.value, self, checkable=True)
            action.setChecked(characteristic in self._characteristics)
            action.toggled.connect(
                lambda on, c=characteristic: self.set_characteristic(c, on))
            menu.addAction(action)
        return menu

    # ── drawing ─────────────────────────────────────────────────

    def refresh(self, *_ignored) -> None:
        """Rebuild the system list and redraw."""
        self._list.blockSignals(True)
        self._list.clear()
        for entry in self.collection:
            item = QListWidgetItem(entry.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if entry.visible else Qt.Unchecked)
            item.setForeground(pg.mkColor(COLORS[entry.colour % len(COLORS)]))
            if entry.note:
                item.setToolTip(entry.note)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._draw()

    @guard("LTI Viewer")
    def _draw(self) -> None:
        data = compute(self.collection, self._kind, self._characteristics)
        self._note.setText(data.note)
        self._clear_plots()
        if len(data.panels) == 2:
            self._draw_two_panels(data)
        else:
            self._draw_one_panel(data)

    def _clear_plots(self) -> None:
        while self._plot_lay.count():
            item = self._plot_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _draw_one_panel(self, data: ViewerData) -> None:
        widget = (make_freq_plot(data.kind.value, data.ylabel) if data.log_x
                  else make_plot(data.kind.value, data.xlabel, data.ylabel))
        plot = widget.getPlotItem()
        plot.addLegend(offset=(-10, 10))
        if data.aspect_locked:
            plot.setAspectLocked(True)
        self._paint(plot, data, "main")
        if data.kind is ResponseKind.NYQUIST:
            self._nyquist_furniture(plot)
        if data.kind is ResponseKind.PZMAP:
            add_vline(plot, 0.0, "#888888", width=0.6)
            add_hline(plot, 0.0, "#888888", width=0.6)
        self._install_context_menu(widget)
        self._plot_lay.addWidget(widget)

    def _draw_two_panels(self, data: ViewerData) -> None:
        splitter = QSplitter(Qt.Vertical)
        top = make_freq_plot(f"{data.kind.value} — magnitude", data.ylabel)
        bottom = make_freq_plot(f"{data.kind.value} — phase",
                                data.phase_label)
        top.setXLink(bottom)
        splitter.addWidget(top)
        splitter.addWidget(bottom)

        top_plot = top.getPlotItem()
        top_plot.addLegend(offset=(-10, 10))
        self._paint(top_plot, data, "main")
        add_hline(top_plot, 0.0, "#888888", width=0.8)

        bottom_plot = bottom.getPlotItem()
        self._paint(bottom_plot, data, "phase")
        add_hline(bottom_plot, -180.0, "#888888", width=0.8)

        for widget in (top, bottom):
            self._install_context_menu(widget)
        self._plot_lay.addWidget(splitter)

    def _paint(self, plot, data: ViewerData, panel: str) -> None:
        for curve in data.curves_on(panel):
            pen = _pen(curve.colour, curve.style)
            if curve.style in ("poles", "zeros"):
                plot.plot(curve.x, curve.y, pen=None,
                          symbol="x" if curve.style == "poles" else "o",
                          symbolSize=13,
                          symbolPen=curve_pen(curve.colour, 2.2),
                          symbolBrush=None, name=curve.name)
            elif data.log_x:
                plot_freq(plot, curve.x, curve.y, pen=pen,
                          name=curve.name if panel == "main" else None)
            else:
                plot.plot(curve.x, curve.y, pen=pen,
                          name=curve.name if panel == "main" else None)

        for mark in data.marks_on(panel):
            colour = COLORS[mark.colour % len(COLORS)]
            if mark.kind == "hline":
                add_hline(plot, mark.y, colour, label=mark.label, width=1.0)
            elif data.log_x:
                freq_marker(plot, mark.x, mark.y, color=colour)
                freq_text(plot, mark.x, mark.y, mark.label, color=colour)
            else:
                add_marker(plot, mark.x, mark.y, color=colour)
                add_text_annotation(plot, mark.x, mark.y, mark.label,
                                    color=colour)

    def _nyquist_furniture(self, plot) -> None:
        theta = np.linspace(0, 2 * np.pi, 200)
        plot.plot(np.cos(theta), np.sin(theta), pen=_pen(-1, "dashed"))
        add_marker(plot, -1.0, 0.0, symbol="x", color="#FF4444", size=14)
        add_text_annotation(plot, -1.0, 0.06, "−1", "#FF4444")
        add_vline(plot, 0.0, "#888888", width=0.6)
        add_hline(plot, 0.0, "#888888", width=0.6)

    def _install_context_menu(self, widget) -> None:
        """
        Right-click on the plot opens the characteristics menu.

        This is the gesture the MATLAB viewer trains into you, and it is the
        reason the button exists too: discoverability for anyone who has not
        been trained into it.
        """
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, w=widget: self._characteristics_menu().exec(
                w.mapToGlobal(pos)))


def _pen(index: int, style: str):
    if index < 0:
        pen = pg.mkPen("#888888", width=1.4)
        pen.setStyle(Qt.DashLine)
        return pen
    pen = curve_pen(index, 2.0 if style == "line" else 1.4)
    if style == "dashed":
        pen.setStyle(Qt.DashLine)
    return pen
