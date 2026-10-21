"""
The launch splash: Evans' name, its version, Cedric, and what is loading.

Evans takes a few seconds to start — numpy, scipy, sympy, python-control and
the Qt widgets all load before the window can be built — and until 0.9.5
nothing appeared in that time. This plate goes up as soon as the
``QApplication`` exists and the theme is applied, says what is happening
underneath, and steps aside when the window shows.

The loading happens on the GUI thread, so there is no event loop to animate
anything: each :meth:`Splash.step` repaints once. Cedric is drawn holding one
pose of his swim rather than frozen mid-blink.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from evans import __version__

from . import theme
from .cedric import VIEW, ink_for, paint_shape

WIDTH, HEIGHT = 640, 360
#: A moment of his swim with the body gently curled and the antennae up.
POSE = 1.9


class Splash(QSplashScreen):
    """A themed plate; :meth:`step` advances the bar and names the stage."""

    def __init__(self, steps: int) -> None:
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        pixmap = QPixmap(int(WIDTH * dpr), int(HEIGHT * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(QColor(theme.tokens().surface))
        super().__init__(pixmap, Qt.WindowStaysOnTopHint)
        self._steps = max(1, steps)
        self._done = 0
        self._text = "Starting"

    def step(self, text: str) -> None:
        """Name the stage now starting; the bar shows the ones before it."""
        self._text = text
        self.repaint()
        QApplication.processEvents()
        self._done = min(self._done + 1, self._steps)

    def drawContents(self, p: QPainter) -> None:
        tok = theme.tokens()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, WIDTH, HEIGHT)
        pad = theme.SPACE_5

        p.fillRect(r, QColor(tok.surface))
        # The signal band down the left edge, as on the rail's plates.
        p.fillRect(QRectF(0, 0, 10, HEIGHT), QColor(tok.signal))
        p.setPen(QPen(QColor(tok.frame), theme.STROKE_BOLD))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(1, 1, -1, -1))

        # Cedric, large, on the right, before the text so it reads over him.
        box = QRectF(WIDTH * 0.47, 40, WIDTH * 0.5, HEIGHT * 0.62)
        scale = min(box.width() / VIEW.width(), box.height() / VIEW.height())
        p.save()
        p.translate(box.center())
        p.rotate(-3)
        paint_shape(p, scale, POSE, ink_for(tok))
        p.restore()

        x = pad + 10
        p.setPen(QColor(tok.ink_muted))
        p.setFont(theme.label_font(8.5))
        p.drawText(QPointF(x, pad + 14), "Control-systems workbench")

        p.setPen(QColor(tok.ink))
        title = theme.title_font(46, 800)
        p.setFont(title)
        fm = p.fontMetrics()
        base = pad + 30 + fm.ascent()
        p.drawText(QPointF(x - 2, base), "Evans")

        p.setPen(QColor(tok.ink_muted))
        p.setFont(theme.data_font(10))
        p.drawText(QPointF(x, base + 30), f"version {__version__}")

        # The status line and its bar, along the foot of the plate.
        bar_y = HEIGHT - pad - 4
        bar = QRectF(x, bar_y, WIDTH - x - pad, 4)
        p.fillRect(bar, QColor(tok.rule))
        frac = self._done / self._steps
        p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * frac,
                          bar.height()), QColor(tok.edge))

        p.setFont(theme.data_font(9))
        p.setPen(QColor(tok.ink))
        p.drawText(QPointF(x, bar_y - 10), f"{self._text}…")
        p.setPen(QColor(tok.ink_muted))
        p.drawText(QRectF(x, bar_y - 26, bar.width(), 20),
                   Qt.AlignRight | Qt.AlignVCenter, "leongorecki.eu/evans")
