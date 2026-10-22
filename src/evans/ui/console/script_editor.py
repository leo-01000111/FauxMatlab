"""
The Script tab: several scripts open at once, each in a tab of its own.

Each tab is a :class:`~evans.ui.code.CodeEditor` and the file it came from,
or *Untitled N* until it is first saved. A tab with changes not yet on disk
says so with a dot, and closing it — or quitting — asks whether to save
them first. The tabs that were open come back at the next start, each at
the line it was left on.

The run and debug controls above the tabs act on the tab that is showing;
:class:`~.console_dock.ConsolePanel` keeps track of which one is running,
since tabs can be switched while a script runs or is paused.

Keys, while a script has the keyboard: Ctrl+N a new script, Ctrl+O open,
Ctrl+S save, Ctrl+Shift+S save as, Ctrl+W close the tab. Elsewhere in the
window the same keys keep their meaning for sessions.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...console.matlab import looks_like_matlab
from ...console.tracer import file_key
from .. import iconset, keys, persist
from ..code import CodeEditor, section_source

#: Shown on a tab whose text differs from its file.
UNSAVED_MARK = " ●"

#: Where the open tabs are remembered between sessions.
OPEN_KEY = "scripts/open"
CURSORS_KEY = "scripts/cursors"
CURRENT_KEY = "scripts/current"

_PLACEHOLDER = (
    "% MATLAB (or Python) — paste a .m script and press Run.\n"
    "s = tf('s');\n"
    "G = 1/((s+1)*(0.5*s+1));\n"
    "T = feedback(pid(2, 1)*G, 1);\n"
    "step(G, T); legend('open loop', 'closed loop')\n"
    "stepinfo(T)")

_SUFFIX_LANGUAGE = {".m": "matlab", ".py": "python"}


class ScriptDocument:
    """One tab: its editor, its file (None until saved) and its language."""

    def __init__(self, code: CodeEditor, number: int) -> None:
        self.code = code
        self.path: Path | None = None
        #: The language selector's choice for this tab: auto, matlab, python.
        self.language = "auto"
        #: *Untitled N*: the N, kept so the name does not change on its own.
        self.number = number
        self._completion_language: tuple[int, str] | None = None

    @property
    def key(self) -> str:
        """The tracer's name for it: its file's, or one for an Untitled."""
        return file_key(self.path) if self.path else f"<untitled:{self.number}>"

    @property
    def name(self) -> str:
        return self.path.name if self.path else f"Untitled {self.number}"

    @property
    def modified(self) -> bool:
        return self.code.document().isModified()

    @property
    def blank(self) -> bool:
        """An Untitled tab nothing was typed into: fine to reuse or drop."""
        return self.path is None and not self.modified \
            and not self.code.toPlainText()

    def text(self) -> str:
        return self.code.toPlainText()


class ScriptEditor(QWidget):
    """
    Editors that run their contents against the console's namespace.

    Their job is to let a sequence of commands be kept, edited and re-run
    without retyping, which is what a script is for — with what that needs
    in practice: highlighting, line numbers, ``%%`` sections run on their
    own (Ctrl+Enter), Tab completion, and a debugger (click the gutter for a
    breakpoint; F5 continues, F10 steps, F11 steps in, Shift+F5 stops).
    Still no project model.

    Each takes MATLAB or Python. *Auto* decides from the text, and a script
    that reads as both (or as nothing yet) is MATLAB, the app's language;
    the selector is there to say otherwise.
    """

    #: (source, language) — language is "matlab" or "python".
    run_requested = Signal(str, str)
    #: A file was opened or saved — the recent-files list listens.
    file_used = Signal(object)                 # Path
    #: (source padded to its lines, language, move on afterwards).
    section_requested = Signal(str, str, bool)
    #: Stop, Continue / Step / Step in: "stop", "continue", "step", "step_in".
    debug_requested = Signal(str)
    #: Breakpoints changed in some tab, or a tab came or went.
    breakpoints_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._numbers = itertools.count(1)
        self._documents: list[ScriptDocument] = []
        self._completion = None
        self._completion_source = None
        #: The tab a run is using, which must not be closed under it.
        self._busy: ScriptDocument | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        row = QHBoxLayout()
        run = QPushButton("Run (F5)")
        iconset.bind(run, "run")
        run.setToolTip(
            "Run the whole script (F5), or continue when paused. The console "
            "and the last run's figures are cleared first; unsaved figures "
            "are offered for saving.")
        run.clicked.connect(self._run)
        row.addWidget(run)
        self._run_button = run
        section = QPushButton("Run section")
        section.setToolTip(keys.label(
            "Run the %% section the cursor is in (Ctrl+Enter); "
            "Ctrl+Shift+Enter runs it and moves to the next. Appends to the "
            "console, like typed commands."))
        section.clicked.connect(lambda: self.run_section(False))
        row.addWidget(section)
        self._section_button = section

        def debug(label: str, action: str, tip: str) -> QToolButton:
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            button.setEnabled(False)
            button.clicked.connect(
                lambda: self.debug_requested.emit(action))
            row.addWidget(button)
            return button

        self._stop_button = debug("Stop", "stop",
                                  "Stop the run (Shift+F5)")
        iconset.bind(self._stop_button, "stop", "hold_ink")
        self._stop_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._step_button = debug("Step", "step",
                                  "Run the paused line (F10)")
        self._step_in_button = debug(
            "Step in", "step_in",
            "Run the paused line, stopping inside a function it calls (F11)")
        # What a run said, beside the controls that started it. Ignored
        # width: a long message must not widen the window.
        self._status = QLabel("")
        self._status.setStyleSheet("color: palette(mid);")
        self._status.setSizePolicy(QSizePolicy.Ignored,
                                   QSizePolicy.Preferred)
        row.addWidget(self._status, stretch=1)
        layout.addLayout(row)

        # A second row for the files and the language, so the run and debug
        # controls do not set the window's minimum width.
        row = QHBoxLayout()
        for label, icon, slot, tip in (
                ("New", "add", self.new_document,
                 "A new, untitled script in a tab of its own (Ctrl+N)"),
                ("Open…", "open", self._open,
                 "Open a script in a new tab (Ctrl+O)"),
                ("Save", "save", self.save,
                 "Save this script (Ctrl+S)"),
                ("Save as…", None, self.save_as,
                 "Save this script under another name (Ctrl+Shift+S)")):
            button = QPushButton(label)
            if icon:
                iconset.bind(button, icon)
            button.setToolTip(keys.label(tip))
            button.clicked.connect(lambda _=False, slot=slot: slot())
            row.addWidget(button)
        row.addSpacing(12)
        row.addWidget(QLabel("Language"))
        self._language = QComboBox()
        for label, key in (("Auto", "auto"), ("MATLAB", "matlab"),
                           ("Python", "python")):
            self._language.addItem(label, key)
        self._language.currentIndexChanged.connect(self._language_chosen)
        row.addWidget(self._language)
        self._detected = QLabel("")
        self._detected.setStyleSheet("color: palette(mid);")
        row.addWidget(self._detected)
        row.addStretch()
        self._path_label = QLabel("")
        self._path_label.setStyleSheet("color: palette(mid);")
        self._path_label.setSizePolicy(QSizePolicy.Ignored,
                                       QSizePolicy.Preferred)
        row.addWidget(self._path_label, stretch=1)
        layout.addLayout(row)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(
            lambda index: self.close_document(self._document_at(index)))
        self._tabs.currentChanged.connect(self._on_current_changed)
        layout.addWidget(self._tabs, stretch=1)

        self._keys = _ScriptKeys(self)
        self.new_document()

    # ── tabs ────────────────────────────────────────────────────

    def documents(self) -> list[ScriptDocument]:
        """The open scripts, in tab order."""
        return [self._document_at(i) for i in range(self._tabs.count())]

    def current_document(self) -> ScriptDocument:
        return self._document_at(self._tabs.currentIndex())

    def _document_at(self, index: int) -> ScriptDocument:
        widget = self._tabs.widget(index)
        return next(d for d in self._documents if d.code is widget)

    def document_for(self, path: str | Path) -> ScriptDocument | None:
        """The tab showing ``path``, if one is."""
        key = file_key(path)
        return next((d for d in self._documents
                     if d.path is not None and d.key == key), None)

    def document_by_key(self, key: str | None) -> ScriptDocument | None:
        return next((d for d in self._documents if d.key == key), None)

    def show_document(self, document: ScriptDocument) -> None:
        self._tabs.setCurrentWidget(document.code)

    def new_document(self) -> ScriptDocument:
        """A new Untitled tab, shown."""
        code = CodeEditor()
        document = ScriptDocument(code, next(self._numbers))
        code.setPlaceholderText(_PLACEHOLDER)
        code.run_section_requested.connect(self.run_section)
        code.textChanged.connect(
            lambda: self._text_changed(document))
        code.document().modificationChanged.connect(
            lambda _modified: self._retitle(document))
        code.breakpoints_changed.connect(
            lambda _lines: self.breakpoints_changed.emit())
        if self._completion is not None:
            code.set_completion(self._completion)
        if self._completion_source is not None:
            code.set_completion_source(self._completion_source)
        code.installEventFilter(self._keys)
        self._documents.append(document)
        self._tabs.addTab(code, document.name)
        self._retitle(document)
        self._tabs.setCurrentWidget(code)
        code.setFocus()
        self.breakpoints_changed.emit()
        return document

    def _retitle(self, document: ScriptDocument) -> None:
        index = self._tabs.indexOf(document.code)
        if index < 0:
            return
        self._tabs.setTabText(
            index, document.name + (UNSAVED_MARK if document.modified else ""))
        self._tabs.setTabToolTip(
            index, str(document.path) if document.path
            else "Not saved yet")

    def _on_current_changed(self, _index: int) -> None:
        if not self._documents or self._tabs.count() == 0:
            return
        document = self.current_document()
        self._language.blockSignals(True)
        self._language.setCurrentIndex(
            max(0, self._language.findData(document.language)))
        self._language.blockSignals(False)
        self._path_label.setText(str(document.path) if document.path
                                 else "not saved yet")
        self._update_detected()

    def _text_changed(self, document: ScriptDocument) -> None:
        if document is self.current_document():
            self._update_detected()

    def close_document(self, document: ScriptDocument) -> bool:
        """
        Close a tab, asking first if it has unsaved changes. Returns False
        if it stayed open. The last tab closed leaves a new Untitled one.
        """
        if document is self._busy:
            self.set_status("Stop the run before closing the script it is "
                            "running.")
            return False
        if document.modified and not self._settle_unsaved(document):
            return False
        self._documents.remove(document)
        self._tabs.removeTab(self._tabs.indexOf(document.code))
        document.code.deleteLater()
        if not self._documents:
            self.new_document()
        self.breakpoints_changed.emit()
        return True

    def _settle_unsaved(self, document: ScriptDocument) -> bool:
        """Save, discard or cancel; True unless the user cancelled."""
        self.show_document(document)
        choice = self._ask_to_save(document)
        if choice == "cancel":
            return False
        return choice == "discard" or self.save(document)

    def _ask_to_save(self, document: ScriptDocument) -> str:
        """'save', 'discard' or 'cancel'. A method so tests can answer it."""
        box = QMessageBox(
            QMessageBox.Question, "Save script?",
            f"{document.name} has changes that are not saved.",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
        box.setDefaultButton(QMessageBox.Save)
        answer = box.exec()
        return {QMessageBox.Save: "save",
                QMessageBox.Discard: "discard"}.get(answer, "cancel")

    def confirm_close_all(self) -> bool:
        """
        Before quitting: settle every tab with unsaved changes, one at a
        time. Returns False if the user cancelled, and Evans stays open.
        """
        return all(self._settle_unsaved(d) for d in self.documents()
                   if d.modified)

    def set_busy(self, document: ScriptDocument | None) -> None:
        """The tab a run is using, which stays open until it ends."""
        self._busy = document

    # ── files ───────────────────────────────────────────────────

    def _open(self) -> None:
        folder = self.current_document().path
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open script", str(folder.parent) if folder else "",
            "Scripts (*.m *.py);;MATLAB scripts (*.m);;Python scripts (*.py);;"
            "All files (*)")
        for path in paths:
            self.load_file(path)

    def load_file(self, path: str | Path,
                  line: int | None = None) -> ScriptDocument:
        """
        Show a script: its tab if it is open already, else a new tab (or
        the blank Untitled one, which it replaces). The language follows
        the suffix. ``line`` puts the cursor there.
        """
        path = Path(path)
        document = self.document_for(path)
        if document is None:
            text = path.read_text(encoding="utf-8")
            current = self.current_document()
            document = current if current.blank else self.new_document()
            document.path = path.resolve()
            document.code.setPlainText(text)
            document.code.document().setModified(False)
            document.code.set_breakpoints(())
            document.language = _SUFFIX_LANGUAGE.get(path.suffix.lower(),
                                                      "auto")
            self._retitle(document)
            self.breakpoints_changed.emit()
        self.show_document(document)
        self._on_current_changed(self._tabs.currentIndex())
        if line:
            document.code.goto_line(line)
        self.file_used.emit(document.path)
        return document

    def save(self, document: ScriptDocument | None = None) -> bool:
        """Save to its file, or ask for one. Returns whether it was saved."""
        document = document or self.current_document()
        if document.path is None:
            return self.save_as(document)
        return self._write(document, document.path)

    def save_as(self, document: ScriptDocument | None = None) -> bool:
        document = document or self.current_document()
        language = self._language_of(document)
        default = document.path or Path(
            "script.m" if language == "matlab" else "script.py")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save script", str(default),
            "MATLAB scripts (*.m);;Python scripts (*.py);;All files (*)")
        if not path:
            return False
        other = self.document_for(path)
        if other is not None and other is not document:
            self.set_status(f"{Path(path).name} is open in another tab; "
                            "close it first.")
            return False
        return self._write(document, Path(path))

    def _write(self, document: ScriptDocument, path: Path) -> bool:
        try:
            path.write_text(document.text(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Save error", str(exc))
            return False
        renamed = document.path != path.resolve()
        document.path = path.resolve()
        document.code.document().setModified(False)
        self._retitle(document)
        if document is self.current_document():
            self._on_current_changed(self._tabs.currentIndex())
        if renamed:
            self.breakpoints_changed.emit()
        self.file_used.emit(document.path)
        return True

    def unsaved_files(self, suffix: str = ".m",
                      exclude: ScriptDocument | None = None
                      ) -> list[ScriptDocument]:
        """Tabs of saved ``suffix`` files whose changes are not on disk."""
        return [d for d in self.documents()
                if d is not exclude and d.path is not None and d.modified
                and d.path.suffix.lower() == suffix]

    # ── remembered between sessions ─────────────────────────────

    def remember_open(self) -> None:
        """Note which files are open, and where, for the next start."""
        saved = [d for d in self.documents() if d.path is not None]
        settings = persist.settings()
        settings.setValue(OPEN_KEY, [str(d.path) for d in saved])
        settings.setValue(CURSORS_KEY, [str(d.code.textCursor().position())
                                        for d in saved])
        current = self.current_document()
        settings.setValue(CURRENT_KEY,
                          str(current.path) if current.path else "")

    def reopen_remembered(self) -> int:
        """Open the files that were open last time. Returns how many."""
        settings = persist.settings()
        paths = persist._string_list(settings.value(OPEN_KEY))
        cursors = persist._string_list(settings.value(CURSORS_KEY))
        opened = 0
        for k, path in enumerate(paths):
            if not Path(path).is_file():
                continue
            try:
                document = self.load_file(path)
            except (OSError, UnicodeDecodeError):
                continue
            opened += 1
            try:
                position = int(cursors[k])
            except (IndexError, ValueError):
                continue
            cursor = document.code.textCursor()
            cursor.setPosition(min(position,
                                   document.code.document().characterCount()
                                   - 1))
            document.code.setTextCursor(cursor)
        current = settings.value(CURRENT_KEY)
        if current:
            document = self.document_for(current) \
                if Path(str(current)).is_file() else None
            if document is not None:
                self.show_document(document)
        return opened

    # ── the showing tab ─────────────────────────────────────────

    @property
    def code(self) -> CodeEditor:
        """The showing tab's text area: breakpoints, highlights, sections."""
        return self.current_document().code

    @property
    def path(self) -> Path | None:
        """The file the showing script was opened from or saved to, if any."""
        return self.current_document().path

    def set_text(self, text: str) -> None:
        """Replace the showing script's text, as typing it would."""
        code = self.code
        cursor = code.textCursor()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(text)

    def text(self) -> str:
        return self.code.toPlainText()

    def set_completion_source(self, source) -> None:
        self._completion_source = source
        for document in self._documents:
            document.code.set_completion_source(source)

    def set_completion(self, request) -> None:
        """The completion popup, offering ``request(text before cursor)``."""
        self._completion = request
        for document in self._documents:
            document.code.set_completion(request)

    def completion_language(self) -> str:
        """
        :meth:`language`, for completing while typing: *Auto* reads the
        whole text, so its answer is kept until the line count changes.
        """
        document = self.current_document()
        if document.language != "auto":
            return document.language
        lines = document.code.blockCount()
        cached = document._completion_language
        if cached is None or cached[0] != lines:
            document._completion_language = (lines,
                                             self._language_of(document))
        return document._completion_language[1]

    def language(self) -> str:
        """The language the next run will use: 'matlab' or 'python'."""
        return self._language_of(self.current_document())

    @staticmethod
    def _language_of(document: ScriptDocument) -> str:
        if document.language != "auto":
            return document.language
        text = document.text()
        return "matlab" if not text.strip() or looks_like_matlab(text) \
            else "python"

    def set_language(self, key: str) -> None:
        index = self._language.findData(key)
        if index >= 0:
            self._language.setCurrentIndex(index)

    def _language_chosen(self, _index: int) -> None:
        self.current_document().language = self._language.currentData()
        self._update_detected()

    def _update_detected(self, *_args) -> None:
        document = self.current_document()
        auto = document.language == "auto"
        language = self._language_of(document)
        name = "MATLAB" if language == "matlab" else "Python"
        self._detected.setText(f"(reads as {name})"
                               if auto and document.text().strip() else "")
        document.code.set_language(language)

    def _run(self) -> None:
        self.run_requested.emit(self.text(), self.language())

    def run_section(self, advance: bool = False) -> None:
        """Ask for the section under the cursor to run (then move on)."""
        section = self.code.current_section()
        self.section_requested.emit(section_source(self.text(), section),
                                    self.language(), advance)

    def next_section(self, document: ScriptDocument | None = None) -> None:
        """Put the cursor at the start of the section after the current."""
        code = (document or self.current_document()).code
        current = code.current_section()
        later = [s for s in code.sections() if s.start > current.start]
        if later:
            code.goto_line(later[0].start)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_run_state(self, running: bool, paused: bool) -> None:
        """Which buttons apply: Run is Continue while paused."""
        self._run_button.setText("Continue (F5)" if paused
                                 else "Run (F5)")
        self._run_button.setEnabled(paused or not running)
        self._section_button.setEnabled(not running)
        self._stop_button.setEnabled(running)
        self._step_button.setEnabled(paused)
        self._step_in_button.setEnabled(paused)


class _ScriptKeys(QObject):
    """
    Ctrl+N / O / S / Shift+S / W for scripts, while a script has the
    keyboard. The window's menu has the same keys for sessions; claiming
    them in ``ShortcutOverride`` is what lets the editor have them first.
    """

    def __init__(self, editor: ScriptEditor) -> None:
        super().__init__(editor)
        self._editor = editor
        self._actions = {
            QKeySequence("Ctrl+N"): editor.new_document,
            QKeySequence("Ctrl+O"): editor._open,
            QKeySequence("Ctrl+S"): editor.save,
            QKeySequence("Ctrl+Shift+S"): editor.save_as,
            QKeySequence("Ctrl+W"): lambda: editor.close_document(
                editor.current_document()),
        }

    def _action(self, event):
        combo = QKeySequence(event.keyCombination())
        return self._actions.get(combo)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        kind = event.type()
        if kind == QEvent.ShortcutOverride and self._action(event):
            event.accept()
            return True
        if kind == QEvent.KeyPress:
            action = self._action(event)
            if action is not None:
                action()
                return True
        return False
