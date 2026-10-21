"""
The title bar: the menus, the title and the window buttons in one strip.

::

  ┌──────────────────────────────────────────────────────────────────┐
  │ ▣ File Export View Apps Presets Help   Evans — …   ─ □ ✕ │
  └──────────────────────────────────────────────────────────────────┘

It is the main window's menu widget, so it sits where the menu bar did, and
it is always there. With the integrated title bar on (Windows only, see
:mod:`winframe`) the native caption is gone and this strip shows the plate,
the title and the three buttons in its place. With it off, those are hidden
and what is left is the ordinary menu bar under the ordinary caption — the
fallback for macOS, Linux and anything that fails on Windows.

The buttons' glyphs are ``window-*.svg`` from the icon set, drawn in the
theme's ink; close turns Holding Point's mandatory red on hover, like the
stop it is.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QSizePolicy,
    QWidget,
)

from . import iconset, theme

#: Height of the strip and size of each button, in logical px: the
#: Windows 11 caption metrics, so the buttons land where hands expect them.
BAR_HEIGHT = 32
BUTTON_SIZE = QSize(46, BAR_HEIGHT)
GLYPH_PX = 20


def draws_own_top_border() -> bool:
    """
    Whether the bar has to draw the window's 1-pixel top border itself.

    With the caption taken away, Windows 11 still draws the frame's top line;
    Windows 10 does not, so there the window's top edge would vanish into
    whatever is behind it.
    """
    return sys.platform == "win32" and sys.getwindowsversion().build < 22000


def _mix(a: str, b: str, amount: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * amount),
        round(ca.green() + (cb.green() - ca.green()) * amount),
        round(ca.blue() + (cb.blue() - ca.blue()) * amount),
    )


class CaptionButton(QAbstractButton):
    """
    Minimise, maximise/restore or close.

    Hover comes from Qt for minimise and close. Maximise answers
    ``HTMAXBUTTON`` on Windows (for Snap Layouts), so it gets non-client
    messages instead and :class:`winframe.NativeFrame` reports hover and
    press through :meth:`set_native_hover` and :meth:`set_native_down`.
    """

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._glyph = f"window-{kind}"
        self._native_hover = False
        self._native_down = False
        self.setFixedSize(BUTTON_SIZE)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAccessibleName({"minimize": "Minimise", "maximize": "Maximise",
                                "close": "Close"}[kind])

    def set_glyph(self, name: str) -> None:
        if name != self._glyph:
            self._glyph = name
            self.update()

    @property
    def glyph(self) -> str:
        return self._glyph

    def set_native_hover(self, on: bool) -> None:
        if on != self._native_hover:
            self._native_hover = on
            self.update()

    def set_native_down(self, on: bool) -> None:
        if on != self._native_down:
            self._native_down = on
            self.update()

    def sizeHint(self) -> QSize:            # noqa: N802 (Qt API)
        return BUTTON_SIZE

    def paintEvent(self, event) -> None:      # noqa: N802 (Qt API)
        t = theme.tokens()
        hover = self.underMouse() or self._native_hover
        down = self.isDown() or self._native_down
        active = self.window().isActiveWindow()
        ink = t.ink if active else _mix(t.ground, t.ink, .5).name()
        p = QPainter(self)
        if self.kind == "close" and (hover or down):
            p.fillRect(self.rect(), _mix(t.hold, "#000000", .2) if down
                       else QColor(t.hold))
            ink = t.on_hold
        elif down:
            p.fillRect(self.rect(), _mix(t.ground, t.ink, .22))
        elif hover:
            p.fillRect(self.rect(), _mix(t.ground, t.ink, .1))
        dpr = self.devicePixelRatioF()
        glyph = iconset.pixmap(self._glyph, GLYPH_PX, ink, dpr)
        x = (self.width() - GLYPH_PX) // 2
        y = (self.height() - GLYPH_PX) // 2
        p.drawPixmap(x, y, glyph)
        p.end()


class TitleBar(QWidget):
    """
    The strip at the top of the main window. ``menu_bar`` is the window's
    menu bar; the window reaches it through ``MainWindow.menuBar()``.
    """

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._window = window
        self._chrome = True

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_2, 0, 0, 0)
        row.setSpacing(theme.SPACE_1)

        self.plate = QLabel()
        self.plate.setObjectName("TitleBarPlate")
        self.plate.setFixedSize(16, 16)
        self.plate.setPixmap(iconset.app_icon().pixmap(16, 16))
        row.addWidget(self.plate, alignment=Qt.AlignVCenter)

        self.menu_bar = QMenuBar(self)
        self.menu_bar.setObjectName("TitleBarMenus")
        self.menu_bar.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        row.addWidget(self.menu_bar, alignment=Qt.AlignVCenter)

        self.title = QLabel(window.windowTitle())
        self.title.setObjectName("TitleBarTitle")
        # It gives way to everything else: never what sets the window's
        # minimum width.
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title.setMinimumWidth(0)
        self.title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(self.title, stretch=1)
        # Takes the space only when the title is hidden, so the menus stay
        # on the left in a plain menu bar.
        row.addStretch(0)
        window.windowTitleChanged.connect(self.title.setText)

        self.minimize_button = CaptionButton("minimize", self)
        self.minimize_button.setToolTip("Minimise")
        self.maximize_button = CaptionButton("maximize", self)
        self.close_button = CaptionButton("close", self)
        self.close_button.setToolTip("Close")
        row.setSpacing(0)
        for button in (self.minimize_button, self.maximize_button,
                       self.close_button):
            row.addWidget(button, alignment=Qt.AlignTop)
        self.minimize_button.clicked.connect(self.minimize_requested)
        self.maximize_button.clicked.connect(self.maximize_requested)
        self.close_button.clicked.connect(self.close_requested)

        window.installEventFilter(self)
        iconset.on_theme_change(self, lambda live: live._repaint_buttons())
        self.sync_window_state()

    # ── chrome ──

    @property
    def chrome_visible(self) -> bool:
        return self._chrome

    def set_chrome_visible(self, on: bool) -> None:
        """
        On: plate, title and buttons, a full title bar. Off: a menu bar.

        Off on macOS, where the menu bar is the system's own, there is
        nothing left to show, so the strip goes too.
        """
        self._chrome = on
        for widget in (self.plate, self.title, self.minimize_button,
                       self.maximize_button, self.close_button):
            widget.setVisible(on)
        self.setProperty("integrated", on)
        self.style().unpolish(self)
        self.style().polish(self)
        if on:
            self.setFixedHeight(BAR_HEIGHT)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
        self.setVisible(on or not self.menu_bar.isNativeMenuBar())

    def paintEvent(self, event) -> None:      # noqa: N802 (Qt API)
        super().paintEvent(event)
        if not (self._chrome and draws_own_top_border()
                and not self._window.isMaximized()):
            return
        t = theme.tokens()
        p = QPainter(self)
        colour = (QColor(t.edge) if self._window.isActiveWindow()
                  else _mix(t.ground, t.ink, .25))
        p.fillRect(QRect(0, 0, self.width(), 1), colour)
        p.end()

    def sync_window_state(self) -> None:
        """Maximise becomes restore, and back, with the window."""
        maximized = self._window.isMaximized()
        self.maximize_button.set_glyph(
            "window-restore" if maximized else "window-maximize")
        self.maximize_button.setToolTip("Restore down" if maximized
                                        else "Maximise")
        self.maximize_button.setAccessibleName(
            "Restore" if maximized else "Maximise")

    def _repaint_buttons(self) -> None:
        for button in (self.minimize_button, self.maximize_button,
                       self.close_button):
            button.update()

    def eventFilter(self, obj, event) -> bool:     # noqa: N802 (Qt API)
        if obj is self._window:
            kind = event.type()
            if kind == QEvent.WindowStateChange:
                self.sync_window_state()
                self.update()               # the top border comes and goes
            elif kind in (QEvent.ActivationChange, QEvent.WindowActivate,
                          QEvent.WindowDeactivate):
                self.setProperty("active", self._window.isActiveWindow())
                self.style().unpolish(self.title)
                self.style().polish(self.title)
                self._repaint_buttons()
        return False

    # ── what is under a point ──

    def region_at(self, window: QWidget, point: QPoint) -> str:
        """
        ``"maximize"``, ``"caption"`` or ``"client"`` for a point in the
        window's logical coordinates.

        Caption is the strip's empty space, the plate and the title — the
        places a drag should move the window. The menus and the other two
        buttons are client: Qt handles them like any other widget.
        """
        if not self._chrome or not self.isVisible():
            return "client"
        local = self.mapFrom(window, point)
        if not self.rect().contains(local):
            return "client"
        if self._contains(self.maximize_button, local):
            return "maximize"
        if (self._contains(self.minimize_button, local) or
                self._contains(self.close_button, local)):
            return "client"
        if self._contains(self.menu_bar, local):
            inner = self.menu_bar.mapFrom(self, local)
            return "client" if self.menu_bar.actionAt(inner) else "caption"
        return "caption"

    @staticmethod
    def _contains(widget: QWidget, local: QPoint) -> bool:
        return widget.isVisible() and QRect(widget.geometry()).contains(local)

    # ── double-click ──

    def mouseDoubleClickEvent(self, event) -> None:   # noqa: N802 (Qt API)
        """
        Where Windows has the caption (``HTCAPTION``) it handles the
        double-click itself and this never runs; it is here for the strip
        when Qt does see the click.
        """
        if (self._chrome and event.button() == Qt.LeftButton and
                self.region_at(self._window,
                               self.mapTo(self._window,
                                          event.position().toPoint()))
                == "caption"):
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
