"""
Holding Point, applied: the palette and the one application stylesheet.

:mod:`fakematlab.ui.theme` says *what* the colours and type are; this module
makes Qt wear them. :func:`apply` is called once at start-up, after which the
module re-applies itself whenever ``theme.notifier().changed`` fires (the
View ▸ Theme menu) or, while the mode is *System*, the operating system flips
between light and dark.

Three decisions worth knowing about:

* **Fusion underneath.** The native Windows style ignores half of what QSS
  says. Fusion draws everything itself, so the palette and the sheet render
  the same on every machine.
* **Palette and sheet both.** The sheet restyles what it names; the palette
  covers everything it does not (custom-painted widgets, pyqtgraph's
  chrome, the Disabled group). Neither is enough alone.
* **Fonts by polish hook.** QSS cannot reach a variable font's width axis, so
  "Archivo condensed, uppercase" cannot be written in a stylesheet. Instead a
  single application event filter watches for a widget being polished and
  hands buttons, tabs and table headers the right :class:`QFont`. It is
  one filter and no subclasses, so widgets built anywhere in the app — by
  code that has never heard of the theme — still come out right. (Dock titles
  get a small replacement title bar for the same reason: a font set on the
  dock itself would be inherited by everything inside it.)
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QStandardPaths, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabBar,
    QToolButton,
    QWidget,
)

from . import theme

_state: dict = {"app": None, "filter": None, "applying": False}


# ── colour helpers ──────────────────────────────────────────────

def mix(a: str, b: str, amount: float) -> str:
    """``a`` blended toward ``b`` by ``amount`` — how "45 % opacity" is made."""
    ca, cb = QColor(a), QColor(b)
    return QColor.fromRgbF(
        ca.redF() + (cb.redF() - ca.redF()) * amount,
        ca.greenF() + (cb.greenF() - ca.greenF()) * amount,
        ca.blueF() + (cb.blueF() - ca.blueF()) * amount,
    ).name()


def tooltip_colours(t: theme.Tokens) -> tuple[str, str, str]:
    """Background, text, border: an inverted plate on Day, a black one on Night."""
    if t.is_night:
        return t.plate, t.ink, t.rule
    return t.ink, t.ground, t.ink


# ── palette ─────────────────────────────────────────────────────

def build_palette(t: theme.Tokens) -> QPalette:
    p = QPalette()
    tip_bg, tip_fg, _ = tooltip_colours(t)
    roles = {
        QPalette.Window: t.ground,
        QPalette.WindowText: t.ink,
        QPalette.Base: t.surface,
        QPalette.AlternateBase: t.ground,
        QPalette.Text: t.ink,
        QPalette.Button: t.surface,
        QPalette.ButtonText: t.ink,
        QPalette.BrightText: t.on_hold,
        QPalette.ToolTipBase: tip_bg,
        QPalette.ToolTipText: tip_fg,
        QPalette.PlaceholderText: t.ink_muted,
        QPalette.Highlight: t.signal,
        QPalette.HighlightedText: t.on_signal,
        QPalette.Link: t.edge,
        QPalette.LinkVisited: t.edge,
        QPalette.Light: t.surface,
        QPalette.Midlight: t.rule,
        QPalette.Mid: t.ink_muted,
        QPalette.Dark: t.ink_muted,
        QPalette.Shadow: t.ink,
    }
    for role, colour in roles.items():
        for group in (QPalette.Active, QPalette.Inactive):
            p.setColor(group, role, QColor(colour))

    dim = {
        QPalette.WindowText: t.ink, QPalette.Text: t.ink,
        QPalette.ButtonText: t.ink, QPalette.PlaceholderText: t.ink_muted,
        QPalette.HighlightedText: t.on_signal,
    }
    for role, colour in dim.items():
        p.setColor(QPalette.Disabled, role, QColor(mix(t.ground, colour, .45)))
    for role in (QPalette.Window, QPalette.Base, QPalette.Button,
                 QPalette.AlternateBase, QPalette.ToolTipBase):
        p.setColor(QPalette.Disabled, role, p.color(QPalette.Active, role))
    p.setColor(QPalette.Disabled, QPalette.Highlight,
               QColor(mix(t.ground, t.signal, .45)))
    for role in (QPalette.ToolTipText, QPalette.BrightText, QPalette.Link,
                 QPalette.LinkVisited, QPalette.Light, QPalette.Midlight,
                 QPalette.Mid, QPalette.Dark, QPalette.Shadow):
        p.setColor(QPalette.Disabled, role, p.color(QPalette.Active, role))
    return p


# ── little pictures the stylesheet needs ────────────────────────
#
# QSS draws arrows and ticks from image files, so they are drawn once per
# theme into the cache directory and referred to by URL. Written with an @2x
# twin, which Qt picks on its own on a high-DPI screen.

def _icon_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
    path = Path(base or Path.home() / ".fauxmatlab-cache") / "theme-icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _draw(name: str, colour: str, painter_fn, size: int = 10) -> str:
    folder = _icon_dir()
    for scale, suffix in ((1, ""), (2, "@2x")):
        img = QImage(size * scale, size * scale, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(scale, scale)
        pen = QPen(QColor(colour), 1.8)
        pen.setCapStyle(Qt.SquareCap)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        painter_fn(p, size)
        p.end()
        img.save(str(folder / f"{name}{suffix}.png"))
    return (folder / f"{name}.png").as_posix()


def _chevron(up: bool):
    def draw(p: QPainter, s: int) -> None:
        a, b = (6.5, 3.5) if up else (3.5, 6.5)
        p.drawPolyline([_pt(1.5, a), _pt(s / 2, b), _pt(s - 1.5, a)])
    return draw


def _tick(p: QPainter, s: int) -> None:
    p.drawPolyline([_pt(1.5, s * .5), _pt(s * .4, s - 2.5), _pt(s - 1.5, 2)])


def _pt(x: float, y: float):
    return QPointF(x, y)


def _dot(colour: str):
    def draw(p: QPainter, s: int) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(colour))
        p.drawEllipse(QPointF(s / 2, s / 2), 2.5, 2.5)
    return draw


def _icons(t: theme.Tokens) -> dict[str, str]:
    """Draw this theme's pictures; returns name -> file URL path."""
    out = {
        "down": _draw(f"{t.name}-down", t.ink, _chevron(False)),
        "up": _draw(f"{t.name}-up", t.ink, _chevron(True)),
        "tick": _draw(f"{t.name}-tick", t.on_signal, _tick, 12),
        "tick_ink": _draw(f"{t.name}-tick-ink", t.ink, _tick, 12),
        "tick_plate": _draw(f"{t.name}-tick-plate", t.on_plate, _tick, 12),
    }

    out["dot"] = _draw(f"{t.name}-dot", t.on_signal, _dot(t.on_signal), 12)
    return out


# ── the stylesheet ──────────────────────────────────────────────

def build_stylesheet(t: theme.Tokens) -> str:
    ic = _icons(t)
    muted = mix(t.ground, t.ink, .45)          # a disabled legend
    muted_line = mix(t.ground, t.ink_muted, .45)
    tip_bg, tip_fg, tip_edge = tooltip_colours(t)
    sig = theme.SPACE_1

    qss = f"""
/* ── ground ─────────────────────────────────────────────── */
QMainWindow, QDialog, QMessageBox {{ background: {t.ground}; }}
QMainWindow::separator {{ background: {t.rule}; width: 3px; height: 3px; }}
QMainWindow::separator:hover {{ background: {t.ink_muted}; }}
QToolTip {{ background: {tip_bg}; color: {tip_fg}; border: 1px solid {tip_edge};
           padding: 3px 6px; }}
QLabel {{ background: transparent; }}
QWidget:disabled {{ color: {muted}; }}

/* ── panels ─────────────────────────────────────────────── */
QFrame[hp="panel"] {{ background: {t.surface}; border: 2px solid {t.ink};
                     border-radius: 0; }}
QFrame[hp="headrule"] {{ background: {t.ink}; border: none; }}
QFrame[hp="plain"] {{ background: {t.surface}; border: 1px solid {t.rule}; }}
QFrame[hp="rule"] {{ background: {t.rule}; border: none; min-width: 1px;
                    max-width: 1px; }}
QFrame[hp="banner"] {{ background: {t.surface}; border: 2px solid {t.hold};
                      border-left: 8px solid {t.hold}; }}
QFrame[hp="banner"] QLabel {{ color: {t.hold_ink}; }}
QGroupBox {{ border: 1px solid {t.rule}; border-radius: 0; margin-top: 14px;
            padding-top: 6px; background: transparent; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
                   left: 8px; padding: 0 4px; color: {t.ink_muted}; }}

/* ── buttons: ghost by default ──────────────────────────── */
QPushButton, QToolButton {{
    background: transparent; color: {t.ink};
    border: 2px solid {t.ink_muted}; border-radius: {theme.RADIUS_PLATE}px;
    padding: 3px 12px; min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {t.ink}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.rule}; }}
QPushButton:focus {{ border-color: {t.edge}; }}
QPushButton:flat {{ border: 2px solid transparent; }}
QPushButton:flat:hover {{ border-color: {t.ink_muted}; }}
QPushButton:checked, QToolButton:checked {{
    background: {t.plate}; color: {t.on_plate}; border-color: {t.on_plate};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {muted}; border-color: {muted_line}; background: transparent;
}}
QPushButton[role="primary"] {{
    background: {t.plate}; color: {t.on_plate}; border-color: {t.on_plate};
}}
QPushButton[role="primary"]:hover {{ background: {mix(t.plate, t.on_plate, .14)}; }}
QPushButton[role="primary"]:pressed {{ background: {mix(t.plate, t.on_plate, .26)}; }}
QPushButton[role="secondary"] {{
    background: {t.signal}; color: {t.on_signal}; border-color: {t.signal};
}}
QPushButton[role="secondary"]:hover {{ border-color: {t.on_signal}; }}
QPushButton[role="secondary"]:pressed {{ background: {mix(t.signal, t.on_signal, .15)}; }}
QPushButton[role="danger"] {{
    background: {t.hold}; color: {t.on_hold}; border-color: {t.hold};
}}
QPushButton[role="danger"]:hover {{ border-color: {t.ink}; }}
QPushButton[role="primary"]:disabled, QPushButton[role="secondary"]:disabled,
QPushButton[role="danger"]:disabled {{
    background: transparent; color: {muted}; border-color: {muted_line};
}}
QToolButton {{ padding: 6px 8px; border-color: transparent; }}
QToolButton:hover {{ border-color: {t.ink_muted}; }}
QToolButton:checked {{ border-color: {t.on_plate}; }}
QToolButton::menu-indicator {{ image: none; }}

/* ── tabs: the sign array ───────────────────────────────── */
QTabWidget::pane {{ border: none; border-top: 2px solid {t.frame};
                   background: transparent; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: {t.surface}; color: {t.ink};
    border: 2px solid {t.frame}; border-radius: 0; margin-right: -2px;
    padding: 5px 16px; min-height: 18px;
}}
QTabBar::tab:hover {{ background: {t.ground}; }}
QTabBar::tab:selected {{
    background: {t.plate}; color: {t.on_plate}; border-color: {t.on_plate};
}}
QTabBar::tab:!selected {{ margin-top: 2px; }}
QTabBar::tab:disabled {{ color: {muted}; }}
QTabBar::close-button {{ subcontrol-position: right; }}
QTabBar QToolButton {{ border: 2px solid {t.frame}; background: {t.surface};
                      padding: 0; }}

/* ── menus and bars ─────────────────────────────────────── */
QMenuBar {{ background: {t.ground}; color: {t.ink};
           border-bottom: 1px solid {t.rule}; padding: 2px; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{
    background: {t.plate}; color: {t.on_plate}; }}
QMenu {{ background: {t.surface}; color: {t.ink};
        border: 2px solid {t.ink}; padding: 3px; }}
QMenu::item {{ padding: 5px 28px 5px 24px; background: transparent; }}
QMenu::item:selected {{ background: {t.plate}; color: {t.on_plate}; }}
QMenu::item:disabled {{ color: {muted}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {t.rule}; margin: 3px 6px; }}
QMenu::indicator {{ width: 12px; height: 12px; left: 6px; }}
QMenu::indicator:checked {{ image: url({ic["tick_ink"]}); }}
QMenu::indicator:checked:selected {{ image: url({ic["tick_plate"]}); }}
QToolBar {{ background: {t.surface}; border: none;
           border-bottom: 1px solid {t.rule}; spacing: {sig}px; padding: 2px; }}
QStatusBar {{ background: {t.ground}; color: {t.ink_muted};
             border-top: 1px solid {t.rule}; }}
QStatusBar::item {{ border: none; }}

/* ── docks ──────────────────────────────────────────────── */
QDockWidget {{ border: 1px solid {t.rule}; }}
QWidget#DockTitle {{ background: {t.surface}; border-bottom: 2px solid {t.frame}; }}
QWidget#DockTitle QLabel {{ color: {t.ink_muted}; }}
QWidget#DockTitle QToolButton {{ padding: 0; border: 2px solid transparent;
                                min-height: 0; font-weight: 700; }}

/* ── inputs ─────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit,
QTextBrowser {{
    background: {t.surface}; color: {t.ink};
    border: 2px solid {t.ink_muted}; border-radius: 0; padding: 2px 6px;
    selection-background-color: {t.signal}; selection-color: {t.on_signal};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus {{
    border-color: {t.edge};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    color: {muted}; border-color: {muted_line}; background: {t.ground};
}}
QLineEdit:read-only {{ background: {t.ground}; }}
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit, QComboBox QLineEdit {{
    border: none; background: transparent; padding: 0; }}
QTextEdit, QPlainTextEdit, QTextBrowser {{ padding: 4px; }}

QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
/* The spin buttons stay Fusion's own: styling them in QSS makes Qt shrink
   the frame by the buttons' width and strand them outside it. */

QComboBox {{ padding-right: 24px; min-height: 18px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
    width: 22px; border-left: 1px solid {t.ink_muted}; background: {t.ground}; }}
QComboBox::down-arrow {{ image: url({ic["down"]}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {t.surface}; color: {t.ink}; border: 2px solid {t.ink};
    selection-background-color: {t.signal}; selection-color: {t.on_signal};
    outline: none; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px; background: {t.surface};
    border: 2px solid {t.ink_muted}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {t.ink}; }}
QCheckBox::indicator:checked {{ background: {t.signal}; border-color: {t.ink_muted};
    image: url({ic["tick"]}); }}
QCheckBox::indicator:indeterminate {{ background: {t.rule}; }}
QRadioButton::indicator {{ border-radius: 9px; width: 14px; height: 14px; }}
QRadioButton::indicator:checked {{ background: {t.signal};
    image: url({ic["dot"]}); }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {muted_line}; background: {t.ground}; }}

QSlider::groove:horizontal {{ height: 4px; background: {t.rule};
    border: 1px solid {t.ink_muted}; margin: 0; }}
QSlider::sub-page:horizontal {{ background: {t.ink_muted}; }}
QSlider::handle:horizontal {{ background: {t.plate}; border: 2px solid {t.on_plate};
    width: 8px; margin: -8px 0; border-radius: 2px; }}
QSlider::groove:vertical {{ width: 4px; background: {t.rule};
    border: 1px solid {t.ink_muted}; }}
QSlider::add-page:vertical {{ background: {t.ink_muted}; }}
QSlider::handle:vertical {{ background: {t.plate}; border: 2px solid {t.on_plate};
    height: 8px; margin: 0 -8px; border-radius: 2px; }}
QSlider::handle:hover {{ border-color: {t.edge}; }}
QSlider::handle:disabled {{ background: {muted_line}; border-color: {muted_line}; }}

QProgressBar {{ background: {t.surface}; border: 2px solid {t.ink_muted};
    border-radius: 0; text-align: center; color: {t.ink}; min-height: 14px; }}
QProgressBar::chunk {{ background: {t.signal}; }}

/* ── scroll bars: slim and square ───────────────────────── */
QScrollBar:vertical {{ background: {t.ground}; width: 12px; margin: 0; border: none; }}
QScrollBar:horizontal {{ background: {t.ground}; height: 12px; margin: 0; border: none; }}
QScrollBar::handle {{ background: {t.ink_muted}; border: none; border-radius: 0;
    min-height: 28px; min-width: 28px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {t.ink}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none;
    background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── lists, tables, trees ───────────────────────────────── */
QTableView, QTreeView, QListView, QTableWidget, QTreeWidget, QListWidget {{
    background: {t.surface}; color: {t.ink}; border: 1px solid {t.rule};
    gridline-color: {t.rule}; border-radius: 0; outline: none;
    selection-background-color: {t.signal}; selection-color: {t.on_signal};
    alternate-background-color: {t.ground};
}}
QTableView::item, QTreeView::item, QListView::item {{ padding: 2px 4px;
    border: none; }}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background: {t.signal}; color: {t.on_signal}; }}
QTableView:disabled, QTreeView:disabled, QListView:disabled {{
    color: {muted}; }}
QHeaderView {{ background: {t.ground}; }}
QHeaderView::section {{ background: {t.ground}; color: {t.ink_muted};
    border: none; border-bottom: 2px solid {t.ink};
    border-right: 1px solid {t.rule}; padding: 4px 8px; }}
QHeaderView::section:vertical {{ border-bottom: 1px solid {t.rule};
    border-right: 2px solid {t.ink}; }}
QTableCornerButton::section {{ background: {t.ground}; border: none;
    border-bottom: 2px solid {t.ink}; }}

QSplitter::handle {{ background: {t.rule}; }}
QSplitter::handle:hover {{ background: {t.ink_muted}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QMessageBox QLabel {{ color: {t.ink}; }}
"""
    return qss


# ── fonts, by polish hook ───────────────────────────────────────

class _GlyphButton(QToolButton):
    """A title-bar button whose pictogram is drawn, not typed: no font needed."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self._kind = kind
        self.setAutoRaise(True)

    def paintEvent(self, event) -> None:      # noqa: N802 (Qt API)
        super().paintEvent(event)
        p = QPainter(self)
        pen = QPen(self.palette().color(QPalette.Mid if not self.underMouse()
                                        else QPalette.WindowText), 1.6)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        r = self.rect().adjusted(6, 6, -6, -6)
        if self._kind == "close":
            p.drawLine(r.topLeft(), r.bottomRight())
            p.drawLine(r.topRight(), r.bottomLeft())
        else:
            p.drawRect(r.adjusted(0, 2, -2, 0))
            p.drawLine(r.left() + 2, r.top(), r.right(), r.top())
            p.drawLine(r.right(), r.top(), r.right(), r.bottom() - 2)


class _DockTitle(QWidget):
    """A dock's title bar, in the label face: mono, uppercase, tracked."""

    def __init__(self, dock: QDockWidget) -> None:
        super().__init__(dock)
        self.setObjectName("DockTitle")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._dock = dock
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_2, theme.SPACE_1, theme.SPACE_1,
                               theme.SPACE_1)
        row.setSpacing(theme.SPACE_1)
        self._label = QLabel(dock.windowTitle())
        self._label.setFont(theme.label_font())
        row.addWidget(self._label, stretch=1)
        self._float = self._button("float", "Float / dock", dock_toggle=True)
        self._close = self._button("close", "Close", dock_toggle=False)
        row.addWidget(self._float)
        row.addWidget(self._close)
        dock.windowTitleChanged.connect(self._label.setText)
        dock.featuresChanged.connect(self._sync)
        self._sync()

    def _button(self, kind: str, tip: str, dock_toggle: bool) -> QToolButton:
        b = _GlyphButton(kind)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)
        b.setFixedSize(20, 20)
        if dock_toggle:
            b.clicked.connect(lambda: self._dock.setFloating(
                not self._dock.isFloating()))
        else:
            b.clicked.connect(self._dock.close)
        return b

    def _sync(self, *_ignored) -> None:
        f = self._dock.features()
        self._float.setVisible(bool(f & QDockWidget.DockWidgetFloatable))
        self._close.setVisible(bool(f & QDockWidget.DockWidgetClosable))


class _FontHook(QObject):
    """Give sign-legend widgets their face as they are polished."""

    def eventFilter(self, obj, event):          # noqa: N802 (Qt API)
        if event.type() != QEvent.Polish:
            return False
        if isinstance(obj, (QPushButton, QToolButton, QTabBar)):
            if not _in_dock_title(obj) and not obj.property("_hp_font"):
                obj.setProperty("_hp_font", True)
                obj.setFont(theme.sign_font(9))
        elif isinstance(obj, QHeaderView):
            if not obj.property("_hp_font"):
                obj.setProperty("_hp_font", True)
                obj.setFont(theme.label_font(7.5))
        elif isinstance(obj, QDockWidget):
            if obj.titleBarWidget() is None:
                obj.setTitleBarWidget(_DockTitle(obj))
        return False


def _in_dock_title(w: QWidget) -> bool:
    p = w.parentWidget()
    return p is not None and p.objectName() == "DockTitle"


# ── apply ───────────────────────────────────────────────────────

def _force_scheme(t: theme.Tokens) -> None:
    """Make Qt's own window chrome (the title bar) match the chosen mode."""
    app = QApplication.instance()
    try:
        hints = app.styleHints()
        if theme.mode() is theme.Mode.SYSTEM:
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(Qt.ColorScheme.Dark if t.is_night
                                 else Qt.ColorScheme.Light)
    except AttributeError:                       # Qt < 6.8
        pass


def release_scheme() -> None:
    """
    Hand colour-scheme detection back to the OS.

    :func:`theme.set_mode` resolves *System* by asking Qt whether the OS is
    dark; if the scheme is still pinned to the last explicit choice it would
    answer with that. Call this before ``set_mode(Mode.SYSTEM)``.
    """
    app = QApplication.instance()
    try:
        app.styleHints().unsetColorScheme()
    except AttributeError:                       # pragma: no cover
        pass


def choose(mode: theme.Mode, *, persist: bool = True) -> theme.Tokens:
    """Switch theme the safe way round (see :func:`release_scheme`)."""
    if mode is theme.Mode.SYSTEM:
        release_scheme()
    return theme.set_mode(mode, persist=persist)


def restyle(t: theme.Tokens | None = None) -> None:
    """Rebuild palette and stylesheet from the current tokens."""
    app = _state["app"]
    if app is None or _state["applying"]:
        return
    t = t or theme.tokens()
    _state["applying"] = True
    try:
        # Qt repolishes every live widget on setStyleSheet even when the
        # string is unchanged, so a no-op apply is not free. Skip it.
        palette = build_palette(t)
        if palette != app.palette():
            app.setPalette(palette)
        sheet = build_stylesheet(t)
        if sheet != app.styleSheet():
            app.setStyleSheet(sheet)
        _force_scheme(t)
    finally:
        _state["applying"] = False


def _on_os_scheme_changed(*_ignored) -> None:
    if _state["applying"] or theme.mode() is not theme.Mode.SYSTEM:
        return
    theme.set_mode(theme.Mode.SYSTEM, persist=False)


def apply(app: QApplication) -> None:
    """Install Holding Point on the application. Safe to call twice."""
    theme.load_fonts()
    if _state["app"] is app:
        restyle()
        return
    _state["app"] = app
    app.setStyle("Fusion")
    app.setFont(theme.ui_font())

    hook = _FontHook(app)
    app.installEventFilter(hook)
    _state["filter"] = hook

    theme.notifier().changed.connect(restyle)
    try:
        app.styleHints().colorSchemeChanged.connect(_on_os_scheme_changed)
    except AttributeError:                       # pragma: no cover
        pass
    restyle()
