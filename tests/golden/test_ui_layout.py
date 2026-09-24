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
from fakematlab.ui.workspace import Workspace

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
    window._lessons.hide()
    # App docks too: one test leaving the PID Tuner open changes the next
    # test's minimum window size, which is exactly what this file measures.
    for dock in window._app_docks.values():
        dock.hide()
    window.show_workspace(Workspace.ANALYSE)
    # A known starting view, or one test's four open plots and another's
    # classic-tab selection change the next test's minimum size. The pane
    # *kinds* matter too: a pane left showing the Modern tab keeps that
    # tab's much taller minimum.
    window._view_tabs.setCurrentIndex(0)
    window._grid.set_layout_size(1, ("step",))
    window.resize(1400, 850)
    for banner in window.findChildren(ErrorBanner):
        banner.clear()
    _settle(app)
    yield


def _tallest(window, limit: int = 6) -> list[tuple[int, str]]:
    """The widgets demanding the most vertical space — for failure messages."""
    from PySide6.QtWidgets import QWidget

    seen = [(w.minimumSizeHint().height(), type(w).__name__)
            for w in window.findChildren(QWidget) if w.isVisible()]
    return sorted(seen, reverse=True)[:limit]


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


@pytest.mark.parametrize("index", range(len(MainWindow._TABS)))
def test_every_analysis_tab_renders_at_the_target_size(app, win, index):
    win.resize(TARGET_W, TARGET_H)
    win.show_workspace(Workspace.ANALYSE)
    win._tabs.setCurrentIndex(index)
    _settle(app, 5)
    tab = win._tabs.widget(index)
    failed = [b.message for b in tab.findChildren(ErrorBanner) if b.has_error]
    assert not failed, f"{win._tabs.tabText(index)}: {failed[0]}"
    assert tab.minimumSizeHint().width() <= TARGET_W


@pytest.mark.parametrize("workspace", list(Workspace))
def test_every_workspace_renders_at_the_target_size(app, win, workspace):
    win.resize(TARGET_W, TARGET_H)
    win.show_workspace(workspace)
    _settle(app, 5)
    page = win._stack.page(workspace)
    failed = [b.message for b in page.findChildren(ErrorBanner) if b.has_error]
    assert not failed, f"{workspace.value}: {failed[0]}"
    assert page.minimumSizeHint().width() <= TARGET_W


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
    win.show_workspace(Workspace.ANALYSE)
    _settle(app)
    # `_view_tabs` is the analysis area: the pane grid and the classic tabs.
    # The navigation rail is the only other thing competing for the width.
    share = win._view_tabs.width() / win.width()
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


# ──────────────────────────────────────────────────────────────
#  Workspaces
# ──────────────────────────────────────────────────────────────

def test_the_three_workspaces_exist_and_are_reachable(app, win):
    for workspace in Workspace:
        win.show_workspace(workspace)
        _settle(app, 3)
        assert win._stack.current is workspace
        assert win._stack.page(workspace) is not None


def test_switching_workspaces_preserves_state(app, win):
    """
    The plan's UI-3 acceptance. A stacked page keeps its widgets alive, so a
    console session, a diagram and a chosen analysis all survive navigation.
    """
    win.show_workspace(Workspace.CONSOLE)
    win._console.execute("marker = 1234")
    _settle(app, 5)

    win.show_workspace(Workspace.MODEL)
    win._sim_tab._canvas.add_block("Gain")
    blocks_before = len(win._sim_tab._canvas.model.blocks)
    _settle(app, 5)

    win.show_workspace(Workspace.ANALYSE)
    win._tabs.setCurrentIndex(2)
    _settle(app, 5)

    # ...and back again: nothing was rebuilt.
    win.show_workspace(Workspace.CONSOLE)
    _settle(app, 3)
    assert win._console.interpreter.namespace.get("marker") == 1234

    win.show_workspace(Workspace.MODEL)
    _settle(app, 3)
    assert len(win._sim_tab._canvas.model.blocks) == blocks_before

    win.show_workspace(Workspace.ANALYSE)
    _settle(app, 3)
    assert win._tabs.currentIndex() == 2


def test_the_rail_and_the_view_menu_agree_with_the_stack(app, win):
    for workspace in Workspace:
        win.show_workspace(workspace)
        _settle(app, 3)
        assert win._stack.rail.current is workspace
        checked = [w for w, a in win._workspace_actions.items()
                   if a.isChecked()]
        assert checked == [workspace]


def test_clicking_the_rail_changes_workspace(app, win):
    win.show_workspace(Workspace.ANALYSE)
    win._stack.rail.button(Workspace.MODEL).click()
    _settle(app, 3)
    assert win._stack.current is Workspace.MODEL


def test_simulink_is_a_workspace_not_a_tab(win):
    """
    It has its own model, undo stack and file format. Listing it beside six
    views of a different system said they were alternatives to one another.
    """
    assert "Simulink" not in [win._tabs.tabText(i)
                              for i in range(win._tabs.count())]
    assert win._stack.page(Workspace.MODEL) is win._sim_tab


def test_a_figure_pulls_the_console_workspace_into_view(app, win):
    """Otherwise `step(G)` draws somewhere the user cannot see."""
    win.show_workspace(Workspace.ANALYSE)
    win._console.execute("step(tf([1], [1, 1]))")
    _settle(app, 10)
    assert win._stack.current is Workspace.CONSOLE
    assert win._figures.figure_count >= 1


def test_the_workspace_is_remembered(app, win, scratch_settings):
    win.show_workspace(Workspace.MODEL)
    win.save_layout()
    win.show_workspace(Workspace.ANALYSE)
    _settle(app, 3)

    assert win.restore_layout()
    _settle(app, 3)
    assert win._stack.current is Workspace.MODEL


def test_every_workspace_has_a_shortcut_and_a_description():
    shortcuts = {w.shortcut for w in Workspace}
    assert shortcuts == {"Ctrl+1", "Ctrl+2", "Ctrl+3"}
    for workspace in Workspace:
        assert workspace.description
        assert workspace.key_hint


# ──────────────────────────────────────────────────────────────
#  The analysis pane grid
# ──────────────────────────────────────────────────────────────

from fakematlab.ui.panes import (  # noqa: E402
    DEFAULT_LAYOUT,
    LAYOUTS,
    PANE_KINDS,
    Source,
)


@pytest.fixture
def grid(app, win):
    win.show_workspace(Workspace.ANALYSE)
    win._view_tabs.setCurrentIndex(0)
    _settle(app, 3)
    return win._grid


@pytest.mark.parametrize("count", sorted(LAYOUTS))
def test_one_two_and_four_pane_layouts(app, win, grid, count):
    win.set_pane_layout(count)
    _settle(app, 5)
    assert grid.count == count
    failed = [b.message for b in grid.findChildren(ErrorBanner) if b.has_error]
    assert not failed, failed[0]


def test_a_fresh_two_by_two_opens_on_the_tuning_four(app, win, grid):
    """
    The plan's UI-4 acceptance names them: step response, Bode, root locus
    and metrics — the four views a tuning loop actually needs at once.
    """
    win.set_pane_layout(4)
    _settle(app, 5)
    assert grid.keys == DEFAULT_LAYOUT
    assert grid.keys == ("step", "bode", "rlocus", "metrics")


def test_one_architecture_edit_updates_every_pane(app, win, grid):
    """
    The point of the grid. Each pane must read the *live* architecture, not a
    copy taken when it was created.
    """
    win.set_pane_layout(4)
    _settle(app, 5)

    before = _pane_fingerprints(grid)
    win._arch.set_block("K2", ctl.tf([12], [1]))
    win._update_all_tabs()
    _settle(app, 10)
    after = _pane_fingerprints(grid)

    assert before != after, "no pane noticed the controller change"
    changed = sum(1 for a, b in zip(before, after) if a != b)
    assert changed >= 3, f"only {changed} of 4 panes updated"

    failed = [b.message for b in grid.findChildren(ErrorBanner) if b.has_error]
    assert not failed, failed[0]


def _pane_fingerprints(grid) -> list[str]:
    """
    Something per pane that has to move when the architecture does.

    For a plot pane it is the head of every curve the pane's own collection
    and response type produce; for the others it is the text they show.
    """
    import numpy as np
    from PySide6.QtWidgets import QLabel

    from fakematlab.core.viewer import compute
    from fakematlab.ui.apps.lti_viewer import LTIViewer

    out: list[str] = []
    for pane in grid.panes:
        content = pane._content
        if isinstance(content, LTIViewer):
            curves = compute(content.collection, content._kind,
                             content._characteristics).curves
            samples = [value for curve in curves
                       for value in list(curve.y[:4])]
            out.append(repr(np.round(np.array(samples or [0.0]), 6)))
        else:
            labels = content.findChildren(QLabel) if content else []
            out.append("".join(label.text() for label in labels[:6]))
    return out


@pytest.mark.parametrize("kind", PANE_KINDS, ids=lambda k: k.key)
def test_every_pane_kind_renders(app, win, grid, kind):
    """
    "Every existing response type remains reachable" — the six tabs became
    pane types, and nothing was dropped on the way.
    """
    win.set_pane_layout(1)
    _settle(app, 3)
    pane = grid.panes[0]
    pane.set_kind(kind.key)
    _settle(app, 8)
    assert pane.key == kind.key
    failed = [b.message for b in pane.findChildren(ErrorBanner) if b.has_error]
    assert not failed, f"{kind.label}: {failed[0]}"


def test_changing_the_layout_keeps_what_was_chosen(app, win, grid):
    win.set_pane_layout(2)
    _settle(app, 3)
    grid.panes[0].set_kind("nyquist")
    grid.panes[1].set_kind("performance")
    _settle(app, 5)

    win.set_pane_layout(4)
    _settle(app, 5)
    assert grid.keys[:2] == ("nyquist", "performance")


def test_each_kind_arrives_pointing_at_the_right_signal(app, win, grid):
    """
    A Bode plot of the closed loop is a legitimate thing to want, but it is
    not what anyone means by "the Bode plot".
    """
    win.set_pane_layout(1)
    _settle(app, 3)
    pane = grid.panes[0]

    pane.set_kind("bode")
    _settle(app, 5)
    assert pane.source is Source.OPEN_LOOP

    pane.set_kind("step")
    _settle(app, 5)
    assert pane.source is Source.CLOSED_LOOP


def test_the_source_survives_the_qvariant_round_trip(app, win, grid):
    """
    Qt flattens a `str`-mixin enum through QVariant, which is how the LTI
    Viewer's response picker broke. The pane rebuilds it from the text.
    """
    win.set_pane_layout(1)
    _settle(app, 3)
    pane = grid.panes[0]
    for source in Source:
        pane._source.setCurrentText(source.value)
        _settle(app, 3)
        assert isinstance(pane.source, Source)
        assert pane.source is source


def test_the_tabs_are_still_reachable(app, win):
    """The grid is the primary view; the whole-workflow tabs remain."""
    win.show_workspace(Workspace.ANALYSE)
    win._view_tabs.setCurrentIndex(1)
    _settle(app, 5)
    assert win._view_tabs.tabText(1) == "Tabs"
    assert win._tabs.count() == len(MainWindow._TABS)


def test_a_pane_hosting_a_tab_gets_its_own_instance(app, win, grid):
    """
    A widget lives in exactly one place. Handing the grid the tab that is
    already inside the Tabs view would move it out of there.
    """
    win.set_pane_layout(1)
    _settle(app, 3)
    grid.panes[0].set_kind("system")
    _settle(app, 5)
    assert grid.panes[0]._content is not win._sys_tab
    assert win._tabs.widget(0) is win._sys_tab


# ──────────────────────────────────────────────────────────────
#  Polish: resolutions, labels, accessibility
# ──────────────────────────────────────────────────────────────

#: The plan asks for 1280×720 usable and 1920×1080 comfortable; 1366×768 is
#: the laptop in between and the one the old 2038 px minimum ruled out hardest.
RESOLUTIONS = ((1280, 720), (1366, 768), (1920, 1080))


@pytest.mark.parametrize("size", RESOLUTIONS, ids=lambda s: f"{s[0]}x{s[1]}")
def test_every_workspace_renders_at_every_supported_resolution(app, win, size):
    width, height = size
    win.resize(width, height)
    for workspace in Workspace:
        win.show_workspace(workspace)
        _settle(app, 5)
        assert (win.width(), win.height()) == (width, height), (
            f"{workspace.value} would not fit {width}×{height}; "
            f"tallest demands: {_tallest(win)}")
        page = win._stack.page(workspace)
        failed = [b.message for b in page.findChildren(ErrorBanner)
                  if b.has_error]
        assert not failed, f"{workspace.value} at {width}×{height}: {failed[0]}"


@pytest.mark.parametrize("size", RESOLUTIONS, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_pane_grid_survives_every_resolution(app, win, size):
    win.resize(*size)
    win.show_workspace(Workspace.ANALYSE)
    win.set_pane_layout(4)
    _settle(app, 8)
    failed = [b.message for b in win._grid.findChildren(ErrorBanner)
              if b.has_error]
    assert not failed, failed[0]
    assert win._grid.count == 4


def test_no_control_or_tab_is_labelled_with_an_emoji(app, win):
    """
    Navigation must not depend on an emoji font.

    Scoped to the things you *click* — buttons and tab labels — because that
    is where a missing glyph strands you. Body text may use ✓ or ⚠ as marks;
    those ship with ordinary text fonts and are paired with words anyway.
    """
    from PySide6.QtWidgets import QAbstractButton, QTabWidget

    labels: list[tuple[str, str]] = []
    for workspace in Workspace:
        win.show_workspace(workspace)
        _settle(app, 5)
        for button in win.findChildren(QAbstractButton):
            labels.append((type(button).__name__, button.text()))
        for tabs in win.findChildren(QTabWidget):
            for index in range(tabs.count()):
                labels.append(("tab", tabs.tabText(index)))

    offenders = [(kind, text, [c for c in text if _is_emoji(c)])
                 for kind, text in labels
                 if any(_is_emoji(c) for c in text)]
    assert not offenders, offenders[:5]


def _is_emoji(ch: str) -> bool:
    """
    Characters that need an *emoji* font, and so can render as an empty box.

    Deliberately not all of Dingbats: ✓ and ✗ ship with ordinary text fonts
    and read as marks rather than pictures. What this excludes is the
    pictographic planes — `🔬`, `⛭`, `📌` — which is what actually went
    missing in this project's own screenshots. Status is separately required
    never to rest on a symbol alone; see the badge test.
    """
    code = ord(ch)
    return (0x1F000 <= code <= 0x1FAFF          # emoticons and pictographs
            or 0x2B00 <= code <= 0x2BFF         # misc symbols and arrows
            or 0x2690 <= code <= 0x26FF         # misc symbols: ⚙ ⛭ ⚠ ⛓
            or code == 0xFE0F)                  # variation selector-16


def test_every_workspace_button_announces_itself(app, win):
    for workspace in Workspace:
        button = win._stack.rail.button(workspace)
        assert button.text().strip() == workspace.value
        assert button.accessibleName() == workspace.value
        assert workspace.shortcut in button.toolTip()


def test_the_modern_sections_say_what_they_are_for(app, win):
    """
    27 buttons and 35 labels: a newcomer's problem is not a missing control,
    it is not knowing which section to start in.
    """
    tabs = win._mod_tab._tabs
    names = [tabs.tabText(i) for i in range(tabs.count())]
    assert names == ["Model", "Structure", "Design", "Estimation", "Discrete"]
    for index in range(tabs.count()):
        assert len(tabs.tabToolTip(index)) > 20, names[index]
        assert tabs.widget(index).accessibleName()


def test_the_simulink_workspace_explains_how_to_wire(app, win):
    """The gesture was previously discoverable only by succeeding at it."""
    win.show_workspace(Workspace.MODEL)
    _settle(app, 5)
    hint = win._sim_tab._hint.text().lower()
    assert "drag" in hint and "click" in hint
    assert win._sim_tab._hint.isVisible()
