"""
Workspaces: three destinations instead of eight peers.

The eight tabs were never siblings. Six of them were *views of one
architecture* that change together; one was a block-diagram editor with its
own model, its own undo stack and its own file format; one was a state-space
workbench with its own model. A tab bar says "these are alternatives to one
another", and they are not — you use the Simulink editor *to produce*
something the analysis views look at.

So: **Analyse**, **Model**, **Console**, on a rail down the left side, with
the panels living inside whichever one they belong to. Switching is a
``QStackedWidget`` page change, so nothing is torn down: a running simulation,
a console session and a half-configured analysis all survive being navigated
away from and back.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .design import NORMAL, TIGHT


class Workspace(str, Enum):
    """The three destinations, in rail order."""

    ANALYSE = "Analyse"
    MODEL = "Model"
    CONSOLE = "Console"

    @property
    def shortcut(self) -> str:
        return f"Ctrl+{list(Workspace).index(self) + 1}"

    @property
    def description(self) -> str:
        return {
            Workspace.ANALYSE: "The current control system: responses, "
                               "margins, stability, design",
            Workspace.MODEL: "The block-diagram editor and its simulation",
            Workspace.CONSOLE: "Command window, workspace variables, figures "
                               "and scripts",
        }[self]

    @property
    def glyph(self) -> str:
        """
        A drawn mark, not an emoji.

        Deliberately from the box-drawing and geometric ranges, which every
        desktop font ships — the old `🔬` tab labels rendered as empty boxes
        wherever the emoji font was missing, including in this project's own
        screenshots.
        """
        return {Workspace.ANALYSE: "◱",
                Workspace.MODEL: "⛭",
                Workspace.CONSOLE: "›_"}[self]


class NavigationRail(QFrame):
    """A narrow column of destinations down the left edge."""

    changed = Signal(object)          # Workspace

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)

        column = QVBoxLayout(self)
        column.setContentsMargins(TIGHT, NORMAL, TIGHT, NORMAL)
        column.setSpacing(TIGHT)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[Workspace, QToolButton] = {}

        for index, workspace in enumerate(Workspace):
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setText(f"{workspace.glyph}\n{workspace.value}")
            button.setToolTip(
                f"{workspace.description}  ({workspace.shortcut})")
            button.setAccessibleName(workspace.value)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._group.addButton(button, index)
            self._buttons[workspace] = button
            column.addWidget(button)

        column.addStretch()
        self._group.idClicked.connect(self._on_clicked)
        self.set_current(Workspace.ANALYSE)

    def _on_clicked(self, index: int) -> None:
        self.changed.emit(list(Workspace)[index])

    def set_current(self, workspace: Workspace) -> None:
        """Check a destination without emitting — for programmatic moves."""
        button = self._buttons[workspace]
        button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(False)

    @property
    def current(self) -> Workspace:
        for workspace, button in self._buttons.items():
            if button.isChecked():
                return workspace
        return Workspace.ANALYSE

    def button(self, workspace: Workspace) -> QToolButton:
        return self._buttons[workspace]


class WorkspaceStack(QWidget):
    """The rail plus the pages it switches between."""

    changed = Signal(object)          # Workspace

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(NORMAL)

        self.rail = NavigationRail()
        self.rail.changed.connect(self.set_current)
        row.addWidget(self.rail)

        self._stack = QStackedWidget()
        row.addWidget(self._stack, stretch=1)
        self._pages: dict[Workspace, QWidget] = {}

    def add_page(self, workspace: Workspace, widget: QWidget) -> QWidget:
        self._pages[workspace] = widget
        self._stack.addWidget(widget)
        return widget

    def set_current(self, workspace: Workspace) -> None:
        page = self._pages.get(workspace)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        self.rail.set_current(workspace)
        self.changed.emit(workspace)

    @property
    def current(self) -> Workspace:
        current = self._stack.currentWidget()
        for workspace, page in self._pages.items():
            if page is current:
                return workspace
        return Workspace.ANALYSE

    def page(self, workspace: Workspace) -> QWidget | None:
        return self._pages.get(workspace)
