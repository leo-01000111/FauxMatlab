"""
sound() in the packaged app: no sounddevice, no Qt Multimedia, so it has
to fall back to winsound on Windows. It used to stay silent there.
"""

from __future__ import annotations

import builtins
import os
import sys
import wave

import numpy as np
import pytest

from evans.console import matlab_runtime as rt

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="winsound is Windows-only")


def test_without_sounddevice_or_qt_audio_winsound_plays(monkeypatch):
    import winsound

    real_import = builtins.__import__

    def frozen_like_import(name, *args, **kwargs):
        if name == "sounddevice" or name.startswith("PySide6.QtMultimedia"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    played = []
    monkeypatch.setattr(builtins, "__import__", frozen_like_import)
    monkeypatch.setattr(winsound, "PlaySound",
                        lambda path, flags: played.append((path, flags)))
    t = np.arange(0, 0.25, 1 / 8192)
    data = (0.3 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)
    try:
        assert rt._play(data, 8192)
        (path, flags), = played
        assert flags & winsound.SND_ASYNC and flags & winsound.SND_FILENAME
        with wave.open(path) as w:                 # a real, readable .wav
            assert w.getframerate() == 8192
            assert w.getnframes() == len(t)
    finally:
        monkeypatch.undo()
        for p in rt._SOUND_FILES:
            if os.path.exists(p):
                os.remove(p)
        rt._SOUND_FILES.clear()
