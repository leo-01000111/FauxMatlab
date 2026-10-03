"""
The lesson panel: the note, and every claim it makes checked live.

The panel does not print the numbers from the note's prose. It runs each
:class:`~fakematlab.core.lessons.Claim` against the model that is actually
loaded and shows *predicted* beside *measured*. So if a student changes the
plant, the ticks turn into crosses in front of them — which is a better
demonstration than any paragraph, and it means the notes cannot quietly go
stale.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core.architecture import CourseArchitecture
from ..core.lessons import Lesson
from . import theme
from .design import Status
from .guard import GuardedPanel, guard


class LessonDock(QDockWidget, GuardedPanel):
    """Shows one lesson, and re-checks it against the live architecture."""

    #: The user asked to run this lesson's snippet in the console.
    console_requested = Signal(tuple)

    def __init__(self, parent=None) -> None:
        super().__init__("Lesson", parent)
        self.setObjectName("LessonDock")
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.lesson: Lesson | None = None
        self._arch: CourseArchitecture | None = None

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(6, 6, 6, 6)
        self.install_error_banner(outer)

        self._title = QLabel("")
        self._title.setWordWrap(True)
        self._title.setFont(theme.title_font(11))
        outer.addWidget(self._title)

        self._slides = QLabel("")
        self._slides.setFont(theme.label_font())
        self._slides.setForegroundRole(QPalette.Mid)      # ink_muted
        outer.addWidget(self._slides)

        split = QSplitter(Qt.Vertical)
        self._text = QTextBrowser()
        self._text.setOpenExternalLinks(False)
        split.addWidget(self._text)

        lower = QWidget()
        lower_lay = QVBoxLayout(lower)
        lower_lay.setContentsMargins(0, 0, 0, 0)
        lower_lay.addWidget(QLabel("What this lesson claims, checked against "
                                   "the model now loaded:"))
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["", "Claim", "Predicted", "Measured"])
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        lower_lay.addWidget(self._table, stretch=1)
        split.addWidget(lower)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, stretch=1)

        row = QHBoxLayout()
        self._recheck_btn = QPushButton("Re-check")
        self._recheck_btn.setToolTip(
            "Measure every claim again against whatever is loaded now.")
        self._recheck_btn.clicked.connect(self.refresh)
        row.addWidget(self._recheck_btn)

        self._console_btn = QPushButton("Try it in the console")
        self._console_btn.clicked.connect(self._send_to_console)
        row.addWidget(self._console_btn)
        row.addStretch()
        self._verdict = QLabel("")
        row.addWidget(self._verdict)
        outer.addLayout(row)

        self.setWidget(body)
        self._passed = self._total = 0
        theme.notifier().changed.connect(self._restyle)

    # ── loading ─────────────────────────────────────────────────

    def show_lesson(self, lesson: Lesson, arch: CourseArchitecture) -> None:
        self.lesson = lesson
        self._arch = arch
        self._title.setText(f"Chapter {lesson.chapter} — {lesson.title}")
        self._slides.setText(lesson.slides)
        self._text.setPlainText(lesson.summary)
        self._console_btn.setEnabled(bool(lesson.console))
        self.refresh()
        self.show()
        self.raise_()

    @guard("lesson check")
    def refresh(self, *_ignored) -> None:
        """
        Re-measure every claim against the *live* architecture.

        Deliberately not against the lesson's own stored blocks: the point is
        to show what happens when the model on screen stops being the one the
        lesson was written about.
        """
        self._table.setRowCount(0)
        if self.lesson is None or self._arch is None:
            return

        passed = 0
        for claim in self.lesson.claims:
            try:
                measured = claim.measure(self._arch)
            except Exception:                                   # noqa: BLE001
                measured = float("nan")
            ok = claim.holds(measured)
            passed += bool(ok)
            self._add_row(claim, measured, ok)

        total = len(self.lesson.claims)
        self._passed, self._total = passed, total
        self._verdict.setText(f"{passed}/{total} hold")
        self._verdict.setFont(theme.label_font(8, 700))
        self._restyle()

    def _restyle(self, *_ignored) -> None:
        """Re-colour what is coloured by hand: the verdict and the ticks."""
        status = Status.OK if self._passed == self._total else Status.CRITICAL
        self._verdict.setStyleSheet(f"color: {status.colour};")
        for row in range(self._table.rowCount()):
            tick = self._table.item(row, 0)
            if tick is not None:
                tick.setForeground(QColor(
                    (Status.OK if tick.text() == "✓" else Status.CRITICAL)
                    .colour))

    def _add_row(self, claim, measured: float, ok: bool) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        symbol = {"equals": "=", "at_least": "≥", "at_most": "≤"}[claim.mode]

        tick = QTableWidgetItem("✓" if ok else "✗")
        tick.setForeground(QColor(
            (Status.OK if ok else Status.CRITICAL).colour))
        self._table.setItem(row, 0, tick)

        text = QTableWidgetItem(claim.text)
        if claim.why:
            text.setToolTip(claim.why)
        self._table.setItem(row, 1, text)

        self._table.setItem(row, 2, QTableWidgetItem(
            f"{symbol} {claim.expected:.4g} {claim.units}".strip()))
        self._table.setItem(row, 3, QTableWidgetItem(f"{measured:.4g}"))
        self._table.resizeRowToContents(row)

    def _send_to_console(self) -> None:
        if self.lesson is not None and self.lesson.console:
            self.console_requested.emit(tuple(self.lesson.console))
