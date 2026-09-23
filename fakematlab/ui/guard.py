"""
Error surfacing for the analysis tabs.
======================================

v1 had fifteen ``except Exception: pass`` / ``: return`` handlers across the
UI.  When a computation failed the tab simply went blank — no message, no
traceback, nothing in a log.  Debugging meant guessing which of six tabs had
swallowed what.

The rule here is the opposite: **a failure is always visible**.  Decorate a
panel method with :func:`guard` and any exception is

* logged in full, with traceback, to the ``fakematlab`` logger, and
* shown to the user in an :class:`ErrorBanner` at the top of the panel,

while the rest of the window keeps working.  Nothing is ever silently
discarded.
"""

from __future__ import annotations

import functools
import logging
import traceback
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

log = logging.getLogger("fakematlab")


# ──────────────────────────────────────────────────────────────
#  Banner
# ──────────────────────────────────────────────────────────────

class ErrorBanner(QFrame):
    """
    A dismissible strip that appears at the top of a panel when something
    fails.  Hidden (and taking no vertical space) the rest of the time.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #4A1420; border: 1px solid #C0392B;"
            " border-radius: 4px; }"
            "QLabel { color: #FFD9D9; }"
            "QPushButton { color: #FFD9D9; border: none; font-weight: bold; }"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 4, 4)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self._label, stretch=1)

        self._detail_btn = QPushButton("Details")
        self._detail_btn.setFlat(True)
        self._detail_btn.setCheckable(True)
        self._detail_btn.toggled.connect(self._toggle_detail)
        lay.addWidget(self._detail_btn)

        close = QPushButton("✕")
        close.setFlat(True)
        close.setFixedWidth(24)
        close.clicked.connect(self.clear)
        lay.addWidget(close)

        self._summary = ""
        self._detail = ""
        #: Bumped on every report. :func:`guard` compares it before and after
        #: a call to tell "nothing failed" from "something failed deeper in".
        self.generation = 0
        self.hide()

    def show_error(self, where: str, exc: BaseException) -> None:
        self._summary = f"⚠  {where} failed — {type(exc).__name__}: {exc}"
        self._detail = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        self._detail_btn.setChecked(False)
        self._label.setText(self._summary)
        self.generation += 1
        self.show()

    def clear(self) -> None:
        self._summary = self._detail = ""
        self._label.setText("")
        self.hide()

    @property
    def has_error(self) -> bool:
        """
        Whether an error is currently posted.

        Distinct from ``isVisible()``, which is also False whenever the parent
        panel is hidden — so a caller asking "did this fail?" gets the answer
        it meant, not the answer for "is this on screen?".
        """
        return bool(self._summary)

    @property
    def message(self) -> str:
        """The posted summary, or an empty string."""
        return self._summary

    def _toggle_detail(self, on: bool) -> None:
        self._label.setText(
            f"{self._summary}\n\n{self._detail}" if on else self._summary
        )


# ──────────────────────────────────────────────────────────────
#  Decorator
# ──────────────────────────────────────────────────────────────

def guard(what: str | None = None) -> Callable:
    """
    Wrap a panel method so failures are reported rather than swallowed.

    Usage::

        @guard("Bode plot")
        def _draw_bode(self, tf): ...

    The panel should own an ``_error_banner``; if it does not, the error is
    still logged, so nothing is lost either way.  A successful call clears any
    banner left over from a previous failure, so the message never outlives
    the problem.

    **Nesting.**  Guarded methods call each other — ``refresh`` calls
    ``_draw_bode``, and both are guarded.  When the inner one fails it reports
    and returns normally, so the outer one sees success; clearing the banner
    there would erase the message that was just posted.  The banner's
    ``generation`` counter distinguishes the two cases: a call only clears the
    banner if nothing was reported while it ran.
    """
    def decorate(fn: Callable) -> Callable:
        label = what or fn.__name__.lstrip("_").replace("_", " ")

        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            banner = getattr(self, "_error_banner", None)
            generation = banner.generation if banner is not None else 0
            try:
                result = fn(self, *args, **kwargs)
            except Exception as exc:                        # noqa: BLE001
                log.exception("%s failed in %s", label, type(self).__name__)
                if banner is not None:
                    banner.show_error(label, exc)
                return None
            if banner is not None and banner.generation == generation:
                banner.clear()
            return result

        return wrapper
    return decorate


class GuardedPanel:
    """
    Mixin giving a panel an :class:`ErrorBanner`.

    Mix it into a ``QWidget`` subclass and call :meth:`install_error_banner`
    with the panel's top-level layout while building the UI.
    """

    def install_error_banner(self, layout) -> ErrorBanner:
        self._error_banner = ErrorBanner()
        layout.addWidget(self._error_banner)
        return self._error_banner

    def report_error(self, where: str, exc: BaseException) -> None:
        """Report a failure caught somewhere ``@guard`` cannot reach."""
        log.error("%s failed", where, exc_info=exc)
        banner = getattr(self, "_error_banner", None)
        if banner is not None:
            banner.show_error(where, exc)
