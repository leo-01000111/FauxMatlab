"""
PyInstaller runtime hook: give a windowed build a real stdout and stderr.

A GUI executable built with ``console=False`` on Windows starts with **no
standard streams at all** — ``sys.stdout`` and ``sys.stderr`` are ``None``.
Plenty of scientific packages capture them at import time, which then fails
before any of this application's own code runs. numpy is the one that bit
here::

    # numpy/f2py/cfuncs.py, line 19
    errmess = sys.stderr.write

reached through ``scipy.linalg`` → ``scipy._lib._array_api`` →
``array_api_compat.numpy`` → ``numpy.f2py``, and it raises

    AttributeError: 'NoneType' object has no attribute 'write'

before the splash screen would have appeared. The console build is unaffected,
which is exactly why the self-test missed it: the self-test was run against
``FauxMatlab-check.exe``.

Replacing the missing streams with a discard sink fixes it for every package
at once, rather than patching them one at a time as each is discovered. The
streams are real file objects, so anything that asks for ``fileno()``,
``isatty()`` or ``encoding`` gets a sensible answer instead of a second
``AttributeError``.
"""

import os
import sys

# stdin is missing in a windowed build too, and libraries call
# `sys.stdin.isatty()` at import time for the same kind of reason.
for _name, _mode in (("stdout", "w"), ("stderr", "w"), ("stdin", "r")):
    if getattr(sys, _name, None) is None:
        try:
            setattr(sys, _name, open(os.devnull, _mode, encoding="utf-8",
                                     errors="replace"))
        except OSError:
            # Nothing sensible left to do; leave the stream as None rather
            # than fail the launch over logging.
            pass
