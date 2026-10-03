"""
The minimum-phase split as a pane (ch.4, slides 44 and 46).
===========================================================
Shows ``G = G_allpass · G_mp`` for one system: the three transfer functions,
the RHP zeros and the mirror images they are swapped for, and two Bode plots
that make the point of the factorisation visible.

* **Magnitude** — ``G`` and ``G_mp`` are drawn on top of each other. They are
  the same curve (``|G_allpass| = 1``); the overlay *is* the demonstration, so
  the legend says so rather than leaving a reader to wonder why one curve is
  missing.
* **Phase** — ``G``, ``G_mp`` and ``G_allpass``. The gap between ``G`` and
  ``G_mp`` is exactly ``G_allpass``: that is where the non-minimum-phase lag
  comes from.

The header is deliberately compact — a few wrapped lines in a scroll area
capped in height — so the plots keep most of a ≈450×350 pane. All frequency
data is raw ω; :mod:`fakematlab.ui.plots` owns the log axis.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ..core import freqresp as _freq
from ..core import tf_utils as _tfu
from ..core.minphase import MinPhaseSplit, minimum_phase_split
from . import theme
from .guard import GuardedPanel, guard
from .plots import curve_pen, make_freq_plot, plot_freq

_G_PEN, _MP_PEN, _AP_PEN = 0, 1, 4      # ink (the system), highlight, muted


class MinPhaseView(QWidget, GuardedPanel):
    """A self-contained pane: call :meth:`show_system` with a transfer function."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.split: MinPhaseSplit | None = None
        self.system_name = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.install_error_banner(lay)

        self._status = QLabel("Select a system to split into "
                              "all-pass × minimum-phase.")
        # One line, not wrapped. A wrapped QLabel is height-for-width (and
        # re-asserts it on every setText), which makes the whole view
        # height-for-width; the pane then sizes it to the full wrapped height
        # of everything (1158 px at 760 wide) and scrolls the phase plot out
        # of sight. The full text is in the tooltip and the header below.
        self._status.setWordWrap(False)
        lay.addWidget(self._status)

        self._text = QLabel("")
        self._text.setFont(theme.data_font(9))
        self._text.setTextFormat(Qt.RichText)
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._text)
        scroll.setMaximumHeight(120)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._header = scroll
        lay.addWidget(scroll)

        self._mag = make_freq_plot(ylabel="|G| (dB)", xlabel="", y_unit="db")
        self._phase = make_freq_plot(ylabel="phase (°)", y_unit="phase")
        for pw in (self._mag, self._phase):
            pw.setMinimumHeight(70)
            pw.getPlotItem().addLegend(offset=(-5, 5))
        lay.addWidget(self._mag, stretch=1)
        lay.addWidget(self._phase, stretch=1)

    # ── public ────────────────────────────────────────────────

    @guard("Minimum-phase split")
    def show_system(self, tf, name: str = "G") -> None:
        """Split ``tf`` (labelled ``name``) and redraw the whole pane."""
        self.system_name = name
        self.split = split = minimum_phase_split(tf)
        self._fill_text(tf, name, split)
        self._draw(tf, name, split)

    # ── text ──────────────────────────────────────────────────

    def _fill_text(self, tf, name: str, sp: MinPhaseSplit) -> None:
        if sp.is_minimum_phase:
            self._status.setText(
                f"{name} is already minimum phase — no RHP zeros, so "
                f"G_allpass = 1 and G_mp = {name}.")
        else:
            self._status.setText(
                f"{name} is NON-minimum phase: {len(sp.rhp_zeros)} RHP "
                f"zero(s). Dissolved into G_allpass · G_mp.")
        self._status.setToolTip(self._status.text())
        rows = [
            (name, _tfu.factored_str(tf)),
            ("G_allpass", _tfu.factored_str(sp.allpass)),
            ("G_mp", _tfu.factored_str(sp.minphase)),
        ]
        html = "<table cellspacing='0' cellpadding='1'>" + "".join(
            f"<tr><td><b>{n}</b>&nbsp;=&nbsp;</td><td>{_esc(v)}</td></tr>"
            for n, v in rows) + "</table>"
        if sp.rhp_zeros:
            html += ("<br>RHP zeros: " + _zlist(sp.rhp_zeros)
                     + "<br>mirrored to: " + _zlist(sp.mirrored_zeros))
        html += f"<br><i>{_esc(sp.explanation)}</i>"
        self._text.setText(html)

    # ── plots ─────────────────────────────────────────────────

    def _draw(self, tf, name: str, sp: MinPhaseSplit) -> None:
        w = _freq._auto_omega(tf)
        curves = {}
        for key, sys in (("G", tf), ("mp", sp.minphase), ("ap", sp.allpass)):
            mag, ph = _freq.response(sys, w)
            curves[key] = (20 * np.log10(np.maximum(mag, 1e-300)),
                           np.degrees(np.unwrap(ph)))

        mag_p = self._mag.getPlotItem()
        ph_p = self._phase.getPlotItem()
        for p in (mag_p, ph_p):
            p.clear()
            if p.legend is not None:
                p.legend.clear()

        plot_freq(mag_p, w, curves["G"][0], pen=curve_pen(_G_PEN, 3),
                  name=f"|{name}|")
        pen = curve_pen(_MP_PEN, 2)
        pen.setStyle(Qt.DashLine)
        plot_freq(mag_p, w, curves["mp"][0], pen=pen,
                  name="|G_mp|  (identical: |G_allpass| = 1)")

        plot_freq(ph_p, w, curves["G"][1], pen=curve_pen(_G_PEN, 3), name=name)
        pen = curve_pen(_MP_PEN, 2)
        pen.setStyle(Qt.DashLine)
        plot_freq(ph_p, w, curves["mp"][1], pen=pen, name="G_mp")
        plot_freq(ph_p, w, curves["ap"][1], pen=curve_pen(_AP_PEN, 2),
                  name="G_allpass  (the extra lag)")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _zlist(zs) -> str:
    def one(z: complex) -> str:
        if abs(z.imag) < 1e-9 * max(1.0, abs(z)):
            return f"{z.real:.4g}"
        return f"{z.real:.4g} {'+' if z.imag >= 0 else '-'} {abs(z.imag):.4g}j"
    return ",&nbsp; ".join(one(z) for z in zs)
