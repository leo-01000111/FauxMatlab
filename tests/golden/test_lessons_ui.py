"""
The Lessons menu and the lesson panel.

The arithmetic is checked in ``test_lessons.py``. What is left here is that
loading a lesson really does load it — the blocks, the tab, the notes — and
that the panel re-measures against what is on screen rather than against the
lesson's own stored copy.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

import control as ctl
from PySide6.QtWidgets import QApplication

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.lessons import all_lessons, lesson
from fakematlab.ui.guard import ErrorBanner
from fakematlab.ui.mainwindow import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    window = MainWindow(CourseArchitecture())
    window.resize(1500, 900)
    window.show()
    _settle(app)
    yield window
    window.hide()


@pytest.fixture(autouse=True)
def reset(request, app):
    if "win" not in request.fixturenames:
        yield
        return
    window = request.getfixturevalue("win")
    window.snapshots.clear()
    window._snapshot_bar.refresh()
    for banner in window.findChildren(ErrorBanner):
        banner.clear()
    _settle(app)
    yield


def _settle(app, rounds: int = 20) -> None:
    for _ in range(rounds):
        app.processEvents()


def _banners_clean(widget) -> None:
    failed = [b.message for b in widget.findChildren(ErrorBanner)
              if b.has_error]
    assert not failed, failed[0]


# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("les", all_lessons(), ids=lambda x: x.key)
def test_every_lesson_loads_cleanly_and_all_its_claims_hold(app, win, les):
    win.load_lesson(les)
    _settle(app, 5)
    _banners_clean(win)
    assert win._lessons._table.rowCount() == len(les.claims)
    assert win._lessons._verdict.text() == \
        f"{len(les.claims)}/{len(les.claims)} hold"


def test_a_lesson_brings_its_own_tab_forward(app, win):
    win.load_lesson(lesson("ch6-margins"))
    _settle(app, 5)
    assert win._tabs.currentWidget() is win._freq_tab
    win.load_lesson(lesson("ch8-ziegler-nichols"))
    _settle(app, 5)
    assert win._tabs.currentWidget() is win._des_tab


def test_a_lesson_loads_its_blocks_into_the_live_architecture(app, win):
    win.load_lesson(lesson("ch2-satellite"))
    _settle(app, 5)
    poles = np.atleast_1d(ctl.poles(win._arch.block_tf("G")))
    assert len(poles) == 2 and np.allclose(poles, 0.0)


def test_the_panel_re_measures_against_the_model_on_screen(app, win):
    """
    Not against the lesson's stored blocks. Changing the plant has to turn
    the ticks into crosses, or the panel is just printing its own prose back.
    """
    les = lesson("ch4-second-order")
    win.load_lesson(les)
    _settle(app, 5)
    assert win._lessons._verdict.text().startswith(f"{len(les.claims)}/")

    win._arch.set_block("G", ctl.tf([1.0], [1.0, 1.0]))
    win._lessons.refresh()
    _settle(app, 5)
    passed = int(win._lessons._verdict.text().split("/")[0])
    assert passed < len(les.claims)
    _banners_clean(win._lessons)


def test_opening_a_lesson_keeps_the_work_it_replaced(app, win):
    """A lesson opened out of curiosity must not cost you your controller."""
    win._arch.set_block("K2", ctl.tf([3.5], [1]))
    win.load_lesson(lesson("ch7-waterbed"))
    _settle(app, 5)
    assert "before lesson" in win.snapshots.labels

    win._snapshot_bar._combo.setCurrentText("before lesson")
    win._snapshot_bar.restore()
    _settle(app, 5)
    assert float(ctl.dcgain(win._arch.block_tf("K2"))) == pytest.approx(3.5)


def test_browsing_lessons_does_not_fill_the_snapshot_store(app, win):
    for les in all_lessons():
        win.load_lesson(les)
    _settle(app, 5)
    assert win.snapshots.labels.count("before lesson") == 1
    assert len(win.snapshots) == 1


def test_the_console_snippet_runs_against_the_shared_workspace(app, win):
    win.load_lesson(lesson("ch2-satellite"))
    _settle(app, 5)
    win._run_lesson_snippet(lesson("ch2-satellite").console)
    _settle(app, 10)
    _banners_clean(win)
    assert "T" in win._console.interpreter.variables()


def test_the_lessons_menu_lists_every_lesson(app, win):
    menus = {m.title().replace("&", ""): m
             for m in win.menuBar().findChildren(type(win.menuBar().addMenu("x")))
             if m.title()}
    assert "Lessons" in menus
    titles = [a.text() for a in menus["Lessons"].actions() if a.text()]
    for les in all_lessons():
        assert any(f"Ch. {les.chapter}" in t for t in titles)
