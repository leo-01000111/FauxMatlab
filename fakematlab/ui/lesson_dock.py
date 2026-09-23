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
from PySide6.QtGui import QFont
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
from .guard import GuardedPanel, guard

_OK = "#56C271"
_BAD = "#F45B69"


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
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        self._title.setFont(title_font)
        outer.addWidget(self._title)

        self._slides = QLabel("")
        self._slides.setStyleSheet("color: palette(mid);")
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
        colour = _OK if passed == total else _BAD
        self._verdict.setText(f"{passed}/{total} hold")
        self._verdict.setStyleSheet(f"color: {colour}; font-weight: bold;")

    def _add_row(self, claim, measured: float, ok: bool) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        symbol = {"equals": "=", "at_least": "≥", "at_most": "≤"}[claim.mode]

        tick = QTableWidgetItem("✓" if ok else "✗")
        tick.setForeground(Qt.GlobalColor.green if ok else Qt.GlobalColor.red)
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
