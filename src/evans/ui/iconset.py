"""
The bundled icon set — Holding Point pictograms, drawn like the markings.

Every icon is a 24 px SVG in ``ui/icons/`` drawn in ``currentColor``: a 2 px
stroke with square caps and mitred joins, nothing rounder than a pole's zero,
no gradients. Solid marks are the stroke colour too. So one file serves both
themes; :func:`icon` substitutes the colour of a theme token when it renders.

Use it like any other ``QIcon``::

    action.setIcon(iconset.icon("run"))
    button.setIcon(iconset.icon("workspace-analyse"))   # checked → on_plate

The returned icon carries four states, so a checkable rail button or tool
button looks right without per-widget styling:

=================  ==============================================
Normal             ``ink``
Disabled           ``ink`` mixed 45 % into the ground (as QSS does)
Selected / On      ``on_plate`` — yellow legend on the black plate
Active (hover)     ``ink``
=================  ==============================================

Icons are cached per theme and the cache empties on
:func:`theme.notifier` ``.changed``; widgets that hold an icon should re-ask
for it on that signal, as they already do for baked stylesheet colours.

``app.svg`` is the application icon — a location plate, black with a yellow
border and legend, the legend being a step response. ``app-16.svg`` is its
small-size cut without the border, which would turn to mush at 16 px.
"""

from __future__ import annotations

import weakref
from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

ICON_DIR = Path(__file__).with_name("icons")

#: The sizes drawn into each icon (at 1× and 2×), covering toolbars (16),
#: the rail and pane menus (24) and anything larger.
SIZES = (16, 20, 24, 32, 48)


def names() -> list[str]:
    """Every icon in the set, without the application icon."""
    return sorted(p.stem for p in ICON_DIR.glob("*.svg")
                  if not p.stem.startswith("app"))


def svg(name: str) -> str:
    """The raw SVG source of one icon."""
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        raise KeyError(f"no icon called {name!r}; see iconset.names()")
    return path.read_text(encoding="utf-8")


def _mix(a: str, b: str, amount: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * amount),
        round(ca.green() + (cb.green() - ca.green()) * amount),
        round(ca.blue() + (cb.blue() - ca.blue()) * amount),
    ).name()


def pixmap(name: str, size: int, colour: str, dpr: float = 1.0) -> QPixmap:
    """One icon drawn in one colour at one size."""
    source = svg(name).replace("currentColor", colour)
    renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
    px = QPixmap(round(size * dpr), round(size * dpr))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


@cache
def _cached(name: str, theme_name: str, role: str) -> QIcon:
    t = theme.tokens()
    normal = getattr(t, role)
    disabled = _mix(t.ground, normal, .45)
    on = t.on_plate
    out = QIcon()
    for size in SIZES:
        for dpr in (1.0, 2.0):
            out.addPixmap(pixmap(name, size, normal, dpr), QIcon.Normal, QIcon.Off)
            out.addPixmap(pixmap(name, size, normal, dpr), QIcon.Active, QIcon.Off)
            out.addPixmap(pixmap(name, size, disabled, dpr), QIcon.Disabled, QIcon.Off)
            out.addPixmap(pixmap(name, size, disabled, dpr), QIcon.Disabled, QIcon.On)
            out.addPixmap(pixmap(name, size, on, dpr), QIcon.Normal, QIcon.On)
            out.addPixmap(pixmap(name, size, on, dpr), QIcon.Active, QIcon.On)
            out.addPixmap(pixmap(name, size, on, dpr), QIcon.Selected, QIcon.Off)
    return out


def icon(name: str, role: str = "ink") -> QIcon:
    """
    A themed icon. ``role`` is a token name — ``ink`` for nearly everything,
    ``hold_ink`` for a destructive action, ``edge`` for a link-like one.
    """
    _ensure_listening()
    return _cached(name, theme.tokens().name, role)


def app_icon() -> QIcon:
    """The application icon, at every size a window manager asks for."""
    out = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        name = "app-16" if size <= 20 else "app"
        # The plate's own colours are fixed: it is a sign, not a theme.
        out.addPixmap(pixmap(name, size, "#000000"))
    return out


_listening = False


def _ensure_listening() -> None:
    global _listening
    if not _listening:
        theme.notifier().changed.connect(lambda *_: _cached.cache_clear())
        _listening = True


def bind(target, name: str, role: str = "ink") -> None:
    """
    Give a widget or action its icon, and give it again whenever the theme
    changes — the icon is baked in the theme's colours, so one set once
    would stay Day-coloured on a Night ground.
    """
    target.setIcon(icon(name, role))
    # Weakly held, and disconnected when the target goes. A closure over the
    # target itself, on this application-wide signal, kept every window that
    # ever bound an icon alive: the test suite grew to 3 GB and four times
    # slower before that was noticed.
    ref = weakref.ref(target)
    signal = theme.notifier().changed

    def refresh(*_):
        live = ref()
        if live is None:
            return
        try:
            live.setIcon(icon(name, role))
        except RuntimeError:            # the C++ side is gone already
            pass

    # Connected after the cache-clearing slot, so it reads the new colours.
    signal.connect(refresh)
    target.destroyed.connect(lambda *_: _disconnect(signal, refresh))


def on_theme_change(owner, method) -> None:
    """
    Call ``method(owner)`` after each theme change, for as long as ``owner``
    lives — without the signal keeping ``owner`` alive.
    """
    ref = weakref.ref(owner)
    signal = theme.notifier().changed

    def call(*_):
        live = ref()
        if live is not None:
            method(live)

    signal.connect(call)
    owner.destroyed.connect(lambda *_: _disconnect(signal, call))


def _disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):   # already gone at shutdown
        pass


def size(px: int = 16) -> QSize:
    """A ``QSize`` for ``setIconSize`` — 16 in toolbars, 24 on the rail."""
    return QSize(px, px)
