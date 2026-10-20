"""
The completion popup: one widget for the console, the script editor and
both kinds of live-script cell.

:class:`CompletionPopup` draws the list — each row the name, the rest of its
call in a muted ink (``step`` ``(sys, t)``) and a one-line description to the
right — and a footer with the highlighted entry in full. It is a child of the
editor's window, never a window of its own, and takes no focus: the editor
keeps the keyboard and the popup only listens.

:class:`CompletionController` attaches to a ``QPlainTextEdit`` or a
``QLineEdit`` through an event filter. ``request(before)`` turns the text
before the cursor into a :class:`~.completion.Request`. Typing opens the
popup once the word is long enough (and something starts with it), and
narrows it; Up/Down/PageUp/PageDown move, Tab or Return accept (a
function with its brackets, see :func:`call_insertion`), Escape
closes; Ctrl+Space opens it on demand. With ``tab_completes`` a Tab with the
popup closed completes too (one match at once, else the common prefix and
the popup); otherwise the editor decides what Tab means and calls
:meth:`CompletionController.complete` itself.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QFrame,
    QLabel,
    QLineEdit,
    QListView,
    QPlainTextEdit,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from .completion import Completion, Request, common_prefix, rank_scored
from .signatures import SIGNATURES

#: Rows shown before the list scrolls.
VISIBLE_ROWS = 10
#: Most rows the list holds; a narrower prefix finds the rest.
MAX_ROWS = 200
#: The one-letter tag drawn before each row, by kind.
KIND_TAGS = {"variable": "v", "function": "f", "command": "f",
             "keyword": "k", "constant": "c", "module": "m", "class": "C",
             "attribute": "a", "file": "m", "latex": "\\",
             "environment": "e", "label": "#"}

_ROLE = Qt.UserRole + 1


class _Model(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[Completion] = []

    def set_items(self, items: list[Completion]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:   # noqa: N802 (Qt API)
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return item.text
        if role == _ROLE:
            return item
        return None


class _Delegate(QStyledItemDelegate):
    """Tag, name, the rest of the call, and the description at the right."""

    def __init__(self, popup: CompletionPopup) -> None:
        super().__init__(popup)
        self._popup = popup

    def sizeHint(self, option, index) -> QSize:        # noqa: N802 (Qt API)
        return QSize(100, self._popup.row_height())

    def paint(self, painter: QPainter, option, index) -> None:
        item: Completion = index.data(_ROLE).resolved()
        t = theme.tokens()
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        painter.save()
        if selected:
            painter.fillRect(rect, QColor(t.signal))
        ink = QColor(t.on_signal if selected else t.ink)
        muted = QColor(t.on_signal if selected else t.ink_muted)
        font = self._popup.font()
        fm = QFontMetrics(font)
        pad = 6
        tag_w = self._popup.tag_width()

        painter.setFont(theme.label_font(8))
        painter.setPen(muted)
        painter.drawText(QRect(rect.left() + pad, rect.top(), tag_w,
                               rect.height()), Qt.AlignVCenter | Qt.AlignLeft,
                         KIND_TAGS.get(item.kind, "·"))

        painter.setFont(font)
        x = rect.left() + pad + tag_w
        right = rect.right() - pad
        name_w = fm.horizontalAdvance(item.text)
        painter.setPen(ink)
        painter.drawText(QRect(x, rect.top(), name_w + 1, rect.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, item.text)
        x += name_w
        rest = _call_rest(item)
        if rest:
            room = max(0, right - x - self._popup.detail_room())
            shown = fm.elidedText(rest, Qt.ElideRight, room)
            painter.setPen(muted)
            painter.drawText(QRect(x, rect.top(), room, rect.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, shown)
            x += fm.horizontalAdvance(shown)
        if item.detail:
            small = theme.ui_font(8.5)
            sfm = QFontMetrics(small)
            room = right - x - 16
            if room > 40:
                painter.setFont(small)
                painter.setPen(muted)
                painter.drawText(QRect(right - room, rect.top(), room,
                                       rect.height()),
                                 Qt.AlignVCenter | Qt.AlignRight,
                                 sfm.elidedText(item.detail, Qt.ElideRight,
                                                room))
        painter.restore()


def _call_rest(item: Completion) -> str:
    """What the signature adds after the name: ``(sys, t)`` for ``step``."""
    sig = item.signature
    if not sig:
        return ""
    if sig.startswith(item.text):
        return sig[len(item.text):]
    return "  " + sig


class CompletionPopup(QFrame):
    """The list. Keyboard-free: its controller feeds it the keys."""

    #: A row was clicked.
    picked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompletionPopup")
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFont(theme.data_font(9.5))
        self.model = _Model(self)
        self.view = QListView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(_Delegate(self))
        self.view.setFocusPolicy(Qt.NoFocus)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setUniformItemSizes(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.clicked.connect(lambda index: self.picked.emit(index.row()))
        self.footer = QLabel(self)
        self.footer.setFont(theme.ui_font(8.5))
        self.footer.setWordWrap(False)
        self.footer.setTextFormat(Qt.PlainText)
        self.footer.setFocusPolicy(Qt.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(self.view)
        layout.addWidget(self.footer)
        t = theme.tokens()
        self.setStyleSheet(
            f"#CompletionPopup {{ background: {t.surface};"
            f" border: 2px solid {t.ink}; }}"
            f"QListView {{ background: {t.surface}; color: {t.ink};"
            f" outline: none; }}"
            f"QLabel {{ color: {t.ink_muted}; background: {t.ground};"
            f" padding: 3px 6px; border-top: 1px solid {t.rule}; }}")
        self.hide()

    # ── metrics ─────────────────────────────────────────────────

    def row_height(self) -> int:
        return QFontMetrics(self.font()).height() + 6

    def tag_width(self) -> int:
        return 16

    def detail_room(self) -> int:
        """Width kept for the description when eliding a long call."""
        return min(220, self.width() // 3)

    # ── contents ────────────────────────────────────────────────

    def set_items(self, items: list[Completion]) -> None:
        self.model.set_items(items[:MAX_ROWS])
        if self.model.items:
            self.set_current(0)

    @property
    def items(self) -> list[Completion]:
        return self.model.items

    def current_row(self) -> int:
        index = self.view.currentIndex()
        return index.row() if index.isValid() else -1

    def current(self) -> Completion | None:
        row = self.current_row()
        return self.model.items[row] if row >= 0 else None

    def set_current(self, row: int) -> None:
        count = len(self.model.items)
        if not count:
            return
        row %= count
        index = self.model.index(row, 0)
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index)
        item = self.model.items[row].resolved()
        text = item.signature or item.text
        if item.detail:
            text += "  —  " + item.detail
        fm = QFontMetrics(self.footer.font())
        self.footer.setText(fm.elidedText(text, Qt.ElideRight,
                                          max(60, self.width() - 16)))
        self.footer.setToolTip(text)

    def move_by(self, step: int, wrap: bool = True) -> None:
        count = len(self.model.items)
        if not count:
            return
        row = self.current_row() + step
        if not wrap:
            row = max(0, min(count - 1, row))
        self.set_current(row)

    # ── placing ─────────────────────────────────────────────────

    def preferred_width(self) -> int:
        fm = QFontMetrics(self.font())
        widest = 0
        for item in self.model.items[:60]:
            item.resolved()
            widest = max(widest, fm.horizontalAdvance(
                item.text + _call_rest(item)) + min(
                    200, QFontMetrics(theme.ui_font(8.5)).horizontalAdvance(
                        item.detail)))
        return max(320, min(680, widest + self.tag_width() + 48))

    def place(self, anchor: QRect, window: QWidget) -> None:
        """
        Size to the rows and sit under ``anchor`` (in ``window``'s
        coordinates) — or above it when there is no room below.
        """
        rows = min(VISIBLE_ROWS, max(1, len(self.model.items)))
        height = rows * self.row_height() + 4 \
            + self.footer.sizeHint().height() + 2
        width = min(self.preferred_width(), max(200, window.width() - 8))
        x = max(4, min(anchor.left(), window.width() - width - 4))
        y = anchor.bottom() + 2
        if y + height > window.height() and anchor.top() - height - 2 > 0:
            y = anchor.top() - height - 2
        self.setGeometry(x, y, width, min(height, max(60,
                                                      window.height() - y)))
        self.raise_()
        self.show()
        if self.current_row() >= 0:
            self.set_current(self.current_row())    # re-elide the footer

    def paintEvent(self, event) -> None:               # noqa: N802 (Qt API)
        super().paintEvent(event)
        # The Holding Point frame: a hard ink edge, no soft shadow.
        painter = QPainter(self)
        painter.setPen(QPen(QColor(theme.tokens().ink), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
        painter.end()


class CompletionController(QObject):
    """
    Completion on one editor: watches its keys, runs the popup.

    ``request(before)`` gets the text before the cursor (the whole of it in
    a ``QPlainTextEdit``) and returns a request or ``None``.
    """

    #: Text was inserted by accepting an entry.
    accepted = Signal(object)              # Completion

    def __init__(self, widget: QPlainTextEdit | QLineEdit,
                 request: Callable[[str], Request | None], *,
                 auto: bool = True, tab_completes: bool = False) -> None:
        super().__init__(widget)
        self._widget = widget
        self._request_fn = request
        self.auto = auto
        self.tab_completes = tab_completes
        self.popup = CompletionPopup(widget)
        self.popup.picked.connect(self._accept_row)
        self._open = False
        self._req: Request | None = None
        self._ranked: list[tuple[int, Completion]] = []
        widget.installEventFilter(self)
        if isinstance(widget, QAbstractScrollArea):
            widget.viewport().installEventFilter(self)
            widget.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ── the widget, either kind ─────────────────────────────────

    def _before(self) -> str:
        w = self._widget
        if isinstance(w, QLineEdit):
            return w.text()[:w.cursorPosition()]
        cursor = w.textCursor()
        return w.toPlainText()[:cursor.position()]

    def _after_char(self) -> str:
        w = self._widget
        if isinstance(w, QLineEdit):
            return w.text()[w.cursorPosition():w.cursorPosition() + 1]
        cursor = w.textCursor()
        return w.toPlainText()[cursor.position():cursor.position() + 1]

    def _replace(self, length: int, text: str, cursor_at: int | None,
                 eat_next: bool = False) -> None:
        w = self._widget
        if isinstance(w, QLineEdit):
            pos = w.cursorPosition()
            full = w.text()
            start = pos - length
            end = pos + (1 if eat_next else 0)
            w.setText(full[:start] + text + full[end:])
            w.setCursorPosition(start + (len(text) if cursor_at is None
                                         else cursor_at))
            return
        cursor = w.textCursor()
        cursor.clearSelection()
        cursor.beginEditBlock()
        if eat_next:
            cursor.deleteChar()
        cursor.movePosition(cursor.MoveOperation.Left,
                            cursor.MoveMode.KeepAnchor, length)
        start = cursor.selectionStart()
        cursor.insertText(text)
        cursor.endEditBlock()
        if cursor_at is not None:
            cursor.setPosition(start + cursor_at)
        w.setTextCursor(cursor)

    def _anchor(self, prefix: str) -> QRect:
        """The cursor's line, from the start of the word, in window space."""
        w = self._widget
        rect = w.cursorRect()
        source = w.viewport() if isinstance(w, QAbstractScrollArea) else w
        shift = QFontMetrics(w.font()).horizontalAdvance(prefix) \
            + self.popup.tag_width() + 8
        window = w.window()
        top_left = source.mapTo(window, rect.topLeft() - QPoint(shift, 0))
        return QRect(top_left, rect.size())

    # ── state ───────────────────────────────────────────────────

    def is_open(self) -> bool:
        return self._open

    def items(self) -> list[Completion]:
        return list(self.popup.items) if self._open else []

    def current(self) -> Completion | None:
        return self.popup.current() if self._open else None

    def close(self) -> None:
        self._open = False
        self._req = None
        self._ranked = []
        self.popup.hide()

    def _show(self, request: Request,
              ranked: list[tuple[int, Completion]]) -> None:
        self._req = request
        self._ranked = ranked
        self._open = True
        self.popup.set_items([item for _tier, item in ranked])
        window = self._widget.window()
        if self.popup.parent() is not window:
            self.popup.setParent(window)
        self.popup.place(self._anchor(request.prefix), window)

    def _rank(self, request: Request, wait: bool
              ) -> list[tuple[int, Completion]]:
        old = self._req
        if self._open and old is not None and request.key is not None \
                and request.key == old.key \
                and request.prefix.startswith(old.prefix):
            pool = [item for _tier, item in self._ranked]   # narrowing
        else:
            pool = request.items(wait)
        return rank_scored(request.prefix, pool)

    # ── opening and narrowing ───────────────────────────────────

    def refresh(self, *, typed: bool = False, wait: bool = False) -> None:
        """
        Bring the popup up to date with the text: narrow it while it is
        open, open it after typing (``typed``) once the word is long
        enough, close it when nothing is left to offer.
        """
        if self._widget_has_selection():
            self.close()
            return
        request = self._request_fn(self._before())
        if request is None:
            self.close()
            return
        if not self._open:
            if not (typed and self.auto) \
                    or len(request.prefix) < request.auto_min:
                return
        elif not request.prefix and request.auto_min > 0:
            self.close()                # the word was deleted, or ended
            return
        ranked = self._rank(request, wait)
        if not self._open and not any(tier < 2 for tier, _ in ranked):
            return             # only fuzzy matches: not worth interrupting
        if not ranked or (len(ranked) == 1
                          and ranked[0][1].insertion == request.prefix):
            self.close()
            return
        self._show(request, ranked)

    def open(self) -> bool:
        """Ctrl+Space: show every completion here, however short the word."""
        request = self._request_fn(self._before())
        if request is None:
            return False
        self._open = False
        ranked = self._rank(request, True)
        if not ranked:
            self.close()
            return False
        self._show(request, ranked)
        return True

    def complete(self) -> bool:
        """
        Tab: complete the word before the cursor.

        One prefix match is inserted at once; several fill in what they
        share and open the popup. Returns ``False`` when there is nothing to
        complete here (the editor then indents) and ``True`` otherwise.
        """
        request = self._request_fn(self._before())
        if request is None or (not request.prefix and request.auto_min > 0):
            return False
        self._open = False
        ranked = self._rank(request, True)
        if not ranked:
            return True
        close = [item for tier, item in ranked if tier < 2]
        if len(close) == 1:
            self._insert(request, close[0])
            return True
        exact = [item.text for tier, item in ranked if tier == 0]
        shared = common_prefix(exact) if len(exact) > 1 else ""
        if len(shared) > len(request.prefix) and all(
                item.insert is None for tier, item in ranked if tier == 0):
            self._replace(len(request.prefix), shared, None)
            request = self._request_fn(self._before()) or request
            ranked = rank_scored(request.prefix,
                                 [item for _t, item in ranked])
        self._show(request, ranked)
        return True

    # ── accepting ───────────────────────────────────────────────

    def accept_current(self) -> bool:
        """Insert the highlighted entry (as Tab or Return would)."""
        item = self.current()
        if item is None or self._req is None:
            return False
        self._insert(self._req, item)
        return True

    def _accept_row(self, row: int) -> None:
        if self._open and 0 <= row < len(self.popup.items):
            self.popup.set_current(row)
            self.accept_current()
            self._widget.setFocus()

    def _insert(self, request: Request, item: Completion) -> None:
        text, cursor = call_insertion(item, self._after_char())
        # A closing brace already there is the one the insertion brings.
        eat = "}" in text and self._after_char() == "}"
        self.close()
        self._replace(len(request.prefix), text, cursor, eat)
        self.accepted.emit(item)
        # \begin{ or \ref{ just inserted: offer what goes inside at once.
        follow = self._request_fn(self._before())
        if follow is not None and follow.auto_min == 0 \
                and follow.key != request.key and self.auto:
            ranked = self._rank(follow, True)
            if ranked:
                self._show(follow, ranked)

    # ── keys ────────────────────────────────────────────────────

    def _widget_has_selection(self) -> bool:
        w = self._widget
        if isinstance(w, QLineEdit):
            return w.hasSelectedText()
        return w.textCursor().hasSelection()

    def _on_scroll(self, _value: int) -> None:
        if getattr(self, "_open", False):
            self.close()

    def eventFilter(self, obj, event) -> bool:         # noqa: N802 (Qt API)
        # Garbage collection can clear this object's attributes while its
        # widget still sends events here (a cycle through ``_widget``):
        # then it has nothing left to do.
        if "_widget" not in self.__dict__:
            return False
        kind = event.type()
        if obj is not self._widget:                    # the viewport
            if kind == QEvent.MouseButtonPress and self._open:
                self.close()
            return False
        if kind == QEvent.KeyPress:
            return self._key(event)
        if kind == QEvent.ShortcutOverride and self._open and \
                event.key() in (Qt.Key_Escape, Qt.Key_Up, Qt.Key_Down,
                                Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
            event.accept()                 # these keys are ours just now
            return True
        if kind == QEvent.FocusOut and self._open:
            self.close()
        elif kind == QEvent.MouseButtonPress and self._open:
            self.close()
        return False

    def _key(self, event: QKeyEvent) -> bool:
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if ctrl and key == Qt.Key_Space:
            self.open()
            return True
        if self._open:
            if key in (Qt.Key_Up, Qt.Key_Down) and not ctrl:
                self.popup.move_by(-1 if key == Qt.Key_Up else 1)
                return True
            if key in (Qt.Key_PageUp, Qt.Key_PageDown):
                self.popup.move_by((-1 if key == Qt.Key_PageUp else 1)
                                   * (VISIBLE_ROWS - 1), wrap=False)
                return True
            if key == Qt.Key_Escape:
                self.close()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter) and not ctrl:
                current = self.current()
                if current is not None and self._req is not None \
                        and current.insertion == self._req.prefix:
                    self.close()      # already typed in full: Return runs
                    return False
            if key in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter) and not ctrl:
                return self.accept_current() or True
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Backtab):
                self.close()                  # Ctrl+Return: run, as usual
                return False
        elif key == Qt.Key_Tab and self.tab_completes and not ctrl \
                and not self._widget_has_selection():
            if self.complete():
                return True
            return False

        text = event.text()
        typed = bool(text) and text.isprintable() and not (
            ctrl and not mods & Qt.AltModifier)
        edits = key in (Qt.Key_Backspace, Qt.Key_Delete)
        moves = key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End)
        if not (typed or ((edits or moves) and self._open)):
            return False
        # Let the editor have the key first, then look at the new text.
        self._widget.event(event)
        self.refresh(typed=typed and _opens(text))
        return True


#: Kinds that are called, so accepting one brings its brackets.
CALLABLE_KINDS = {"function", "command"}


def call_insertion(item: Completion, after: str = "") -> tuple[str, int | None]:
    """
    What accepting ``item`` inserts, and where the cursor lands.

    A function comes with its brackets: ``step()`` with the cursor between
    them when it takes arguments (or when that is not known), after them
    when it takes none. Not when a ``(`` already follows, nor for a MATLAB
    command written without them (``clc``, ``tic``).
    """
    if item.insert is not None or after == "(":
        return item.insertion, item.cursor
    item.resolved()
    if item.kind not in CALLABLE_KINDS:
        return item.insertion, item.cursor
    sig = item.signature
    if not sig and item.text in SIGNATURES:
        return item.insertion, item.cursor     # clc, tic: a bare command
    no_args = sig.replace(" ", "") == item.text + "()"
    text = item.text + "()"
    return text, len(text) if no_args else len(text) - 1


def _opens(text: str) -> bool:
    """Does typing ``text`` start (or continue) something to complete?"""
    char = text[-1]
    return char.isalnum() or char in "_.\\{"
