"""
Interrupting and debugging what the console runs.
=================================================
One mechanism serves both the Stop button and the debugger: a *line hook* on
the code the user wrote, nothing else.

Why not a worker thread
-----------------------
Running scripts on a worker would keep the window live for free, but nearly
everything a script touches is GUI-thread state: plot commands build
``FigureView`` widgets through the figure sink, ``close all`` closes tabs,
the workspace table reads the namespace the script is writing, and the
console must evaluate in the *paused* frame while debugging. Marshalling all
of that back, and locking the namespace, is a large surface for one benefit.
Python loops would not run any faster on a worker either — the GIL is held.

So the script runs where it always did, on the GUI thread, and the hook
gives the event loop a turn (``poll``) every :attr:`Tracer.poll_interval`
seconds. A Stop click is delivered during that turn; the next line raises
:class:`Interrupted`. A breakpoint is the same hook calling ``on_pause``,
which runs a nested event loop until the user chooses Continue or Step.

Why ``sys.monitoring`` rather than ``sys.settrace``
---------------------------------------------------
``settrace`` calls back on every Python call in the process — numpy, control,
the MATLAB runtime — just to be told "not this frame". PEP 669 (Python 3.12)
lets the hook be switched on per code object, so only code compiled from the
console, a script or a section raises line events; library code runs at full
speed. It also leaves ``settrace`` free for a real debugger or coverage.

What it cannot do: interrupt a single long call into C (a huge ``lsim``).
The stop lands on the next line of user code after it returns.
"""

from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import CodeType, FrameType

_MON = sys.monitoring

#: What ``on_pause`` returns.
CONTINUE, STEP, STEP_IN, STOP = "continue", "step", "step_in", "stop"


class Interrupted(BaseException):
    """
    The user stopped the run.

    A ``BaseException``, like ``KeyboardInterrupt``: a script's
    ``try … catch`` becomes ``except Exception`` and must not swallow it.
    """

    def __init__(self, line: int | None) -> None:
        super().__init__(line)
        self.line = line

    def __str__(self) -> str:
        return (f"Interrupted at line {self.line}" if self.line
                else "Interrupted")


@dataclass
class Pause:
    """Where a run is stopped: the frame, and the user's line in it."""
    frame:    FrameType
    line:     int
    debuggable: bool

    @property
    def scope(self) -> dict:
        return self.frame.f_locals

    @property
    def in_function(self) -> bool:
        return self.frame.f_locals is not self.frame.f_globals


@dataclass
class _Watched:
    code:   CodeType
    lines:  list[int] | None       # Python line → user line; None = same
    debuggable: bool
    quiet:  bool                   # a function-definition chunk's top level

    def line(self, pyline: int) -> int:
        if self.lines is None:
            return pyline
        if 0 < pyline <= len(self.lines):
            return self.lines[pyline - 1]
        return self.lines[-1] if self.lines else pyline


class Tracer:
    """
    The line hook, and the debugger state it drives.

    The interpreter registers each code object it compiles with
    :meth:`watch` and runs it inside :meth:`active`. The UI sets
    :attr:`poll` (give the event loop a turn) and :attr:`on_pause` (wait for
    the user, then return one of ``"continue"``, ``"step"``, ``"step_in"`` or
    ``"stop"``). Without them it still interrupts, from another thread or a
    test, through :meth:`request_stop`.
    """

    #: Seconds between event-loop turns while user code runs.
    poll_interval = 0.05

    def __init__(self) -> None:
        #: User lines (of the script editor's text) to pause on.
        self.breakpoints: set[int] = set()
        self.poll: Callable[[], None] | None = None
        self.on_pause: Callable[[Pause], str] | None = None
        self._codes: dict[int, _Watched] = {}
        self._depth = 0
        self._tool: int | None = None
        self._stop = False
        self._mode = CONTINUE
        self._step_frame: FrameType | None = None
        self._last: dict[FrameType, tuple[int, int]] = {}
        self._polled = 0.0
        self._namespace: dict | None = None
        #: Where the run is paused, or None.
        self.paused: Pause | None = None

    # ── state ───────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        """User code is executing (or paused) right now."""
        return self._depth > 0

    @property
    def stop_requested(self) -> bool:
        return self._stop

    def request_stop(self) -> None:
        """Stop at the next line of user code (or leave the pause)."""
        if self._depth:
            self._stop = True

    # ── registration ────────────────────────────────────────────

    def watch(self, code: CodeType, lines: list[int] | None = None, *,
              debuggable: bool = False, quiet: bool = False) -> None:
        """
        Raise line events in ``code`` and every function nested in it.

        ``lines`` maps Python line numbers (1-based) to the line the user
        wrote; ``debuggable`` lets breakpoints and the editor's highlight
        apply; ``quiet`` skips the top level of a chunk that only defines a
        function, so a breakpoint on ``function`` pauses at the call.
        """
        self._codes[id(code)] = _Watched(code, lines, debuggable, quiet)
        if self._tool is not None:
            _MON.set_local_events(self._tool, code, _MON.events.LINE)
        for const in code.co_consts:
            if isinstance(const, CodeType):
                self.watch(const, lines, debuggable=debuggable)

    @contextmanager
    def active(self, namespace: dict | None = None) -> Iterator[None]:
        """
        Run user code under the hook. Re-entrant: only the outermost
        call claims the monitoring tool, and only it resets the stop flag.
        """
        self._depth += 1
        try:
            if self._depth == 1:
                self._begin(namespace)
            yield
        finally:
            self._depth -= 1
            if self._depth == 0:
                self._end()

    def _begin(self, namespace: dict | None) -> None:
        self._stop = False
        self._mode = CONTINUE
        self._step_frame = None
        self._last.clear()
        self._polled = time.monotonic()
        self._namespace = namespace
        for tool in (_MON.DEBUGGER_ID, 3, 4, 5):
            try:
                _MON.use_tool_id(tool, "evans")
            except ValueError:
                continue
            self._tool = tool
            break
        else:                                          # pragma: no cover
            return          # every slot taken: run untraced, as before
        _MON.register_callback(self._tool, _MON.events.LINE, self._on_line)
        for watched in self._codes.values():
            _MON.set_local_events(self._tool, watched.code,
                                  _MON.events.LINE)

    def _end(self) -> None:
        if self._tool is not None:
            for watched in self._codes.values():
                _MON.set_local_events(self._tool, watched.code, 0)
            _MON.register_callback(self._tool, _MON.events.LINE, None)
            _MON.free_tool_id(self._tool)
            self._tool = None
        self._last.clear()
        self._step_frame = None
        self.paused = None
        self._prune(self._namespace)
        self._namespace = None

    def _prune(self, namespace: dict | None) -> None:
        """
        Forget code that can no longer run, once a run ends: its chunks,
        the command that started it. A
        function the namespace still holds keeps its entry, so an endless
        loop inside it can still be stopped when it is called from the
        prompt.
        """
        alive: set[int] = set()

        def collect(code: CodeType) -> None:
            alive.add(id(code))
            for const in code.co_consts:
                if isinstance(const, CodeType):
                    collect(const)

        for value in (namespace or {}).values():
            code = getattr(value, "__code__", None)
            if isinstance(code, CodeType) and id(code) in self._codes:
                collect(code)
        self._codes = {k: w for k, w in self._codes.items() if k in alive}

    # ── the hook ────────────────────────────────────────────────

    def _on_line(self, code: CodeType, pyline: int):
        watched = self._codes.get(id(code))
        if watched is None or watched.code is not code:
            return None
        line = watched.line(pyline)
        if self._stop:
            raise Interrupted(line)
        now = time.monotonic()
        if self.poll is not None and now - self._polled >= self.poll_interval:
            self._polled = now
            self.poll()
            if self._stop:
                raise Interrupted(line)
        if self.paused is not None or watched.quiet:
            # A command typed while paused runs, and can be stopped, but
            # does not step or break.
            return None

        frame = sys._getframe(1)
        previous = self._last.get(frame)
        if len(self._last) > 10_000:
            self._last.clear()
        self._last[frame] = (line, pyline)
        # One user line can be several Python lines; it is "reached" when
        # it is entered, or re-entered by a loop jumping back.
        if previous is not None and previous[0] == line \
                and pyline > previous[1]:
            return None

        pause = False
        # A function's argument set-up maps to its ``function`` line;
        # stepping lands on the first line of the body instead, as MATLAB
        # does. (A breakpoint on that line still pauses at the call.)
        header = code.co_name != "<module>" \
            and line == watched.line(code.co_firstlineno)
        if self._mode == STEP_IN:
            pause = not header
        elif self._mode == STEP:
            pause = not header and not _below(frame, self._step_frame)
        if not pause and watched.debuggable and line in self.breakpoints:
            pause = True
        if pause:
            self._pause(frame, line, watched.debuggable)
        return None

    def _pause(self, frame: FrameType, line: int, debuggable: bool) -> None:
        self.paused = Pause(frame, line, debuggable)
        try:
            action = self.on_pause(self.paused) if self.on_pause else CONTINUE
        finally:
            self.paused = None
            self._polled = time.monotonic()
        if action == STOP or self._stop:
            self._stop = True
            raise Interrupted(line)
        self._mode = action if action in (STEP, STEP_IN) else CONTINUE
        self._step_frame = frame


def _below(frame: FrameType, ancestor: FrameType | None) -> bool:
    """Is ``frame`` called (however deeply) from ``ancestor``?"""
    if ancestor is None:
        return False
    f = frame.f_back
    while f is not None:
        if f is ancestor:
            return True
        f = f.f_back
    return False


def write_back(frame: FrameType) -> None:
    """
    Make assignments to ``frame.f_locals`` stick in a function frame.

    Python 3.12 hands out a snapshot of a function's locals; this copies it
    back into the frame (``PyFrame_LocalsToFast``), so ``k = 3`` typed while
    paused inside a function changes the ``k`` that function sees. 3.13 made
    ``f_locals`` write-through and dropped the call, which is then not needed.
    """
    fn = getattr(ctypes.pythonapi, "PyFrame_LocalsToFast", None)
    if fn is None:                                      # pragma: no cover
        return
    fn(ctypes.py_object(frame), ctypes.c_int(0))
