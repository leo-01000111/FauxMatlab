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

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

# ── spacing scale ───────────────────────────────────────────────
#
# Four steps, and nothing between them. A layout that needs 7 px is a layout
# that has not decided what it is. They are the first four rungs of the
# brand's 8:5 scale (``theme.SPACE_*``).

TIGHT = theme.SPACE_1      # inside a control group
NORMAL = theme.SPACE_2     # between controls
SECTION = theme.SPACE_3    # between sections of a panel
PANEL = theme.SPACE_4      # around a panel's contents


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

    The colours follow the Day/Night theme: ``colour`` is for words about the
    status, ``lamp`` is the fill of the round lamp. They differ for caution —
    sign yellow is a lamp, never text on the Day ground.
    """

    NEUTRAL = ("neutral", "·", "")
    OK = ("ok", "●", "stable")
    WARNING = ("warning", "▲", "undefined")
    ERROR = ("error", "■", "failed")
    CRITICAL = ("critical", "×", "unstable")

    @property
    def colour(self) -> str:
        """Colour for text about this status, in the current theme."""
        t = theme.tokens()
        return {
            Status.NEUTRAL: t.ink_muted,
            Status.OK: t.lamp_go,
            Status.WARNING: t.ink,
            Status.ERROR: t.hold_ink,
            Status.CRITICAL: t.hold_ink,
        }[self]

    @property
    def lamp(self) -> str:
        """Fill for the status lamp, in the current theme."""
        t = theme.tokens()
        return {
            Status.NEUTRAL: t.ink_muted,
            Status.OK: t.lamp_go,
            Status.WARNING: t.lamp_caution,
            Status.ERROR: t.hold,
            Status.CRITICAL: t.hold,
        }[self]

    @property
    def symbol(self) -> str:
        return self.value[1]

    @property
    def default_text(self) -> str:
        return self.value[2]


class StatusBadge(QLabel):
    """
    A round lamp and a word. Never colour alone.

    The text is still ``"<symbol> <word>"`` — that is what a screen reader
    and the context bar's summary read — but it is *painted* as a lamp and the
    word, so the symbol never shows twice. Colours are read at paint time, so
    a theme switch needs no restyling.
    """

    _LAMP = 9

    def __init__(self, status: Status = Status.NEUTRAL, text: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        self.setFont(theme.label_font(8))
        self._word = ""
        self.set_status(status, text)
        theme.notifier().changed.connect(self._on_theme)

    def set_status(self, status: Status, text: str = "") -> None:
        self._status = status
        label = text or status.default_text
        self._word = label
        self.setText(f"{status.symbol} {label}".strip())
        self.setAccessibleName(f"status: {label or status.name.lower()}")
        self.updateGeometry()
        self.update()

    @property
    def status(self) -> Status:
        return self._status

    def _on_theme(self, *_ignored) -> None:
        self.update()

    def sizeHint(self) -> QSize:          # noqa: N802 (Qt API)
        width = self.fontMetrics().horizontalAdvance(self._word.upper())
        return QSize(self._LAMP + TIGHT * 2 + width + 2,
                     max(self.fontMetrics().height(), self._LAMP) + 2)

    def minimumSizeHint(self) -> QSize:   # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        centre = QPointF(self._LAMP / 2 + 1, self.height() / 2)
        radius = self._LAMP / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._status.lamp))
        p.drawEllipse(centre, radius, radius)
        if self._status is Status.WARNING:            # yellow is pale: ring it
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(theme.tokens().ink))
            p.drawEllipse(centre, radius, radius)
        p.setPen(QColor(self._status.colour))
        p.setFont(self.font())
        p.drawText(self.rect().adjusted(self._LAMP + TIGHT * 2, 0, 0, 0),
                   Qt.AlignVCenter | Qt.AlignLeft, self._word)


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
        self._title.setFont(theme.title_font(11))
        row.addWidget(self._title)

        self._subtitle = QLabel(subtitle)
        self._subtitle.setFont(theme.label_font())
        self._subtitle.setForegroundRole(QPalette.Mid)    # ink_muted
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
    """
    A titled group of controls, with the house margins.

    Drawn as the brand's DataPlate: a surface panel in a 2 px ink frame, its
    header closed off by a 2 px ink rule. The look itself lives in the
    application stylesheet, keyed on the ``hp`` property.
    """

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setProperty("hp", "panel")
        outer = apply_spacing(QVBoxLayout(self), margin=SECTION,
                              spacing=NORMAL)
        if title:
            self.header = PanelHeader(title)
            outer.addWidget(self.header)
            rule = QFrame()
            rule.setProperty("hp", "headrule")
            rule.setFixedHeight(theme.STROKE_BOLD)
            outer.addWidget(rule)
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
        name_font = theme.label_font()
        if not name.isascii():             # "ωc" must not become "ΩC"
            name_font.setCapitalization(QFont.MixedCase)
        self._name.setFont(name_font)
        self._name.setForegroundRole(QPalette.Mid)        # ink_muted
        row.addWidget(self._name)
        self._value = QLabel("—")
        self._value.setFont(theme.data_font(9.5, 600))
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
        title.setFont(theme.title_font(11))
        layout.addWidget(title)
        if hint:
            note = QLabel(hint)
            note.setAlignment(Qt.AlignCenter)
            note.setWordWrap(True)
            note.setForegroundRole(QPalette.Mid)          # ink_muted
            layout.addWidget(note)
        layout.addStretch()


def monospace(point_size: int = 9) -> QFont:
    """The font for transfer functions and anything column-aligned."""
    return theme.data_font(point_size * 0.95)
