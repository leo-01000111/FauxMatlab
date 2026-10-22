"""
The assistant panel: a question box, a short conversation, and proposals
that do nothing until the user says so.

What the panel talks about comes from a :class:`Source`, set by whoever has
focus: the console, a script tab or a live script. A source builds the
narrow :class:`~evans.assistant.context.Context` for one question and knows
how to apply an edit to its own document. The panel never reads an editor
directly, so wiring it to a new kind of editor is a new source, not a change
here.

A proposed edit is shown as a diff of the code that was sent against the
model's replacement; Apply replaces that code in one undo step, and refuses
if the code has changed since. A proposed command is shown with Run (emits
:attr:`AssistantPanel.run_command`), Copy to console (emits
:attr:`AssistantPanel.paste_command`) and Dismiss. Nothing runs by itself.

Without ``OPENROUTER_API_KEY`` the panel shows how to get a free key; the
key is only ever read from the environment, never typed in or saved.
"""

from __future__ import annotations

import html
import sys
import threading
from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...assistant import client as orc
from ...assistant import context as ctx
from ...assistant import protocol
from ...assistant.client import AssistantError, Client, ModelInfo
from ...assistant.context import Context
from ...assistant.protocol import Command, Edit, History, StaleEdit, Text
from .. import persist, theme

#: Where the chosen model is remembered. Only the model's id is stored;
#: the key never is.
MODEL_KEY = "assistant/model"

KEY_URL = "https://openrouter.ai/keys"


# ──────────────────────────────────────────────────────────────
#  Sources: what the panel is about
# ──────────────────────────────────────────────────────────────

class Source:
    """
    Whatever the panel is asking about. Subclasses fill in the two methods.

    ``context()`` is called once per question, on the GUI thread.
    ``apply(context, edit)`` replaces the code that ``context`` was built
    from, or raises :class:`StaleEdit`.
    """

    def context(self) -> Context:
        raise NotImplementedError

    def apply(self, context: Context, edit: Edit) -> None:
        raise StaleEdit("This place cannot be edited.")


class EditorSource(Source):
    """
    A source over any ``QPlainTextEdit`` or ``QTextEdit``: a script or a
    live-script cell.

    ``variables`` and ``last_error`` are callables, read at question time,
    so the source never holds on to a stale workspace.
    """

    def __init__(self, editor: QPlainTextEdit | QTextEdit, *, where: str,
                 language: str | Callable[[], str] = "python",
                 variables: Callable[[], Mapping[str, Any]] = dict,
                 last_error: Callable[[], str] = str) -> None:
        self.editor = editor
        self.where = where
        self._language = language
        self._variables = variables
        self._last_error = last_error

    def context(self) -> Context:
        text = self.editor.toPlainText()
        cursor = self.editor.textCursor()
        language = self._language() if callable(self._language) else self._language
        return ctx.build(
            self.where, language=language, text=text,
            cursor=_from_qt(text, cursor.position()),
            sel_start=_from_qt(text, cursor.selectionStart()),
            sel_end=_from_qt(text, cursor.selectionEnd()),
            variables=self._variables(), last_error=self._last_error())

    def apply(self, context: Context, edit: Edit) -> None:
        text = self.editor.toPlainText()
        protocol.apply_edit(text, context, edit)          # raises if stale
        region = context.region
        cursor = QTextCursor(self.editor.document())
        cursor.beginEditBlock()                           # one undo step
        cursor.setPosition(_to_qt(text, region.start))
        cursor.setPosition(_to_qt(text, region.end), QTextCursor.KeepAnchor)
        cursor.insertText(edit.code)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)


def _to_qt(text: str, index: int) -> int:
    """A Python string index as a Qt position (Qt counts UTF-16 units)."""
    return len(text[:index].encode("utf-16-le")) // 2


def _from_qt(text: str, position: int) -> int:
    """A Qt position as a Python string index."""
    units = 0
    for i, ch in enumerate(text):
        if units >= position:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


def windows_user_key() -> str | None:
    """
    ``OPENROUTER_API_KEY`` as saved for the user on Windows, if it is.

    A variable set with ``setx`` (or in System Properties) only reaches
    processes started afterwards. Reading the user's saved environment lets
    *Check again* find a key set while Evans was open. Read-only.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, orc.ENV_KEY)
        return str(value).strip() or None
    except OSError:
        return None


# ──────────────────────────────────────────────────────────────
#  The panel
# ──────────────────────────────────────────────────────────────

class _Bridge(QObject):
    """Carries a worker thread's news to the GUI thread (queued signals)."""
    text = Signal(int, str)            # request, piece of the reply
    done = Signal(int, object)         # request, Reply or AssistantError
    models = Signal(object)            # list[ModelInfo] or AssistantError
    allowance = Signal(object)         # Allowance, None or AssistantError


class AssistantPanel(QWidget):
    """The assistant: header, conversation, question box."""

    #: The user pressed Run on a proposed command.
    run_command = Signal(str)
    #: The user pressed Copy to console: put it in the console's input.
    paste_command = Signal(str)

    def __init__(self, parent: QWidget | None = None, *,
                 client_factory: Callable[[str | None], Client] = Client,
                 key_reader: Callable[[], str | None] = orc.api_key) -> None:
        super().__init__(parent)
        self._client_factory = client_factory
        self._key_reader = key_reader
        self._key: str | None = None
        self._source: Source | None = None
        self._history = History()
        self._request = 0                  # the id of the request in flight
        self._cancel: threading.Event | None = None
        self._reply_label: QLabel | None = None
        self._reply_text = ""
        self._asked: tuple[str, Context] | None = None

        self._bridge = _Bridge(self)
        self._bridge.text.connect(self._on_text)
        self._bridge.done.connect(self._on_done)
        self._bridge.models.connect(self._on_models)
        self._bridge.allowance.connect(self._on_allowance)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._header = QWidget()
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        self._model_box = QComboBox()
        self._model_box.setToolTip("Free models on OpenRouter right now")
        self._model_box.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._model_box.setMinimumContentsLength(14)
        self._model_box.activated.connect(self._on_model_chosen)
        header.addWidget(self._model_box, stretch=1)
        self._clear_button = QPushButton("Clear")
        self._clear_button.setToolTip("Forget the conversation")
        self._clear_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._clear_button.clicked.connect(self.clear)
        header.addWidget(self._clear_button)
        layout.addWidget(self._header)

        self._allowance = QLabel("")
        self._allowance.setFont(theme.label_font(8))
        self._allowance.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._allowance)

        self._stack = QStackedWidget()
        self._setup = self._build_setup()
        self._stack.addWidget(self._setup)
        self._stack.addWidget(self._build_conversation())
        layout.addWidget(self._stack, stretch=1)

        self._sends = QLabel("")
        self._sends.setWordWrap(True)
        self._sends.setFont(theme.label_font(8))
        self._sends.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._sends)

        self._ask_row = QWidget()
        ask = QHBoxLayout(self._ask_row)
        ask.setContentsMargins(0, 0, 0, 0)
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Ask about the code…  (Ctrl+Enter)")
        self._input.setFixedHeight(64)
        ask.addWidget(self._input, stretch=1)
        self._send_button = QPushButton("Ask")
        self._send_button.setProperty("role", "primary")
        self._send_button.clicked.connect(self._send_or_stop)
        ask.addWidget(self._send_button, alignment=Qt.AlignBottom)
        layout.addWidget(self._ask_row)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self._input,
                      activated=self._send_or_stop,
                      context=Qt.WidgetShortcut)

        self.check_key()

    # ── the key ───────────────────────────────────────────────

    def _build_setup(self) -> QWidget:
        card = QFrame()
        card.setProperty("hp", "panel")
        box = QVBoxLayout(card)
        title = QLabel("Set up the assistant")
        title.setFont(theme.title_font(11))
        box.addWidget(title)
        steps = QLabel(
            f"<ol>"
            f"<li>Get a free key at <a href='{KEY_URL}'>openrouter.ai/keys</a>.</li>"
            f"<li>Set the environment variable <code>{orc.ENV_KEY}</code> "
            f"to it — on Windows, <code>setx {orc.ENV_KEY} &lt;key&gt;</code> "
            f"in a terminal; on a Mac, an <code>export</code> line in "
            f"<code>~/.zshrc</code>.</li>"
            f"<li>Press <b>Check again</b> (or restart Evans).</li></ol>"
            f"<p>Evans never stores the key. Each question sends the selected "
            f"code (or the current %% section), your variables' names, types "
            f"and sizes — never their values — and the last error, to "
            f"OpenRouter and the model's host. Free models allow 50 questions "
            f"a day.</p>")
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        steps.setOpenExternalLinks(True)
        steps.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.addWidget(steps)
        again = QPushButton("Check again")
        again.setProperty("role", "secondary")
        again.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        again.clicked.connect(self.check_key)
        box.addWidget(again)
        self._setup_note = QLabel("")
        self._setup_note.setWordWrap(True)
        box.addWidget(self._setup_note)
        box.addStretch()
        return card

    def check_key(self) -> bool:
        """Look for the key again; show the conversation if there is one."""
        self._key = self._key_reader() or (
            windows_user_key() if self._key_reader is orc.api_key else None)
        have = bool(self._key)
        self._stack.setCurrentIndex(1 if have else 0)
        self._input.setEnabled(have)
        self._send_button.setEnabled(have)
        self._model_box.setEnabled(have)
        for widget in (self._header, self._allowance, self._sends, self._ask_row):
            widget.setVisible(have)
        if have:
            self._load_models()
            self._load_allowance()
        else:
            self._allowance.setText("")
            if self.sender() is not None:
                self._setup_note.setText(f"{orc.ENV_KEY} is still not set.")
        return have

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def _client(self) -> Client:
        return self._client_factory(self._key)

    # ── where the questions are about ─────────────────────────

    def set_source(self, source: Source | None) -> None:
        """What the next question is about (the focused editor or console)."""
        self._source = source

    def source(self) -> Source | None:
        return self._source

    # ── the conversation ──────────────────────────────────────

    def _build_conversation(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self._log = QVBoxLayout(holder)
        self._log.setContentsMargins(0, 0, 0, 0)
        self._log.setSpacing(6)
        self._log.addStretch()
        scroll.setWidget(holder)
        self._scroll = scroll
        return scroll

    def _append(self, widget: QWidget) -> None:
        self._log.insertWidget(self._log.count() - 1, widget)
        QTimer.singleShot(0, self._scroll_to_end)

    def _scroll_to_end(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        """Forget the conversation (and stop a reply in progress)."""
        self.stop()
        self._history.clear()
        while self._log.count() > 1:
            _drop(self._log.takeAt(0).widget())
        self._sends.setText("")

    def cards(self) -> list[QWidget]:
        """The conversation's widgets, oldest first (for tests)."""
        return [self._log.itemAt(i).widget() for i in range(self._log.count() - 1)]

    # ── asking ────────────────────────────────────────────────

    @property
    def busy(self) -> bool:
        return self._cancel is not None

    def _send_or_stop(self) -> None:
        if self.busy:
            self.stop()
        else:
            self.ask(self._input.toPlainText())

    def ask(self, question: str) -> bool:
        """Send ``question`` with the current source's context."""
        question = question.strip()
        if not question or self.busy or not self._key:
            return False
        model = self.model()
        if not model:
            self._append(_note("No free model is available yet — the list "
                               "is still loading, or could not be fetched.",
                               error=True))
            return False
        context = (self._source.context() if self._source is not None
                   else ctx.build("console"))
        messages = protocol.messages(context, question, self._history)

        self._input.clear()
        self._sends.setText(f"Sent: {context.summary()}")
        self._append(_question(question, context))
        self._reply_label = _reply_label()
        self._reply_text = ""
        self._append(self._reply_label)
        self._asked = (question, context)

        self._request += 1
        request = self._request
        cancel = threading.Event()
        self._cancel = cancel
        self._send_button.setText("Stop")
        self._send_button.setProperty("role", "danger")
        _restyle(self._send_button)

        client = self._client()
        bridge = self._bridge

        def work() -> None:
            try:
                result = client.stream(
                    model, messages, cancel=cancel,
                    on_text=lambda piece: bridge.text.emit(request, piece))
            except AssistantError as exc:
                result = exc
            except Exception as exc:          # noqa: BLE001 - never kill the thread silently
                result = AssistantError(f"Unexpected failure: {type(exc).__name__}")
            bridge.done.emit(request, result)

        self._in_background(work)
        return True

    def stop(self) -> None:
        """Stop the reply in progress; what arrived so far stays."""
        if self._cancel is None:
            return
        self._cancel.set()
        self._finish_request()
        if self._reply_label is not None:
            self._reply_label.setText(self._reply_text + "\n\n[stopped]")
        self._reply_label = None
        self._asked = None

    def _finish_request(self) -> None:
        self._cancel = None
        self._request += 1                 # late news from the old one is ignored
        self._send_button.setText("Ask")
        self._send_button.setProperty("role", "primary")
        _restyle(self._send_button)

    def _on_text(self, request: int, piece: str) -> None:
        if request != self._request or self._reply_label is None:
            return
        self._reply_text += piece
        self._reply_label.setText(self._reply_text)

    def _on_done(self, request: int, result: object) -> None:
        if request != self._request:
            return
        label, asked = self._reply_label, self._asked
        self._finish_request()
        self._reply_label = None
        self._asked = None
        if label is not None:
            self._log.removeWidget(label)
            _drop(label)
        if isinstance(result, AssistantError):
            self._append(_note(str(result), error=True))
            if result.kind == "rate_limit":
                self._load_allowance()
            return
        question, context = asked
        for part in protocol.parse(result.text):
            self._append(self._part_widget(part, context))
        self._history.add(question, result.text)
        self._load_allowance()

    def _part_widget(self, part, context: Context) -> QWidget:
        if isinstance(part, Edit):
            return EditCard(part, context, self._source, self)
        if isinstance(part, Command):
            return CommandCard(part, self)
        return _prose(part.text if isinstance(part, Text) else str(part))

    # ── models and allowance ──────────────────────────────────

    def model(self) -> str | None:
        data = self._model_box.currentData()
        return str(data) if data else None

    def _load_models(self) -> None:
        if self._model_box.count():
            return
        self._model_box.addItem("Loading free models…", None)
        client, bridge = self._client(), self._bridge

        def work() -> None:
            try:
                result = client.free_models()
            except AssistantError as exc:
                result = exc
            except Exception as exc:          # noqa: BLE001
                result = AssistantError(f"Unexpected failure: {type(exc).__name__}")
            bridge.models.emit(result)

        self._in_background(work)

    def _on_models(self, result: object) -> None:
        self._model_box.clear()
        if isinstance(result, AssistantError):
            self._model_box.addItem("Model list unavailable", None)
            self._append(_note(str(result), error=True))
            return
        models: list[ModelInfo] = result
        wanted = persist.settings().value(MODEL_KEY, orc.DEFAULT_MODEL)
        chosen = orc.pick_model(models, str(wanted) if wanted else None)
        for m in models:
            self._model_box.addItem(m.name, m.id)
            self._model_box.setItemData(self._model_box.count() - 1,
                                        m.id, Qt.ToolTipRole)
        if chosen:
            self._model_box.setCurrentIndex(self._model_box.findData(chosen))
        if not models:
            self._model_box.addItem("No free models offered", None)

    def _on_model_chosen(self, index: int) -> None:
        model = self._model_box.itemData(index)
        if model:
            persist.settings().setValue(MODEL_KEY, model)

    def _load_allowance(self) -> None:
        client, bridge = self._client(), self._bridge

        def work() -> None:
            try:
                result = client.allowance()
            except AssistantError as exc:
                result = exc
            except Exception:                 # noqa: BLE001
                result = None
            bridge.allowance.emit(result)

        self._in_background(work)

    def _on_allowance(self, result: object) -> None:
        if isinstance(result, orc.Allowance):
            self._allowance.setText(
                f"{result.remaining} of {result.limit} free questions left today")
        elif isinstance(result, AssistantError) and result.kind == "auth":
            self._allowance.setText(str(result))
        else:
            self._allowance.setText("")

    # ── threads ───────────────────────────────────────────────

    def _in_background(self, work: Callable[[], None]) -> None:
        """Run ``work`` on a thread. A method so tests can run it in line."""
        threading.Thread(target=work, name="evans-assistant", daemon=True).start()


# ──────────────────────────────────────────────────────────────
#  Conversation pieces
# ──────────────────────────────────────────────────────────────

def _drop(widget: QWidget | None) -> None:
    """Take a widget off screen now and delete it later (a removed but
    still visible child would go on painting where it was)."""
    if widget is not None:
        widget.hide()
        widget.deleteLater()


def _restyle(widget: QWidget) -> None:
    """Re-read the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _prose(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.MarkdownText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    label.setOpenExternalLinks(True)
    return label


def _reply_label() -> QLabel:
    label = QLabel("…")
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _question(question: str, context: Context) -> QLabel:
    label = QLabel(f"<b>You</b> <span style='color: palette(mid)'>"
                   f"· with {html.escape(context.summary())}</span><br>"
                   f"{html.escape(question).replace(chr(10), '<br>')}")
    label.setTextFormat(Qt.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _note(text: str, *, error: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if error:
        label.setStyleSheet(f"color: {theme.tokens().hold_ink};")
    return label


class EditCard(QFrame):
    """A proposed edit: its diff, then Apply or Reject."""

    def __init__(self, edit: Edit, context: Context, source: Source | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("hp", "panel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.edit, self.context, self.source = edit, context, source
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        what = {"selection": "the selection", "section": "this section",
                "line": "this line"}.get(context.origin, "the code")
        title = QLabel(f"Proposed edit to {what}")
        title.setFont(theme.label_font(8))
        box.addWidget(title)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(theme.data_font(8.5))
        self.view.document().setDocumentMargin(4)
        self.view.setLineWrapMode(QTextEdit.NoWrap)
        self._lines = protocol.diff(context.region.text if context.region else "",
                                    edit.code)
        self._render()
        theme.notifier().changed.connect(self._render)
        rows = min(max(len(self._lines), 3), 18)
        self.view.setFixedHeight(
            (rows + 1) * QFontMetrics(self.view.font()).lineSpacing() + 8)
        box.addWidget(self.view)

        row = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.setProperty("role", "primary")
        self.apply_button.clicked.connect(self.apply)
        self.reject_button = QPushButton("Reject")
        self.reject_button.clicked.connect(self.reject)
        row.addWidget(self.apply_button)
        row.addWidget(self.reject_button)
        row.addStretch()
        box.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.hide()
        box.addWidget(self.status)

        if not context.editable or source is None:
            self.apply_button.setEnabled(False)
            self.status.show()
            self.status.setText("Shown for reading: the code it is for was cut "
                                "short, or this place cannot be edited.")
        elif not self._lines:
            self.apply_button.setEnabled(False)
            self.status.show()
            self.status.setText("No change from the code as it is.")

    def _render(self, *_ignored) -> None:
        t = theme.tokens()
        rows = []
        for line in self._lines:
            colour = (t.lamp_go if line.startswith("+") and not line.startswith("+++")
                      else t.hold_ink if line.startswith("-") and not line.startswith("---")
                      else t.edge if line.startswith("@@")
                      else t.ink_muted if line.startswith(("+++", "---"))
                      else t.ink)
            rows.append(f"<span style='color:{colour}'>{html.escape(line) or '&nbsp;'}</span>")
        # Rich text ignores the widget's font: name the mono face outright.
        family = self.view.font().family()
        self.view.setHtml(f"<pre style=\"margin:0; font-family:'{family}'\">"
                          + "\n".join(rows) + "</pre>")

    def apply(self) -> bool:
        try:
            self.source.apply(self.context, self.edit)
        except StaleEdit as exc:
            self.status.show()
            self.status.setText(str(exc))
            self.status.setStyleSheet(f"color: {theme.tokens().hold_ink};")
            return False
        self._settle("Applied — Undo in the editor takes it back.")
        return True

    def reject(self) -> None:
        self._settle("Rejected.")

    def _settle(self, message: str) -> None:
        self.apply_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        self.status.setStyleSheet("")
        self.status.show()
        self.status.setText(message)


class CommandCard(QFrame):
    """A proposed command: Run, Copy to console, or Dismiss."""

    def __init__(self, command: Command, panel: AssistantPanel) -> None:
        super().__init__(panel)
        self.setProperty("hp", "panel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.command, self._panel = command, panel
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        title = QLabel("Proposed command")
        title.setFont(theme.label_font(8))
        box.addWidget(title)
        code = QLabel(command.code)
        code.setTextFormat(Qt.PlainText)
        code.setFont(theme.data_font(9))
        code.setWordWrap(True)
        code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(code)
        row = QHBoxLayout()
        self.run_button = QPushButton("Run")
        self.run_button.setProperty("role", "primary")
        self.run_button.clicked.connect(self.run)
        self.paste_button = QPushButton("Copy to console")
        self.paste_button.clicked.connect(self.paste)
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.clicked.connect(self.dismiss)
        for b in (self.run_button, self.paste_button, self.dismiss_button):
            row.addWidget(b)
        row.addStretch()
        box.addLayout(row)
        self.status = QLabel("")
        self.status.hide()
        box.addWidget(self.status)

    def run(self) -> None:
        self._panel.run_command.emit(self.command.code)
        self._settle("Ran in the console.")

    def paste(self) -> None:
        self._panel.paste_command.emit(self.command.code)
        self._settle("Copied to the console's input.")

    def dismiss(self) -> None:
        self._settle("Dismissed.")

    def _settle(self, message: str) -> None:
        for b in (self.run_button, self.paste_button, self.dismiss_button):
            b.setEnabled(False)
        self.status.show()
        self.status.setText(message)


# ──────────────────────────────────────────────────────────────
#  The dock
# ──────────────────────────────────────────────────────────────

class AssistantDock(QDockWidget):
    """The panel as a dock; its object name lets the layout remember it."""

    def __init__(self, parent: QWidget | None = None, **panel_options) -> None:
        super().__init__("Assistant", parent)
        self.setObjectName("assistantDock")
        self.panel = AssistantPanel(self, **panel_options)
        self.setWidget(self.panel)
