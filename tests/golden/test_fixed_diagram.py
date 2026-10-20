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

from evans.ui.diagram.fixed_diagram import FixedDiagramView
from evans.ui.diagram.items import DiagramWire


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


def test_the_model_panel_cannot_be_zoomed_panned_or_scrolled(app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QGraphicsView

    from evans.core.architecture import CourseArchitecture
    from evans.ui.diagram.fixed_diagram import FixedDiagramView

    view = FixedDiagramView(CourseArchitecture())
    view.resize(420, 260)
    view.show()
    for _ in range(5):
        app.processEvents()
    before = (view.transform(), view.horizontalScrollBar().value(),
              view.verticalScrollBar().value())

    assert view.dragMode() == QGraphicsView.NoDrag
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    centre = QPointF(210, 130)
    for delta in (480, -480):
        view.wheelEvent(QWheelEvent(centre, view.mapToGlobal(centre),
                                    QPoint(0, 0), QPoint(0, delta),
                                    Qt.NoButton, Qt.NoModifier,
                                    Qt.NoScrollPhase, False))
    for key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown):
        QTest.keyClick(view, key)
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                     QPoint(30, 30))
    QTest.mouseMove(view.viewport(), QPoint(200, 160))
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                       QPoint(200, 160))
    app.processEvents()
    after = (view.transform(), view.horizontalScrollBar().value(),
             view.verticalScrollBar().value())
    assert after == before

    # It still fits the whole loop when the panel changes size.
    view.resize(300, 400)
    app.processEvents()
    shown = view.mapToScene(view.viewport().rect()).boundingRect()
    assert shown.contains(view.scene().itemsBoundingRect())
    view.deleteLater()
