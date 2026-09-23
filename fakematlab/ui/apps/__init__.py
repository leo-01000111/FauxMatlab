"""
The MATLAB-style apps: LTI Viewer, Control System Designer, PID Tuner.

Each is a window over a core module that does the arithmetic headlessly —
:mod:`fakematlab.core.viewer`, :mod:`fakematlab.core.designer` and
:mod:`fakematlab.core.pidtune`. The split is the same one the console uses,
and for the same reason: a design decision that can only be checked by looking
at a window is a design decision that does not get checked.
"""

from .designer_app import ControlSystemDesigner
from .lti_viewer import LTIViewer
from .pid_tuner import PIDTuner
from .snapshots import SnapshotBar

__all__ = ["LTIViewer", "ControlSystemDesigner", "PIDTuner", "SnapshotBar"]
