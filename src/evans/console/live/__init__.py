"""
Live scripts: cells of MATLAB and formatted text, run in the shared workspace.

Qt-free. :mod:`.document` is the model, :mod:`.markup` the text-cell
dialect, :mod:`.livem` and :mod:`.mlx` the two MATLAB file formats,
:mod:`.runner` runs cells, :mod:`.report` writes LaTeX / PDF / HTML, and
:mod:`.render` draws math and figures to PNG with matplotlib.
"""

from __future__ import annotations

from pathlib import Path

from .document import (
    TEXT_KINDS,
    Cell,
    CellKind,
    CellOutput,
    FigureMeta,
    InterpolationError,
    LiveDocument,
    format_value,
    workspace_evaluator,
)
from .livem import (
    is_live_text,
    parse_live_document,
    parse_live_m,
    to_live_m,
    write_live_m,
)
from .mlx import MlxError, read_mlx, write_mlx
from .runner import LiveRunner, current_folder
from .template import DEFAULT, ReportTemplate, resolve_template

#: The native format is the plain-text live script — see :mod:`.livem`.
NATIVE_SUFFIX = ".m"


def load(path: str | Path) -> LiveDocument:
    """Open an ``.mlx``, a plain-text live ``.m``, or an ordinary ``.m``."""
    path = Path(path).resolve()
    if path.suffix.lower() == ".mlx":
        return read_mlx(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_live_document(text, path)


def save(document: LiveDocument, path: str | Path) -> Path:
    """Save as ``.mlx`` or, for any other suffix, a plain-text live ``.m``."""
    path = Path(path)
    if path.suffix.lower() == ".mlx":
        write_mlx(document, path)
    else:
        write_live_m(document, path)
    document.path = path
    return path


__all__ = [
    "DEFAULT", "NATIVE_SUFFIX", "TEXT_KINDS", "Cell", "CellKind",
    "CellOutput", "FigureMeta", "InterpolationError", "LiveDocument",
    "LiveRunner", "MlxError", "ReportTemplate", "current_folder",
    "format_value", "is_live_text", "load", "parse_live_document",
    "parse_live_m", "resolve_template", "read_mlx", "save", "to_live_m", "workspace_evaluator",
    "write_live_m", "write_mlx",
]
