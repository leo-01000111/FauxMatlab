"""
The snapshot bar — "remember this design, and show me what changed".

The Design tab already kept a private list of controller transfer functions.
This generalises it: a snapshot is the *whole* architecture, the store is
shared, and comparing means handing the stored designs to the LTI Viewer
rather than re-implementing an overlay in every tab.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QWidget,
)

from ...core.architecture import CourseArchitecture
from ...core.collection import Snapshot, SnapshotStore, restore_snapshot


class SnapshotBar(QWidget):
    """
    A one-row strip: take a snapshot, restore one, compare them.

    Embeddable in any tab. It holds no state of its own beyond the store it is
    given, so two bars in two tabs show the same snapshots — which is the
    point of generalising it.
    """

    #: A snapshot was restored into the architecture.
    restored = Signal(object)              # Snapshot
    #: The user asked to compare the stored designs.
    compare_requested = Signal(object)     # SystemCollection
    #: The store's contents changed.
    changed = Signal()

    def __init__(self, arch: CourseArchitecture, store: SnapshotStore | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self.store = store if store is not None else SnapshotStore()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._take_btn = QPushButton("Snapshot")
        self._take_btn.setToolTip(
            "Freeze the four block transfer functions under a name.")
        self._take_btn.clicked.connect(self.take)
        row.addWidget(self._take_btn)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(160)
        row.addWidget(self._combo)

        for label, slot, tip in (
            ("Restore", self.restore, "Put this snapshot's blocks back."),
            ("Delete", self.delete, "Forget this snapshot."),
            ("Compare…", self.compare,
             "Open every snapshot's closed-loop response in the LTI Viewer."),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)

        self._status = QLabel("")
        self._status.setStyleSheet("color: palette(mid);")
        row.addWidget(self._status, stretch=1)
        self.refresh()

    # ── architecture ────────────────────────────────────────────

    def set_architecture(self, arch: CourseArchitecture) -> None:
        self._arch = arch

    # ── actions ─────────────────────────────────────────────────

    def take(self, label: str | None = None) -> Snapshot:
        """Freeze the architecture. Asks for a name when driven by the button."""
        if not isinstance(label, str) or not label:
            suggested = f"Design {len(self.store) + 1}"
            label, ok = QInputDialog.getText(self, "Snapshot", "Name:",
                                             text=suggested)
            if not ok:
                return None                                  # type: ignore[return-value]
            label = label or suggested
        snapshot = self.store.take(self._arch, label)
        self.refresh()
        self._combo.setCurrentText(snapshot.label)
        self.changed.emit()
        return snapshot

    def restore(self) -> None:
        snapshot = self.current()
        if snapshot is None:
            return
        restore_snapshot(self._arch, snapshot)
        self._status.setText(f"restored “{snapshot.label}”")
        self.restored.emit(snapshot)

    def delete(self) -> None:
        snapshot = self.current()
        if snapshot is None:
            return
        self.store.remove(snapshot.label)
        self.refresh()
        self.changed.emit()

    def compare(self) -> None:
        if not len(self.store):
            self._status.setText("nothing to compare yet")
            return
        collection = self.store.collection()
        collection.add("current", self._arch.get_closed_loop_tf("r", "y"))
        self.compare_requested.emit(collection)

    # ── state ───────────────────────────────────────────────────

    def current(self) -> Snapshot | None:
        label = self._combo.currentText()
        if not label:
            self._status.setText("no snapshot selected")
            return None
        try:
            return self.store.get(label)
        except KeyError:
            self.refresh()
            return None

    def refresh(self) -> None:
        keep = self._combo.currentText()
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItems(self.store.labels)
        if keep in self.store.labels:
            self._combo.setCurrentText(keep)
        self._combo.blockSignals(False)
        count = len(self.store)
        self._status.setText("" if count else "no snapshots yet")
        for button in self.findChildren(QPushButton):
            if button.text() in ("Restore", "Delete", "Compare…"):
                button.setEnabled(bool(count))
