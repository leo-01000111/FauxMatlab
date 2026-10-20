"""
Cedric the shrimp, at the foot of the navigation rail, asking "need help?".

The same Cedric as on leongorecki.eu and in the Cedric app: the shape is the
site's ``assets/cedric/design.js`` (generated there from cedric-lab's
``shrimp.js``), copied in as data, and the palette is the site's coral one —
flat coral with a black eye by day, coral fading to pink with a blue eye at
night. He is twenty-odd straight hatch strokes, so he is painted directly with
``QPainter`` rather than carried as an SVG: that keeps the idle motion (bob,
swim wave, antenna wiggle, blink) the site has without a web view.

Clicking him emits ``clicked``; what that opens is :mod:`evans.ui.help`'s
business, not his.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from . import theme

# ── the shape (design "Cedric", viewBox 152 51 923 658) ─────────────────────
#
# Body: (x0, y0, x1, y1, s) — s runs 0 at the nose to 1 at the tail tip; it
# picks the gradient colour and delays the swim wave. Every stroke is 14 wide.

VIEW = QRectF(152, 51, 923, 658)
BODY_W = 14.0
BODY = (
    (652, 254.3, 749, 215.1, 0.0),
    (542.7, 263.9, 748.5, 180.8, 0.1),
    (363, 163.9, 462.3, 123.8, 0.3),
    (288.2, 228.7, 580.6, 110.6, 0.3),
    (248.2, 279.4, 640.2, 121, 0.3),
    (209.7, 364, 730.4, 153.6, 0.3),
    (201.5, 401.8, 364.5, 335.9, 0.5),
    (198.6, 437.5, 306.9, 393.7, 0.5),
    (201, 471, 286.2, 436.6, 0.6),
    (208.7, 502.4, 279, 474, 0.6),
    (221, 532, 283.6, 506.7, 0.6),
    (237.4, 559.8, 294.9, 536.6, 0.7),
    (257.9, 586.1, 311.9, 564.2, 0.7),
    (283.3, 610.3, 337.5, 588.4, 0.7),
    (316.5, 631.4, 373, 608.6, 0.8),
    (360.6, 648.1, 417, 625.3, 0.8),
    (417.4, 659.7, 472.4, 637.5, 0.9),
    (496.4, 662.3, 542, 643.8, 0.9),
)

# Antennae: (x0, y0, x1, y1, i), 10.5 wide, wiggling about their shared root.
ANT_W = 10.5
ANT_PIVOT = QPointF(772.596, 171.034)
ANTENNAE = (
    (772.6, 171, 958, 96.1, 0),
    (797.3, 195.6, 1029.1, 101.9, 1),
)

# The eye is a short coloured dash riding in a gap of its own hatch line.
EYE_P = (224.112, 323.610)
EYE_DIR = (0.927184, -0.374607)
EYE_LENGTH = 498.377          # of the host line
EYE_U0 = 426.383              # where along it the eye sits
EYE_LEN = 18.0
EYE_CLEAR = 7.0
EYE_S = 0.3

# The site's coral palette (cedric.css): (nose, tail tip, eye).
DAY_INK = ("#f2643f", "#f2643f", "#121314")
NIGHT_INK = ("#ff7048", "#ffa3c2", "#86a8ff")

LINE = "need help?"


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
    )


def _ease(phase: float) -> float:
    """0 → 1 → 0 over one period, eased like CSS ``ease-in-out``."""
    return (1 - math.cos(2 * math.pi * phase)) / 2


class CedricButton(QWidget):
    """Cedric with a "need help?" callout; the whole thing is one button."""

    clicked = Signal()

    FPS = 24

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("Open the Evans documentation")
        self.setAccessibleName("Cedric: need help?")
        self.setAccessibleDescription("Opens the Evans documentation")
        self.setMouseTracking(True)

        self._t0 = time.monotonic()
        self._hover = False
        self._pressed = False
        self._hop_at = -1e9
        self._blink_at = -1e9
        self._next_blink = 3.0

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // self.FPS)
        self._timer.timeout.connect(self.update)
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._sync_timer)
        theme.notifier().changed.connect(lambda _t: self.update())

    # ── size ────────────────────────────────────────────────

    # As wide as his line and no wider: the rail grows to fit him, and the
    # window's minimum width has to stay inside the 1280 px budget.
    def sizeHint(self) -> QSize:
        return QSize(self._text_width() + 4, 84)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._text_width() + 4, 72)

    def _text_width(self) -> int:
        return QFontMetrics(self._font()).horizontalAdvance(LINE)

    def _font(self):
        # The site's callout is lowercase mono, so the data face, not the
        # uppercase sign/label one.
        return theme.data_font(7.0)

    # ── animation clock ──────────────────────────────────────
    #
    # Only ticks while he can be seen: hidden, minimised or in a background
    # window he holds still instead of repainting the rail 24 times a second.

    def _sync_timer(self, *_args) -> None:
        app = QApplication.instance()
        active = app is None or app.applicationState() == Qt.ApplicationActive
        if self.isVisible() and active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _now(self) -> float:
        return time.monotonic() - self._t0

    # ── input ───────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self._poke()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._poke()
            return
        super().keyPressEvent(event)

    def _poke(self) -> None:
        self._hop_at = self._now()
        self._blink_at = self._hop_at
        self.update()
        self.clicked.emit()

    # ── painting ────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        tok = theme.tokens()
        g1, g2, eye_ink = (QColor(c) for c in
                           (NIGHT_INK if tok.is_night else DAY_INK))
        now = self._now() if self._timer.isActive() else 0.0
        fast = 2.0 if self._hover else 1.0

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())

        # The callout: text on an underline, as on the site. (The site's
        # leader line has no room on a rail this narrow.)
        p.setFont(self._font())
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(LINE)
        text_h = fm.height()
        ink = QColor(tok.ink if (self._hover or self.hasFocus())
                     else tok.ink_muted)
        tx = max(1.0, (r.width() - text_w) / 2)
        ty = 4.0
        p.setPen(ink)
        p.drawText(QRectF(tx, ty, text_w + 2, text_h), Qt.AlignLeft, LINE)
        rule_y = ty + text_h + 2
        p.setPen(QPen(ink, 1.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(tx, rule_y), QPointF(tx + text_w, rule_y))

        # Cedric, fitted under the callout with room for the bob.
        box = QRectF(1, rule_y + 4, r.width() - 2, r.height() - rule_y - 8)
        scale = min(box.width() / VIEW.width(), box.height() / VIEW.height())
        w, h = VIEW.width() * scale, VIEW.height() * scale
        ox = box.left() + (box.width() - w) / 2
        oy = box.top() + (box.height() - h) / 2

        p.translate(ox + w / 2, oy + h / 2)
        # Idle bob: float up 5 % and rock ±1.5° over 4.2 s.
        bob = _ease(now / 4.2)
        p.translate(0, -0.05 * h * bob)
        p.rotate(-1.5 + 3.0 * bob)
        # Poke: a soft hop backwards, tail first, then settle.
        hop = (now - self._hop_at) / 1.1
        if 0 <= hop < 1:
            lift = math.sin(math.pi * hop)
            p.translate(-0.06 * w * lift, -0.09 * h * lift)
            p.rotate(-5 * lift)
        if self._pressed:
            p.translate(0, 1)
        p.scale(scale, scale)
        p.translate(-VIEW.center())

        def sway(s: float) -> float:
            """The swim wave: 7 units up, head first, every 2.6 s."""
            return -7.0 * _ease((now + s * 1.3 - 3.0) / 2.6)

        # At rail size a 14-unit stroke is barely a pixel; keep the hatching
        # legible rather than faithful.
        thick = max(1.0, 1.5 / (BODY_W * scale))

        def pen(colour: QColor, width: float) -> QPen:
            return QPen(colour, width * thick, Qt.SolidLine, Qt.RoundCap)

        for x0, y0, x1, y1, s in BODY:
            dy = sway(s)
            p.setPen(pen(_mix(g1, g2, s), BODY_W))
            p.drawLine(QPointF(x0, y0 + dy), QPointF(x1, y1 + dy))

        # Antennae wiggle -4°..5° about their root (faster under the cursor).
        for x0, y0, x1, y1, i in ANTENNAE:
            phase = (now * fast - i * 0.45) / 3.0
            angle = -4.0 + 9.0 * _ease(phase)
            p.save()
            p.translate(ANT_PIVOT)
            p.rotate(angle)
            p.translate(-ANT_PIVOT)
            p.setPen(pen(g1, ANT_W))
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            p.restore()

        # The eye line: solid, a gap, the eye in the gap, solid again.
        if now > self._next_blink:
            self._blink_at = now
            self._next_blink = now + random.uniform(3.5, 6.5)
        k = 1.0
        pb = (now - self._blink_at) / 0.18
        if 0 <= pb < 1:
            k = 1 - 0.95 * math.sin(math.pi * pb)
        dy = sway(EYE_S)

        def at(u: float) -> QPointF:
            return QPointF(EYE_P[0] + EYE_DIR[0] * u,
                           EYE_P[1] + EYE_DIR[1] * u + dy)

        gap = EYE_LEN + 2 * BODY_W + 2 * EYE_CLEAR
        host = pen(_mix(g1, g2, EYE_S), BODY_W)
        p.setPen(host)
        p.drawLine(at(0), at(EYE_U0 - gap / 2))
        p.drawLine(at(EYE_U0 + gap / 2), at(EYE_LENGTH))
        half = EYE_LEN / 2 * k
        p.setPen(pen(eye_ink, BODY_W))
        p.drawLine(at(EYE_U0 - half), at(EYE_U0 + half))

        p.end()

        if self.hasFocus():
            q = QPainter(self)
            q.setPen(QPen(QColor(tok.focus), 1.5, Qt.DotLine))
            q.drawRect(self.rect().adjusted(1, 1, -2, -2))
            q.end()
