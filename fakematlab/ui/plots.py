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
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from pyqtgraph import InfiniteLine, PlotItem, PlotWidget, mkBrush, mkPen
from PySide6.QtCore import Qt
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
              ylabel: str = "", log_x: bool = False) -> PlotWidget:
    """
    Create a styled PlotWidget.

    For a frequency axis prefer :func:`make_freq_plot`, which also installs
    decade ticks and documents the raw-ω contract.
    """
    pw = PlotWidget()
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


def _superscript(n: int) -> str:
    digits = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
              "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻"}
    return "".join(digits.get(ch, ch) for ch in str(n))


def make_freq_plot(title: str = "", ylabel: str = "",
                   xlabel: str = "ω (rad/s)") -> PlotWidget:
    """
    A Bode-style plot: logarithmic ω axis with decade ticks.

    Feed it through :func:`plot_freq` / :func:`freq_vline` / :func:`freq_marker`
    / :func:`freq_text`, all of which take **raw ω in rad/s**.
    """
    pw = PlotWidget(axisItems={"bottom": LogFreqAxis(orientation="bottom")})
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
