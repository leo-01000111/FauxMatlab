"""
Tab completion from a plain list of names — the original interface.

:class:`Completer` is the shared popup (:mod:`.popup`) driven by a source
that maps the word before the cursor to the names completing it, as
:func:`completion_candidates` does. The editors themselves now hand the
popup richer requests (:mod:`.completion`, :mod:`.latex`) with signatures
and descriptions; this stays for anything that only has names.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

from .completion import (
    WORD_CHARS,
    Completion,
    Request,
    common_prefix,
    completion_candidates,
    library_names,
    m_file_names,
    word_before,
)
from .popup import CompletionController

__all__ = ["WORD_CHARS", "Completer", "common_prefix",
           "completion_candidates", "m_files", "matlab_builtins",
           "word_before"]


def matlab_builtins() -> frozenset[str]:
    """The MATLAB library's function and constant names (``zeros``, ``pi``…)."""
    return library_names()


def m_files(prefix: str, folder=None) -> list[str]:
    """Names of ``.m`` files in ``folder`` starting with ``prefix``."""
    return [n for n in m_file_names(folder) if n.startswith(prefix)]


class Completer(CompletionController):
    """
    Completion attached to a ``QPlainTextEdit`` or a ``QLineEdit``, offering
    ``source(word)``. It opens on Tab (:meth:`complete`), not while typing.
    """

    def __init__(self, widget: QPlainTextEdit | QLineEdit,
                 source: Callable[[str], list[str]]) -> None:
        self._source = source
        super().__init__(widget, self._names_request, auto=False)

    def _names_request(self, before: str) -> Request | None:
        word = word_before(before.rpartition("\n")[2])
        return Request(word, None,
                       lambda _wait: [Completion(n) for n in
                                      self._source(word)])

    def candidates(self) -> list[str]:
        """What Tab would offer now."""
        return self._source(word_before(self._before().rpartition("\n")[2]))
