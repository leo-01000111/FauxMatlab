"""
Pictures with nothing to install: math and figures through matplotlib.

Why matplotlib
--------------
Math in text cells has to be drawn in the app. The two candidates were
**matplotlib's mathtext** and **QtWebEngine with a vendored KaTeX**.
matplotlib is already a hard runtime dependency — python-control imports it
at module level, so it is in every install and in the frozen build (see
``packaging/evans.spec``). WebEngine is in the dev environment but is
deliberately *excluded* from the frozen build, where it would be the largest
thing in it. mathtext covers the TeX a lab report uses — fractions, sums,
integrals, roots, Greek, accents, sub/superscripts — and renders to a PNG
that a QTextDocument, an HTML page and a LaTeX report can all use. What it
cannot parse (``\\begin{bmatrix}``, say) falls back to showing the source.

The same module draws a :class:`FigureSpec` to a PNG for the reports, so a
report can be written headless — no widget has to be on screen to be grabbed.
"""

from __future__ import annotations

import io
from functools import lru_cache

import numpy as np

from ..figures import FigureSpec


class MathError(ValueError):
    """mathtext could not parse the LaTeX."""


@lru_cache(maxsize=512)
def math_png(latex: str, *, display: bool = False, color: str = "#121314",
             fontsize: float = 11.0, dpi: int = 120) -> bytes:
    """
    Render LaTeX math to a transparent, tightly cropped PNG.

    Raises :class:`MathError` when mathtext cannot parse it. Display math is
    drawn a size larger, as TeX's display style is.
    """
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties

    text = " ".join(latex.split())
    if not text:
        raise MathError("empty equation")
    size = fontsize * (1.2 if display else 1.0)
    figure = Figure(figsize=(0.01, 0.01))
    figure.text(0, 0, f"${text}$", fontproperties=FontProperties(size=size),
                color=color)
    buffer = io.BytesIO()
    try:
        figure.savefig(buffer, dpi=dpi, format="png", transparent=True,
                       bbox_inches="tight", pad_inches=0.02)
    except ValueError as exc:
        lines = [line.strip() for line in str(exc).splitlines()]
        raise MathError(next((line for line in lines if line),
                             "unparseable")) from exc
    return buffer.getvalue()


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height of a PNG, read from its header."""
    return (int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"))


# ──────────────────────────────────────────────────────────────
#  Figures
# ──────────────────────────────────────────────────────────────

_CYCLE = ("#1f4fd1", "#c1122e", "#0d6e37", "#b8860b", "#6a3fb5", "#4b4f55")


def figure_png(spec: FigureSpec, path=None, *, width: float = 6.4,
               height: float = 3.6, dpi: int = 150) -> bytes:
    """
    Draw a figure spec with matplotlib's Agg canvas; returns the PNG bytes
    and writes them to ``path`` too if one is given.

    Covers the kinds the console produces — time and xy plots (log axes,
    scatter, dashed), Bode as magnitude over phase, Nyquist with the unit
    circle and −1, pole-zero maps and root loci — enough for a report;
    the live figure in the app stays the reference rendering.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    bode = spec.kind == "bode"
    figure = Figure(figsize=(width, height * (1.5 if bode else 1.0)))
    FigureCanvasAgg(figure)
    if bode:
        mag, phase = figure.subplots(2, 1, sharex=True)
        for i, t in enumerate(spec.traces):
            mag.semilogx(t.x, t.y, color=_colour(i), label=t.label or None)
        for i, (omega, degrees, _label) in enumerate(spec.extra.get("phase", [])):
            phase.semilogx(omega, degrees, color=_colour(i))
        mag.set_ylabel("|G| (dB)")
        phase.set_ylabel("Phase (°)")
        phase.set_xlabel(spec.xlabel or "ω (rad/s)")
        mag.set_title(spec.title or "Bode")
        axes = [mag, phase]
        if any(t.label for t in spec.traces):
            mag.legend(fontsize=8)
    else:
        ax = figure.subplots()
        axes = [ax]
        _plain(ax, spec)
    for ax in axes:
        ax.grid(True, alpha=0.3)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    data = buffer.getvalue()
    if path is not None:
        with open(path, "wb") as handle:
            handle.write(data)
    return data


def _colour(i: int) -> str:
    return _CYCLE[i % len(_CYCLE)]


def _plain(ax, spec: FigureSpec) -> None:
    logx = bool(spec.extra.get("logx"))
    logy = bool(spec.extra.get("logy"))
    for i, t in enumerate(spec.traces):
        x, y = np.asarray(t.x, float), np.asarray(t.y, float)
        label = t.label or None
        if spec.kind == "pzmap":
            marker = "x" if "pole" in t.label else "o"
            ax.plot(x, y, linestyle="none", marker=marker, markersize=9,
                    markerfacecolor="none", color=_colour(i), label=label)
        elif t.style == "scatter":
            ax.plot(x, y, linestyle="none", marker="o", markersize=4,
                    color=_colour(i), label=label)
        else:
            ax.plot(x, y, color=_colour(i), label=label,
                    linestyle="--" if t.style == "dashed" else "-",
                    linewidth=1.4)
    if spec.kind == "nyquist":
        theta = np.linspace(0, 2 * np.pi, 200)
        ax.plot(np.cos(theta), np.sin(theta), "--", color="#999999",
                linewidth=0.8)
        ax.plot([-1], [0], "x", color="#c1122e", markersize=10)
        ax.set_aspect("equal", adjustable="datalim")
    if spec.kind in ("nyquist", "pzmap", "rlocus"):
        ax.axhline(0, color="#999999", linewidth=0.6)
        ax.axvline(0, color="#999999", linewidth=0.6)
    if logx:
        ax.set_xscale("log")
    if logy:
        ax.set_yscale("log")
    if spec.extra.get("xlim") is not None:
        ax.set_xlim(*map(float, spec.extra["xlim"]))
    if spec.extra.get("ylim") is not None:
        ax.set_ylim(*map(float, spec.extra["ylim"]))
    ax.set_title(spec.title)
    ax.set_xlabel(spec.xlabel)
    ax.set_ylabel(spec.ylabel)
    if any(t.label for t in spec.traces) and spec.kind != "rlocus":
        ax.legend(fontsize=8)
