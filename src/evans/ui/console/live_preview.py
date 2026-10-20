"""
The live script's PDF, beside it: an Overleaf-style preview.

The editor asks for a build (Ctrl+Enter, *Rebuild*, a run) and never on a
keystroke. The .tex and the figure PNGs are written on the UI thread — the
``{{expr}}`` placeholders read the interpreter, which is not thread-safe —
and the TeX engine runs on a thread of its own, with the same engine search
and fallbacks as *Export report*. Until it finishes, the last good PDF stays
on screen; a failed build shows TeX's error above it and keeps it. A request
made while a build runs is remembered and run straight after, once.

The PDF is shown with QtPdf (``QPdfDocument`` + ``QPdfView``). Each good
build is copied to a file of its own before it is loaded, because the
document keeps its file open and the next build must be able to write.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import weakref
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...console.live.report import (
    INSTALL_HINT,
    build_with,
    compile_pdf,
    find_engines,
    write_tex,
)
from .. import theme

#: The preview's own narrowest: the Live tab must still fit a 1280 px window.
MIN_WIDTH = 220


class LivePreview(QWidget):
    """The PDF of a live script, rebuilt on request."""

    #: The user asked for a build (Rebuild, or Ctrl+Enter over the PDF);
    #: the editor answers with :meth:`build`, as only it has the document.
    rebuild_requested = Signal()
    #: The user asked to edit the report template.
    template_requested = Signal()
    #: A build finished: (ok, pdf or None, log). Emitted from the build
    #: thread, delivered on the UI thread.
    finished = Signal(bool, object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(MIN_WIDTH)
        self._work = Path(tempfile.mkdtemp(prefix="evans-preview-"))
        weakref.finalize(self, shutil.rmtree, str(self._work), True)
        self._figures: dict = {}          # spec id → (spec, png), see report
        self._thread: threading.Thread | None = None
        self._pending = False
        self._started = 0.0
        self._engine = ""
        self._shown: Path | None = None
        self._builds = 0
        #: Builds that produced a PDF — for the status line and the tests.
        self.good_builds = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        row = QHBoxLayout()
        self.rebuild_button = QPushButton("Rebuild")
        self.rebuild_button.setToolTip("Build the PDF again (Ctrl+Enter in "
                                       "the script also rebuilds)")
        self.rebuild_button.clicked.connect(self.rebuild_requested)
        row.addWidget(self.rebuild_button)
        template = QPushButton("Template…")
        template.setToolTip("Page, title, header and footer, numbering, "
                            "preamble — for this script or every script")
        template.clicked.connect(self.template_requested)
        row.addWidget(template)
        self.status = QLabel("")
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.status, stretch=1)
        layout.addLayout(row)

        t = theme.tokens()
        self.error = QPlainTextEdit()
        self.error.setReadOnly(True)
        self.error.setFont(theme.data_font(9))
        self.error.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.error.setMaximumHeight(130)
        self.error.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.surface}; color: {t.hold_ink};"
            f" border: 1px solid {t.hold_ink}; }}")
        self.error.hide()
        layout.addWidget(self.error)

        self.pdf = QPdfDocument(self)
        self.view = QPdfView(self)
        self.view.setDocument(self.pdf)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setMinimumWidth(MIN_WIDTH)
        layout.addWidget(self.view, stretch=1)

        self.placeholder = QLabel("Press Ctrl+Enter or Rebuild to build "
                                  "the PDF.")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder)
        self.view.hide()

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.rebuild_requested)
        self.finished.connect(self._on_finished)

    # ── building ────────────────────────────────────────────────

    @property
    def building(self) -> bool:
        return self._thread is not None

    def build(self, document, evaluate, template) -> bool:
        """
        Start a build of ``document`` with ``template``. Returns whether one
        started; while one runs, the request is kept and run afterwards.
        """
        if self.building:
            self._pending = True
            self.status.setText("Building… (another build queued)")
            return False
        engines = find_engines()
        if not engines:
            self._show_error("No TeX engine was found, so there is no PDF "
                             "to show.\n\n" + INSTALL_HINT.split("\n\n", 1)[1])
            self.status.setText("No TeX engine")
            return False
        self._builds += 1
        try:
            report = write_tex(document, self._work / "preview.tex",
                               evaluate=evaluate, template=template,
                               cache=self._figures)
        except Exception as exc:                      # noqa: BLE001
            self._show_error(f"Could not write the LaTeX: "
                             f"{type(exc).__name__}: {exc}")
            return False
        self._engine = engines[0][0]
        self._started = time.monotonic()
        self.status.setText(f"Building with {self._engine}…")
        self._thread = threading.Thread(
            target=lambda: self.finished.emit(
                *build_with(report, engines, compile=compile_pdf)),
            daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float = 10) -> None:
        """Block until the running build's thread is done (for tests)."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _on_finished(self, ok: bool, pdf, log: str) -> None:
        self._thread = None
        seconds = time.monotonic() - self._started
        if ok and pdf is not None and Path(pdf).exists():
            self._show_pdf(Path(pdf))
            self.error.hide()
            self.good_builds += 1
            self.status.setText(f"Built in {seconds:.1f} s")
        else:
            self._show_error(log or "The build failed without a log.")
            self.status.setText("Build failed — "
                                + ("showing the last good PDF"
                                   if self._shown else "no PDF yet"))
        if self._pending:
            self._pending = False
            self.rebuild_requested.emit()

    def _show_error(self, text: str) -> None:
        self.error.setPlainText(text.strip())
        self.error.show()

    # ── showing ─────────────────────────────────────────────────

    def _show_pdf(self, built: Path) -> None:
        """Load a new build where the reader was: same page, same scroll."""
        target = self._work / f"shown-{self._builds}.pdf"
        shutil.copy2(built, target)
        bars = self.view.verticalScrollBar(), self.view.horizontalScrollBar()
        where = [bar.value() for bar in bars]
        old = self._shown
        self.pdf.load(str(target))
        self._shown = target
        self.placeholder.hide()
        self.view.show()

        def restore() -> None:
            for bar, value in zip(bars, where):
                bar.setValue(min(value, bar.maximum()))
        restore()
        # The view lays the new pages out on its next turn as well.
        QTimer.singleShot(0, restore)
        if old is not None and old != target:
            try:
                old.unlink()
            except OSError:
                pass                       # still open somewhere: left to go

    def current_page(self) -> int:
        return self.view.pageNavigator().currentPage()

    @property
    def page_count(self) -> int:
        return self.pdf.pageCount()

    @property
    def scroll(self) -> int:
        return self.view.verticalScrollBar().value()
