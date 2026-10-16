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


# ──────────────────────────────────────────────────────────────
#  Command history
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def history(win):
    panel = win._console.history
    panel.clear()
    panel.set_filter("")
    yield panel
    panel.set_filter("")
    panel.clear()


def test_typed_commands_are_listed_in_the_history(app, win, history):
    win._console.execute("hx = 1")
    win._console.execute("hx = 1")              # an immediate repeat: once
    win._console.execute("hy = hx + 1")
    _settle(app)
    assert history.commands() == ["hx = 1", "hy = hx + 1"]


def test_script_lines_stay_out_of_the_history(app, win, history, answers):
    win._console.execute("typed = 1")
    win._console._run_script("from_script = 2", "python")
    _settle(app)
    assert history.commands() == ["typed = 1"]


def test_the_history_outlives_the_session(app, win, history):
    from fakematlab.ui.console.history_widget import HistoryWidget
    from fakematlab.ui.persist import CommandHistory

    win._console.execute("kept = 3")
    _settle(app)
    assert CommandHistory().items[-1] == "kept = 3"
    assert HistoryWidget().commands()[-1] == "kept = 3"


def test_the_history_filter(app, win, history):
    for command in ("step(G)", "bode(G)", "Gs = step(G)"):
        win._console.execute(command)
    history.set_filter("STEP")                  # case does not matter
    assert history.commands(visible_only=True) == ["step(G)", "Gs = step(G)"]
    win._console.execute("stepinfo(G)")         # arrives filtered too
    win._console.execute("margin(G)")
    assert history.commands(visible_only=True)[-1] == "stepinfo(G)"
    history.set_filter("")
    assert len(history.commands(visible_only=True)) == 5


def test_double_click_puts_a_command_back_at_the_prompt(app, win, history):
    win._console.execute("recalled = 5")
    _settle(app)
    item = history._list.item(0)
    history._list.itemDoubleClicked.emit(item)
    assert win._console.console._input.text() == "recalled = 5"
    win._console.console._input.clear()


def test_run_again_from_the_context_menu(app, win, history):
    win._console.execute("counter = 1")
    win._console.execute("counter = counter + 1")
    _settle(app)
    history._list.setCurrentRow(1)
    menu = history.context_menu()
    run = next(a for a in menu.actions() if a.text() == "Run again")
    run.trigger()
    _settle(app)
    assert win._console.interpreter.namespace["counter"] == 3


def test_the_history_is_a_tab_beside_the_workspace(app, win):
    panel = win._console
    tabs = panel._side
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Workspace", "History"]
    panel.show_history()
    assert tabs.currentWidget() is panel.history
    tabs.setCurrentWidget(panel.workspace)


# ──────────────────────────────────────────────────────────────
#  Recent files
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def recent(win):
    win.recent_files.clear()
    yield win.recent_files
    win.recent_files.clear()


def test_recent_files_are_newest_first_without_repeats(tmp_path, recent):
    paths = []
    for name in ("a.m", "b.fmdl", "c.py"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
        paths.append(tmp_path / name)
        recent.add(tmp_path / name)
    recent.add(paths[0])                         # reopened: moves to the top
    recent.add(tmp_path / "notes.txt")           # not a script or model
    assert [p.name for p in recent.paths()] == ["a.m", "c.py", "b.fmdl"]


def test_recent_files_keep_ten(tmp_path, recent):
    for n in range(14):
        path = tmp_path / f"s{n}.m"
        path.write_text("", encoding="utf-8")
        recent.add(path)
    names = [p.name for p in recent.paths()]
    assert len(names) == 10 and names[0] == "s13.m"


def test_missing_recent_files_are_forgotten(tmp_path, recent):
    from fakematlab.ui.persist import RecentFiles

    gone = tmp_path / "gone.m"
    gone.write_text("", encoding="utf-8")
    recent.add(gone)
    gone.unlink()
    assert recent.paths() == []
    assert RecentFiles()._stored() == []         # and the forgetting sticks


def test_the_recent_menu_lists_and_clears(app, win, tmp_path, recent):
    script = tmp_path / "loop.m"
    script.write_text("x = 1;\n", encoding="utf-8")
    recent.add(script)
    win._fill_recent_menu()
    texts = [a.text() for a in win._recent_menu.actions() if a.text()]
    assert any("loop.m" in t for t in texts)
    clear = next(a for a in win._recent_menu.actions()
                 if "Clear recent" in a.text())
    clear.trigger()
    win._fill_recent_menu()
    actions = win._recent_menu.actions()
    assert not any("loop.m" in a.text() for a in actions)
    assert not next(a for a in actions
                    if "Clear recent" in a.text()).isEnabled()


def test_opening_a_script_records_it_and_reopens_it(app, win, tmp_path,
                                                    recent):
    script = tmp_path / "first.m"
    script.write_text("a = 1;\n", encoding="utf-8")
    win._console.editor.load_file(script)
    assert recent.paths() == [script.resolve()]

    win._console.editor.set_text("")
    assert win.open_recent(script)
    _settle(app)
    assert win._console.editor.text() == "a = 1;\n"
    assert win._stack.current is Workspace.CONSOLE
    assert win._console._tabs.currentWidget() is win._console.editor
    win._console._tabs.setCurrentIndex(0)


def test_a_recent_model_opens_on_the_canvas(app, win, tmp_path, recent):
    path = tmp_path / "loop.fmdl"
    win._sim_tab._canvas.root_model().save(path)
    recent.add(path)
    assert win.open_recent(path)
    _settle(app)
    assert win._stack.current is Workspace.MODEL
    assert recent.paths()[0] == path.resolve()


# ──────────────────────────────────────────────────────────────
#  Figure export
# ──────────────────────────────────────────────────────────────

def _figure(app, win, command: str):
    win._console.execute(command)
    _settle(app)
    return win._figures.current_figure()


@pytest.mark.parametrize("command", ["step(G)", "bode(G)"])
def test_a_figure_exports_as_png_svg_and_csv(app, win, tmp_path, command):
    from fakematlab.ui.console.figure_view import export_figure

    view = _figure(app, win, command)
    png = export_figure(view, tmp_path / "f.png")
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    svg = (export_figure(view, tmp_path / "f.svg")
           .read_text(encoding="utf-8"))
    assert svg.lstrip().startswith("<?xml") and svg.rstrip().endswith("</svg>")
    # One nested plot per pane: a Bode diagram is two.
    assert svg.count("<svg") == 1 + len(view.plot_widgets())
    assert view.saved


def test_csv_has_an_x_and_a_y_column_per_series(app, win, tmp_path):
    import csv

    from fakematlab.ui.console.figure_view import export_figure

    view = _figure(app, win, "bode(G)")
    with export_figure(view, tmp_path / "bode.csv").open(
            encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header, first = rows[0], rows[1]
    assert len(header) == 4                     # magnitude x/y, phase x/y
    assert "phase" in header[3]
    trace = view.spec.traces[0]
    assert len(rows) - 1 == len(trace.x)
    assert float(first[0]) == pytest.approx(trace.x[0])
    assert float(first[1]) == pytest.approx(trace.y[0])


def test_an_unknown_extension_is_refused(app, win, tmp_path):
    from fakematlab.ui.console.figure_view import export_figure

    view = _figure(app, win, "step(G)")
    with pytest.raises(ValueError, match=".png"):
        export_figure(view, tmp_path / "f.gif")


def test_the_plot_menu_offers_export(app, win, tmp_path, monkeypatch):
    from fakematlab.ui.console import figure_view

    view = _figure(app, win, "step(G)")
    menu = view.plot_widgets()[0].getPlotItem().getViewBox().menu
    export = next(a.menu() for a in menu.actions()
                  if a.text() == "Export figure")
    labels = [a.text() for a in export.actions()]
    assert labels == ["As PNG image…", "As SVG vector image…",
                      "Data as CSV…"]

    # A name typed without an extension takes the chosen filter's.
    monkeypatch.setattr(
        figure_view.QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "plain"),
                                 figure_view.EXPORT_FILTERS["svg"]))
    export.actions()[1].trigger()
    assert (tmp_path / "plain.svg").is_file()


def test_the_save_button_saves_svg_too(app, win, tmp_path, monkeypatch):
    from fakematlab.ui.console import figure_view

    view = _figure(app, win, "step(G)")
    monkeypatch.setattr(
        figure_view.QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "saved.csv"), ""))
    win._figures.save_current()
    assert (tmp_path / "saved.csv").is_file()
    assert view.saved
