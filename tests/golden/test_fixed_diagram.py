"""
The fixed architecture diagram: does it draw the loop it claims to?

Regression for a stray wire: measurement noise n used to be a bare line that
ran along the feedback wire with no summing junction. It now enters ``sum_m``
like the other disturbances enter theirs.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtWidgets import QApplication

from fakematlab.ui.diagram.fixed_diagram import FixedDiagramView
from fakematlab.ui.diagram.items import DiagramWire


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _segments(view):
    """Every straight piece of every wire, as ((x0, y0), (x1, y1))."""
    segs = []
    for item in view._scene.items():
        if isinstance(item, DiagramWire):
            pts = [(p.x(), p.y()) for p in item.points]
            segs += list(zip(pts, pts[1:]))
    return segs


def _collinear_overlap(a, b) -> bool:
    """True if two axis-aligned segments share more than a single point."""
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    if ay0 == ay1 == by0 == by1:          # both horizontal, same row
        lo = max(min(ax0, ax1), min(bx0, bx1))
        hi = min(max(ax0, ax1), max(bx0, bx1))
        return hi > lo
    if ax0 == ax1 == bx0 == bx1:          # both vertical, same column
        lo = max(min(ay0, ay1), min(by0, by1))
        hi = min(max(ay0, ay1), max(by0, by1))
        return hi > lo
    return False


def test_measurement_summer_exists(app):
    view = FixedDiagramView()
    assert "sum_m" in view._summers
    assert view._summers["sum_m"].signs.get("right") == "+n"


def test_no_wires_overlap(app):
    segs = _segments(FixedDiagramView())
    for i, a in enumerate(segs):
        for b in segs[i + 1:]:
            assert not _collinear_overlap(a, b), f"{a} overlaps {b}"


def test_n_label_emits_signal(app):
    view = FixedDiagramView()
    got = []
    view.signal_selected.connect(got.append)
    view._signals["n"].clicked.emit("n")
    assert got == ["n"]
