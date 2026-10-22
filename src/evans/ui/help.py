"""
Where "help" goes.

Every way of asking for help (Cedric at the foot of the rail, Help ▸
Documentation, F1, and Ctrl+click on a function name in the editor) lands in
:func:`open_help`, so changing what help *is* happens here once. It opens the
help window: a separate top-level window, as MATLAB's is, showing the
hand-written pages in :mod:`evans.help`.

The window has the index on the left (a search box over a tree of the
groups) and the page on the right, with back and forward. An example on a
page has a Run link that runs it in the console, through the hook the main
window installs with :func:`set_console`; with no console (a test, or the
window opened before the console exists) the link is left out.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QByteArray, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QSplitter,
    QTextBrowser,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import help as pages
from ..help.render import Colours, to_html
from . import persist, theme
from .theme_qt import mix

_window: HelpWindow | None = None
_execute: Callable[[str], object] | None = None
_busy: Callable[[], bool] = lambda: False


def open_help(topic: str | None = None) -> bool:
    """Show the help window at ``topic`` (a function's name), or the overview."""
    global _window
    if _window is None:
        _window = HelpWindow()
    _window.show_topic(topic or pages.HOME)
    _window.present()
    return True


def set_console(execute: Callable[[str], object],
                busy: Callable[[], bool] = lambda: False) -> None:
    """
    Let examples run: ``execute(source)`` runs it as if typed, ``busy()``
    says a script is running, when Run would have to wait.
    """
    global _execute, _busy
    _execute, _busy = execute, busy
    if _window is not None:
        _window.refresh()


def window() -> HelpWindow | None:
    """The help window, if it has been opened."""
    return _window


def _load(topic: str) -> pages.Page | None:
    """A page, or None: a broken page shows as missing, never as a crash."""
    try:
        return pages.load(topic)
    except (pages.PageError, OSError, UnicodeDecodeError):
        return None


class HelpWindow(QWidget):
    """The index and search on the left, the page on the right."""

    def __init__(self) -> None:
        super().__init__(None, Qt.Window)
        self.setObjectName("HelpWindow")
        self.setWindowTitle("Evans Help")
        self._history: list[str] = []
        self._at = -1
        self._page: pages.Page | None = None
        self._texts = {t: (p.text().lower() if (p := _load(t)) else "")
                       for t in pages.topics()}

        self.search = QLineEdit(placeholderText="Search functions")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._open_first_match)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemActivated.connect(self._on_item)
        self.tree.itemClicked.connect(self._on_item)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._fill_tree()

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 0, 8)
        lv.addWidget(self.search)
        lv.addWidget(self.tree)

        self.back = self._button("Back", QKeySequence.Back, lambda: self._go(-1))
        self.forward = self._button("Forward", QKeySequence.Forward,
                                    lambda: self._go(1))
        self.home = self._button("Contents", None,
                                 lambda: self.show_topic(pages.HOME))

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._on_link)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 8, 8, 8)
        bar = QHBoxLayout()
        for button in (self.back, self.forward, self.home):
            bar.addWidget(button)
        bar.addStretch(1)
        rv.addLayout(bar)
        rv.addWidget(self.browser)

        self.splitter = QSplitter()
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 640])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self.resize(900, 640)
        self._restore()
        theme.notifier().changed.connect(lambda _t: self.refresh())

    # ── navigation ───────────────────────────────────────────────

    @property
    def topic(self) -> str | None:
        return self._history[self._at] if self._at >= 0 else None

    def show_topic(self, topic: str) -> None:
        """Open ``topic``, as a new step in the history."""
        if topic != self.topic:
            del self._history[self._at + 1:]
            self._history.append(topic)
            self._at = len(self._history) - 1
        self._render()

    def present(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def refresh(self) -> None:
        """Paint the page again: the theme or the console hook changed."""
        if self.topic is not None:
            self._render()

    def _go(self, step: int) -> None:
        at = self._at + step
        if 0 <= at < len(self._history):
            self._at = at
            self._render()

    def _render(self) -> None:
        topic = self.topic
        self._page = _load(topic)
        scroll = self.browser.verticalScrollBar()
        if self._page is None:
            self.browser.setHtml(self._missing(topic))
            self.search.setText(topic)
        else:
            self.browser.setHtml(to_html(self._page, self._colours(),
                                         mono=theme.MONO,
                                         mono_pt=self._mono_pt(),
                                         run=_execute is not None))
            item = self._items.get(topic)
            if item is not None:
                self.tree.setCurrentItem(item)
        scroll.setValue(0)
        title = self._page.title if self._page else topic
        self.setWindowTitle(f"{title} · Evans Help")
        self.back.setEnabled(self._at > 0)
        self.forward.setEnabled(self._at < len(self._history) - 1)

    def _missing(self, topic: str) -> str:
        import html
        near = [t for t in self._items if topic.lower() in t.lower()][:12]
        links = " · ".join(f'<a href="help:{t}">{t}</a>' for t in near)
        more = f"<p>Close matches: {links}</p>" if near else ""
        c = self._colours()
        return (f'<html><body style="color:{c.ink}">'
                f"<h1>No page for {html.escape(topic)}</h1>"
                f'<p style="color:{c.ink_muted}">There is no help page with '
                f"that name. The search box on the left looks through every "
                f"page.</p>{more}</body></html>")

    def _mono_pt(self) -> float:
        size = self.browser.font().pointSizeF()
        return round((size if size > 0 else 10) * 0.85, 1)

    def _colours(self) -> Colours:
        t = theme.tokens()
        return Colours(ink=t.ink, ink_muted=t.ink_muted, rule=t.rule,
                       code_bg=mix(t.surface, t.ink, 0.07), link=t.edge)

    def _on_link(self, url: QUrl) -> None:
        scheme, target = url.scheme(), url.path()
        if scheme == "help":
            self.show_topic(target)
        elif scheme in ("run", "copy") and self._page is not None:
            examples = self._page.examples
            n = int(target) if target.isdigit() else -1
            if not 0 <= n < len(examples):
                return
            if scheme == "copy":
                QGuiApplication.clipboard().setText(examples[n])
            else:
                self._run(examples[n])
        elif scheme:
            QDesktopServices.openUrl(url)
        else:
            self.show_topic(url.toString())

    def _run(self, source: str) -> None:
        if _execute is None:
            return
        if _busy():
            self.browser.setToolTip("The console is busy: wait for it to "
                                    "finish, then run the example.")
            QApplication.beep()
            return
        self.browser.setToolTip("")
        _execute(source)

    # ── the index ────────────────────────────────────────────────

    def _fill_tree(self) -> None:
        def add(group: str, names) -> None:
            head = QTreeWidgetItem(self.tree, [group])
            head.setFlags(Qt.ItemIsEnabled)
            for name in names:
                if name in self._texts:
                    item = QTreeWidgetItem(head, [name])
                    item.setData(0, Qt.UserRole, name)
                    self._items[name] = item

        add("Guides", pages.GUIDES)
        for group, names in pages.GROUPS.items():
            add(group, names)
        self.tree.collapseAll()

    def _on_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        topic = item.data(0, Qt.UserRole)
        if topic:
            self.show_topic(topic)
        else:
            item.setExpanded(not item.isExpanded())

    def _matches(self, text: str) -> list[str]:
        """Name matches first, then pages that mention it."""
        text = text.strip().lower()
        if not text:
            return []
        names = [t for t in self._items if text in t.lower()]
        names.sort(key=lambda t: (not t.lower().startswith(text), len(t)))
        body = [t for t in self._items
                if t not in names and text in self._texts[t]]
        return names + body

    def _filter(self, text: str) -> None:
        hits = set(self._matches(text))
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            shown = 0
            for j in range(head.childCount()):
                child = head.child(j)
                visible = not text.strip() or child.data(
                    0, Qt.UserRole) in hits
                child.setHidden(not visible)
                shown += visible
            head.setHidden(shown == 0)
            head.setExpanded(bool(text.strip()) and shown > 0)

    def _open_first_match(self) -> None:
        hits = self._matches(self.search.text())
        if hits:
            self.show_topic(hits[0])

    # ── chrome ───────────────────────────────────────────────────

    def _button(self, text: str, key, slot) -> QToolButton:
        button = QToolButton(text=text)
        button.setAutoRaise(True)
        button.clicked.connect(slot)
        if key is not None:
            button.setShortcut(key)
        return button

    def _restore(self) -> None:
        s = persist.settings()
        geometry = s.value("help/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        split = s.value("help/splitter")
        if isinstance(split, QByteArray):
            self.splitter.restoreState(split)

    def closeEvent(self, event) -> None:          # noqa: N802 (Qt API)
        s = persist.settings()
        s.setValue("help/geometry", self.saveGeometry())
        s.setValue("help/splitter", self.splitter.saveState())
        super().closeEvent(event)
