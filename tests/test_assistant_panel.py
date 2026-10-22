"""
The assistant panel: the setup card, a streamed question, and proposals that
wait for the user.

The network is an ``httpx.MockTransport``, the key is handed in rather than
read from the environment, and the panel's worker threads run in line.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import pytest

KEY = "sk-or-v1-test-0123456789abcdef"

SCRIPT = "G = tf(1, [1, 2, 1])\n%% Controller\nK = 3\nL = K*G\n%% Plot\nstep(feedback(L, 1))"

MODELS = {"data": [
    {"id": "google/gemma-4-31b-it:free", "name": "Gemma 4 31B (free)",
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "cohere/north-mini-code:free", "name": "North Mini Code (free)",
     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"]},
]}

REPLY = ("Lower the gain.\n```evans-edit\nK = 1.5\nL = K*G\n```\n"
         "Then:\n```evans-run\nstep(feedback(L, 1))\n```")


def sse(text: str) -> bytes:
    events = [{"model": "m", "choices": [{"delta": {"content": piece},
                                          "finish_reason": None}]}
              for piece in (text[:10], text[10:])]
    events.append({"model": "m", "choices": [{"delta": {}, "finish_reason": "stop"}]})
    body = ": OPENROUTER PROCESSING\n\n" + "".join(
        f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return body.encode()


class Fake:
    def __init__(self, reply: str = REPLY, completions=None):
        self.reply = reply
        self.completions = completions
        self.sent: list[dict] = []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        if path.endswith("/key"):
            return httpx.Response(200, json={"data": {"free_model_daily_requests":
                                  {"used": 3, "limit": 50, "remaining": 47}}})
        self.sent.append(json.loads(request.content))
        if self.completions is not None:
            return self.completions
        return httpx.Response(200, content=sse(self.reply),
                              headers={"content-type": "text/event-stream"})


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make_panel(qapp, fake: Fake, key: str | None = KEY):
    from evans.assistant.client import Client
    from evans.ui.assistant import AssistantPanel

    class Inline(AssistantPanel):
        def _in_background(self, work):
            work()

    panel = Inline(client_factory=lambda k: Client(k, transport=httpx.MockTransport(fake)),
                   key_reader=lambda: key)
    panel.show()                       # the model list loads when first seen
    return panel


def editor_source(text=SCRIPT, cursor_at="K = 3", **options):
    from PySide6.QtWidgets import QPlainTextEdit

    from evans.ui.assistant import EditorSource
    from evans.ui.assistant.sources import to_qt

    editor = QPlainTextEdit()
    editor.setPlainText(text)
    cursor = editor.textCursor()
    cursor.setPosition(to_qt(text, text.index(cursor_at)))
    editor.setTextCursor(cursor)
    return editor, EditorSource(editor, where="script", language="matlab", **options)


class TestSetup:
    def test_without_a_key_the_setup_card_shows(self, qapp):
        fake = Fake()
        panel = make_panel(qapp, fake, key=None)
        assert not panel.has_key
        assert panel._stack.currentIndex() == 0
        assert not panel._input.isEnabled()
        assert not panel.ask("hello")
        assert fake.requests == []

    def test_check_again_finds_the_key(self, qapp):
        fake = Fake()
        keys = [None]
        from evans.assistant.client import Client
        from evans.ui.assistant import AssistantPanel

        class Inline(AssistantPanel):
            def _in_background(self, work):
                work()

        panel = Inline(client_factory=lambda k: Client(k, transport=httpx.MockTransport(fake)),
                       key_reader=lambda: keys[0])
        panel.show()
        assert not panel.has_key
        keys[0] = KEY
        assert panel.check_key()
        assert panel._stack.currentIndex() == 1
        assert panel.model() == "cohere/north-mini-code:free"
        assert "47 of 50" in panel._allowance.text()

    def test_the_key_is_not_saved(self, qapp):
        from evans.ui import persist
        make_panel(qapp, Fake())
        store = persist.settings()
        for name in store.allKeys():
            assert KEY not in str(store.value(name))


class TestAsking:
    def test_question_goes_out_with_narrow_context(self, qapp):
        fake = Fake()
        panel = make_panel(qapp, fake)
        _, source = editor_source(variables=lambda: {"K": 3.14159, "G": [1, 2]},
                                  last_error=lambda: "Undefined function 'stepp'.")
        panel.set_source(source)
        assert panel.ask("make it less oscillatory")
        body = fake.sent[0]
        assert body["model"] == "cohere/north-mini-code:free"
        user = body["messages"][-1]["content"]
        assert "K = 3\nL = K*G" in user                 # the section
        assert "G = tf(1" not in user and "step(" not in user   # not the script
        assert "3.14159" not in user                    # no values
        assert "K: float, scalar" in user
        assert "Undefined function 'stepp'." in user
        assert "section (2 lines)" in panel._sends.text()

    def test_reply_becomes_text_edit_and_command(self, qapp):
        from evans.ui.assistant.panel import CommandCard, EditCard
        panel = make_panel(qapp, Fake())
        _, source = editor_source()
        panel.set_source(source)
        panel.ask("lower the gain")
        kinds = [type(w).__name__ for w in panel.cards()]
        # You, "Cedric", his prose, the edit, more prose, the command.
        assert kinds == ["QLabel", "QLabel", "QLabel", "EditCard", "QLabel",
                         "CommandCard"]
        edit = next(w for w in panel.cards() if isinstance(w, EditCard))
        text = edit.view.toPlainText()
        assert "-K = 3" in text and "+K = 1.5" in text
        assert any(isinstance(w, CommandCard) for w in panel.cards())
        assert not panel.busy

    def test_apply_replaces_the_section_in_one_undo_step(self, qapp):
        from evans.ui.assistant.panel import EditCard
        panel = make_panel(qapp, Fake())
        editor, source = editor_source()
        panel.set_source(source)
        panel.ask("lower the gain")
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert card.apply()
        assert editor.toPlainText() == SCRIPT.replace("K = 3", "K = 1.5")
        assert not card.apply_button.isEnabled()
        editor.undo()
        assert editor.toPlainText() == SCRIPT

    def test_apply_refuses_after_the_code_changed(self, qapp):
        from evans.ui.assistant.panel import EditCard
        panel = make_panel(qapp, Fake())
        editor, source = editor_source()
        panel.set_source(source)
        panel.ask("lower the gain")
        editor.setPlainText(SCRIPT.replace("K = 3", "K = 4"))
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert not card.apply()
        assert "changed" in card.status.text()
        assert "K = 4" in editor.toPlainText()

    def test_reject_leaves_the_code_alone(self, qapp):
        from evans.ui.assistant.panel import EditCard
        panel = make_panel(qapp, Fake())
        editor, source = editor_source()
        panel.set_source(source)
        panel.ask("lower the gain")
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        card.reject()
        assert editor.toPlainText() == SCRIPT
        assert not card.apply_button.isEnabled()

    def test_apply_with_characters_outside_the_bmp(self, qapp):
        from evans.ui.assistant.panel import EditCard
        # The emoji is two UTF-16 units to Qt and one character to Python;
        # the section after it only lines up if the offsets are converted.
        text = "a = 1\n%% 📈 plots\nK = 3\n%% next\nx = 1"
        panel = make_panel(qapp, Fake(reply="```evans-edit\nK = 2\n```"))
        editor, source = editor_source(text=text, cursor_at="K = 3")
        panel.set_source(source)
        panel.ask("halve")
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert card.apply()
        assert editor.toPlainText() == text.replace("K = 3", "K = 2")

    def test_commands_run_only_when_asked(self, qapp):
        from evans.ui.assistant.panel import CommandCard
        panel = make_panel(qapp, Fake())
        ran, pasted = [], []
        panel.run_command.connect(ran.append)
        panel.paste_command.connect(pasted.append)
        panel.ask("plot it")
        assert ran == [] and pasted == []
        card = next(w for w in panel.cards() if isinstance(w, CommandCard))
        card.paste()
        assert pasted == ["step(feedback(L, 1))"] and ran == []
        assert not card.run_button.isEnabled()

        panel.ask("again")
        card = [w for w in panel.cards() if isinstance(w, CommandCard)][-1]
        card.run()
        assert ran == ["step(feedback(L, 1))"]

    def test_edits_from_the_console_are_read_only(self, qapp):
        from evans.ui.assistant.panel import EditCard
        panel = make_panel(qapp, Fake())
        panel.ask("what is wrong?")                      # no source: the console
        card = next(w for w in panel.cards() if isinstance(w, EditCard))
        assert not card.apply_button.isEnabled()

    def test_follow_up_carries_two_exchanges(self, qapp):
        fake = Fake(reply="Fine.")
        panel = make_panel(qapp, fake)
        for q in ("one", "two", "three"):
            panel.ask(q)
        roles = [m["role"] for m in fake.sent[-1]["messages"]]
        assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
        assert fake.sent[-1]["messages"][1]["content"] == "one"
        panel.ask("four")
        assert fake.sent[-1]["messages"][1]["content"] == "two"
        panel.clear()
        panel.ask("five")
        assert len(fake.sent[-1]["messages"]) == 2
        assert panel.cards()                             # five is shown

    def test_failure_is_shown_not_raised(self, qapp):
        fake = Fake(completions=httpx.Response(429, json={"error": {"code": 429,
                                               "message": "Rate limit exceeded"}}))
        panel = make_panel(qapp, fake)
        panel.ask("hello")
        last = panel.cards()[-1]
        assert "limit" in last.text()
        assert not panel.busy

    def test_stop_ignores_the_rest(self, qapp):
        panel = make_panel(qapp, Fake())
        started = []
        panel._in_background = started.append           # hold the request
        panel.ask("long one")
        assert panel.busy
        panel.stop()
        assert not panel.busy
        started[0]()                                     # it finishes late
        assert not any(type(w).__name__ == "EditCard" for w in panel.cards())
        assert "[stopped]" in panel.cards()[-1].text()


def test_dock_has_a_stable_object_name(qapp):
    from evans.ui.assistant import AssistantDock
    dock = AssistantDock(key_reader=lambda: None)
    assert dock.objectName() == "assistantDock"
    assert dock.panel is dock.widget()
