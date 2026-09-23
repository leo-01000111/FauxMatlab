"""
QGraphicsItem subclasses for the block-diagram canvas.
All items are theme-aware (respects QPalette for dark/light mode).

Item hierarchy (designed for future extension to free-form canvas):
  DiagramBlock    – a TF block (rectangle + label)
  DiagramSummer   – a summing junction (circle with ±)
  DiagramWire     – a connection arrow between items
  DiagramSignal   – a named tap-point (signal label that can be clicked)
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsObject,
)

# ──────────────────────────────────────────────────────────────
#  Colours (palette-independent fallbacks)
# ──────────────────────────────────────────────────────────────

def _clr(light: str, dark: str) -> QColor:
    """Choose colour based on application theme."""
    palette = QApplication.palette()
    bg = palette.window().color()
    is_dark = bg.lightness() < 128
    return QColor(dark if is_dark else light)


BLOCK_BG      = lambda: _clr("#D6E8FF", "#1E3A5F")
BLOCK_BORDER  = lambda: _clr("#2255AA", "#5599FF")
BLOCK_TEXT    = lambda: _clr("#000000", "#E8F0FF")
SUMMER_BG     = lambda: _clr("#FFF0D0", "#3A2800")
SUMMER_BORDER = lambda: _clr("#AA7700", "#FFB300")
WIRE_COLOR    = lambda: _clr("#333333", "#CCCCCC")
SIGNAL_TEXT   = lambda: _clr("#006600", "#00CC44")
SELECTED_BG   = lambda: _clr("#FFE066", "#665500")
HOVER_BORDER  = lambda: _clr("#FF4400", "#FF8844")


# ──────────────────────────────────────────────────────────────
#  DiagramBlock
# ──────────────────────────────────────────────────────────────

class DiagramBlock(QGraphicsObject):
    """
    A TF block rendered as a rounded rectangle with a label.
    Emits `clicked(block_id)` when pressed.
    """

    clicked = Signal(str)       # block_id

    W, H = 90, 50

    def __init__(self, block_id: str, label: str,
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.block_id = block_id
        self.label    = label
        self._selected = False
        self._hovered  = False
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setCursor(Qt.PointingHandCursor)

    # ── geometry ─────────────────────────────────────────────

    def boundingRect(self) -> QRectF:
        return QRectF(-self.W / 2, -self.H / 2, self.W, self.H)

    def centre(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    def port_in(self) -> QPointF:
        """Scene-coords of the left input port."""
        return self.mapToScene(QPointF(-self.W / 2, 0))

    def port_out(self) -> QPointF:
        """Scene-coords of the right output port."""
        return self.mapToScene(QPointF(self.W / 2, 0))

    # ── painting ─────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)

        bg     = SELECTED_BG() if self._selected else BLOCK_BG()
        border = HOVER_BORDER() if self._hovered  else BLOCK_BORDER()

        pen = QPen(border, 2.0)
        painter.setPen(pen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(self.boundingRect(), 8, 8)

        painter.setPen(QPen(BLOCK_TEXT()))
        font = QFont("Segoe UI", 11, QFont.Bold)
        painter.setFont(font)
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self.label)

    # ── interaction ───────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.block_id)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()


# ──────────────────────────────────────────────────────────────
#  DiagramSummer
# ──────────────────────────────────────────────────────────────

class DiagramSummer(QGraphicsObject):
    """
    Summing junction: circle with ⊕ symbol and ± signs near each input port.
    """

    clicked = Signal(str)   # summer_id

    R = 18  # radius

    def __init__(self, summer_id: str,
                 signs: dict[str, str] | None = None,
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.summer_id = summer_id
        # signs: {direction: sign}  e.g. {"left": "+", "bottom": "−", "top": "+"}
        self.signs = signs or {}
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        r = self.R
        return QRectF(-r, -r, 2 * r, 2 * r)

    def port(self, direction: str) -> QPointF:
        """Scene-coords of a port on the circle rim."""
        r = self.R
        offsets = {
            "left":   QPointF(-r, 0),
            "right":  QPointF(+r, 0),
            "top":    QPointF(0, -r),
            "bottom": QPointF(0, +r),
        }
        return self.mapToScene(offsets.get(direction, QPointF(0, 0)))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        border = HOVER_BORDER() if self._hovered else SUMMER_BORDER()
        painter.setPen(QPen(border, 2.0))
        painter.setBrush(QBrush(SUMMER_BG()))
        r = self.R
        painter.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))

        # ⊕ cross
        painter.setPen(QPen(SUMMER_BORDER(), 1.5))
        painter.drawLine(QPointF(-r * 0.5, 0), QPointF(r * 0.5, 0))
        painter.drawLine(QPointF(0, -r * 0.5), QPointF(0, r * 0.5))

        # ± labels near ports
        font = QFont("Segoe UI", 8, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QPen(SIGNAL_TEXT()))
        label_offset = r + 4
        pos_map = {
            "left":   QPointF(-label_offset - 8, -8),
            "right":  QPointF(label_offset,      -8),
            "top":    QPointF(-6, -label_offset - 10),
            "bottom": QPointF(-6,  label_offset + 2),
        }
        for direction, sign in self.signs.items():
            if direction in pos_map:
                painter.drawText(pos_map[direction], sign)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.summer_id)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True; self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False; self.update()


# ──────────────────────────────────────────────────────────────
#  DiagramWire
# ──────────────────────────────────────────────────────────────

class DiagramWire(QGraphicsItem):
    """
    Orthogonal wire with an arrowhead at the destination end.
    The path is specified as a list of QPointF in scene coordinates.
    """

    def __init__(self, points: list[QPointF],
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.setZValue(-1)
        self.points = points

    def boundingRect(self) -> QRectF:
        if not self.points:
            return QRectF()
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        pad = 10
        return QRectF(min(xs) - pad, min(ys) - pad,
                      max(xs) - min(xs) + 2 * pad,
                      max(ys) - min(ys) + 2 * pad)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if len(self.points) < 2:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(WIRE_COLOR(), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        path = QPainterPath(self.points[0])
        for pt in self.points[1:]:
            path.lineTo(pt)
        painter.drawPath(path)

        # Arrowhead at last point
        _draw_arrow(painter, self.points[-2], self.points[-1],
                    WIRE_COLOR())


def _draw_arrow(painter: QPainter, p1: QPointF, p2: QPointF,
                color: QColor, size: float = 9.0) -> None:
    """Draw a filled arrowhead pointing from p1 → p2."""
    import math
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    lx, ly = -uy, ux  # left normal

    tip = p2
    base_x = tip.x() - ux * size
    base_y = tip.y() - uy * size
    left  = QPointF(base_x + lx * size * 0.4, base_y + ly * size * 0.4)
    right = QPointF(base_x - lx * size * 0.4, base_y - ly * size * 0.4)

    poly = QPolygonF([tip, left, right])
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPolygon(poly)


# ──────────────────────────────────────────────────────────────
#  DiagramSignalLabel
# ──────────────────────────────────────────────────────────────

class DiagramSignalLabel(QGraphicsObject):
    """
    A clickable signal label on the wire (e.g. 'r', 'y', 'di').
    Clicking it selects this signal as the active analysis tap.
    """

    clicked = Signal(str)   # signal_id

    def __init__(self, signal_id: str, display: str,
                 pos: QPointF,
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.signal_id = signal_id
        self.display   = display
        self.setPos(pos)
        self._active  = False
        self._hovered = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(-20, -10, 40, 20)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        color = HOVER_BORDER() if self._hovered else (
            QColor("#FF6600") if self._active else SIGNAL_TEXT()
        )
        painter.setPen(QPen(color, 1.5))
        font = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(font)
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self.display)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.signal_id)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True; self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False; self.update()
