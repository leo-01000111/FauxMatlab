"""
Where "help" goes.

Every way of asking for help — Cedric at the foot of the rail, Help ▸
Documentation, F1 — lands in :func:`open_help`, so changing what help *is*
happens here once. Today it opens the documentation site in the browser; the
plan is an undockable help window inside Evans, as MATLAB has, and that window
replaces the body of this function without any caller noticing.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

DOCS_URL = "https://www.leongorecki.eu/evans/"


def open_help(topic: str | None = None) -> bool:
    """Show the documentation, at ``topic`` (a page path) when given."""
    url = DOCS_URL + (topic.lstrip("/") if topic else "")
    return QDesktopServices.openUrl(QUrl(url))
