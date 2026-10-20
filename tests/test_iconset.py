"""
The icon set: every icon loads, and every icon keeps to Holding Point.

Like the theme tests these check the contract, not the look — the look is the
contact sheet. The contract is what makes one file serve both themes: drawn in
``currentColor`` and nothing else, on the 24 px grid, square caps and mitred
joins, no gradients, no hard-coded colour that would vanish on one ground.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from evans.ui import iconset, theme

# What the interface asks for. A name here that has no file is a broken icon
# at run time, so the list is checked rather than trusted.
REQUIRED = [
    "workspace-analyse", "workspace-model", "workspace-console",
    "blocks", "run", "stop", "undo", "redo", "fit", "align-row",
    "align-column", "distribute", "ascend", "linearise", "open", "save",
    "pane-step", "pane-impulse", "pane-ramp", "pane-bode", "pane-nyquist",
    "pane-nichols", "pane-pzmap", "pane-rlocus", "pane-metrics",
    "pane-minphase", "pane-system", "pane-time", "pane-frequency",
    "pane-stability", "pane-performance", "pane-design", "pane-modern",
    "grid-1", "grid-1x2", "grid-2x2",
    "snapshot", "restore", "delete", "compare",
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_every_required_icon_exists():
    missing = sorted(set(REQUIRED) - set(iconset.names()))
    assert not missing


def test_every_pane_kind_has_an_icon():
    from evans.ui.panes import PANE_KINDS
    missing = [k.key for k in PANE_KINDS
               if f"pane-{k.key}" not in iconset.names()]
    assert not missing


@pytest.mark.parametrize("name", iconset.names())
def test_icon_keeps_to_holding_point(name):
    source = iconset.svg(name)
    root = ET.fromstring(source)
    assert root.get("viewBox") == "0 0 24 24"
    assert root.get("stroke-linecap") == "square"
    assert root.get("stroke-linejoin") == "miter"
    assert "Gradient" not in source and "filter" not in source
    # The only colour is the one the theme substitutes.
    colours = set(re.findall(r'(?:fill|stroke)="([^"]+)"', source))
    assert colours <= {"currentColor", "none"}, colours
    assert "#" not in source


@pytest.mark.parametrize("name", iconset.names())
def test_icon_renders_in_both_themes(app, name):
    # Drawn in each theme's ink directly. Switching the live theme here, twice
    # per icon, restyled every window the UI tests had left open and made the
    # whole suite four times slower; test_icon_follows_the_theme covers the
    # live switch once.
    assert not iconset.icon(name).isNull()
    for tokens in (theme.DAY, theme.NIGHT):
        img = iconset.pixmap(name, 24, tokens.ink).toImage()
        assert any(img.pixelColor(x, y).alpha() > 0
                   for x in range(24) for y in range(24)), "drew nothing"


def test_checked_state_uses_the_plate_legend(app):
    t = theme.tokens()
    on = iconset.icon("run").pixmap(24, 24, QIcon.Normal, QIcon.On).toImage()
    colours = {on.pixelColor(x, y).name() for x in range(24) for y in range(24)
               if on.pixelColor(x, y).alpha() == 255}
    assert t.on_plate in colours


def test_app_icon_has_every_size(app):
    sizes = {(s.width(), s.height()) for s in iconset.app_icon().availableSizes()}
    assert {(16, 16), (32, 32), (256, 256)} <= sizes
    assert (iconset.ICON_DIR / "app.ico").is_file()


def test_icon_follows_the_theme(app):
    def ink_pixels():
        img = iconset.icon("stop").pixmap(24, 24).toImage()
        return {img.pixelColor(x, y).name() for x in range(24) for y in range(24)
                if img.pixelColor(x, y).alpha() == 255}
    theme.set_mode(theme.Mode.DAY, persist=False)
    day = ink_pixels()
    theme.set_mode(theme.Mode.NIGHT, persist=False)
    night = ink_pixels()
    theme.set_mode(theme.Mode.DAY, persist=False)
    assert theme.DAY.ink in day and theme.NIGHT.ink in night
