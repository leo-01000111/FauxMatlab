"""
Where an app command's request goes.

``ltiview(G, T)`` and ``sisotool(G)`` have to open a window somewhere. The
same split as :mod:`fakematlab.console.figures`: the command builds an
:class:`AppRequest` describing what to open and hands it to the installed
**sink**, so the API stays free of Qt and the commands stay runnable from a
headless script — where they record the request instead of opening anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: The apps a request can name.
APPS = ("ltiview", "sisotool", "pidtuner")


@dataclass
class AppRequest:
    """A request to open one of the apps, described rather than opened."""

    app: str
    #: Named systems to load, in the order given.
    systems: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.app not in APPS:
            raise ValueError(f"unknown app {self.app!r}. "
                             f"Known: {', '.join(APPS)}")

    def __repr__(self) -> str:
        names = ", ".join(self.systems) or "nothing"
        return f"<{self.app}: {names}>"


class _RecordingSink:
    """Default sink: remember what was asked for, open nothing."""

    def __init__(self, limit: int = 16) -> None:
        self.requests: list[AppRequest] = []
        self._limit = limit

    def __call__(self, request: AppRequest) -> AppRequest:
        self.requests.append(request)
        del self.requests[:-self._limit]
        return request

    @property
    def last(self) -> AppRequest | None:
        return self.requests[-1] if self.requests else None

    def clear(self) -> None:
        self.requests.clear()


_sink: Callable[[AppRequest], Any] = _RecordingSink()


def set_app_sink(sink: Callable[[AppRequest], Any]) -> Callable:
    """Install the launcher. Returns the previous one, so it can be restored."""
    global _sink
    previous, _sink = _sink, sink
    return previous


def app_sink() -> Callable[[AppRequest], Any]:
    """The sink currently installed."""
    return _sink


def emit(request: AppRequest) -> AppRequest:
    """Send a request to the installed sink."""
    _sink(request)
    return request


def recording_sink() -> _RecordingSink:
    """A fresh recording sink, for tests and headless scripts."""
    return _RecordingSink()
