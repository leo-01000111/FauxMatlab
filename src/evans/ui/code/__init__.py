"""
Editing code: highlighting, completion, sections and a gutter.

Reusable pieces — the Script tab uses all of them, and any other editor of
MATLAB or Python text (a live script) can take them:

* :class:`MatlabHighlighter` — a ``QSyntaxHighlighter`` for MATLAB or Python.
* :class:`CompletionController` — the completion popup on a
  ``QPlainTextEdit`` or a ``QLineEdit``, fed by :func:`code_request` (MATLAB,
  Python) or :func:`latex_request`; :class:`Completer` is the same popup fed
  by a plain list of names, as :func:`completion_candidates` makes.
* :func:`split_sections` — ``%%`` cells, and the source to run one.
* :class:`FollowController` — hover for a function's syntax, Ctrl+click to
  go to it, on any of those text widgets; :func:`resolve` decides where.
* :class:`CodeEditor` — a ``QPlainTextEdit`` with all of the above, plus
  line numbers, breakpoints and error / paused-line highlights.
"""

from .completer import Completer, completion_candidates, matlab_builtins
from .completion import Completion, Request, code_request, rank, warm_up
from .editor import CodeEditor
from .follow import Context, FollowController, Target, resolve
from .highlighter import MATLAB_KEYWORDS, MatlabHighlighter, tokenize_line
from .latex import latex_request
from .popup import CompletionController, CompletionPopup
from .sections import Section, section_at, section_source, split_sections

__all__ = [
    "MATLAB_KEYWORDS", "CodeEditor", "Completer", "Completion",
    "CompletionController", "CompletionPopup", "Context", "FollowController",
    "MatlabHighlighter", "Request", "Section", "Target", "code_request",
    "completion_candidates", "latex_request", "matlab_builtins", "rank",
    "resolve", "section_at", "section_source", "split_sections",
    "tokenize_line", "warm_up",
]
