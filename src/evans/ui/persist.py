"""
What outlives a session: the command history, the recent-files list and
the integrated-title-bar preference.

All live in ``QSettings``, beside the window layout but not inside it:
*Reset layout* clears the layout's settings wholesale, and forgetting what was
typed and opened is not part of putting the panels back. The location is read
from :data:`ORG` / :data:`APP` each time, so the test suite can point it at a
scratch key before anything is written — a test run must never overwrite a
user's real history.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QSettings

#: Where ``QSettings`` keeps it: the app's organisation, its own application.
ORG = "Evans"
APP = "Evans History"


#: (old organisation, old application) → (new organisation, new application).
#: The program was FauxMatlab before 0.9; these are where it kept things.
LEGACY_STORES = {
    ("FauxMatlab", "FauxMatlab"): ("Evans", "Evans"),
    ("FauxMatlab", "FauxMatlab History"): ("Evans", "Evans History"),
}


def migrate_legacy_settings(stores=None) -> int:
    """
    Copy settings saved under the old name into the new one, once.

    A store that already has keys under the new name is left alone, so this
    never overwrites anything and is safe to call at every start. Returns how
    many keys were copied.
    """
    copied = 0
    for (old_org, old_app), (org, app) in (stores or LEGACY_STORES).items():
        old, new = QSettings(old_org, old_app), QSettings(org, app)
        if new.allKeys() or not old.allKeys():
            continue
        for key in old.allKeys():
            new.setValue(key, old.value(key))
            copied += 1
        new.sync()
    return copied


def settings() -> QSettings:
    return QSettings(ORG, APP)


def _string_list(value) -> list[str]:
    """
    A stored list back as a list of strings.

    ``QSettings`` hands a one-element list back as a bare string and an empty
    one back as ``None`` (both on the registry backend), and a hand-edited key
    can hold anything at all.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError:
        return []


class CommandHistory:
    """
    The commands typed at the prompt, oldest first, kept across sessions.

    Like MATLAB's history: an immediate repeat is stored once, blank lines are
    not stored at all, and the oldest entries fall off past :attr:`limit`.
    Every append is written straight away, so a crash loses nothing.
    """

    KEY = "console/history"

    def __init__(self, limit: int = 1000) -> None:
        self.limit = limit
        self._items = _string_list(settings().value(self.KEY))[-limit:]

    @property
    def items(self) -> list[str]:
        return list(self._items)

    def append(self, command: str) -> bool:
        """Record a command. Returns whether it was stored."""
        command = command.rstrip()
        if not command.strip() or (self._items and self._items[-1] == command):
            return False
        self._items.append(command)
        del self._items[:-self.limit]
        self._save()
        return True

    def clear(self) -> None:
        self._items.clear()
        self._save()

    def _save(self) -> None:
        settings().setValue(self.KEY, list(self._items))


class RecentFiles:
    """
    The last few scripts and models opened or saved, newest first.

    Files that have since been moved or deleted are dropped when the list is
    read, rather than offered and then failing to open.
    """

    KEY = "recentFiles"
    #: What counts: MATLAB and Python scripts, and Simulink-style models.
    SUFFIXES = (".m", ".py", ".fmdl")

    def __init__(self, limit: int = 10) -> None:
        self.limit = limit

    def add(self, path: str | Path) -> None:
        path = Path(path).resolve()
        if path.suffix.lower() not in self.SUFFIXES:
            return
        key = _key(path)
        items = [p for p in self._stored() if _key(Path(p)) != key]
        self._store([str(path), *items])

    def paths(self) -> list[Path]:
        """The files still there, newest first; the missing ones forgotten."""
        stored = self._stored()
        present = [p for p in stored if Path(p).is_file()]
        if present != stored:
            self._store(present)
        return [Path(p) for p in present]

    def clear(self) -> None:
        self._store([])

    def _stored(self) -> list[str]:
        return _string_list(settings().value(self.KEY))

    def _store(self, items: Iterable[str]) -> None:
        settings().setValue(self.KEY, list(items)[:self.limit])


def _key(path: Path) -> str:
    """The same file however its case was spelled, where the OS ignores it."""
    return os.path.normcase(str(path))


#: Whether the menus and window buttons share one strip (Windows only).
#: Kept here rather than with the layout: *Reset layout* puts panels back,
#: it does not undo a preference.
INTEGRATED_TITLE_BAR_KEY = "window/integratedTitleBar"


def integrated_title_bar(default: bool) -> bool:
    value = settings().value(INTEGRATED_TITLE_BAR_KEY)
    if value is None:
        return default
    if isinstance(value, str):            # the INI backend stores text
        return value.lower() in ("true", "1")
    return bool(value)


def set_integrated_title_bar(on: bool) -> None:
    settings().setValue(INTEGRATED_TITLE_BAR_KEY, bool(on))
