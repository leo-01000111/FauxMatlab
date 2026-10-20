"""
The arrange panel: Fit, Align row, Align column and Space, floating over a
corner of the canvas.

They change how the diagram looks, never what it computes, so they are kept
out of the toolbar beside Run and Linearise. The toolbar has a fixed width
to share, and when they lived there they were among the buttons that pushed
Open and Save out of sight on a narrow window.

The panel sits in the canvas's top-right corner at reduced opacity, so the
diagram shows through it, and comes up to full strength under the mouse.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QToolButton,
    QWidget,
)

from .. import iconset, theme

#: Opacity at rest and under the mouse.
REST, HOVER = 0.55, 1.0
#: Distance from the canvas edges, in px.
INSET = 10


class ArrangePanel(QFrame):
    """Four icon buttons over the top-right corner of ``canvas``."""

    def __init__(self, canvas, align, distribute) -> None:
        super().__init__(canvas)
        self.setObjectName("ArrangePanel")
        self._canvas = canvas
        t = theme.tokens()
        self.setStyleSheet(
            f"#ArrangePanel {{ background: {t.surface}; "
            f"border: 1px solid {t.rule}; }}"
            f"#ArrangePanel QToolButton {{ border: none; padding: 4px; }}"
            f"#ArrangePanel QToolButton:hover {{ background: {t.ground}; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(0)
        self.buttons: dict[str, QToolButton] = {}
        for key, icon, tip, slot in (
            ("fit", "fit", "Fit the whole diagram in view",
             canvas.fit_all),
            ("row", "align-row", "Align the selected blocks on one row",
             lambda: align("y")),
            ("column", "align-column",
             "Align the selected blocks in one column", lambda: align("x")),
            ("space", "distribute", "Space the selected blocks evenly across",
             lambda: distribute("x")),
        ):
            button = QToolButton(self)
            iconset.bind(button, icon)
            button.setIconSize(QSize(18, 18))
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            row.addWidget(button)
            self.buttons[key] = button

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(REST)
        self.setGraphicsEffect(self._effect)
        self.setAttribute(Qt.WA_Hover, True)
        # The viewport, not the view: when the view gets its Resize, the
        # viewport inside it still has the old size. Kept as a reference so
        # the filter never has to ask a canvas being destroyed for it.
        self._viewport = canvas.viewport()
        self._viewport.installEventFilter(self)
        canvas.installEventFilter(self)
        self.adjustSize()
        self.place()
        self.raise_()

    @property
    def opacity(self) -> float:
        return self._effect.opacity()

    def place(self) -> None:
        """Keep to the top-right corner of the canvas's visible area."""
        try:
            vp = self._viewport.geometry()
        except RuntimeError:                # the canvas is being destroyed
            return
        self.move(vp.right() - self.width() - INSET + 1, vp.top() + INSET)

    def eventFilter(self, obj, event) -> bool:     # noqa: N802 (Qt API)
        # Only cheap comparisons first: this runs for every event of the
        # canvas, including those sent while it is being destroyed.
        if event.type() in (QEvent.Resize, QEvent.Show) and \
                (obj is self._viewport or obj is self._canvas):
            self.place()
        return False

    def enterEvent(self, event) -> None:         # noqa: N802 (Qt API)
        self._effect.setOpacity(HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:         # noqa: N802 (Qt API)
        self._effect.setOpacity(REST)
        super().leaveEvent(event)


def hidden_actions(bar: QWidget) -> list[str]:
    """
    The toolbar entries that do not fit and are behind the overflow button.

    Qt hides the widget of each action that does not fit; separators and
    actions hidden on purpose (the subsystem Up button) are not counted.
    """
    names = []
    for action in bar.actions():
        if action.isSeparator() or not action.isVisible():
            continue
        widget = bar.widgetForAction(action)
        if widget is not None and not widget.isVisible():
            text = action.text() or action.toolTip()
            if not text and hasattr(widget, "findChildren"):
                # A labelled spin box or combo added as a widget.
                labels = [w.text() for w in widget.findChildren(QWidget)
                          if hasattr(w, "text") and w.text()]
                text = labels[0] if labels else "setting"
            names.append(text.replace("…", "").replace("&", ""))
    return names
