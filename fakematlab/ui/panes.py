"""
The analysis pane grid: choose how many views, and what each one shows.

Six fixed tabs meant you could look at exactly one thing at a time, which is
the wrong shape for the question this application exists to answer. Tuning a
controller is watching the step response *and* the Bode plot *and* the root
locus move together; a tab bar makes that a sequence of glances and a memory
test.

A pane is a content picker plus whatever it picked. Every pane reads the same
live architecture, so one edit updates all of them at once.

**Where the content comes from.** The plot panes are
:class:`~fakematlab.ui.apps.lti_viewer.LTIViewer` in compact mode, over a
one-system collection — the same renderer the LTI Viewer app uses, which is
what makes the viewer "the multi-system form of the analysis area" rather
than a separate application that happens to draw similar things. The panes
that are whole workflows rather than a single plot (System, Stability,
Design, Modern) host the existing tab widget.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.architecture import CourseArchitecture
from ..core.collection import SystemCollection
from ..core.viewer import ResponseKind
from .design import TIGHT, monospace
from .guard import GuardedPanel, guard


class Source(str, Enum):
    """Which system a plot pane draws."""

    CLOSED_LOOP = "T — closed loop r→y"
    OPEN_LOOP = "L — open loop"
    PLANT = "G — plant"
    SENSITIVITY = "S — sensitivity"

    def system(self, arch: CourseArchitecture):
        return {
            Source.CLOSED_LOOP: lambda: arch.get_closed_loop_tf("r", "y"),
            Source.OPEN_LOOP: arch.loop_tf,
            Source.PLANT: lambda: arch.block_tf("G"),
            Source.SENSITIVITY: arch.sensitivity,
        }[self]()


@dataclass(frozen=True)
class PaneKind:
    """One entry in a pane's content menu."""

    key: str
    label: str
    response: ResponseKind | None = None   # plot panes
    tab: str | None = None                 # panes that host an existing tab
    default_source: Source = Source.CLOSED_LOOP

    @property
    def is_plot(self) -> bool:
        return self.response is not None


#: Everything a pane can show. The plot kinds are the viewer's response
#: types; the rest host a whole workflow widget built by the window's tab
#: factory (System, Time, Frequency, ...) rather than one curve. To add a
#: kind, append a PaneKind here and, for a hosted widget, teach the factory
#: its ``tab`` name; nothing else in this module enumerates the kinds.
PANE_KINDS: tuple[PaneKind, ...] = (
    PaneKind("step", "Step response", ResponseKind.STEP),
    PaneKind("impulse", "Impulse response", ResponseKind.IMPULSE),
    PaneKind("ramp", "Ramp response", ResponseKind.RAMP),
    PaneKind("bode", "Bode", ResponseKind.BODE, default_source=Source.OPEN_LOOP),
    PaneKind("nyquist", "Nyquist", ResponseKind.NYQUIST,
             default_source=Source.OPEN_LOOP),
    PaneKind("nichols", "Nichols", ResponseKind.NICHOLS,
             default_source=Source.OPEN_LOOP),
    PaneKind("pzmap", "Pole-zero map", ResponseKind.PZMAP),
    PaneKind("rlocus", "Root locus", ResponseKind.RLOCUS,
             default_source=Source.OPEN_LOOP),
    PaneKind("metrics", "Step metrics"),
    # G = G_allpass · G_mp (ch.4, 44/46). It takes a source like a plot does,
    # and arrives on the plant, because "is the plant minimum phase?" is the
    # question the slide asks.
    PaneKind("minphase", "Minimum-phase split", default_source=Source.PLANT),
    PaneKind("system", "System overview", tab="system"),
    PaneKind("time", "Time analysis (signals, sweep)", tab="time"),
    PaneKind("frequency", "Frequency analysis (templates, overlays)",
             tab="frequency"),
    PaneKind("stability", "Stability & Routh", tab="stability"),
    PaneKind("performance", "Performance", tab="performance"),
    PaneKind("design", "Design", tab="design"),
    PaneKind("modern", "Modern control", tab="modern"),
)

_BY_KEY = {kind.key: kind for kind in PANE_KINDS}

#: What a fresh 2×2 opens with — the four views a tuning loop actually needs
#: side by side.
DEFAULT_LAYOUT = ("step", "bode", "rlocus", "metrics")


def kind(key: str) -> PaneKind:
    return _BY_KEY[key]


# ──────────────────────────────────────────────────────────────
#  Metrics pane
# ──────────────────────────────────────────────────────────────

class MetricsPane(QWidget, GuardedPanel):
    """The step-response numbers, as text rather than a plot."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(TIGHT, TIGHT, TIGHT, TIGHT)
        self.install_error_banner(layout)
        self._body = QLabel("—")
        self._body.setFont(monospace())
        self._body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.setWordWrap(True)
        layout.addWidget(self._body, stretch=1)

    @guard("step metrics")
    def refresh(self, arch: CourseArchitecture, source: Source) -> None:
        import numpy as np

        from ..core.timeresp import compute_step_metrics, step_response

        system = source.system(arch)
        metrics = compute_step_metrics(step_response(system))
        rows = []
        for name, value in metrics.as_dict().items():
            shown = "—" if not np.isfinite(value) else f"{value:.5g}"
            rows.append(f"{name:<24s} {shown:>12s}")
        self._body.setText("\n".join(rows))


# ──────────────────────────────────────────────────────────────
#  One pane
# ──────────────────────────────────────────────────────────────

class AnalysisPane(QFrame):
    """A content picker, a source picker, and whatever they selected."""

    changed = Signal()

    def __init__(self, arch: CourseArchitecture, key: str = "step",
                 tab_factory=None, parent=None,
                 source: Source | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._arch = arch
        self._tab_factory = tab_factory or (lambda name, arch: None)
        self._content: QWidget | None = None
        self._kind = kind(key)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(TIGHT, TIGHT, TIGHT, TIGHT)
        outer.setSpacing(TIGHT)

        header = QHBoxLayout()
        header.setSpacing(TIGHT)
        self._picker = QComboBox()
        for entry in PANE_KINDS:
            self._picker.addItem(entry.label, entry.key)
        self._picker.setCurrentIndex(
            [k.key for k in PANE_KINDS].index(self._kind.key))
        self._picker.setAccessibleName("pane content")
        self._picker.currentIndexChanged.connect(self._on_kind_picked)
        header.addWidget(self._picker)

        self._source = QComboBox()
        for entry in Source:
            self._source.addItem(entry.value)
        # An explicit source wins; otherwise the kind's own default. That is
        # the *only* time the default applies: after this the user owns the
        # choice, and changing the kind does not touch it.
        self._source.setCurrentIndex(list(Source).index(
            source if source is not None else self._kind.default_source))
        self._source.setEnabled(self._uses_source)
        self._source.setAccessibleName("signal shown")
        self._source.currentIndexChanged.connect(lambda _i: self.refresh())
        header.addWidget(self._source)
        header.addStretch()
        outer.addLayout(header)

        self._host = QVBoxLayout()
        self._host.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._host, stretch=1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._rebuild()

    def sizeHint(self):
        """
        The same for every pane, whatever it hosts.

        A grid short of room shares it out between each row's minimum and
        its *hint* before stretch gets a say, so one pane with a tall hint
        (the minimum-phase view wants 1124 px) takes its row's height from
        the other row. Equal hints leave the equal stretch factors in charge.
        """
        from PySide6.QtCore import QSize

        return QSize(480, 320)

    # ── state ───────────────────────────────────────────────────

    @property
    def key(self) -> str:
        return self._kind.key

    @property
    def content(self) -> QWidget | None:
        """The widget the pane currently hosts."""
        return self._content

    @property
    def source(self) -> Source:
        """
        Rebuilt from the combo's *text*, not from ``currentData``.

        Qt stores item data in a ``QVariant``, and a ``str``-mixin enum goes
        in as a member and comes back out as a plain ``str`` — which compares
        and hashes equal to the member, so lookups still work and the only
        symptom is ``.value`` raising somewhere else entirely. The LTI
        Viewer's response picker had exactly this bug.
        """
        return Source(self._source.currentText())

    def set_kind(self, key: str) -> None:
        index = [k.key for k in PANE_KINDS].index(key)
        self._picker.setCurrentIndex(index)

    def _on_kind_picked(self, index: int) -> None:
        """
        Change what is shown, but not which system it is shown *of*.

        Looking at the plant's Bode plot and then flipping to its step
        response means "the same plant, another view"; resetting the source
        to the kind's default threw that away. A kind that ignores the source
        only disables the combo, so the remembered choice is still there when
        you come back to one that uses it.
        """
        self._kind = kind(self._picker.itemData(index))
        self._source.setEnabled(self._uses_source)
        self._rebuild()
        self.changed.emit()

    @property
    def _uses_source(self) -> bool:
        return self._kind.is_plot or self._kind.key in ("metrics", "minphase")

    def set_source(self, source: Source) -> None:
        self._source.setCurrentIndex(list(Source).index(source))

    # ── content ─────────────────────────────────────────────────

    def _rebuild(self) -> None:
        while self._host.count():
            item = self._host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._content = self._make_content()
        if self._content is not None:
            # Scrolled, and not only for small panes. A word-wrapped label
            # anywhere inside makes the content height-for-width, and a grid
            # honours that above stretch *and* size hints: the minimum-phase
            # view's status line asked for 1158 px at 760 wide, its row took
            # 653 of 844, and the Bode pane above was left with zero-height
            # plots. A scroll area does not pass height-for-width up, so the
            # grid's equal stretch decides; the classic Tabs view was scrolled
            # for the same reason.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(self._content)
            self._host.addWidget(scroll)
        self.refresh()

    def _make_content(self) -> QWidget | None:
        if self._kind.key == "metrics":
            return MetricsPane()
        if self._kind.key == "minphase":
            from .minphase_view import MinPhaseView

            return MinPhaseView()
        if self._kind.is_plot:
            from .apps.lti_viewer import LTIViewer

            viewer = LTIViewer(SystemCollection(), compact=True)
            viewer.set_response(self._kind.response)
            return viewer
        return self._tab_factory(self._kind.tab, self._arch)

    # ── refresh ─────────────────────────────────────────────────

    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        if arch is not None:
            self._arch = arch
        if self._content is None:
            return

        if self._kind.key == "metrics":
            self._content.refresh(self._arch, self.source)
            return

        if self._kind.key == "minphase":
            source = self.source
            self._content.show_system(source.system(self._arch),
                                      source.value.split(" ")[0])
            return

        if self._kind.is_plot:
            collection = SystemCollection()
            source = self.source
            collection.add(source.value.split(" ")[0],
                           source.system(self._arch))
            self._content.set_collection(collection)
            return

        refresh = getattr(self._content, "refresh", None)
        if callable(refresh):
            refresh(self._arch)


# ──────────────────────────────────────────────────────────────
#  The grid
# ──────────────────────────────────────────────────────────────

#: Pane counts and how they are arranged.
LAYOUTS = {1: (1, 1), 2: (1, 2), 4: (2, 2)}


class PaneGrid(QWidget):
    """One, two or four panes over the same architecture."""

    def __init__(self, arch: CourseArchitecture, tab_factory=None,
                 parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self._tab_factory = tab_factory
        self.panes: list[AnalysisPane] = []

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(TIGHT)
        self.set_layout_size(1)

    # ── layout ──────────────────────────────────────────────────

    def set_layout_size(self, count: int,
                        keys: tuple[str, ...] | None = None,
                        sources: tuple[Source | None, ...] | None = None
                        ) -> None:
        """Re-lay the grid to ``count`` panes, keeping what was chosen."""
        if count not in LAYOUTS:
            raise ValueError(f"layout must be one of {sorted(LAYOUTS)}, "
                             f"got {count}")
        existing = keys or tuple(p.key for p in self.panes)
        wanted = list(existing[:count])
        # Sources ride along with the panes that survive a re-layout; an
        # explicit ``sources`` (restoring a saved layout) overrides them, and
        # new panes get None, i.e. their kind's default.
        carried = sources if sources is not None else (
            tuple(p.source for p in self.panes) if keys is None else ())
        chosen: list[Source | None] = list(carried[:count])
        while len(wanted) < count:
            wanted.append(DEFAULT_LAYOUT[len(wanted) % len(DEFAULT_LAYOUT)])
        chosen += [None] * (count - len(chosen))

        for pane in self.panes:
            self._grid.removeWidget(pane)
            pane.setParent(None)
            pane.deleteLater()
        self.panes = []

        rows, columns = LAYOUTS[count]
        # Equal shares, whatever the panes hold. Left to size hints, a pane
        # with a tall hint (a Nichols chart, the minimum-phase view) took
        # most of the height and crushed its neighbour's Bode plot to a
        # strip; and a 4 → 2 relayout would keep the old rows' stretch.
        for index in range(max(LAYOUTS[4])):
            self._grid.setRowStretch(index, 1 if index < rows else 0)
            self._grid.setColumnStretch(index, 1 if index < columns else 0)
        for index, key in enumerate(wanted):
            pane = AnalysisPane(self._arch, key, self._tab_factory,
                                source=chosen[index])
            self.panes.append(pane)
            self._grid.addWidget(pane, index // columns, index % columns)
        self.refresh()

    @property
    def count(self) -> int:
        return len(self.panes)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(pane.key for pane in self.panes)

    @property
    def sources(self) -> tuple[Source, ...]:
        return tuple(pane.source for pane in self.panes)

    def set_active_signal(self, signal_id: str) -> None:
        """A diagram signal was clicked: tell every pane that can use it."""
        for pane in self.panes:
            setter = getattr(pane.content, "set_active_signal", None)
            if callable(setter):
                setter(signal_id)

    # ── refresh ─────────────────────────────────────────────────

    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        """One architecture edit, every visible pane."""
        if arch is not None:
            self._arch = arch
        for pane in self.panes:
            pane.refresh(self._arch)
