"""
Files named on the command line.

``Evans.exe model.fmdl`` is what the installer's file association sends when
someone double-clicks a model, so a model passed that way has to land on the
Model canvas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evans.app import _file_arguments


def test_no_arguments_means_no_files():
    assert _file_arguments([]) == []


def test_a_model_path_is_a_file():
    assert _file_arguments([r"C:\models\loop.fmdl"]) == [
        Path(r"C:\models\loop.fmdl")]


def test_options_are_not_files():
    assert _file_arguments(["--quiet", "-style", "a b.fmdl", ""]) == [
        Path("a b.fmdl")]


def test_several_files_keep_their_order():
    assert _file_arguments(["one.fmdl", "two.m"]) == [
        Path("one.fmdl"), Path("two.m")]


@pytest.fixture(scope="module")
def window():
    from PySide6.QtWidgets import QApplication

    from evans.core.architecture import CourseArchitecture
    from evans.core.tf_utils import second_order, unity
    from evans.ui.mainwindow import MainWindow

    QApplication.instance() or QApplication([])
    arch = CourseArchitecture(G=second_order(K=1.0, zeta=0.5, wn=2.0),
                              K2=unity(), K1=unity(), H=unity())
    win = MainWindow(arch)
    yield win
    win.close()
    win.deleteLater()


def test_a_model_argument_opens_on_the_model_canvas(window, tmp_path):
    from evans.sim.model import SimModel
    from evans.ui.workspace import Workspace

    path = tmp_path / "from-the-shell.fmdl"
    SimModel("from-the-shell").save(path)

    (arg,) = _file_arguments([str(path)])
    assert window.open_recent(arg)
    assert window._stack.current is Workspace.MODEL
    assert window._sim_tab._canvas.root_model().name == "from-the-shell"


def test_a_missing_file_does_not_fail_the_launch(window, tmp_path):
    (arg,) = _file_arguments([str(tmp_path / "gone.fmdl")])
    assert window.open_recent(arg) is False
