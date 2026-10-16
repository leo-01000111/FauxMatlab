"""
The command window as a widget: transcript, history, completion, figures,
and the two bridges to the rest of the app.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

import control as ctl
from PySide6.QtWidgets import QApplication

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.tf_utils import second_order
from fakematlab.ui.guard import ErrorBanner
from fakematlab.ui.mainwindow import MainWindow
from fakematlab.ui.workspace import Workspace


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    window = MainWindow(CourseArchitecture(G=second_order(1.0, 0.5, 2.0)))
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
    window._console.interpreter.clear()
    window._console.push(**window._console_state())
    window._figures.close_all()
    for banner in window.findChildren(ErrorBanner):
        banner.clear()
    _settle(app)
    yield


def _settle(app, rounds: int = 20) -> None:
    for _ in range(rounds):
        app.processEvents()


# ──────────────────────────────────────────────────────────────

def test_console_starts_with_the_app_state(app, win):
    """
    The plant is already in the workspace, so the first useful command does
    not have to be a re-declaration of what the window is already showing.
    """
    variables = win._console.interpreter.variables()
    assert {"G", "K2", "arch", "model"} <= set(variables)
    assert isinstance(variables["G"], ctl.TransferFunction)


def test_docks_start_hidden(app, win):
    """A console nobody asked for should not take a third of the window."""
    assert not win._console.isVisible()
    assert not win._figures.isVisible()


def test_a_command_runs_and_shows_in_the_transcript(app, win):
    result = win._console.execute("T = feedback(G, 1)")
    _settle(app)
    assert result.ok
    assert "T" in win._console.interpreter.variables()
    assert "T = feedback(G, 1)" in win._console.console._transcript.toPlainText()


def test_a_plot_command_opens_a_figure(app, win):
    assert win._figures.figure_count == 0
    win._console.execute("step(G)")
    _settle(app)
    assert win._figures.figure_count == 1
    assert win._figures.isVisible(), "drawing should reveal the figure dock"


@pytest.mark.parametrize("command", [
    "step(G)", "bode(G)", "nyquist(G)", "pzmap(G)", "rlocus(G)",
])
def test_every_figure_kind_renders(app, win, command):
    win._console.execute(command)
    _settle(app)
    assert win._figures.figure_count == 1
    assert not [b for b in win.findChildren(ErrorBanner) if b.has_error]


def test_figures_are_capped(app, win):
    from fakematlab.ui.console.console_dock import MAX_FIGURES

    for _ in range(MAX_FIGURES + 3):
        win._console.execute("step(G)")
    _settle(app)
    assert win._figures.figure_count == MAX_FIGURES


def test_workspace_lists_what_was_created(app, win):
    win._console.execute("myvar = 42")
    _settle(app)
    table = win._console.workspace._table
    names = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert "myvar" in names


def test_double_clicking_a_system_loads_it_as_the_plant(app, win):
    win._console.execute("H = tf([5], [1, 7])")
    _settle(app)
    win._on_console_system("H", win._console.interpreter.namespace["H"])
    _settle(app)

    assert np.allclose(np.atleast_1d(ctl.poles(win._arch.block_tf("G"))),
                       [-7.0])
    assert win._stack.current is Workspace.ANALYSE


def test_push_to_console_shares_the_loop(app, win):
    win._push_to_console()
    _settle(app)
    variables = win._console.interpreter.variables()
    assert {"G", "K2", "L", "T", "arch", "model"} <= set(variables)


def test_the_console_and_the_tabs_share_one_architecture(app, win):
    """
    ``arch`` is the live object, not a copy — a command at the prompt changes
    what the tabs analyse.
    """
    win._console.execute("arch.set_block('G', tf([3], [1, 3]))")
    _settle(app)
    assert np.allclose(np.atleast_1d(ctl.poles(win._arch.block_tf("G"))),
                       [-3.0])


def test_an_error_is_shown_without_stopping_the_session(app, win):
    result = win._console.execute("1/0")
    _settle(app)
    assert result.error
    assert "ZeroDivisionError" in win._console.console._transcript.toPlainText()
    assert win._console.execute("ok = 1").ok


def test_history_recall(app, win):
    win._console.execute("first = 1")
    win._console.execute("second = 2")
    console = win._console.console
    console._recall(-1)
    assert console._input.text() == "second = 2"
    console._recall(-1)
    assert console._input.text() == "first = 1"
    console._input.clear()


def test_tab_completion_fills_in(app, win):
    console = win._console.console
    console._input.setText("stepin")
    console._input.setCursorPosition(6)
    console._complete()
    assert console._input.text() == "stepinfo"
    console._input.clear()


def test_script_editor_runs_against_the_same_workspace(app, win):
    win._console.editor.set_text("alpha = 7\nbeta = alpha * 2")
    win._console._run_script(win._console.editor.text())
    _settle(app)
    assert win._console.interpreter.namespace["beta"] == 14


def test_simulink_model_is_in_the_workspace(app, win):
    from fakematlab.sim.model import SimModel

    model = win._console.interpreter.namespace.get("model")
    assert isinstance(model, SimModel)
    result = win._console.execute("r = sim(model, 2.0)")
    _settle(app)
    assert result.ok
    assert len(win._console.interpreter.namespace["r"].t) > 10


# ──────────────────────────────────────────────────────────────
#  Running a whole script starts from a clean slate
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def answers(win, monkeypatch, tmp_path):
    """Stand in for the save prompt and the folder picker, and record them."""
    record = {"asked": [], "answer": "discard", "folder": tmp_path}
    panel = win._console

    def ask(count):
        record["asked"].append(count)
        return record["answer"]

    monkeypatch.setattr(panel, "_ask_to_save_figures", ask)
    monkeypatch.setattr(panel, "_choose_figure_folder",
                        lambda: record["folder"])
    yield record
    win._figures.set_split(False)


def _transcript(win) -> str:
    return win._console.console._transcript.toPlainText()


def test_running_a_script_twice_does_not_append(app, win, answers):
    win._console.editor.set_text("alpha = 7\nprint(alpha * 6)")
    win._console._run_script(win._console.editor.text())
    win._console._run_script(win._console.editor.text())
    _settle(app)
    assert _transcript(win).count("alpha = 7") == 1
    assert _transcript(win).count("42") == 1


def test_commands_at_the_prompt_still_append(app, win):
    win._console.execute("x = 1")
    win._console.execute("x = 1")
    _settle(app)
    assert _transcript(win).count(">> x = 1") == 2


def test_a_run_replaces_the_last_runs_figures_but_not_the_prompts(
        app, win, answers):
    win._console.execute("bode(G)")                 # typed: not a script's
    script = "s = tf('s');\nH = 1/(s+1);\nstep(H)\nnyquist(H)"
    win._console._run_script(script, "matlab")
    _settle(app)
    assert win._figures.figure_count == 3
    win._console._run_script(script, "matlab")
    _settle(app)
    kinds = sorted(v.spec.kind for v in win._figures.figures)
    assert win._figures.figure_count == 3, kinds
    assert answers["asked"] == [2]
    assert not any(v.from_script for v in win._figures.figures
                   if v.spec.kind == "bode")


def test_unsaved_figures_are_saved_under_placeholder_names(
        app, win, answers, tmp_path):
    answers["answer"] = "save"
    win._console._run_script("step(G)\nbode(G)", "python")
    win._console._run_script("step(G)", "python")
    _settle(app)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "figure_1.png", "figure_2.png"]
    assert "Saved 2 figures" in _transcript(win)

    # A third run saves beside them rather than over them.
    win._console._run_script("step(G)", "python")
    _settle(app)
    assert "figure_3.png" in {p.name for p in tmp_path.iterdir()}


def test_figures_already_saved_are_not_asked_about(app, win, answers,
                                                   tmp_path):
    win._console._run_script("step(G)", "python")
    _settle(app)
    (view,) = win._figures.script_figures()
    assert win._figures.save_figure(view, tmp_path / "mine.png")
    win._console._run_script("step(G)", "python")
    _settle(app)
    assert answers["asked"] == []
    assert win._figures.figure_count == 1


def test_cancelling_the_prompt_leaves_everything_as_it_was(app, win, answers):
    win._console._run_script("first_run = 1\nstep(G)", "python")
    _settle(app)
    before = _transcript(win)
    answers["answer"] = "cancel"
    assert win._console._run_script("second_run = 2", "python") is False
    _settle(app)
    assert _transcript(win) == before
    assert "second_run" not in win._console.interpreter.namespace
    assert win._figures.figure_count == 1


def test_placeholder_names_skip_files_already_there(tmp_path):
    from fakematlab.ui.console.console_dock import placeholder_names

    (tmp_path / "figure_2.png").write_bytes(b"")
    names = [p.name for p in placeholder_names(tmp_path, 3)]
    assert names == ["figure_1.png", "figure_3.png", "figure_4.png"]


# ──────────────────────────────────────────────────────────────
#  Undocking and side-by-side figures
# ──────────────────────────────────────────────────────────────

def test_a_figure_undocks_into_its_own_window_and_back(app, win):
    win._console.execute("step(G)")
    _settle(app)
    figures = win._figures
    view = figures.current_figure()
    window = figures.undock()
    _settle(app)
    assert window is not None and window.isWindow() and window.isVisible()
    assert view.window() is window             # the live widget, reparented
    assert figures._tabs.count() == 0
    assert figures.figure_count == 1           # still open, just elsewhere

    window.close()                             # closing docks it back
    _settle(app)
    assert figures.window_for(view) is None
    assert figures._tabs.indexOf(view) >= 0


def test_closing_all_figures_closes_undocked_windows(app, win):
    win._console.execute("step(G)")
    _settle(app)
    window = win._figures.undock()
    win._figures.close_all()
    _settle(app)
    assert win._figures.figure_count == 0
    assert not window.isVisible()


def test_two_figures_side_by_side(app, win, answers):
    figures = win._figures
    win._console.execute("step(G)")
    assert not figures._split_button.isEnabled()   # nothing to compare yet
    win._console.execute("bode(G)")
    _settle(app)
    newest = figures.current_figure()

    figures.set_split(True)
    _settle(app)
    assert figures.split
    assert figures._tabs.count() == 1 and figures._side.count() == 1
    assert figures._side.currentWidget() is newest
    assert figures._tabs.isVisible() and figures._side.isVisible()

    figures.move_to_other_side(newest)          # emptying a side unsplits
    _settle(app)
    assert not figures.split
    assert figures._tabs.count() == 2

    figures.set_split(True)
    figures.set_split(False)
    assert figures._tabs.count() == 2 and figures._side.count() == 0
