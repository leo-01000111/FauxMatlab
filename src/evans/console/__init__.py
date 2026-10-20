"""
The command window: a Python REPL wearing MATLAB's vocabulary.

Decision D4 from the plan: **aliases, not a language.** There is no ``.m``
parser. What there is instead is a namespace where ``tf``, ``step``, ``bode``,
``margin``, ``lqr``, ``c2d`` and ``stepinfo`` behave the way a MATLAB user
expects, so a snippet from the course transcribes almost directly and nobody
has to maintain a parser for a language this tool does not need to speak.
"""

from .api import build_namespace, describe_api
from .apps import AppRequest, app_sink, set_app_sink
from .figures import FigureSpec, figure_sink, set_figure_sink
from .interpreter import Interpreter, Result

__all__ = [
    "build_namespace", "describe_api",
    "FigureSpec", "figure_sink", "set_figure_sink",
    "AppRequest", "app_sink", "set_app_sink",
    "Interpreter", "Result",
]
