"""
The command window: MATLAB, translated to Python as it is typed.

A namespace where ``tf``, ``step``, ``bode``, ``margin``, ``lqr``, ``c2d`` and
``stepinfo`` behave the way a MATLAB user expects (:mod:`.api`), and a
translator (:mod:`.matlab`) that reads MATLAB's syntax into calls on it — so a
snippet from the course runs as written, at the prompt or in a script.

Decision D4 once kept the prompt Python. MATLAB is now the default
everywhere; Python still runs wherever it is typed.
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
