"""
Canvas graphics: blocks, ports and wires.
=========================================
The items hold no model state of their own — each one points at a block id or
a :class:`~fakematlab.sim.model.Connection` and reads through to the
:class:`~fakematlab.sim.model.SimModel`. The model is the single source of
truth; the canvas is a view of it. That is what keeps undo/redo honest: a
command changes the model and the canvas is rebuilt from it, so the two cannot
drift apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsObject, QStyle

BLOCK_W, BLOCK_H = 110.0, 60.0
PORT_R = 5.0
#: Extra radius that counts as a click on the port but is not
#: drawn. Wiring is the canvas's most-used gesture and a 5 px
#: circle is a hard target.
PORT_HIT_MARGIN = 7.0
GRID = 10.0


def _clr(light: str, dark: str) -> QColor:
    palette = QApplication.palette()
    return QColor(dark if palette.window().color().lightness() < 128 else light)


def block_bg():      return _clr("#E8F0FE", "#1E3A5F")
def block_border():  return _clr("#2255AA", "#5599FF")
def block_text():    return _clr("#101820", "#E8F0FF")
def wire_colour():   return _clr("#33404D", "#B8C4D0")
def port_in():       return _clr("#2E7D32", "#66BB6A")
def port_out():      return _clr("#C62828", "#EF5350")
def sel_colour():    return _clr("#FF6F00", "#FFB300")
def error_colour():  return _clr("#C0392B", "#FF6B6B")


def snap(value: float, grid: float = GRID) -> float:
    return round(value / grid) * grid


# ──────────────────────────────────────────────────────────────
#  Alignment snapping
# ──────────────────────────────────────────────────────────────

#: How close (scene px) a dragged block's line must come to another block's
#: before it jumps onto it. Small enough not to fight a deliberate placement,
#: large enough to catch a hand that is "about level".
ALIGN_THRESHOLD = 8.0


@dataclass
class Guide:
    """One dashed alignment line: ``"h"`` at y = ``coord``, or ``"v"`` at x."""
    orientation: str
    coord: float
    lo: float                # extent along the line, so it can be drawn short
    hi: float


@dataclass
class SnapResult:
    x: float
    y: float
    aligned_x: bool = False
    aligned_y: bool = False
    guides: list[Guide] = field(default_factory=list)


def align_snap(x: float, y: float, half_w: float, half_h: float,
               others: list[tuple[float, float, float, float]],
               threshold: float = ALIGN_THRESHOLD) -> SnapResult:
    """
    Pull a block's position onto the lines of the blocks around it.

    ``(x, y)`` is the dragged block's centre and ``others`` holds
    ``(cx, cy, half_w, half_h)`` for every block that stays put. The centre
    line is the one that matters — a single-port block's ports sit on it, so
    matching centres is what makes a wire come out straight — but top and
    bottom edges (and left and right) are offered too, for blocks of different
    heights whose *edges* are what the eye lines up.

    Each axis is decided independently and takes the nearest line within
    ``threshold``; on a tie the centre wins, because it is listed first.
    Returns the snapped position plus a :class:`Guide` for every line the block
    now lies on, so the canvas can show *why* it jumped.
    """
    def best(pos: float, half: float, axis: int):
        """``(correction, which line)`` for the nearest match, or ``None``."""
        chosen = None
        for other in others:
            centre, other_half = other[axis], other[2 + axis]
            for kind, (mine, theirs) in enumerate(
                    ((0.0, 0.0), (-half, -other_half), (half, other_half))):
                delta = (centre + theirs) - (pos + mine)
                if abs(delta) <= threshold and (
                        chosen is None or abs(delta) < abs(chosen[0]) - 1e-9):
                    chosen = (delta, kind)
        return chosen

    hit_x = best(x, half_w, 0)
    hit_y = best(y, half_h, 1)
    nx = x + (hit_x[0] if hit_x else 0.0)
    ny = y + (hit_y[0] if hit_y else 0.0)

    guides: dict[tuple[str, float], Guide] = {}

    def add(orientation: str, coord: float, lo: float, hi: float) -> None:
        key = (orientation, round(coord, 3))
        if key in guides:
            guides[key].lo = min(guides[key].lo, lo)
            guides[key].hi = max(guides[key].hi, hi)
        else:
            guides[key] = Guide(orientation, coord, lo, hi)

    # Only the *kind* of line that snapped is drawn (centre, or top/bottom):
    # two blocks of equal height also share their edges, and three dashed
    # lines where one explains the jump is clutter.
    for cx, cy, ohw, ohh in others:
        if hit_y:
            mine, theirs = ((0.0, 0.0), (-half_h, -ohh),
                            (half_h, ohh))[hit_y[1]]
            if abs((ny + mine) - (cy + theirs)) < 0.5:
                add("h", cy + theirs,
                    min(nx - half_w, cx - ohw), max(nx + half_w, cx + ohw))
        if hit_x:
            mine, theirs = ((0.0, 0.0), (-half_w, -ohw),
                            (half_w, ohw))[hit_x[1]]
            if abs((nx + mine) - (cx + theirs)) < 0.5:
                add("v", cx + theirs,
                    min(ny - half_h, cy - ohh), max(ny + half_h, cy + ohh))
    return SnapResult(nx, ny, hit_x is not None, hit_y is not None,
                      list(guides.values()))


# ──────────────────────────────────────────────────────────────
#  Port
# ──────────────────────────────────────────────────────────────

class PortItem(QGraphicsObject):
    """
    A connection point on a block.

    Clicking one starts a wire; releasing on another finishes it. Inputs are
    drawn green on the left, outputs red on the right, so the direction of a
    half-drawn wire is never ambiguous.
    """

    def __init__(self, block_id: str, port: str, is_input: bool,
                 parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.block_id = block_id
        self.port = port
        self.is_input = is_input
        self._hover = False
        self._highlight = False
        self.setAcceptHoverEvents(True)
        self.setZValue(3)
        self.setToolTip(f"{block_id}.{port} ({'input' if is_input else 'output'})")

    def boundingRect(self) -> QRectF:
        r = PORT_R + PORT_HIT_MARGIN
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self):
        """
        The clickable area, which is deliberately larger than the dot.

        A 5-pixel circle is a 10-pixel target, and half of it overlaps the
        block body. Widening the *hit* area without widening the mark is the
        difference between "click the port" and "click near the port".
        """
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        r = PORT_R + PORT_HIT_MARGIN
        path.addEllipse(QPointF(0, 0), r, r)
        return path

    def scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    def set_highlight(self, on: bool) -> None:
        if self._highlight != on:
            self._highlight = on
            self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        colour = port_in() if self.is_input else port_out()
        if self._hover or self._highlight:
            colour = sel_colour()
            painter.setPen(QPen(colour, 2.0))
        else:
            painter.setPen(QPen(colour.darker(130), 1.2))
        painter.setBrush(QBrush(colour))
        r = PORT_R + (2 if (self._hover or self._highlight) else 0)
        painter.drawEllipse(QPointF(0, 0), r, r)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()


# ──────────────────────────────────────────────────────────────
#  Block
# ──────────────────────────────────────────────────────────────

class BlockItem(QGraphicsObject):
    """A block on the canvas."""

    moved = Signal(str, float, float)      # block_id, x, y
    double_clicked = Signal(str)
    #: The alignment guides to show while this block is dragged; an empty list
    #: when the drag ends or nothing is aligned.
    guides_changed = Signal(list)

    def __init__(self, block, x: float, y: float) -> None:
        super().__init__()
        self.block_id = block.block_id
        self.block = block
        self._error: str = ""
        self.setPos(x, y)
        self.setFlags(QGraphicsItem.ItemIsMovable |
                      QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self._press_pos = QPointF(x, y)
        #: True between press and release, so programmatic ``setPos`` calls
        #: (rebuilds, undo) are never "helpfully" snapped.
        self._dragging = False
        self._snap_on = True
        self._aligned = (False, False)

        self.ports: dict[tuple[str, bool], PortItem] = {}
        self._build_ports()
        self.setToolTip(f"{block.type_name} — {block.description}")

    # ── geometry ────────────────────────────────────────────────

    def height(self) -> float:
        n = max(len(self.block.inputs), len(self.block.outputs), 1)
        return max(BLOCK_H, 24.0 + 22.0 * n)

    def boundingRect(self) -> QRectF:
        h = self.height()
        return QRectF(-BLOCK_W / 2 - 8, -h / 2 - 8, BLOCK_W + 16, h + 16)

    def body_rect(self) -> QRectF:
        h = self.height()
        return QRectF(-BLOCK_W / 2, -h / 2, BLOCK_W, h)

    def _build_ports(self) -> None:
        for item in list(self.ports.values()):
            item.setParentItem(None)
        self.ports.clear()
        h = self.height()
        for i, name in enumerate(self.block.inputs):
            p = PortItem(self.block_id, name, True, self)
            p.setPos(-BLOCK_W / 2, self._port_y(i, len(self.block.inputs), h))
            self.ports[(name, True)] = p
        for i, name in enumerate(self.block.outputs):
            p = PortItem(self.block_id, name, False, self)
            p.setPos(BLOCK_W / 2, self._port_y(i, len(self.block.outputs), h))
            self.ports[(name, False)] = p

    @staticmethod
    def _port_y(index: int, count: int, height: float) -> float:
        if count <= 1:
            return 0.0
        span = height - 20.0
        return -span / 2 + span * index / (count - 1)

    def refresh(self) -> None:
        """Rebuild after a parameter change altered the port list or label."""
        self.prepareGeometryChange()
        self._build_ports()
        self.update()

    def set_error(self, message: str) -> None:
        self._error = message
        self.setToolTip(message or
                        f"{self.block.type_name} — {self.block.description}")
        self.update()

    # ── painting ────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.body_rect()
        selected = bool(option.state & QStyle.State_Selected)

        if self._error:
            pen = QPen(error_colour(), 2.5)
        elif selected:
            pen = QPen(sel_colour(), 2.5)
        else:
            pen = QPen(block_border(), 1.6)
        painter.setPen(pen)
        painter.setBrush(QBrush(block_bg()))
        painter.drawRoundedRect(rect, 7, 7)

        painter.setPen(QPen(block_text()))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(rect.adjusted(6, 4, -6, -16),
                         Qt.AlignCenter | Qt.TextWordWrap, self.block.label())

        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QPen(block_text().darker(140)))
        painter.drawText(rect.adjusted(4, rect.height() - 16, -4, -2),
                         Qt.AlignCenter, self.block_id)

        if self._error:
            painter.setPen(QPen(error_colour(), 2.0))
            painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
            painter.drawText(QRectF(rect.right() - 16, rect.top() - 2, 20, 18),
                             Qt.AlignCenter, "!")

    # ── interaction ─────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        self._press_pos = self.pos()
        self._dragging = True
        self._snap_on = not (event.modifiers() & Qt.AltModifier)
        self._aligned = (False, False)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        # Alt is read from the event so that holding it *mid-drag* lets go of
        # the alignment, and releasing it snaps back on.
        self._snap_on = not (event.modifiers() & Qt.AltModifier)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._dragging = False
        self.guides_changed.emit([])
        # Alignment takes precedence over the grid: snapping an aligned axis
        # to the grid afterwards would throw away exactly the coordinate the
        # guide promised. Only the axes that did not align fall back to it.
        ax, ay = self._aligned
        self._aligned = (False, False)
        new = QPointF(self.pos().x() if ax else snap(self.pos().x()),
                      self.pos().y() if ay else snap(self.pos().y()))
        self.setPos(new)
        if (abs(new.x() - self._press_pos.x()) > 0.01 or
                abs(new.y() - self._press_pos.y()) > 0.01):
            self.moved.emit(self.block_id, new.x(), new.y())

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit(self.block_id)
        event.accept()

    def _aligned_position(self, wanted: QPointF) -> QPointF:
        """Snap the drag's next position onto other blocks' lines."""
        if not self._snap_on:
            self._aligned = (False, False)
            self.guides_changed.emit([])
            return wanted
        others = [(o.pos().x(), o.pos().y(), BLOCK_W / 2, o.height() / 2)
                  for o in self.scene().items()
                  # Selected blocks travel with this one, so they are not
                  # landmarks: aligning to something that is moving is noise.
                  if isinstance(o, BlockItem) and o is not self
                  and not o.isSelected()]
        result = align_snap(wanted.x(), wanted.y(), BLOCK_W / 2,
                            self.height() / 2, others)
        self._aligned = (result.aligned_x, result.aligned_y)
        self.guides_changed.emit(result.guides)
        return QPointF(result.x, result.y)

    def itemChange(self, change, value):
        if (change == QGraphicsItem.ItemPositionChange and self._dragging
                and self.scene() is not None):
            return self._aligned_position(value)
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            for item in self.scene().items():
                if isinstance(item, WireItem) and item.touches(self.block_id):
                    item.reroute()
        return super().itemChange(change, value)


# ──────────────────────────────────────────────────────────────
#  Wire
# ──────────────────────────────────────────────────────────────

class WireItem(QGraphicsObject):
    """
    An orthogonal wire between two ports.

    Routed with a three-segment Manhattan path when the destination is to the
    right of the source, and a five-segment path that goes *around* the blocks
    when it is to the left — which is every feedback path, so it is worth
    getting right rather than drawing a diagonal through the plant.
    """

    clicked = Signal(object)               # the Connection

    def __init__(self, connection, src_port: PortItem,
                 dst_port: PortItem) -> None:
        super().__init__()
        self.connection = connection
        self.src_port = src_port
        self.dst_port = dst_port
        self._path = QPainterPath()
        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(0)
        self.setToolTip(str(connection))
        self.reroute()

    def touches(self, block_id: str) -> bool:
        return block_id in (self.connection.src.block, self.connection.dst.block)

    def reroute(self) -> None:
        self.prepareGeometryChange()
        a = self.src_port.scene_pos()
        b = self.dst_port.scene_pos()
        self._path = _manhattan(a, b)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._path.boundingRect().adjusted(-8, -8, 8, 8)

    def shape(self) -> QPainterPath:
        stroker = QPainterPath()
        stroker.addPath(self._path)
        from PySide6.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(10.0)
        return s.createStroke(self._path)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        selected = bool(option.state & QStyle.State_Selected)
        colour = sel_colour() if (selected or self._hover) else wire_colour()
        painter.setPen(QPen(colour, 2.4 if selected else 1.7,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._path)
        _arrow(painter, self._path, colour)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.connection)
        super().mousePressEvent(event)


def _manhattan(a: QPointF, b: QPointF) -> QPainterPath:
    """Orthogonal route from an output port to an input port."""
    path = QPainterPath(a)
    stub = 18.0
    if b.x() - a.x() > 2 * stub:
        mid = (a.x() + b.x()) / 2
        path.lineTo(mid, a.y())
        path.lineTo(mid, b.y())
        path.lineTo(b)
    else:
        # Feedback: leave right, drop below both blocks, come back and enter
        # from the left. A straight diagonal here would cut through whatever
        # sits between the two blocks, which for a control loop is the plant.
        drop = max(a.y(), b.y()) + 55.0
        path.lineTo(a.x() + stub, a.y())
        path.lineTo(a.x() + stub, drop)
        path.lineTo(b.x() - stub, drop)
        path.lineTo(b.x() - stub, b.y())
        path.lineTo(b)
    return path


def _arrow(painter: QPainter, path: QPainterPath, colour: QColor,
           size: float = 8.0) -> None:
    """Arrowhead at the end of the path, aimed along its last segment."""
    n = path.elementCount()
    if n < 2:
        return
    end = path.elementAt(n - 1)
    prev = path.elementAt(n - 2)
    dx, dy = end.x - prev.x, end.y - prev.y
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    tip = QPointF(end.x, end.y)
    base = QPointF(tip.x() - ux * size, tip.y() - uy * size)
    left = QPointF(base.x() - uy * size * 0.45, base.y() + ux * size * 0.45)
    right = QPointF(base.x() + uy * size * 0.45, base.y() - ux * size * 0.45)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(colour))
    painter.drawPolygon(QPolygonF([tip, left, right]))
