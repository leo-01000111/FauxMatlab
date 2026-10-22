"""
Cedric at the foot of the navigation rail: he is there, he paints in both
themes, and poking him asks for help — which opens the documentation site.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from evans.ui import help as evans_help
from evans.ui import theme
from evans.ui.cedric import DAY_INK, NIGHT_INK, CedricButton


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_rail_ends_with_cedric(app):
    from evans.ui.workspace import NavigationRail

    rail = NavigationRail()
    layout = rail.layout()
    assert layout.itemAt(layout.count() - 1).widget() is rail.cedric
    asked = []
    rail.help_requested.connect(lambda: asked.append(True))
    rail.resize(90, 400)
    rail.show()
    QTest.mouseClick(rail.cedric, Qt.LeftButton, pos=QPoint(30, 50))
    assert asked == [True]
    rail.deleteLater()


@pytest.mark.parametrize("tokens, ink", [(theme.DAY, DAY_INK[0]),
                                         (theme.NIGHT, NIGHT_INK[0])])
def test_he_is_drawn_in_the_site_coral(app, monkeypatch, tokens, ink):
    monkeypatch.setattr(theme, "_current", tokens)
    c = CedricButton()
    c.resize(c.sizeHint())
    img = c.grab().toImage().convertToFormat(QImage.Format_RGB32)
    want = int(ink[1:], 16)
    near = 0
    for y in range(img.height()):
        for x in range(img.width()):
            px = img.pixel(x, y) & 0xFFFFFF
            if all(abs(((px >> sh) & 255) - ((want >> sh) & 255)) < 24
                   for sh in (0, 8, 16)):
                near += 1
    assert near > 20, f"only {near} coral pixels"
    c.deleteLater()


def test_help_opens_the_help_window(app, monkeypatch):
    monkeypatch.setattr(evans_help, "_window", None)
    assert evans_help.open_help()
    window = evans_help.window()
    assert window.isVisible() and window.topic == "index"
    assert evans_help.open_help("step")
    assert evans_help.window() is window and window.topic == "step"
    window.close()
