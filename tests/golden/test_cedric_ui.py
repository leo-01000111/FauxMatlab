"""
Cedric in the window: his dock on the Console workspace, what each Console
tab hands him, the floating Ask Cedric button, and his proposals landing in
the console, a script tab and a live cell.

The network is an ``httpx.MockTransport`` given to the panel by hand; the
suite's conftest hides any real key.
"""

from __future__ import annotations

import json

import httpx
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from evans.assistant.client import Client
from evans.core.architecture import CourseArchitecture
from evans.core.tf_utils import second_order
from evans.ui.assistant import AskCedricFloat
from evans.ui.assistant.panel import CommandCard, EditCard
from evans.ui.mainwindow import MainWindow
from evans.ui.workspace import Workspace

SCRIPT = "G = tf(1, [1, 2, 1]);\n%% Gain\nK = 3;\nL = K*G;\n%% Plot\nstep(L)"


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
    window.set_cedric_visible(False)
    window.hide()


@pytest.fixture
def console(win, app):
    win.show_workspace(Workspace.CONSOLE)
    panel = win._console
    panel._tabs.setCurrentIndex(0)
    panel.console._input.clear()
    panel.console._transcript.moveCursor(QTextCursor.End)
    panel.last_error = ""
    _settle(app)
    return panel


class Fake:
    def __init__(self, reply="Fine."):
        self.reply = reply
        self.sent: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [
                {"id": "cohere/north-mini-code:free", "name": "North Mini Code",
                 "pricing": {"prompt": "0", "completion": "0"}}]})
        if path.endswith("/key"):
            return httpx.Response(200, json={"data": {}})
        self.sent.append(json.loads(request.content))
        body = (f"data: {json.dumps({'choices': [{'delta': {'content': self.reply}}]})}"
                "\n\ndata: [DONE]\n\n")
        return httpx.Response(200, content=body.encode(),
                              headers={"content-type": "text/event-stream"})


@pytest.fixture
def cedric(win, app, monkeypatch):
    """Cedric's panel with a key and a fake OpenRouter, threads in line."""
    fake = Fake()
    panel = win._cedric_dock.panel
    monkeypatch.setattr(panel, "_client_factory",
                        lambda key: Client(key, transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(panel, "_key_reader", lambda: "sk-or-test")
    monkeypatch.setattr(panel, "_in_background", lambda work: work())
    panel._loaded = False
    panel._model_box.clear()
    panel.clear()
    panel.unpin()
    panel.check_key()
    win.set_cedric_visible(True)
    _settle(app)
    yield panel, fake
    panel.clear()
    panel.unpin()
    win.set_cedric_visible(False)


def _settle(app, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


def _select(widget, text: str) -> None:
    """Select ``text`` (its last occurrence) in a text edit."""
    whole = widget.toPlainText()
    start = whole.rindex(text)
    cursor = widget.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(start + len(text), QTextCursor.KeepAnchor)
    widget.setTextCursor(cursor)


# ── the dock ───────────────────────────────────────────────────────

class TestDock:
    def test_hidden_until_asked_for(self, win, console):
        assert not win._cedric_dock.isVisible()
        assert not win._act_cedric.isChecked()

    def test_the_tab_bar_button_carries_the_action(self, win, console):
        assert console.cedric_button.defaultAction() is win._act_cedric
        assert win._act_cedric.shortcut().toString() == "Ctrl+Shift+A"

    def test_shown_only_on_the_console_workspace(self, win, console, app):
        win._act_cedric.trigger()
        _settle(app)
        assert win._cedric_dock.isVisible()
        win.show_workspace(Workspace.ANALYSE)
        _settle(app)
        assert not win._cedric_dock.isVisible()
        assert win._act_cedric.isChecked()              # still wanted
        win.show_workspace(Workspace.CONSOLE)
        _settle(app)
        assert win._cedric_dock.isVisible()
        win._act_cedric.trigger()
        _settle(app)
        assert not win._cedric_dock.isVisible()

    def test_closing_the_dock_forgets_the_wish(self, win, console, app):
        win.set_cedric_visible(True)
        _settle(app)
        win._cedric_dock.close()
        _settle(app)
        assert not win._act_cedric.isChecked()
        win.show_workspace(Workspace.ANALYSE)
        win.show_workspace(Workspace.CONSOLE)
        _settle(app)
        assert not win._cedric_dock.isVisible()

    def test_opening_from_another_workspace_goes_to_the_console(self, win, app):
        win.show_workspace(Workspace.ANALYSE)
        win.set_cedric_visible(True)
        _settle(app)
        assert win._stack.current is Workspace.CONSOLE
        assert win._cedric_dock.isVisible()
        win.set_cedric_visible(False)

    def test_the_hidden_panel_never_touches_the_network(self, app):
        from evans.ui.assistant import AssistantPanel
        seen = []
        transport = httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(500))
        panel = AssistantPanel(
            client_factory=lambda key: Client(key, transport=transport),
            key_reader=lambda: "sk-or-test")
        panel._in_background = lambda work: work()
        assert panel.has_key
        panel.check_key()
        assert seen == []                    # with a key, but never shown
        panel.show()
        assert seen                          # first sight loads the models


# ── what each tab hands him ────────────────────────────────────────

class TestSources:
    def test_console_sends_the_unsent_prompt_line(self, console):
        console.console.set_input("bode(G")
        context = console.assistant_source.context()
        assert context.where == "console"
        assert (context.origin, context.code) == ("prompt", "bode(G")

    def test_console_attaches_selected_output_with_its_error(self, console, app):
        console.execute("undefined_thing_xyz + 1")
        _settle(app)
        assert "undefined_thing_xyz" in console.last_error
        transcript = console.console._transcript
        _select(transcript, "undefined_thing_xyz")
        context = console.assistant_source.context()
        assert "undefined_thing_xyz" in context.attachment
        assert "undefined_thing_xyz" in context.last_error

    def test_script_tab_sends_its_section(self, console):
        console.show_script()
        console.editor.set_text(SCRIPT)
        code = console.editor.code
        cursor = code.textCursor()
        cursor.setPosition(SCRIPT.index("K = 3"))
        code.setTextCursor(cursor)
        context = console.assistant_source.context()
        assert (context.where, context.origin) == ("script", "section")
        assert context.code == "K = 3;\nL = K*G;"
        assert context.language == "matlab"

    def test_live_tab_sends_the_current_cell(self, console):
        console._tabs.setCurrentWidget(console.live)
        cell = console.live.current_cell
        widget = console.live.widget_for(cell)
        widget.editor.setPlainText("x = 1;\ny = x + 1;")
        context = console.assistant_source.context()
        assert (context.where, context.origin) == ("live", "cell")
        assert context.code == "x = 1;\ny = x + 1;"

    def test_values_never_leave(self, console):
        console.push(secret_gain=271828.18)
        context = console.assistant_source.context()
        from evans.assistant.context import render
        assert "271828" not in render(context)
        assert any(v.name == "secret_gain" for v in context.variables)


# ── the floating button ────────────────────────────────────────────

class TestAskFloat:
    def _float(self, widget) -> AskCedricFloat:
        floats = widget.findChildren(AskCedricFloat)
        assert floats, "no Ask Cedric button on this widget"
        return floats[0]

    def test_every_place_code_is_has_one(self, console):
        assert self._float(console.console._transcript)
        assert self._float(console.console._input)
        for document in console.editor.documents():
            assert self._float(document.code)
        console.editor.new_document()                    # new tabs too
        assert self._float(console.editor.current_document().code)
        for widget in console.live.cell_widgets:
            if hasattr(widget, "editor"):
                assert self._float(widget.editor)

    def test_floats_up_on_a_selection_only(self, console):
        transcript = console.console._transcript
        float_ = self._float(transcript)
        transcript.moveCursor(QTextCursor.End)
        assert not float_.offer()
        console.execute("1 + 1")
        _select(transcript, "1 + 1")
        assert float_.offer() and float_.button.isVisibleTo(transcript)
        transcript.moveCursor(QTextCursor.End)
        assert not float_.button.isVisibleTo(transcript)

    def test_explain_asks_at_once_with_the_selection(self, console, cedric, app):
        panel, fake = cedric
        console.execute("undefined_thing_xyz + 1")
        transcript = console.console._transcript
        _select(transcript, "undefined_thing_xyz")
        float_ = self._float(transcript)
        float_.offer()
        float_._choose("fix")
        _settle(app)
        user = fake.sent[-1]["messages"][-1]["content"]
        assert "undefined_thing_xyz" in user
        assert user.endswith("What is wrong here, and how do I fix it?")

    def test_ask_attaches_and_waits_for_the_question(self, console, cedric, app):
        panel, fake = cedric
        console.show_script()
        console.editor.set_text(SCRIPT)
        _select(console.editor.code, "step(L)")
        float_ = self._float(console.editor.code)
        float_.offer()
        float_._choose("ask")
        _settle(app)
        assert fake.sent == []
        assert panel.pinned is not None and panel.pinned.code == "step(L)"
        console.editor.code.moveCursor(QTextCursor.Start)   # selection gone
        panel.ask("plot it as a bode instead")
        user = fake.sent[-1]["messages"][-1]["content"]
        assert "step(L)" in user and "G = tf" not in user
        assert panel.pinned is None


# ── proposals landing ──────────────────────────────────────────────

class TestProposals:
    def test_applying_at_the_prompt_runs_it(self, console, cedric, app):
        panel, fake = cedric
        fake.reply = "Close the bracket:\n```evans-edit\ncedric_fixed = 5\n```"
        console.console.set_input("cedric_fixed = (5")
        panel.ask("why won't this run?")
        _settle(app)
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert card.apply()
        _settle(app)
        assert console.console._input.text() == ""              # it was sent
        assert console.interpreter.variables()["cedric_fixed"] == 5

    def test_multi_line_edit_cannot_go_into_the_prompt(self, console, cedric, app):
        panel, fake = cedric
        fake.reply = "```evans-edit\nK = 2;\nbode(K*G)\n```"
        console.console.set_input("bode(G)")
        panel.ask("scale it")
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert not card.apply()
        assert "several lines" in card.status.text()
        assert console.console._input.text() == "bode(G)"

    def test_edit_lands_in_the_tab_it_came_from(self, console, cedric, app):
        panel, fake = cedric
        fake.reply = "```evans-edit\nK = 1.5;\nL = K*G;\n```"
        console.show_script()
        console.editor.set_text(SCRIPT)
        first = console.editor.current_document()
        cursor = first.code.textCursor()
        cursor.setPosition(SCRIPT.index("K = 3"))
        first.code.setTextCursor(cursor)
        panel.ask("lower the gain")
        console.editor.new_document()                    # switch tabs
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert card.apply()
        assert first.code.toPlainText() == SCRIPT.replace("K = 3", "K = 1.5")
        assert console.editor.current_document().code.toPlainText() == ""

    def test_edit_replaces_the_live_cell(self, console, cedric, app):
        panel, fake = cedric
        fake.reply = "```evans-edit\nx = 2;\n```"
        console._tabs.setCurrentWidget(console.live)
        widget = console.live.widget_for(console.live.current_cell)
        widget.editor.setPlainText("x = 1;")
        panel.ask("make it two")
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert card.apply()
        assert widget.editor.toPlainText() == "x = 2;"
        assert console.live.current_cell.source == "x = 2;"

    def test_run_executes_in_the_console(self, console, cedric, app):
        panel, fake = cedric
        fake.reply = "```evans-run\ncedric_ran = 42\n```"
        panel.ask("set something")
        card = next(w for w in panel.cards() if isinstance(w, CommandCard))
        assert "cedric_ran" not in console.interpreter.variables()
        card.run()
        _settle(app)
        assert console.interpreter.variables()["cedric_ran"] == 42

    def test_copy_to_console_waits_at_the_prompt(self, console, cedric, app):
        panel, fake = cedric
        fake.reply = "```evans-run\ncedric_copied = 7\n```"
        panel.ask("set something")
        card = next(w for w in panel.cards() if isinstance(w, CommandCard))
        card.paste()
        assert console.console._input.text() == "cedric_copied = 7"
        assert "cedric_copied" not in console.interpreter.variables()


# ── a command that failed, and the buttons beside errors ──────────

class TestErrors:
    def test_failed_command_is_what_he_fixes(self, console, cedric, app):
        panel, fake = cedric
        console.execute("G = tf(1, [1, 1])")
        console.execute("stpe(G)")
        _settle(app)
        assert console.last_failed_command == "stpe(G)"
        context = console.assistant_source.context()       # prompt is empty
        assert (context.origin, context.code) == ("failed", "stpe(G)")
        assert "stpe" in context.last_error
        fake.reply = "A typo:\n```evans-edit\ncedric_after = 1\n```"
        panel.ask("fix it")
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert card.apply_button.isEnabled()
        assert "-stpe(G)" in card.view.toPlainText()
        assert card.apply()
        _settle(app)
        assert console.interpreter.variables()["cedric_after"] == 1
        assert console.last_failed_command == ""             # ran cleanly

    def test_a_typed_prompt_refuses_the_failed_fix(self, console, cedric, app):
        panel, fake = cedric
        console.execute("stpe(1)")
        fake.reply = "```evans-edit\nstep(1)\n```"
        panel.ask("fix it")
        console.console.set_input("x = 1")
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert not card.apply()
        assert console.console._input.text() == "x = 1"

    def test_a_failed_command_gets_a_button_that_asks_at_once(
            self, console, cedric, app):
        panel, fake = cedric
        marks = console._transcript_marks
        before = marks.count
        console.execute("undefined_thing_abc + 1")
        _settle(app)
        assert marks.count == min(before + 1, 12)
        button = marks.buttons()[-1]
        assert button.isVisible()
        button.click()
        _settle(app)
        user = fake.sent[-1]["messages"][-1]["content"]
        assert "undefined_thing_abc + 1" in user                # the command
        assert "undefined_thing_abc" in user.split("Last error:")[1]
        assert user.endswith("What is wrong here, and how do I fix it?")

    def test_clean_commands_get_no_button(self, console):
        before = console._transcript_marks.count
        console.execute("1 + 1")
        assert console._transcript_marks.count == before

    def test_a_script_error_gets_a_button_on_its_line(self, console, cedric, app):
        panel, fake = cedric
        console.show_script()
        document = console.editor.new_document()
        console.editor.set_language("matlab")
        script = "a = 1;\nb = undefined_thing_q;\nc = 3;"
        console.editor.set_text(script)
        console._run_script(console.editor.text(), "matlab")
        _settle(app)
        marks = document.code._cedric_marks
        assert marks.count == 1
        fake.reply = "Define it first:\n```evans-edit\nb = 2;\n```"
        marks.buttons()[0].click()
        _settle(app)
        user = fake.sent[-1]["messages"][-1]["content"]
        assert "b = undefined_thing_q;" in user and "c = 3;" not in user
        assert user.endswith("What is wrong here, and how do I fix it?")
        card = [w for w in panel.cards() if isinstance(w, EditCard)][-1]
        assert card.apply()
        assert document.code.toPlainText() == script.replace(
            "undefined_thing_q", "2")
        _settle(app)
        assert marks.count == 0                    # its line is gone


class TestPanelKeys:
    def test_enter_sends_and_shift_enter_breaks_the_line(self, cedric, app):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        panel, fake = cedric
        box = panel._input
        box.setPlainText("first line")
        box.moveCursor(QTextCursor.End)
        QApplication.sendEvent(box, QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                                              Qt.ShiftModifier))
        assert fake.sent == [] and "\n" in box.toPlainText()
        QApplication.sendEvent(box, QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                                              Qt.NoModifier))
        _settle(app)
        assert len(fake.sent) == 1
        assert box.toPlainText() == ""


def test_the_diff_has_no_headers():
    from evans.ui.assistant.panel import GAP, diff_lines
    old = "\n".join(f"line {i}" for i in range(20))
    new = old.replace("line 1\n", "line one\n").replace("line 18", "line 18!")
    lines = diff_lines(old, new)
    assert not any(line.startswith(("---", "+++", "@@")) for line in lines)
    assert "-line 1" in lines and "+line one" in lines and GAP in lines
