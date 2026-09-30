"""
Pyqtgraph helpers: consistent plot widgets for all analysis tabs.
=================================================================
All plots use a shared theme (dark or light) and expose helpers for
common annotation patterns: vertical/horizontal lines, markers,
shaded bands, arrow annotations with text labels.

Frequency axes — read this before touching a Bode plot
-------------------------------------------------------
pyqtgraph's log mode is a trap, and v1 fell into it on all 18 call sites:

* **Curve data** passed to ``PlotItem.plot`` must be in **linear** ω.
  pyqtgraph takes ``log10`` internally.  Passing ``np.log10(omega)`` makes it
  take the log *twice*, so every ω < 1 becomes ``log10`` of a negative number
  → ``NaN`` → silently dropped.  That is why the whole low-frequency half of
  v1's Bode plots did not exist.
* **Annotation positions** (``InfiniteLine``, ``TextItem``, scatter markers)
  are in *view* coordinates, which for a log axis means ``log10(ω)``.

So the two need opposite treatment, which is exactly the kind of rule nobody
remembers.  Use the ``freq_*`` helpers below — they take **raw ω** every time
and convert internally where needed.  Don't call ``plot()`` on a log axis
directly.

Tick labels — multiples of what you read, not of what is convenient
--------------------------------------------------------------------
pyqtgraph's default ticks land on 50, 100, 150 — meaningless for a phase axis,
where the values that matter are 0, ±90, ±180, ±270. :class:`PhaseAxis` and
:class:`DbAxis` recompute their ticks from the *visible* span on every paint,
so they keep working while the user pans and zooms. Ask for them with
``make_plot(x_unit="phase", y_unit="db")`` / ``make_freq_plot(y_unit=...)``.

Hover readouts
--------------
:func:`install_hover_readout` gives a plot a cursor readout: nearest point of
any registered curve, in **screen pixels** (so a log axis, or a flat plateau on
a steep axis, behaves the way the eye reads it). The lookup itself lives in
:class:`HoverModel`, which knows nothing about Qt, and is what the tests call.
The model takes **raw** data — raw ω for a log axis, converted internally — so
it obeys the same contract as the ``freq_*`` helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from pyqtgraph import InfiniteLine, PlotItem, PlotWidget, mkBrush, mkPen
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

# ──────────────────────────────────────────────────────────────
#  Theme
# ──────────────────────────────────────────────────────────────

def _is_dark() -> bool:
    pal = QApplication.palette()
    return pal.window().color().lightness() < 128


def set_title(plot: PlotItem, title: str, **kwargs) -> None:
    """
    Set a plot title without letting it drive the layout.

    A pyqtgraph title is a ``LabelItem`` in the ``PlotItem``'s grid layout, and
    a ``LabelItem``'s *minimum* width is the width of its text. So a title long
    enough to outgrow the panel silently lays the whole ``PlotItem`` out wider
    than the scene it sits in, and the curves end up off the right-hand edge:
    measured here, a 63-character title stretched a 434-pixel panel to 1080,
    leaving a plot that looked blank while reporting nothing wrong.

    Capping the label's maximum width lets the view box drive the layout
    instead. Titles should still be *short* — a sentence belongs in a readout,
    not on an axis — but a long one can now only be clipped, which is a
    symptom you can see, rather than a panel you cannot.
    """
    plot.setTitle(title, **kwargs)
    label = getattr(plot, "titleLabel", None)
    if label is not None:
        label.setMaximumWidth(1)


def apply_theme(plot: PlotItem, title: str = "",
                xlabel: str = "", ylabel: str = "") -> None:
    """Apply consistent colours, grid, labels to a PlotItem."""
    dark = _is_dark()
    bg   = "#1A1A2E" if dark else "#FAFAFA"
    fg   = "#E8E8F0" if dark else "#111111"

    plot.getViewBox().setBackgroundColor(bg)
    label_style = {"color": fg, "font-size": "11pt"}

    if title:
        set_title(plot, title, color=fg, size="12pt")
    if xlabel:
        plot.setLabel("bottom", xlabel, **label_style)
    if ylabel:
        plot.setLabel("left",   ylabel, **label_style)

    plot.showGrid(x=True, y=True, alpha=0.3)
    plot.getAxis("left"  ).setPen(mkPen(fg))
    plot.getAxis("bottom").setPen(mkPen(fg))
    plot.getAxis("left"  ).setTextPen(mkPen(fg))
    plot.getAxis("bottom").setTextPen(mkPen(fg))


def make_plot(title: str = "", xlabel: str = "",
              ylabel: str = "", log_x: bool = False,
              x_unit: str | None = None,
              y_unit: str | None = None) -> PlotWidget:
    """
    Create a styled PlotWidget.

    For a frequency axis prefer :func:`make_freq_plot`, which also installs
    decade ticks and documents the raw-ω contract. ``x_unit`` / ``y_unit`` may
    be ``"phase"`` or ``"db"`` to get ticks at meaningful multiples.
    """
    axes = {}
    if x_unit in _UNIT_AXES:
        axes["bottom"] = _UNIT_AXES[x_unit](orientation="bottom")
    if y_unit in _UNIT_AXES:
        axes["left"] = _UNIT_AXES[y_unit](orientation="left")
    pw = PlotWidget(axisItems=axes) if axes else PlotWidget()
    pw.setBackground("transparent")
    pi = pw.getPlotItem()
    apply_theme(pi, title, xlabel, ylabel)
    if log_x:
        pi.setLogMode(x=True, y=False)
    return pw


# ──────────────────────────────────────────────────────────────
#  Frequency axis
# ──────────────────────────────────────────────────────────────

class LogFreqAxis(pg.AxisItem):
    """
    Log frequency axis with proper decade majors and 2…9 minors.

    pyqtgraph's stock log axis drops the minor ticks as soon as the span grows
    past a couple of decades, which leaves a Bode plot with nothing between
    10⁻² and 10⁻¹ — precisely where you read a corner frequency off.
    """

    #: Above this many decades the 2…9 minors become visual noise.
    MAX_DECADES_FOR_MINORS = 6

    def logTickValues(self, minVal, maxVal, size, stdTicks):
        decades = [float(v) for v in range(int(np.floor(minVal)),
                                           int(np.ceil(maxVal)) + 1)]
        ticks = [(1.0, decades)]
        if (maxVal - minVal) <= self.MAX_DECADES_FOR_MINORS:
            minors = [
                d + np.log10(m)
                for d in decades
                for m in range(2, 10)
                if minVal <= d + np.log10(m) <= maxVal
            ]
            if minors:
                ticks.append((None, minors))
        return ticks

    def logTickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            exp = int(round(v))
            if abs(v - exp) < 1e-9:                 # a decade
                out.append(f"10{_superscript(exp)}")
            else:                                   # a minor tick, unlabelled
                out.append("")
        return out


# ──────────────────────────────────────────────────────────────
#  Phase and dB axes
# ──────────────────────────────────────────────────────────────

def _ladder(base: list[float], value: float) -> float:
    """Smallest entry of ``base`` (extended upward by doubling) ≥ ``value``."""
    for step in base:
        if step >= value:
            return step
    step = base[-1]
    while step < value:
        step *= 2
    return step


def _nice(value: float) -> float:
    """Round up to 1, 2 or 5 × 10ⁿ — for spans too small for a fixed rule."""
    if value <= 0:
        return 1.0
    exp = np.floor(np.log10(value))
    for m in (1, 2, 5, 10):
        if m * 10 ** exp >= value * (1 - 1e-9):
            return float(m * 10 ** exp)
    return float(10 ** (exp + 1))


_PHASE_LADDER = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 45, 90, 180, 360, 720]
_DB_LADDER = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 40, 60, 100, 200]


def phase_tick_step(span: float, size: float = 600.0) -> float:
    """
    Major tick spacing for a phase axis showing ``span`` degrees.

    Multiples of 90° normally, 45° once the view is under ~270°, then 15° and
    finer as the user zooms in — and a coarser rung only when the ticks would
    crowd (``size`` is the axis length in pixels). Never 50, 100, 150.
    """
    span = abs(span)
    if span >= 270:
        step = 90.0
    elif span >= 90:
        step = 45.0
    elif span >= 45:
        step = 15.0
    else:
        step = _nice(span / 6.0)
    limit = max(4.0, size / 40.0)
    while span / step > limit:
        step = _ladder(_PHASE_LADDER, step * 1.0001 + 1e-9)
    return step


def db_tick_step(span: float, size: float = 600.0) -> float:
    """Major tick spacing for a dB axis: multiples of 20, 10 for small spans."""
    span = abs(span)
    if span >= 60:
        step = 20.0
    elif span >= 30:
        step = 10.0
    elif span >= 15:
        step = 5.0
    else:
        step = _nice(span / 6.0)
    limit = max(4.0, size / 40.0)
    while span / step > limit:
        step = _ladder(_DB_LADDER, step * 1.0001 + 1e-9)
    return step


_MINOR = {0.5: 0.1, 1: 0.5, 2: 1, 5: 1, 10: 5, 15: 5, 20: 10, 30: 10,
          45: 15, 40: 20, 60: 20, 90: 30, 100: 20, 180: 90, 360: 90}


class _StepAxis(pg.AxisItem):
    """
    An axis whose major ticks come from a rule on the visible span.

    Overriding :meth:`tickSpacing` (rather than ``tickValues``) keeps
    pyqtgraph's own de-duplication and axis scaling; the rule is re-evaluated
    every time the view range changes, so zooming re-picks the step.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)      # a "×10³" on a degree axis is noise
        self._major = 0.0

    def major_step(self, span: float, size: float) -> float:
        raise NotImplementedError

    def tickSpacing(self, minVal, maxVal, size):
        span = abs(maxVal - minVal)
        if span <= 0 or not np.isfinite(span):
            return super().tickSpacing(minVal, maxVal, size)
        major = self.major_step(span, max(float(size), 1.0))
        self._major = major
        minor = _MINOR.get(major, major / 2.0)
        return [(major, 0), (minor, 0)]

    def tickStrings(self, values, scale, spacing):
        if self._major and spacing < self._major * 0.999:
            return [""] * len(values)          # minors are unlabelled
        return [f"{v * scale:g}" for v in values]


class PhaseAxis(_StepAxis):
    """Phase in degrees: labelled at 0, ±90, ±180, ±270 …"""

    def major_step(self, span, size):
        return phase_tick_step(span, size)


class DbAxis(_StepAxis):
    """Magnitude in dB: labelled at multiples of 20 (10 when zoomed in)."""

    def major_step(self, span, size):
        return db_tick_step(span, size)


_UNIT_AXES = {"phase": PhaseAxis, "db": DbAxis}


def _superscript(n: int) -> str:
    digits = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
              "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻"}
    return "".join(digits.get(ch, ch) for ch in str(n))


def make_freq_plot(title: str = "", ylabel: str = "",
                   xlabel: str = "ω (rad/s)",
                   y_unit: str | None = None) -> PlotWidget:
    """
    A Bode-style plot: logarithmic ω axis with decade ticks.

    Feed it through :func:`plot_freq` / :func:`freq_vline` / :func:`freq_marker`
    / :func:`freq_text`, all of which take **raw ω in rad/s**. ``y_unit`` is
    ``"phase"`` or ``"db"`` for ticks at multiples of 90° / 20 dB.
    """
    axes = {"bottom": LogFreqAxis(orientation="bottom")}
    if y_unit in _UNIT_AXES:
        axes["left"] = _UNIT_AXES[y_unit](orientation="left")
    pw = PlotWidget(axisItems=axes)
    pw.setBackground("transparent")
    pi = pw.getPlotItem()
    apply_theme(pi, title, xlabel, ylabel)
    pi.setLogMode(x=True, y=False)
    return pw


def to_freq_coord(omega):
    """Raw ω → the view coordinate of a log frequency axis."""
    return np.log10(np.maximum(np.asarray(omega, dtype=float), 1e-300))


def plot_freq(plot: PlotItem, omega, y, **kwargs):
    """
    Plot ``y`` against **raw ω** on a log frequency axis.

    Non-finite samples are dropped rather than breaking the curve — an
    unstable system's phase can legitimately contain them.
    """
    omega = np.asarray(omega, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(omega) & np.isfinite(y) & (omega > 0)
    return plot.plot(omega[ok], y[ok], **kwargs)


def freq_vline(plot: PlotItem, omega: float, color: str = "#FF6600",
               label: str = "", width: float = 1.5):
    """Vertical marker at a frequency, given in **raw ω**."""
    if omega is None or not np.isfinite(omega) or omega <= 0:
        return None
    return add_vline(plot, float(to_freq_coord(omega)),
                     color=color, label=label, width=width)


def freq_marker(plot: PlotItem, omega: float, y: float,
                symbol: str = "o", color: str = "#FF6600", size: int = 10):
    """Point marker at (**raw ω**, y)."""
    if not (np.isfinite(omega) and np.isfinite(y)) or omega <= 0:
        return None
    return add_marker(plot, float(to_freq_coord(omega)), float(y),
                      symbol=symbol, color=color, size=size)


def freq_text(plot: PlotItem, omega: float, y: float, text: str,
              color: str = "#FFAA00", anchor=(0, 1)):
    """Text annotation anchored at (**raw ω**, y)."""
    if not (np.isfinite(omega) and np.isfinite(y)) or omega <= 0:
        return None
    return add_text_annotation(plot, float(to_freq_coord(omega)), float(y),
                               text, color=color, anchor=anchor)


def freq_region(plot: PlotItem, omega_lo: float, omega_hi: float,
                color: str = "#F45B69", alpha: int = 30):
    """Shaded frequency band between two **raw ω** limits."""
    if not (np.isfinite(omega_lo) and np.isfinite(omega_hi)):
        return None
    brush = QColor(color)
    brush.setAlpha(alpha)
    region = pg.LinearRegionItem(
        values=[float(to_freq_coord(omega_lo)), float(to_freq_coord(omega_hi))],
        orientation="vertical", movable=False,
        brush=mkBrush(brush), pen=mkPen(color, width=0.5),
    )
    region.setZValue(-20)
    plot.addItem(region)
    return region


# ──────────────────────────────────────────────────────────────
#  Line styles
# ──────────────────────────────────────────────────────────────

COLORS = [
    "#4C9BE8",  # blue
    "#F45B69",  # red
    "#56C271",  # green
    "#F4A261",  # orange
    "#9B72CF",  # purple
    "#26BFBF",  # teal
    "#E9C46A",  # yellow
    "#FF6B9D",  # pink
]

STYLES = [Qt.SolidLine, Qt.DashLine, Qt.DotLine, Qt.DashDotLine]


def curve_pen(idx: int, width: float = 2.0) -> pg.mkPen:
    color = COLORS[idx % len(COLORS)]
    style = STYLES[(idx // len(COLORS)) % len(STYLES)]
    return mkPen(color=color, width=width, style=style)


# ──────────────────────────────────────────────────────────────
#  Annotation helpers
# ──────────────────────────────────────────────────────────────

def add_vline(plot: PlotItem, x: float, color: str = "#FF6600",
              label: str = "", width: float = 1.5) -> InfiniteLine:
    """Add a vertical dashed line annotation."""
    # Pass label through constructor — pyqtgraph 0.14 has no setLabel method.
    opts = {"position": 0.92, "color": color,
            "fill": mkBrush(QColor(color).darker(180))} if label else {}
    line = InfiniteLine(pos=x, angle=90, movable=False,
                        pen=mkPen(color=color, width=width, style=Qt.DashLine),
                        label=label or None,
                        labelOpts=opts or None)
    plot.addItem(line)
    return line


def add_hline(plot: PlotItem, y: float, color: str = "#FF6600",
              label: str = "", width: float = 1.5) -> InfiniteLine:
    """Add a horizontal dashed line annotation."""
    opts = {"position": 0.92, "color": color,
            "fill": mkBrush(QColor(color).darker(180))} if label else {}
    line = InfiniteLine(pos=y, angle=0, movable=False,
                        pen=mkPen(color=color, width=width, style=Qt.DashLine),
                        label=label or None,
                        labelOpts=opts or None)
    plot.addItem(line)
    return line


def add_marker(plot: PlotItem, x: float, y: float,
               symbol: str = "o", color: str = "#FF6600",
               size: int = 10) -> pg.ScatterPlotItem:
    """Place a single marker at (x, y)."""
    scatter = pg.ScatterPlotItem(
        x=[x], y=[y],
        symbol=symbol, size=size,
        pen=mkPen(color, width=1.5),
        brush=mkBrush(color),
    )
    plot.addItem(scatter)
    return scatter


def add_band(plot: PlotItem, y_center: float, half_width: float,
             color: str = "#44FF44", alpha: int = 40) -> pg.LinearRegionItem:
    """Add a horizontal shaded band (±half_width around y_center)."""
    brush_color = QColor(color)
    brush_color.setAlpha(alpha)
    region = pg.LinearRegionItem(
        values=[y_center - half_width, y_center + half_width],
        orientation="horizontal", movable=False,
        brush=mkBrush(brush_color),
        pen=mkPen(color, width=0.5),
    )
    plot.addItem(region)
    return region


def add_text_annotation(plot: PlotItem, x: float, y: float,
                         text: str, color: str = "#FFAA00",
                         anchor=(0, 1)) -> pg.TextItem:
    """Add a floating text annotation."""
    item = pg.TextItem(text=text, color=color, anchor=anchor)
    item.setPos(x, y)
    plot.addItem(item)
    return item


# ──────────────────────────────────────────────────────────────
#  Bode asymptotes
# ──────────────────────────────────────────────────────────────

def draw_asymptotes(plot: PlotItem, segments, colour: str, *,
                    hover: HoverReadout | None = None,
                    corners=()) -> None:
    """
    Draw classical asymptote ``segments`` (raw ω) on a log-frequency plot.

    Dashed, semi-transparent and *under* the exact curve, with a small square
    at each join between segments. With a ``hover`` readout, every segment is
    registered so the cursor reports its slope and end points, and each of
    ``corners`` (:class:`~fakematlab.core.asymptotes.AsymptoteBreak`) gets a
    corner-frequency label.
    """
    if not segments:
        return
    faint = QColor(colour)
    faint.setAlpha(150)
    pen = mkPen(faint, width=1.3, style=Qt.DashLine)
    xs, ys = [], []
    for seg in segments:
        xs += [seg.omega_start, seg.omega_end]
        ys += [seg.value_start, seg.value_end]
    item = plot_freq(plot, xs, ys, pen=pen)
    item.setZValue(-5)
    for seg in segments[1:]:
        freq_marker(plot, seg.omega_start, seg.value_start,
                    symbol="s", color=colour, size=6)
    if hover is None:
        return
    for seg in segments:
        hover.model.add_segment(seg.omega_start, seg.value_start,
                                seg.omega_end, seg.value_end,
                                seg.describe(), colour)
    for corner in corners:
        hover.model.add_mark(
            corner.omega, corner.mag_dB,
            (f"corner ω = {corner.omega:.4g} rad/s ({corner.description}): "
             f"{corner.slope_change:+.0f} dB/dec").replace("-", "−"),
            colour=colour)


# ──────────────────────────────────────────────────────────────
#  Pole-zero map helper
# ──────────────────────────────────────────────────────────────

def draw_pz_map(plot: PlotItem,
                poles: list[complex], zeros: list[complex],
                pole_color: str = "#F45B69",
                zero_color: str = "#4C9BE8",
                label_prefix: str = "") -> None:
    """Draw poles (×) and zeros (○) on a complex-plane plot."""
    # Imaginary axis
    add_vline(plot, 0.0, color="#666666", width=0.8)
    add_hline(plot, 0.0, color="#666666", width=0.8)

    if poles:
        pr = [p.real for p in poles]
        pi = [p.imag for p in poles]
        scatter_p = pg.ScatterPlotItem(
            x=pr, y=pi, symbol="x", size=14,
            pen=mkPen(pole_color, width=2.5),
            brush=mkBrush(None),
        )
        plot.addItem(scatter_p)

    if zeros:
        zr = [z.real for z in zeros]
        zi = [z.imag for z in zeros]
        scatter_z = pg.ScatterPlotItem(
            x=zr, y=zi, symbol="o", size=12,
            pen=mkPen(zero_color, width=2.0),
            brush=mkBrush(None),
        )
        plot.addItem(scatter_z)


# ──────────────────────────────────────────────────────────────
#  Hover readout
# ──────────────────────────────────────────────────────────────

def _num(v: float, digits: int = 4) -> str:
    """Compact number with a typographic minus, no trailing noise."""
    if abs(v) < 10 ** (-digits - 1):
        v = 0.0
    return f"{v:.{digits}g}".replace("-", "−")


def _cplx(re: float, im: float) -> str:
    """``−0.5 ± j1.3`` for a conjugate pair, ``−2`` for a real point."""
    if abs(im) < 1e-9 * max(1.0, abs(re)):
        return _num(re)
    return f"{_num(re)} ± j{_num(abs(im))}"


def format_curve_point(quantity: str, x: float, y: float,
                       param: float | None = None) -> str:
    """
    The readout text for one data point, worded for what the curve *is*.

    ``x``/``y`` are raw data values (ω in rad/s on Bode, never log₁₀).
    """
    if quantity == "bode_mag":
        return f"ω = {_num(x)} rad/s, |L| = {y:.2f} dB".replace("-", "−")
    if quantity == "bode_phase":
        return f"ω = {_num(x)} rad/s, phase = {y:.1f}°".replace("-", "−")
    if quantity == "time":
        return f"t = {_num(x)} s, y = {_num(y)}"
    if quantity == "nyquist":
        head = f"ω = {_num(param)} rad/s, " if param is not None else ""
        return f"{head}Re = {_num(x)}, Im = {_num(y)}"
    if quantity == "nichols":
        head = f"ω = {_num(param)} rad/s, " if param is not None else ""
        return f"{head}phase = {x:.1f}°, |L| = {y:.2f} dB".replace("-", "−")
    if quantity == "rlocus":
        head = f"K = {_num(param)}, " if param is not None else ""
        return f"{head}s = {_cplx(x, y)}"
    if quantity == "pole":
        return f"pole at {_cplx(x, y)}"
    if quantity == "zero":
        return f"zero at {_cplx(x, y)}"
    return f"x = {_num(x)}, y = {_num(y)}"


@dataclass
class HoverHit:
    """What the cursor is over: the text, and where to put the marker."""

    text: str
    x: float               # marker position, in *view* coordinates
    y: float
    kind: str              # "mark" | "curve" | "segment" | "line"
    colour: str | None = None


@dataclass
class _HoverCurve:
    vx: np.ndarray          # view coordinates (log10 ω on a log axis)
    vy: np.ndarray
    x: np.ndarray           # raw data
    y: np.ndarray
    param: np.ndarray | None
    quantity: str
    name: str
    colour: str | None
    connected: bool


@dataclass
class _HoverMark:
    vx: float
    vy: float
    text: str
    kind: str
    colour: str | None


@dataclass
class _HoverSegment:
    vx: np.ndarray          # the two end points, view coordinates
    vy: np.ndarray
    text: str
    colour: str | None


def _nearest_on_polyline(px: float, py: float, cx: np.ndarray,
                         cy: np.ndarray, connected: bool):
    """
    ``(distance, index, (qx, qy))`` of the point of a pixel-space polyline
    closest to ``(px, py)``. ``index`` is the nearer *sample* of the segment
    the closest point lies on — hover snaps to real data, not to interpolation.
    Segments with a non-finite end are skipped (a NaN gap breaks a curve).
    """
    n = len(cx)
    if n == 0:
        return np.inf, -1, (np.nan, np.nan)
    if n == 1 or not connected:
        with np.errstate(invalid="ignore"):
            d = np.hypot(cx - px, cy - py)
        d = np.where(np.isfinite(d), d, np.inf)
        i = int(np.argmin(d))
        return float(d[i]), i, (float(cx[i]), float(cy[i]))
    ax, ay, bx, by = cx[:-1], cy[:-1], cx[1:], cy[1:]
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(len2 > 0, ((px - ax) * dx + (py - ay) * dy) / len2, 0.0)
        t = np.clip(t, 0.0, 1.0)
        qx, qy = ax + t * dx, ay + t * dy
        d = np.hypot(px - qx, py - qy)
    d = np.where(np.isfinite(d), d, np.inf)
    i = int(np.argmin(d))
    idx = i + (1 if t[i] >= 0.5 else 0)
    return float(d[i]), idx, (float(qx[i]), float(qy[i]))


class HoverModel:
    """
    Everything a hover can land on, and the pixel-distance search over it.

    Qt-free on purpose: ``hit`` takes the cursor in view coordinates and the
    axis scales in pixels per view unit, so a test can stand in for the mouse.
    Everything added is **raw data** — ω in rad/s on a log-x plot — and is
    converted here, once, so the per-move work is a few vectorised numpy ops.
    """

    def __init__(self, log_x: bool = False) -> None:
        self.log_x = log_x
        self.curves: list[_HoverCurve] = []
        self.marks: list[_HoverMark] = []
        self.segments: list[_HoverSegment] = []

    def clear(self) -> None:
        self.curves.clear()
        self.marks.clear()
        self.segments.clear()

    def _view_x(self, x):
        x = np.asarray(x, dtype=float)
        if not self.log_x:
            return x
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(x > 0, np.log10(np.where(x > 0, x, 1.0)), np.nan)

    def add_curve(self, x, y, *, quantity: str = "xy", name: str = "",
                  param=None, colour: str | None = None,
                  connected: bool | None = None) -> None:
        x = np.atleast_1d(np.asarray(x, dtype=float))
        y = np.atleast_1d(np.asarray(y, dtype=float))
        if connected is None:
            connected = quantity not in ("pole", "zero")
        self.curves.append(_HoverCurve(
            self._view_x(x), y.copy(), x, y,
            None if param is None else np.atleast_1d(
                np.asarray(param, dtype=float)),
            quantity, name, colour, connected))

    def add_mark(self, x: float, y: float, text: str, *,
                 kind: str = "point", colour: str | None = None) -> None:
        vx = float(self._view_x(x))
        self.marks.append(_HoverMark(vx, float(y), text, kind, colour))

    def add_segment(self, x0: float, y0: float, x1: float, y1: float,
                    text: str, colour: str | None = None) -> None:
        vx = self._view_x([x0, x1])
        self.segments.append(_HoverSegment(vx, np.array([y0, y1], float),
                                           text, colour))

    # ── the lookup ──────────────────────────────────────────────

    def hit(self, vx: float, vy: float, sx: float, sy: float, *,
            mark_px: float = 12.0, curve_px: float = 14.0,
            segment_px: float = 5.0, line_px: float = 6.0) -> HoverHit | None:
        """
        What is under the cursor ``(vx, vy)`` (view coordinates), given
        ``sx``/``sy`` pixels per view unit, or ``None``.

        Priority: a point marker (its full label), then the nearest curve
        point, with any asymptote segment the cursor is also on appended as a
        second line, then a bare reference line such as ``y∞``. Distances are
        in *pixels*, so "nearest" is what the eye sees on a log axis.
        """
        best_mark, best_d = None, mark_px
        for m in self.marks:
            if m.kind != "point" or not np.isfinite(m.vx):
                continue
            d = np.hypot((m.vx - vx) * sx, (m.vy - vy) * sy)
            if d <= best_d:
                best_mark, best_d = m, d
        if best_mark is not None:
            return HoverHit(best_mark.text, best_mark.vx, best_mark.vy,
                            "mark", best_mark.colour)

        names = {c.name for c in self.curves if c.name}
        show_names = len(names) > 1
        hit: HoverHit | None = None
        best_d = curve_px
        for c in self.curves:
            d, i, _q = _nearest_on_polyline(vx * sx, vy * sy, c.vx * sx,
                                            c.vy * sy, c.connected)
            if i >= 0 and d <= best_d:
                p = None if c.param is None or i >= len(c.param) else c.param[i]
                text = format_curve_point(c.quantity, c.x[i], c.y[i], p)
                if show_names and c.name:
                    text = f"{c.name}\n{text}"
                hit = HoverHit(text, float(c.vx[i]), float(c.vy[i]),
                               "curve", c.colour)
                best_d = d

        lines: list[str] = []
        seg_pos = None
        for sgm in self.segments:
            d, _i, q = _nearest_on_polyline(vx * sx, vy * sy, sgm.vx * sx,
                                            sgm.vy * sy, True)
            if d <= segment_px:
                lines.append(sgm.text)
                if seg_pos is None:
                    seg_pos = (q[0] / sx, q[1] / sy, sgm.colour)
        if lines:
            if hit is None:
                return HoverHit("\n".join(lines), seg_pos[0], seg_pos[1],
                                "segment", seg_pos[2])
            hit.text += "\n" + "\n".join(lines)
        if hit is not None:
            return hit

        for m in self.marks:
            if m.kind == "point":
                continue
            if m.kind == "hline":
                d = abs(m.vy - vy) * sy
                pos = (vx, m.vy)
            else:
                d = abs(m.vx - vx) * sx
                pos = (m.vx, vy)
            if d <= line_px:
                return HoverHit(m.text, pos[0], pos[1], "line", m.colour)
        return None


class _LeaveFilter(QObject):
    """Hides the readout when the cursor leaves the plot's widget."""

    def __init__(self, readout: HoverReadout) -> None:
        super().__init__(readout)
        self._readout = readout

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Leave:
            self._readout.hide()
        return False


class HoverReadout(QObject):
    """A marker and a text label that follow the cursor over a ``PlotItem``."""

    def __init__(self, plot_item: PlotItem, log_x: bool = False) -> None:
        super().__init__()
        self.plot = plot_item
        self.model = HoverModel(log_x)
        dark = _is_dark()
        self._fg = "#E8E8F0" if dark else "#111111"
        fill = QColor(26, 26, 46, 235) if dark else QColor(255, 255, 255, 240)
        self._marker = pg.ScatterPlotItem(size=10, symbol="o",
                                          brush=mkBrush(None))
        self._label = pg.TextItem(color=self._fg, anchor=(0, 1),
                                  fill=mkBrush(fill),
                                  border=mkPen("#888888", width=0.8))
        for item in (self._marker, self._label):
            item.setZValue(1000)
        self.attach()
        self.hide()

        scene = plot_item.scene()
        if scene is not None:
            scene.sigMouseMoved.connect(self._on_moved)
        view = plot_item.getViewWidget()
        if view is not None:
            self._filter = _LeaveFilter(self)
            view.viewport().installEventFilter(self._filter)

    def attach(self) -> None:
        """(Re-)add the marker and label — ``PlotItem.clear()`` removes them."""
        for item in (self._marker, self._label):
            if item not in self.plot.items:
                self.plot.addItem(item, ignoreBounds=True)

    def reset(self, log_x: bool = False) -> None:
        """Forget everything registered and start over on a cleared plot."""
        self.model.clear()
        self.model.log_x = log_x
        self.attach()
        self.hide()

    def hide(self) -> None:
        self._marker.setVisible(False)
        self._label.setVisible(False)

    def show_hit(self, hit: HoverHit | None) -> None:
        if hit is None:
            self.hide()
            return
        colour = hit.colour or "#FF6600"
        self._marker.setData([hit.x], [hit.y], pen=mkPen(colour, width=2))
        self._marker.setVisible(True)
        vb = self.plot.getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        self._label.setAnchor((1 if hit.x > (x0 + x1) / 2 else 0,
                               0 if hit.y > (y0 + y1) / 2 else 1))
        self._label.setText(hit.text, color=self._fg)
        self._label.setPos(hit.x, hit.y)
        self._label.setVisible(True)

    def update_at_view(self, vx: float, vy: float) -> HoverHit | None:
        """Look up and show the readout for a cursor at view coordinates."""
        vb = self.plot.getViewBox()
        dx, dy = vb.viewPixelSize()
        if dx <= 0 or dy <= 0:
            self.hide()
            return None
        hit = self.model.hit(vx, vy, 1.0 / dx, 1.0 / dy)
        self.show_hit(hit)
        return hit

    def _on_moved(self, pos) -> None:
        vb = self.plot.getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            self.hide()
            return
        point = vb.mapSceneToView(pos)
        self.update_at_view(point.x(), point.y())


def install_hover_readout(plot_item: PlotItem,
                          log_x: bool = False) -> HoverReadout:
    """
    Give ``plot_item`` a hover readout and return it for registering data.

    Idempotent: calling it again on the same plot (after ``plot_item.clear()``
    and a redraw, say) empties the model and re-attaches the marker rather
    than stacking another readout on top. Register what was drawn with
    ``readout.model.add_curve / add_mark / add_segment`` — **raw** data.
    """
    existing = getattr(plot_item, "_faux_hover", None)
    if existing is not None:
        existing.reset(log_x)
        return existing
    readout = HoverReadout(plot_item, log_x)
    plot_item._faux_hover = readout
    return readout
