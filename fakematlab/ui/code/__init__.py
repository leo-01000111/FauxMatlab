"""
Editing code: highlighting, completion, sections and a gutter.

Reusable pieces — the Script tab uses all of them, and any other editor of
MATLAB or Python text (a live script, a lesson's snippet) can take them:

* :class:`MatlabHighlighter` — a ``QSyntaxHighlighter`` for MATLAB or Python.
* :class:`Completer` — Tab completion with a popup, on a ``QPlainTextEdit``
  or a ``QLineEdit``; :func:`completion_candidates` is what it offers.
* :func:`split_sections` — ``%%`` cells, and the source to run one.
* :class:`CodeEditor` — a ``QPlainTextEdit`` with all of the above, plus
  line numbers, breakpoints and error / paused-line highlights.
"""

from .completer import Completer, completion_candidates, matlab_builtins
from .editor import CodeEditor
from .highlighter import MATLAB_KEYWORDS, MatlabHighlighter, tokenize_line
from .sections import Section, section_at, section_source, split_sections

__all__ = [
    "MATLAB_KEYWORDS", "CodeEditor", "Completer", "MatlabHighlighter",
    "Section", "completion_candidates", "matlab_builtins", "section_at",
    "section_source", "split_sections", "tokenize_line",
]
