"""
Layout regressions: size, context bar, model panel, persistence.

The first test here is the one the project did not have. The application's
minimum width had grown to **2038 px** — wider than a 1920 monitor — because
the Simulink toolbar was a single unbreakable row and a tab bar is as wide as
its widest tab. Nothing noticed, because nothing measured.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

import control as ctl
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.ui.design import (
    NORMAL,
    PANEL,
    SECTION,
    TIGHT,
    MetricLabel,
    Status,
    StatusBadge,
)
from fakematlab.ui.guard import ErrorBanner
from fakematlab.ui.mainwindow import MainWindow

#: The plan's target: usable at 1280×720, comfortable at 1920×1080.
TARGET_W, TARGET_H = 1280, 720


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    window = MainWindow(CourseArchitecture())
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
    window._model_dock.hide()
    window.resize(1400, 850)
    for banner in window.findChildren(ErrorBanner):
        banner.clear()
    _settle(app)
    yield


def _settle(app, rounds: int = 20) -> None:
    for _ in range(rounds):
        app.processEvents()


# ──────────────────────────────────────────────────────────────
#  Size
# ──────────────────────────────────────────────────────────────

def test_the_window_fits_a_1280x720_screen(win):
    """
    The regression that matters.

    `SimTab._build_toolbar` was one non-wrapping QHBoxLayout demanding
    1602 px; the tab bar propagated that to the whole window, which then could
    not be made narrower than 2038 px by any means.
    """
    hint = win.minimumSizeHint()
    assert hint.width() <= TARGET_W, (
        f"the window cannot be narrower than {hint.width()} px, so it does "
        f"not fit a {TARGET_W}-wide screen")
    assert hint.height() <= TARGET_H


def test_the_window_actually_resizes_to_the_target(app, win):
    """`resize()` used to be ignored: it came back 2038 wide regardless."""
    win.resize(TARGET_W, TARGET_H)
    _settle(app)
    assert win.width() == TARGET_W
    assert win.height() == TARGET_H


@pytest.mark.parametrize("index", range(8))
def test_every_tab_renders_at_the_target_size(app, win, index):
    win.resize(TARGET_W, TARGET_H)
    win._tabs.setCurrentIndex(index)
    _settle(app, 5)
    tab = win._tabs.widget(index)
    failed = [b.message for b in tab.findChildren(ErrorBanner) if b.has_error]
    assert not failed, f"{win._tabs.tabText(index)}: {failed[0]}"
    assert tab.minimumSizeHint().width() <= TARGET_W


def test_no_single_panel_dictates_the_window_width(win):
    """
    Each tab must fit the budget on its own. One oversized panel used to set
    the minimum for every other view in the application.
    """
    oversized = {
        win._tabs.tabText(i): win._tabs.widget(i).minimumSizeHint().width()
        for i in range(win._tabs.count())
        if win._tabs.widget(i).minimumSizeHint().width() > TARGET_W
    }
    assert not oversized, oversized


def test_the_analysis_area_gets_the_window(app, win):
    """
    The plan's UI-2 acceptance: ≥ 85 % of the width at 1280 px.

    The permanent left column used to take 420–760 px — a third of a 1280
    window — on every tab, including the two that analyse a different model.
    """
    win.resize(TARGET_W, TARGET_H)
    _settle(app)
    share = win._tabs.width() / win.width()
    assert share >= 0.85, f"analysis area is only {share:.0%} of the window"


# ──────────────────────────────────────────────────────────────
#  Context bar
# ──────────────────────────────────────────────────────────────

def test_the_context_bar_shows_factored_transfer_functions(app, win):
    """Not `G=[1, 2]/[1, 3, 3, 1]`, which is what the status bar used to say."""
    win._arch.set_block("G", ctl.tf([1], [1, 3, 2]))
    win._context.refresh()
    _settle(app, 3)
    summary = win._context.summary()
    assert "G(s)" in summary
    assert "[" not in summary.split("●")[0], \
        "the bar is still printing coefficient arrays"
    assert "(s + 1)" in summary and "(s + 2)" in summary


def test_the_context_bar_reports_stability_without_opening_a_tab(app, win):
    win._arch.set_block("G", ctl.tf([1], [1, 1]))
    win._arch.set_block("K2", ctl.tf([1], [1]))
    win._context.refresh()
    _settle(app, 3)
    assert win._context.verdict is Status.OK

    # A loop that cannot be stabilised by this gain.
    win._arch.set_block("G", ctl.tf([1], [1, -1]))
    win._arch.set_block("K2", ctl.tf([0.1], [1]))
    win._context.refresh()
    _settle(app, 3)
    assert win._context.verdict is Status.CRITICAL
    assert "right half plane" in win._context.summary()


def test_an_undefined_margin_reads_as_a_dash_not_nan(app, win):
    """
    `1/(s+1)³` starts at exactly 0 dB and never crosses, so there is no phase
    margin. That is not a failure, and printing `nan` says it is.
    """
    win._arch.set_block("G", ctl.tf([1], [1, 3, 3, 1]))
    win._arch.set_block("K2", ctl.tf([1], [1]))
    win._context.refresh()
    _settle(app, 3)
    assert win._context._pm._value.text() == "—"
    assert "0 dB" in win._context._pm.toolTip()


def test_the_context_bar_survives_a_broken_model(app, win):
    """Chrome must not become an error banner; it reports in its own fields."""
    win._arch.set_block("G", ctl.tf([1], [1, 0, 0]))
    win._arch.set_block("K2", ctl.tf([0], [1]))
    win._context.refresh()
    _settle(app, 3)
    assert win._context.summary()


# ──────────────────────────────────────────────────────────────
#  Model panel
# ──────────────────────────────────────────────────────────────

def test_the_model_panel_is_hidden_until_asked_for(win):
    assert not win._model_dock.isVisible()


def test_toggling_the_model_panel_shows_the_diagram_and_editor(app, win):
    win.toggle_model_panel()
    _settle(app, 3)
    assert win._model_dock.isVisible()
    assert win._act_model.isChecked()
    assert win._diagram.isVisible() and win._editor.isVisible()

    win.toggle_model_panel()
    _settle(app, 3)
    assert not win._model_dock.isVisible()
    assert not win._act_model.isChecked()


def test_the_context_bar_button_opens_the_model_panel(app, win):
    win._context.edit_requested.emit()
    _settle(app, 3)
    assert win._model_dock.isVisible()


def test_editing_a_block_still_reaches_every_tab(app, win):
    """Moving the editor into a dock must not break the wiring."""
    win.toggle_model_panel()
    _settle(app, 3)
    win._on_tf_edited("K2", ctl.tf([5], [1]))
    _settle(app, 3)
    assert float(ctl.dcgain(win._arch.block_tf("K2"))) == pytest.approx(5.0)
    assert "5" in win._context.summary()


# ──────────────────────────────────────────────────────────────
#  Labels
# ──────────────────────────────────────────────────────────────

def test_tab_labels_are_words_not_emoji(win):
    """
    `🔬 System` renders as an empty box wherever the emoji font is missing —
    as it does in this project's own headless screenshots — and it is not a
    label anything can read aloud.
    """
    for index in range(win._tabs.count()):
        label = win._tabs.tabText(index)
        assert label.isascii(), f"{label!r} contains non-ASCII characters"
        assert label.strip()


# ──────────────────────────────────────────────────────────────
#  Persistence
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def scratch_settings(monkeypatch):
    """Keep the tests out of the real registry."""
    monkeypatch.setattr(MainWindow, "SETTINGS_ORG", "FauxMatlabTest")
    monkeypatch.setattr(MainWindow, "SETTINGS_APP", "LayoutTest")
    yield
    QSettings("FauxMatlabTest", "LayoutTest").clear()


def test_layout_is_saved_and_restored(app, win, scratch_settings):
    win.resize(1310, 742)
    win._tabs.setCurrentIndex(3)
    win.toggle_model_panel()
    _settle(app)
    win.save_layout()

    win.resize(900, 600)
    win._tabs.setCurrentIndex(0)
    win._model_dock.hide()
    _settle(app)

    assert win.restore_layout()
    _settle(app)
    assert win._tabs.currentIndex() == 3
    assert win._model_dock.isVisible()


def test_restore_reports_when_there_is_nothing_saved(win, scratch_settings):
    QSettings(MainWindow.SETTINGS_ORG, MainWindow.SETTINGS_APP).clear()
    assert win.restore_layout() is False


def test_reset_layout_clears_the_saved_state(app, win, scratch_settings):
    win.toggle_model_panel()
    win.save_layout()
    _settle(app)

    win.reset_layout()
    _settle(app)
    assert not win._model_dock.isVisible()
    assert win._tabs.currentIndex() == 0
    assert win.restore_layout() is False, "reset must forget what was saved"


def test_the_view_menu_agrees_with_the_window_after_a_restore(app, win,
                                                             scratch_settings):
    """
    `restoreState` brings dock visibility back on its own, so the menu check
    marks have to be re-synchronised or they silently disagree.
    """
    win.toggle_model_panel()
    win.save_layout()
    win._model_dock.hide()
    win._act_model.setChecked(False)
    _settle(app)

    win.restore_layout()
    _settle(app)
    assert win._act_model.isChecked() == win._model_dock.isVisible()


# ──────────────────────────────────────────────────────────────
#  Design primitives
# ──────────────────────────────────────────────────────────────

def test_the_spacing_scale_has_four_steps_in_order():
    assert TIGHT < NORMAL < SECTION < PANEL
    assert (TIGHT, NORMAL, SECTION, PANEL) == (4, 8, 12, 16)


def test_status_is_never_communicated_by_colour_alone(app):
    """An accessibility requirement from the plan, as a test."""
    for status in Status:
        badge = StatusBadge(status, "example")
        assert badge.text().strip(), f"{status.name} has no text"
        assert status.symbol in badge.text()
        assert badge.accessibleName()


def test_a_metric_shows_a_dash_for_an_undefined_value(app):
    metric = MetricLabel("PM", "°")
    metric.set_value(float("nan"))
    assert metric._value.text() == "—"
    metric.set_value(60.0, "{:.1f}")
    assert metric._value.text() == "60.0 °"
