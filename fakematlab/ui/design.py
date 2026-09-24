"""
Shared UI primitives: one spacing scale, one set of panel parts.

Before this, every tab was laid out by whichever phase built it — margins of
0, 2, 4 and 6 in four files, headings that were sometimes a bold ``QLabel``
and sometimes a ``QGroupBox`` title, and status shown as coloured text in one
place and a banner in another. The result reads as several applications
sharing a window.

Everything here is deliberately small. It is a vocabulary, not a widget
toolkit: a spacing scale, a panel header, a status badge, a metric readout and
an empty state. Panels compose them instead of re-inventing them.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# ── spacing scale ───────────────────────────────────────────────
#
# Four steps, and nothing between them. A layout that needs 7 px is a layout
# that has not decided what it is.

TIGHT = 4        # inside a control group
NORMAL = 8       # between controls
SECTION = 12     # between sections of a panel
PANEL = 16       # around a panel's contents


def apply_spacing(layout, margin: int = NORMAL, spacing: int = NORMAL):
    """Give a layout the house margins. Returns it, so it can be chained."""
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


# ── status ──────────────────────────────────────────────────────

class Status(Enum):
    """
    The five states a panel can report.

    Each carries a symbol as well as a colour, because colour alone is not an
    indicator — the plan's accessibility requirement, and the reason a
    red/green dot is not enough on its own.
    """

    NEUTRAL = ("#8A8AA0", "·", "")
    OK = ("#56C271", "●", "stable")
    WARNING = ("#E9C46A", "▲", "undefined")
    ERROR = ("#F4A261", "■", "failed")
    CRITICAL = ("#F45B69", "×", "unstable")

    @property
    def colour(self) -> str:
        return self.value[0]

    @property
    def symbol(self) -> str:
        return self.value[1]

    @property
    def default_text(self) -> str:
        return self.value[2]


class StatusBadge(QLabel):
    """A coloured symbol plus a word. Never colour alone."""

    def __init__(self, status: Status = Status.NEUTRAL, text: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        self.set_status(status, text)

    def set_status(self, status: Status, text: str = "") -> None:
        self._status = status
        label = text or status.default_text
        self.setText(f"{status.symbol} {label}".strip())
        self.setStyleSheet(f"color: {status.colour}; font-weight: 600;")
        self.setAccessibleName(f"status: {label or status.name.lower()}")

    @property
    def status(self) -> Status:
        return self._status


# ── panel furniture ─────────────────────────────────────────────

class PanelHeader(QWidget):
    """
    A panel's title row: a name, an optional subtitle, and room for actions.

    Use it instead of a bold ``QLabel`` so every panel's title sits at the
    same height with the same weight.
    """

    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        row = apply_spacing(QHBoxLayout(self), margin=0, spacing=NORMAL)

        self._title = QLabel(title)
        font = self._title.font()
        font.setBold(True)
        font.setPointSize(max(font.pointSize(), 1))
        self._title.setFont(font)
        row.addWidget(self._title)

        self._subtitle = QLabel(subtitle)
        self._subtitle.setStyleSheet("color: palette(mid);")
        self._subtitle.setVisible(bool(subtitle))
        row.addWidget(self._subtitle)

        row.addStretch()
        self._actions = QHBoxLayout()
        self._actions.setSpacing(TIGHT)
        row.addLayout(self._actions)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def add_action(self, widget: QWidget) -> QWidget:
        self._actions.addWidget(widget)
        return widget


class SectionCard(QFrame):
    """A titled group of controls, with the house margins."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        outer = apply_spacing(QVBoxLayout(self), margin=SECTION,
                              spacing=NORMAL)
        if title:
            self.header = PanelHeader(title)
            outer.addWidget(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(NORMAL)
        outer.addLayout(self.body)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget


class MetricLabel(QWidget):
    """
    One number with its name, laid out the same way everywhere.

    Shows an em dash rather than ``nan`` when a quantity is undefined — a
    margin that does not exist is not a failed calculation, and printing
    ``nan`` invites the reader to think something broke.
    """

    def __init__(self, name: str, units: str = "", parent=None) -> None:
        super().__init__(parent)
        row = apply_spacing(QHBoxLayout(self), margin=0, spacing=TIGHT)
        self._name = QLabel(name)
        self._name.setStyleSheet("color: palette(mid);")
        row.addWidget(self._name)
        self._value = QLabel("—")
        value_font = self._value.font()
        value_font.setBold(True)
        self._value.setFont(value_font)
        row.addWidget(self._value)
        self._units = units
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_value(self, value, fmt: str = "{:.4g}") -> None:
        import math

        try:
            number = float(value)
        except (TypeError, ValueError):
            self._value.setText(str(value))
            return
        if not math.isfinite(number):
            self._value.setText("—")
            self.setToolTip("undefined for this system")
            return
        text = fmt.format(number)
        self._value.setText(f"{text} {self._units}".strip())
        self.setToolTip("")

    def set_undefined(self, why: str = "") -> None:
        self._value.setText("—")
        self.setToolTip(why)


class EmptyState(QWidget):
    """
    What a panel shows before its first calculation, or when there is
    nothing to draw. A blank panel is indistinguishable from a broken one.
    """

    def __init__(self, message: str, hint: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = apply_spacing(QVBoxLayout(self), margin=PANEL,
                               spacing=NORMAL)
        layout.addStretch()
        title = QLabel(message)
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        if hint:
            note = QLabel(hint)
            note.setAlignment(Qt.AlignCenter)
            note.setWordWrap(True)
            note.setStyleSheet("color: palette(mid);")
            layout.addWidget(note)
        layout.addStretch()


def monospace(point_size: int = 9) -> QFont:
    """The font for transfer functions and anything column-aligned."""
    font = QFont("Consolas")
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(point_size)
    return font
