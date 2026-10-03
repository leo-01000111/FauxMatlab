"""
Holding Point — the design system of leongorecki.eu, carried into the app.

The website's tokens (``design/holding-point/tokens.css`` in the site repo)
are the source of truth; this module is their Qt translation. Two themes:
**Day** is dry concrete, **Night** is asphalt. Each hue has exactly one job:

==============  ==========================================================
``ground``      the window; ``surface`` is a panel sitting on it
``ink``         all text; ``ink_muted`` also draws control borders
``rule``        hairlines between rows
``signal``      sign yellow — markings, selection, the highlighted series.
                Never text on the Day ground (1.3:1).
``plate``       location plate (black) with ``on_plate`` (yellow) legend —
                the primary button, the current tab
``hold``        mandatory red: stop / destructive / unstable. As text use
                ``hold_ink``.
``edge``        taxiway blue: links, the focus ring, reference lines.
                Nothing else is blue.
``lamp_go``     the green status lamp; always beside a word
==============  ==========================================================

Everything is rectangular (``RADIUS_PLATE`` = 2 px is the most a corner
gets), there are no gradients and no blur, and depth is a hard 4 px offset.

Widgets should not hard-code hex values. Ask :func:`tokens` for the current
theme and listen to :func:`notifier` ``.changed`` if the colour is baked into
something that does not repaint from the palette (a stylesheet string, a
pyqtgraph pen).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

# ── tokens ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tokens:
    name: str
    ground: str
    surface: str
    ink: str
    ink_muted: str
    rule: str
    signal: str
    on_signal: str
    plate: str
    on_plate: str
    hold: str
    on_hold: str
    hold_ink: str
    edge: str
    lamp_go: str
    lamp_caution: str
    shadow: str          # colour of the hard 4 px offset ("shadow-lift")
    frame: str           # the SignArray / tab-bar frame

    @property
    def is_night(self) -> bool:
        return self.name == "night"

    @property
    def focus(self) -> str:
        return self.edge


DAY = Tokens(
    name="day",
    ground="#e7e8e3", surface="#f5f5f2",
    ink="#121314", ink_muted="#4b4f55", rule="#c4c7bf",
    signal="#f5c518", on_signal="#121314",
    plate="#121314", on_plate="#f5c518",
    hold="#c1122e", on_hold="#ffffff", hold_ink="#b0102a",
    edge="#1f4fd1",
    lamp_go="#0d6e37", lamp_caution="#f5c518",
    shadow="#121314", frame="#121314",
)

NIGHT = Tokens(
    name="night",
    ground="#0e0f11", surface="#17191c",
    ink="#ecede7", ink_muted="#a2a6ac", rule="#2c2f34",
    signal="#f5c518", on_signal="#121314",
    plate="#000000", on_plate="#f5c518",
    hold="#c1122e", on_hold="#ffffff", hold_ink="#ff7a88",
    edge="#86a8ff",
    lamp_go="#45c97a", lamp_caution="#f5c518",
    shadow="#f5c518", frame="#2c2f34",
)

# ── spacing, shape ──────────────────────────────────────────────
#
# The 8:5 scale. Pick by jump, never by nudging: "inside" is SPACE_2–3,
# "between siblings" SPACE_5. A desktop app rarely needs past SPACE_6.

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 20
SPACE_5 = 32
SPACE_6 = 52

RADIUS_PLATE = 2
STROKE_HAIR = 1
STROKE_BOLD = 2
STROKE_SIGN = 3

# ── type ────────────────────────────────────────────────────────

SANS = "Archivo"          # everything with words
MONO = "Martian Mono"     # data only: labels, values, code

# Neither face has Greek (ω, ζ, τ — the whole vocabulary of this app), and
# Martian Mono lacks Δ and √ too. Name the fallbacks rather than trusting the
# platform's font merging, so a missing glyph lands in a face of the same
# kind: a monospace for data, a sans for words.
SANS_FALLBACKS = ("Segoe UI", "Helvetica Neue", "Arial")
MONO_FALLBACKS = ("Consolas", "Cascadia Mono", "Menlo", "DejaVu Sans Mono")


def _family(primary: str) -> QFont:
    f = QFont(primary)
    rest = MONO_FALLBACKS if primary == MONO else SANS_FALLBACKS
    f.setFamilies([primary, *rest])
    return f

STRETCH_DISPLAY = 118     # expanded: titles
STRETCH_SIGN = 82         # condensed + uppercase: sign legends, buttons, tabs

_FONT_DIR = Path(__file__).with_name("fonts")
_fonts_loaded = False


def load_fonts() -> bool:
    """Register the bundled typefaces. Safe to call more than once."""
    global _fonts_loaded
    if _fonts_loaded:
        return True
    ok = True
    for name in ("Archivo-Variable.ttf", "MartianMono-Variable.ttf"):
        if QFontDatabase.addApplicationFont(str(_FONT_DIR / name)) < 0:
            ok = False
    _fonts_loaded = ok
    return ok


def _axes(font: QFont, weight: int, stretch: int) -> QFont:
    """Set weight and width on the variable axes (and the classic API)."""
    font.setWeight(QFont.Weight(min(max(weight, 100), 900)))
    if hasattr(font, "setVariableAxis"):
        from PySide6.QtGui import QFont as _F
        font.setVariableAxis(_F.Tag("wght"), float(weight))
        font.setVariableAxis(_F.Tag("wdth"), float(stretch))
    else:  # pragma: no cover - Qt < 6.7
        font.setStretch(stretch)
    return font


def ui_font(point_size: float = 10, weight: int = 400) -> QFont:
    """Body text: Archivo at normal width."""
    f = _family(SANS)
    f.setPointSizeF(point_size)
    return _axes(f, weight, 100)


def title_font(point_size: float = 13, weight: int = 720) -> QFont:
    """A panel or window title: Archivo, heavy, expanded."""
    f = _family(SANS)
    f.setPointSizeF(point_size)
    f.setLetterSpacing(QFont.PercentageSpacing, 98)
    return _axes(f, weight, STRETCH_DISPLAY)


def sign_font(point_size: float = 10, weight: int = 760) -> QFont:
    """A sign legend: Archivo condensed, uppercase. Buttons and tabs."""
    f = _family(SANS)
    f.setPointSizeF(point_size)
    f.setCapitalization(QFont.AllUppercase)
    f.setLetterSpacing(QFont.PercentageSpacing, 103)
    return _axes(f, weight, STRETCH_SIGN)


def label_font(point_size: float = 8, weight: int = 600) -> QFont:
    """A key or kicker: Martian Mono, small, uppercase, tracked."""
    f = _family(MONO)
    f.setPointSizeF(point_size)
    f.setCapitalization(QFont.AllUppercase)
    f.setLetterSpacing(QFont.PercentageSpacing, 110)
    f.setStyleHint(QFont.Monospace)
    return _axes(f, weight, 100)


def data_font(point_size: float = 9.5, weight: int = 400) -> QFont:
    """A value, a metric, code: Martian Mono with tabular figures."""
    f = _family(MONO)
    f.setPointSizeF(point_size)
    f.setStyleHint(QFont.Monospace)
    return _axes(f, weight, 100)


# ── the current theme ───────────────────────────────────────────


class Mode(str, Enum):
    SYSTEM = "system"
    DAY = "day"
    NIGHT = "night"


class _Notifier(QObject):
    changed = Signal(object)   # the new Tokens


_notifier: _Notifier | None = None
_mode: Mode = Mode.SYSTEM
_current: Tokens = DAY

_SETTINGS_KEY = "appearance/theme"


def notifier() -> _Notifier:
    global _notifier
    if _notifier is None:
        _notifier = _Notifier()
    return _notifier


def tokens() -> Tokens:
    """The theme in force right now."""
    return _current


def mode() -> Mode:
    return _mode


def _system_is_dark() -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return False
    try:
        from PySide6.QtCore import Qt
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # pragma: no cover
        return False


def resolve(m: Mode) -> Tokens:
    if m is Mode.DAY:
        return DAY
    if m is Mode.NIGHT:
        return NIGHT
    return NIGHT if _system_is_dark() else DAY


def saved_mode() -> Mode:
    try:
        return Mode(QSettings().value(_SETTINGS_KEY, Mode.SYSTEM.value))
    except ValueError:
        return Mode.SYSTEM


def set_mode(m: Mode, *, persist: bool = True) -> Tokens:
    """
    Switch theme. Updates the current tokens and emits ``changed``; whoever
    owns the application stylesheet (``theme_qt.apply``) listens and repaints.
    """
    global _mode, _current
    _mode = Mode(m)
    if persist:
        QSettings().setValue(_SETTINGS_KEY, _mode.value)
    new = resolve(_mode)
    if new is not _current:
        _current = new
    notifier().changed.emit(_current)
    return _current


def plot_colour(role: str) -> str:
    """
    Colours for data, following the brand's plot rule: ``ink`` for data,
    ``signal`` for the highlighted series, ``edge`` for a reference line,
    ``hold`` for what must not be crossed (instability, poles).
    """
    t = _current
    return {
        "data": t.ink,
        "highlight": plot_line_highlight(),
        "reference": t.edge,
        "danger": t.hold_ink if t.is_night else t.hold,
        "ok": t.lamp_go,
        "muted": t.ink_muted,
        "grid": t.rule,
        "background": t.surface,
    }[role]


def plot_line_highlight() -> str:
    """
    ``signal`` for a *thin line* that stands out: plain sign yellow on Night,
    a darker amber on Day, where #f5c518 on the concrete ground is ~1.3:1.
    """
    return "#f5c518" if _current.is_night else "#b8900a"
