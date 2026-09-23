"""
Where a plot command's output goes.

``step(G)`` in a console has to draw somewhere. Rather than let the API import
Qt — which would make the whole namespace untestable headless and drag a GUI
into every script — a plot command builds a :class:`FigureSpec` describing
what to draw and hands it to the installed **sink**.

The UI installs a sink that opens a docked figure window. The default sink
just remembers the last few specs, so the API can be tested, scripted and run
headless with no display at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np


@dataclass
class Trace:
    """One curve on a figure."""
    x:     np.ndarray
    y:     np.ndarray
    label: str = ""
    style: str = "line"          # line | scatter | dashed


@dataclass
class FigureSpec:
    """
    A plot request, described rather than drawn.

    ``kind`` tells the sink which axes to build — ``"time"``, ``"bode"``,
    ``"nyquist"``, ``"pzmap"``, ``"rlocus"`` or ``"xy"`` — so the renderer can
    apply the right scales and annotations without the API knowing anything
    about widgets.
    """
    kind:    str
    title:   str = ""
    xlabel:  str = ""
    ylabel:  str = ""
    traces:  list[Trace] = field(default_factory=list)
    extra:   dict[str, Any] = field(default_factory=dict)

    def add(self, x, y, label: str = "", style: str = "line") -> "FigureSpec":
        self.traces.append(Trace(np.asarray(x, dtype=float),
                                 np.asarray(y, dtype=float), label, style))
        return self


class _RecordingSink:
    """Default sink: remember what was asked for, draw nothing."""

    def __init__(self, limit: int = 32) -> None:
        self.figures: list[FigureSpec] = []
        self._limit = limit

    def __call__(self, spec: FigureSpec) -> FigureSpec:
        self.figures.append(spec)
        del self.figures[:-self._limit]
        return spec

    @property
    def last(self) -> FigureSpec | None:
        return self.figures[-1] if self.figures else None

    def clear(self) -> None:
        self.figures.clear()


_sink: Callable[[FigureSpec], Any] = _RecordingSink()


def set_figure_sink(sink: Callable[[FigureSpec], Any]) -> Callable:
    """Install the renderer. Returns the previous one, so it can be restored."""
    global _sink
    previous, _sink = _sink, sink
    return previous


def figure_sink() -> Callable[[FigureSpec], Any]:
    """The sink currently installed."""
    return _sink


def emit(spec: FigureSpec) -> FigureSpec:
    """Send a figure to the installed sink."""
    _sink(spec)
    return spec


def recording_sink() -> _RecordingSink:
    """A fresh recording sink, for tests and headless scripts."""
    return _RecordingSink()
