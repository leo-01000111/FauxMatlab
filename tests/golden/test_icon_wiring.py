"""
The icon set wired into the interface: every name the code asks for exists,
the files ship in the wheel and the exe, and the controls carry them.

The set's own contract — currentColor, the grid, both themes — is
``tests/test_iconset.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from fakematlab.ui import iconset

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_every_icon_the_code_asks_for_exists():
    """A typo in a name would only show as a button with no picture."""
    wanted = set()
    for path in (ROOT / "fakematlab" / "ui").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        wanted |= set(re.findall(r'iconset\.(?:bind\(\w[\w.]*, |icon\()"([\w-]+)"',
                                 text))
    assert wanted, "no icon uses found — the pattern above is stale"
    assert not wanted - set(iconset.names())


def test_the_app_icon_and_ico_ship(app):
    assert not iconset.app_icon().isNull()
    ico = ROOT / "fakematlab" / "ui" / "icons" / "app.ico"
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"    # an ICO header
    spec = (ROOT / "packaging" / "fauxmatlab.spec").read_text(encoding="utf-8")
    assert "app.ico" in spec and '"icons"' in spec
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"icons/*"' in pyproject


def test_the_rail_and_toolbars_carry_icons(app):
    from fakematlab.ui.sim.sim_tab import SimTab
    from fakematlab.ui.workspace import NavigationRail, Workspace

    rail = NavigationRail()
    for workspace in Workspace:
        assert not rail.button(workspace).icon().isNull(), workspace
    tab = SimTab()
    actions = [a for a in tab._toolbar.actions() if a.text()]
    with_icons = [a.text() for a in actions if not a.icon().isNull()]
    assert {"Blocks", "Undo", "Redo", "Fit", "Linearise"} <= set(with_icons)
    assert not tab._run_btn.icon().isNull()
    assert isinstance(tab._run_btn.icon(), QIcon)
    rail.deleteLater()
    tab.deleteLater()
