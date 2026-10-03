"""
Holding Point, as the app wears it: tokens, fonts, palette, stylesheet.

These run offscreen. They check the contract other modules rely on — every
token present in both themes, the bundled fonts loading, the stylesheet
actually changing when the mode does — not how anything looks; that is for
screenshots.
"""

from __future__ import annotations

import dataclasses
import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QPushButton

from fakematlab.ui import theme, theme_qt
from fakematlab.ui.design import Status, StatusBadge


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("FauxMatlabTest")
    app.setApplicationName("theme-tests")
    theme.load_fonts()
    theme.set_mode(theme.Mode.DAY, persist=False)
    theme_qt.apply(app)
    yield app
    theme.set_mode(theme.Mode.DAY, persist=False)


class _Recorder:
    """
    Stands in for the application while the mode flips.

    Re-applying the application stylesheet repolishes every live widget. In
    the app that is one window and a third of a second; at this point in the
    suite it is every window the earlier UI tests left behind, and four
    switches cost the run fifteen minutes. The switching logic is what is
    under test here, so record what it would install instead.
    """

    def __init__(self) -> None:
        self.sheet, self.pal = "", None

    def setStyleSheet(self, sheet: str) -> None:        # noqa: N802 (Qt API)
        self.sheet = sheet

    def setPalette(self, pal) -> None:                  # noqa: N802 (Qt API)
        self.pal = pal

    def styleSheet(self) -> str:                        # noqa: N802 (Qt API)
        return self.sheet

    def palette(self):
        return self.pal


@pytest.fixture
def recorded(app, monkeypatch):
    rec = _Recorder()
    monkeypatch.setitem(theme_qt._state, "app", rec)
    monkeypatch.setattr(theme_qt, "_force_scheme", lambda t: None)
    yield rec
    theme.set_mode(theme.Mode.DAY, persist=False)


def test_both_themes_define_every_token():
    for tokens in (theme.DAY, theme.NIGHT):
        for field in dataclasses.fields(tokens):
            value = getattr(tokens, field.name)
            assert value, f"{tokens.name}.{field.name} is empty"
            if field.name != "name":
                assert QColor(value).isValid(), (tokens.name, field.name)
    assert theme.DAY.name != theme.NIGHT.name
    assert not theme.DAY.is_night and theme.NIGHT.is_night


def test_the_bundled_fonts_load(app):
    assert theme.load_fonts()
    families = set(QFontDatabase.families())
    assert theme.SANS in families
    assert theme.MONO in families
    assert theme.sign_font().family() == theme.SANS
    assert theme.data_font().family() == theme.MONO


def test_the_fonts_ship_with_the_package():
    folder = theme._FONT_DIR
    assert (folder / "Archivo-Variable.ttf").is_file()
    assert (folder / "MartianMono-Variable.ttf").is_file()
    spec = (theme._FONT_DIR.parents[2] / "packaging" / "fauxmatlab.spec")
    assert "fonts" in spec.read_text(encoding="utf-8")
    pyproject = (theme._FONT_DIR.parents[2] / "pyproject.toml")
    assert "fonts/*" in pyproject.read_text(encoding="utf-8")


def test_apply_installs_palette_and_stylesheet(app):
    assert app.styleSheet().strip()
    palette = app.palette()
    assert palette.color(QPalette.Window) == QColor(theme.tokens().ground)
    assert palette.color(QPalette.Highlight) == QColor(theme.tokens().signal)
    assert palette.color(QPalette.Link) == QColor(theme.tokens().edge)
    disabled = palette.color(QPalette.Disabled, QPalette.WindowText)
    assert disabled != palette.color(QPalette.Active, QPalette.WindowText)


def test_apply_twice_is_harmless(app):
    before = app.styleSheet()
    theme_qt.apply(app)
    assert app.styleSheet() == before


def test_switching_mode_reapplies_the_stylesheet(recorded):
    theme_qt.choose(theme.Mode.DAY, persist=False)
    day_sheet, day_window = recorded.styleSheet(), recorded.palette().color(
        QPalette.Window)
    theme_qt.choose(theme.Mode.NIGHT, persist=False)
    assert theme.tokens() is theme.NIGHT
    assert recorded.styleSheet() != day_sheet
    assert theme.NIGHT.ground in recorded.styleSheet()
    assert recorded.palette().color(QPalette.Window) != day_window
    theme_qt.choose(theme.Mode.DAY, persist=False)
    assert recorded.styleSheet() == day_sheet


def test_status_colours_follow_the_theme(recorded):
    theme_qt.choose(theme.Mode.DAY, persist=False)
    day = {s: s.colour for s in Status}
    theme_qt.choose(theme.Mode.NIGHT, persist=False)
    night = {s: s.colour for s in Status}
    assert night[Status.OK] == theme.NIGHT.lamp_go
    assert night[Status.CRITICAL] == theme.NIGHT.hold_ink
    assert day[Status.CRITICAL] == theme.DAY.hold_ink
    assert day != night
    theme_qt.choose(theme.Mode.DAY, persist=False)


def test_yellow_is_never_status_text(recorded):
    """Sign yellow is 1.3:1 on the Day ground: a lamp, not a legend."""
    for mode in (theme.Mode.DAY, theme.Mode.NIGHT):
        theme_qt.choose(mode, persist=False)
        assert Status.WARNING.colour != theme.tokens().signal or \
            theme.tokens().is_night
        assert Status.WARNING.lamp == theme.tokens().lamp_caution
    theme_qt.choose(theme.Mode.DAY, persist=False)


def test_a_badge_keeps_its_symbol_and_word(app):
    badge = StatusBadge(Status.OK)
    assert Status.OK.symbol in badge.text()
    assert "stable" in badge.text()
    badge.set_status(Status.CRITICAL, "unstable")
    assert badge.status is Status.CRITICAL
    badge.grab()                                  # paints without raising


def test_buttons_get_the_sign_face_when_polished(app):
    button = QPushButton("Run")
    button.show()
    app.processEvents()
    assert button.font().family() == theme.SANS
    assert button.font().capitalization() == button.font().Capitalization.AllUppercase
    button.close()


def test_the_main_window_offers_a_theme_menu(app, recorded):
    from fakematlab.core.architecture import CourseArchitecture
    from fakematlab.core.tf_utils import second_order, unity
    from fakematlab.ui.mainwindow import MainWindow

    arch = CourseArchitecture(G=second_order(K=1.0, zeta=0.5, wn=2.0),
                              K2=unity(), K1=unity(), H=unity())
    win = MainWindow(arch)
    try:
        actions = win._theme_actions
        assert set(actions) == set(theme.Mode)
        actions[theme.Mode.NIGHT].trigger()
        assert theme.tokens() is theme.NIGHT
        assert actions[theme.Mode.NIGHT].isChecked()
        assert not actions[theme.Mode.DAY].isChecked()
        assert theme.NIGHT.ground in recorded.styleSheet()
    finally:
        theme_qt.choose(theme.Mode.DAY)       # the menu persisted Night: undo it
        win.close()
        win.deleteLater()


def test_plot_colours_follow_a_theme_chosen_before_any_plot():
    """
    ``app.py`` applies the saved theme after ``plots`` is imported but before
    a plot exists. The series palette once missed that switch, so a Night
    start drew near-black curves on asphalt: a blank-looking main view.
    Import order is the bug, so it needs a fresh interpreter.
    """
    import subprocess
    import sys

    probe = (
        "import os; os.environ['PYQTGRAPH_QT_LIB'] = 'PySide6'\n"
        "from fakematlab.ui import plots, theme\n"
        "theme.set_mode(theme.Mode.NIGHT, persist=False)\n"
        "assert plots.COLORS[0] == theme.NIGHT.ink, plots.COLORS\n"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run([sys.executable, "-c", probe], env=env,
                          capture_output=True, text=True, timeout=120,
                          cwd=theme._FONT_DIR.parents[2])
    assert done.returncode == 0, done.stderr


def test_the_stylesheet_never_chains_sub_controls():
    """
    ``QMenu::item:selected::indicator`` is not Qt syntax. Qt did not reject
    it: it painted the tick image over the middle of every menu item.
    """
    import re

    for t in (theme.DAY, theme.NIGHT):
        sheet = theme_qt.build_stylesheet(t)
        chained = re.findall(r"::[\w-]+(?::[\w-]+)*::[\w-]+", sheet)
        assert not chained, chained
