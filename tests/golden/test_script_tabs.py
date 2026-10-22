"""
Several scripts open at once: the Script tab's tabs, their files, and a
debugger that follows a run into the function files it calls.
"""

from __future__ import annotations

import pytest

from evans.console.tracer import CONTINUE, STEP_IN, file_key

pytest.importorskip("PySide6", reason="Qt not available")


@pytest.fixture(scope="module")
def panel():
    from PySide6.QtWidgets import QApplication

    from evans.console.figures import set_figure_sink
    from evans.ui.console import ConsolePanel, FigureArea

    app = QApplication.instance() or QApplication([])
    previous = set_figure_sink(None)
    set_figure_sink(previous)
    widget = ConsolePanel(FigureArea())
    widget.resize(900, 600)
    widget.show()
    app.processEvents()
    yield widget
    widget.hide()
    set_figure_sink(previous)


@pytest.fixture
def editor(panel, monkeypatch):
    """The panel's editor, down to one blank tab, discarding what was there."""
    editor = panel.editor
    monkeypatch.setattr(editor, "_ask_to_save", lambda _doc: "discard")
    for document in editor.documents():
        editor.close_document(document)
    monkeypatch.undo()
    panel.interpreter.tracer.breakpoints = set()
    return editor


def _later(ms: int, fn) -> None:
    from PySide6.QtCore import QTimer
    QTimer.singleShot(ms, fn)


def _write(path, text: str):
    path.write_text(text, encoding="utf-8")
    return path


# ── tabs and files ──────────────────────────────────────────────

def test_new_tabs_are_untitled_and_numbered(editor):
    first = editor.current_document()
    assert first.blank and first.name.startswith("Untitled ")
    second = editor.new_document()
    assert second.number == first.number + 1
    assert editor.current_document() is second
    assert len(editor.documents()) == 2


def test_typing_marks_the_tab_unsaved(editor):
    document = editor.current_document()
    editor.set_text("x = 1;")
    index = editor._tabs.indexOf(document.code)
    assert document.modified
    assert editor._tabs.tabText(index).endswith("●")


def test_opening_a_file_reuses_the_blank_tab_and_never_doubles(editor,
                                                               tmp_path):
    path = _write(tmp_path / "one.m", "a = 1;\n")
    blank = editor.current_document()
    document = editor.load_file(path)
    assert document is blank and document.path == path.resolve()
    assert not document.modified
    editor.new_document()
    assert editor.load_file(path) is document           # its tab, shown
    assert editor.current_document() is document
    assert len(editor.documents()) == 2


def test_closing_an_unsaved_tab_asks(editor, monkeypatch):
    editor.set_text("unsaved = 1;")
    document = editor.current_document()
    monkeypatch.setattr(editor, "_ask_to_save", lambda _doc: "cancel")
    assert not editor.close_document(document)
    assert document in editor.documents()
    monkeypatch.setattr(editor, "_ask_to_save", lambda _doc: "discard")
    assert editor.close_document(document)
    # The last tab closed leaves a fresh one, never an empty tab bar.
    assert len(editor.documents()) == 1 and editor.current_document().blank


def test_save_writes_the_file_and_clears_the_mark(editor, tmp_path,
                                                  monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    target = tmp_path / "saved.m"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(target), ""))
    editor.set_text("k = 3;")
    assert editor.save()
    document = editor.current_document()
    assert target.read_text(encoding="utf-8") == "k = 3;"
    assert document.path == target.resolve() and not document.modified
    editor.set_text("k = 4;")
    assert editor.save()                     # its file now: no dialog needed
    assert target.read_text(encoding="utf-8") == "k = 4;"


def test_ctrl_s_saves_the_script_not_the_session(editor, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    path = _write(tmp_path / "keyed.m", "a = 1;\n")
    document = editor.load_file(path)
    editor.set_text("a = 2;\n")
    document.code.setFocus()
    QTest.keyClick(document.code, Qt.Key_S, Qt.ControlModifier)
    assert path.read_text(encoding="utf-8") == "a = 2;\n"
    assert not document.modified


def test_quitting_settles_every_unsaved_tab(editor, monkeypatch):
    editor.set_text("one = 1;")
    editor.new_document()
    editor.set_text("two = 2;")
    asked = []

    def answer(document):
        asked.append(document.name)
        return "discard" if len(asked) == 1 else "cancel"

    monkeypatch.setattr(editor, "_ask_to_save", answer)
    assert not editor.confirm_close_all()      # cancelled at the second
    assert len(asked) == 2


def test_open_files_come_back_where_they_were_left(editor, tmp_path):
    first = _write(tmp_path / "first.m", "a = 1;\nb = 2;\nc = 3;\n")
    second = _write(tmp_path / "second.m", "d = 4;\n")
    editor.load_file(first).code.goto_line(3)
    editor.load_file(second)
    editor.load_file(first)                       # the one showing
    editor.remember_open()

    for document in editor.documents():
        editor.close_document(document)
    assert editor.reopen_remembered() == 2
    names = [d.name for d in editor.documents()]
    assert names == ["first.m", "second.m"]
    current = editor.current_document()
    assert current.name == "first.m"
    assert current.code.textCursor().blockNumber() + 1 == 3


# ── runs and the debugger across files ──────────────────────────

def test_a_run_offers_to_save_function_files_first(panel, editor, tmp_path,
                                                   monkeypatch):
    helper = _write(tmp_path / "helper_fn.m",
                    "function r = helper_fn(x)\n    r = x + 1;\nend\n")
    main = _write(tmp_path / "main_save.m", "v = helper_fn(1);\n")
    document = editor.load_file(helper)
    editor.set_text("function r = helper_fn(x)\n    r = x + 10;\nend\n")
    editor.load_file(main)
    asked = []
    monkeypatch.setattr(panel, "_ask_to_save_scripts",
                        lambda names: asked.append(names) or "save")
    assert panel._run_script(editor.text(), "matlab")
    assert asked == [["helper_fn.m"]]
    assert not document.modified
    assert panel.interpreter.namespace["v"] == 11      # the saved version


def test_cancelling_the_save_offer_cancels_the_run(panel, editor, tmp_path,
                                                   monkeypatch):
    helper = _write(tmp_path / "cancel_fn.m",
                    "function r = cancel_fn(x)\n    r = x;\nend\n")
    editor.load_file(helper)
    editor.set_text("function r = cancel_fn(x)\n    r = -x;\nend\n")
    editor.new_document()
    editor.set_text("never_set = 1;")
    monkeypatch.setattr(panel, "_ask_to_save_scripts",
                        lambda names: "cancel")
    panel.interpreter.namespace.pop("never_set", None)
    assert not panel._run_script(editor.text(), "matlab")
    assert "never_set" not in panel.interpreter.namespace


def test_a_breakpoint_in_a_function_file_pauses_in_its_tab(panel, editor,
                                                           tmp_path):
    helper = _write(tmp_path / "twice.m",
                    "function r = twice(x)\n    r = 2*x;\nend\n")
    main = _write(tmp_path / "main_bp.m", "y = twice(3);\n")
    helper_doc = editor.load_file(helper)
    helper_doc.code.set_breakpoints({2})
    main_doc = editor.load_file(main)
    assert panel.interpreter.tracer.file_breakpoints == {
        file_key(helper): {2}}
    log = {}

    def at_breakpoint():
        log["script_tab"] = panel._tabs.currentWidget() is editor
        log["showing"] = editor.current_document().name
        log["line"] = helper_doc.code.current_line
        log["x"] = panel.execute("x").output.strip()
        panel._debug(CONTINUE)

    _later(100, at_breakpoint)
    assert panel._run_script(main_doc.text(), "matlab")
    helper_doc.code.set_breakpoints(())
    assert log == {"script_tab": True, "showing": "twice.m", "line": 2,
                   "x": "x = 3"}
    assert panel.interpreter.namespace["y"] == 6
    assert helper_doc.code.current_line is None


def test_stepping_in_opens_the_function_file(panel, editor, tmp_path):
    _write(tmp_path / "thrice.m",
           "function r = thrice(x)\n    r = 3*x;\nend\n")
    main = _write(tmp_path / "main_step.m", "z = thrice(2);\n")
    main_doc = editor.load_file(main)
    main_doc.code.set_breakpoints({1})
    log = {}

    def at_breakpoint():
        panel._debug(STEP_IN)
        _later(50, stepped)

    def stepped():
        document = editor.current_document()
        log["showing"] = document.name
        log["line"] = document.code.current_line
        panel._debug(CONTINUE)

    _later(100, at_breakpoint)
    assert panel._run_script(main_doc.text(), "matlab")
    main_doc.code.set_breakpoints(())
    assert log == {"showing": "thrice.m", "line": 2}
    assert panel.interpreter.namespace["z"] == 6


def test_a_stop_inside_a_function_file_names_it(panel, editor, tmp_path):
    _write(tmp_path / "spin.m",
           "function spin()\n    while true\n    end\nend\n")
    main = _write(tmp_path / "main_spin.m", "a = 1;\nspin();\n")
    document = editor.load_file(main)
    _later(150, panel.stop)
    assert panel._run_script(document.text(), "matlab")
    transcript = panel.console._transcript.toPlainText()
    assert "in spin.m" in transcript
    # Line 2 or 3 of spin.m is not a line of the script: no tint there.
    assert document.code.error_line is None


def test_a_running_tab_cannot_be_closed(panel, editor):
    editor.set_text("while true\nend")
    document = editor.current_document()
    closed = []
    _later(100, lambda: closed.append(editor.close_document(document)))
    _later(200, panel.stop)
    panel._run_script(document.text(), "matlab")
    assert closed == [False]
    assert document in editor.documents()
