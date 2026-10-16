"""
The command history: what was typed at the prompt, this session and before.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..persist import CommandHistory


class HistoryWidget(QWidget):
    """
    A filterable list of past commands, newest at the bottom.

    MATLAB's Command History, more or less: double-click a command to put it
    back at the prompt for editing, or run it again from the right-click menu.
    The list survives restarts, so last week's ``bode(L)`` is still there.
    """

    #: Put this command back at the prompt.
    recall = Signal(str)
    #: Run this command again, as if typed.
    rerun = Signal(str)

    def __init__(self, store: CommandHistory | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.store = store or CommandHistory()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        row = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter commands…")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        row.addWidget(self._filter, stretch=1)
        clear = QPushButton("Clear")
        clear.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        clear.setToolTip("Forget the whole command history")
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        layout.addLayout(row)

        self._list = QListWidget()
        self._list.setFont(theme.data_font(10))
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.itemDoubleClicked.connect(
            lambda item: self.recall.emit(_command(item)))
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._list, stretch=1)

        self._hint = QLabel(
            "Double-click to edit at the prompt; right-click to run again.")
        self._hint.setStyleSheet("color: palette(mid);")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        for command in self.store.items:
            self._add_item(command)
        self._list.scrollToBottom()

    # ── contents ────────────────────────────────────────────────

    def add(self, command: str) -> None:
        """Record a command that ran, and show it if the filter lets it."""
        if not self.store.append(command):
            return
        item = self._add_item(command.rstrip())
        item.setHidden(not self._matches(item))
        self._list.scrollToBottom()

    def clear(self) -> None:
        self.store.clear()
        self._list.clear()

    def commands(self, *, visible_only: bool = False) -> list[str]:
        """The listed commands, oldest first — optionally only those shown."""
        return [_command(self._list.item(i)) for i in range(self._list.count())
                if not (visible_only and self._list.item(i).isHidden())]

    def set_filter(self, text: str) -> None:
        self._filter.setText(text)

    def _add_item(self, command: str) -> QListWidgetItem:
        # A multi-line block shows its first line; the tooltip has the rest.
        lines = command.splitlines() or [""]
        label = lines[0] + (" …" if len(lines) > 1 else "")
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, command)
        item.setToolTip(command)
        self._list.addItem(item)
        return item

    # ── filtering ───────────────────────────────────────────────

    def _matches(self, item: QListWidgetItem) -> bool:
        needle = self._filter.text().strip().casefold()
        return not needle or needle in _command(item).casefold()

    def _apply_filter(self, *_args) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(not self._matches(item))

    # ── context menu ────────────────────────────────────────────

    def _selected(self) -> list[str]:
        """The selected commands, in the order they were typed."""
        rows = sorted(self._list.row(item)
                      for item in self._list.selectedItems())
        return [_command(self._list.item(row)) for row in rows]

    def _context_menu(self, position) -> None:
        item = self._list.itemAt(position)
        if item is not None and not item.isSelected():
            self._list.setCurrentItem(item)
        menu = self.context_menu()
        if menu.actions():
            menu.exec(self._list.viewport().mapToGlobal(position))

    def context_menu(self) -> QMenu:
        """The right-click menu for the current selection."""
        menu = QMenu(self)
        commands = self._selected()
        if commands:
            run = QAction("Run again" if len(commands) == 1
                          else f"Run {len(commands)} commands again", menu)
            run.triggered.connect(lambda: self._run(commands))
            menu.addAction(run)
            edit = QAction("Edit at the prompt", menu)
            edit.triggered.connect(lambda: self.recall.emit(commands[-1]))
            edit.setEnabled(len(commands) == 1)
            menu.addAction(edit)
            copy = QAction("Copy", menu)
            copy.triggered.connect(lambda: QApplication.clipboard().setText(
                "\n".join(commands)))
            menu.addAction(copy)
            menu.addSeparator()
        forget = QAction("Clear history", menu)
        forget.triggered.connect(self.clear)
        forget.setEnabled(self._list.count() > 0)
        menu.addAction(forget)
        return menu

    def _run(self, commands: list[str]) -> None:
        for command in commands:
            self.rerun.emit(command)


def _command(item: QListWidgetItem) -> str:
    return item.data(Qt.UserRole)
