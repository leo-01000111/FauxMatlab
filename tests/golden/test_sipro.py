"""
The signal-processing coursework (SiPro), run unmodified.

``tests/fixtures/sipro`` holds three MATLAB R2023a live scripts — C1 (DFT of
a sampled cosine, aliasing, zero-padding), C2 (an audio file's spectrum, a
crude FFT codec through ``codeur.m`` / ``decodeur.m``, playback) and C3
(c2d of a resonator) — with the function files they call. Each live script's
code cells are run in order from a copy of that folder, as MATLAB would run
them with it as the current folder.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pytest

from fakematlab.console import Interpreter, matlab_runtime, set_figure_sink
from fakematlab.console.figures import recording_sink

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sipro"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def mlx_code_cells(path: Path) -> list[str]:
    """
    The code of a live script, one string per code paragraph.

    An ``.mlx`` is a zip; ``matlab/document.xml`` holds paragraphs, and the
    code ones carry ``<w:pStyle w:val="code"/>``.
    """
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("matlab/document.xml"))
    cells = []
    for para in root.iter(f"{_W}p"):
        style = para.find(f"{_W}pPr/{_W}pStyle")
        if style is not None and style.get(f"{_W}val") == "code":
            cells.append("".join(t.text or "" for t in para.iter(f"{_W}t")))
    return cells


@pytest.fixture
def sink():
    recorder = recording_sink()
    previous = set_figure_sink(recorder)
    yield recorder
    set_figure_sink(previous)


@pytest.fixture
def folder(tmp_path):
    """A scratch copy of the fixtures: C2 writes compressed\\musique.wav."""
    target = tmp_path / "sipro"
    shutil.copytree(FIXTURES, target)
    return target


@pytest.fixture
def silent(monkeypatch):
    """No speakers and no waiting: record what would have been played."""
    played: list[tuple[np.ndarray, float]] = []
    waited: list[float] = []

    def play(data, rate):
        played.append((data, rate))
        return True

    monkeypatch.setattr(matlab_runtime, "_play", play)
    monkeypatch.setattr(matlab_runtime, "_pause_for", waited.append)
    return played, waited


def run_live_script(it: Interpreter, name: str, folder: Path):
    """Run every code cell of ``name.mlx`` in order; insist each succeeds."""
    transcript = []
    for cell in mlx_code_cells(folder / f"{name}.mlx"):
        results = it.run_script(cell, "matlab", folder=str(folder))
        failed = [r for r in results if r.error]
        assert not failed, f"{name}: {failed[0].source!r} → {failed[0].error}"
        transcript += [r.display() for r in results]
    return "\n".join(transcript)


def test_code_cells_are_extracted_in_order():
    cells = mlx_code_cells(FIXTURES / "C1.mlx")
    assert cells[0].startswith("Nt = 128;\nfs = 1000;")
    assert any("transffourier" in c for c in cells)
    assert any("sound(y, Fs, info.BitsPerSample);" in c
               for c in mlx_code_cells(FIXTURES / "C2.mlx"))


def test_c1_dft_of_a_cosine(sink, folder, silent):
    it = Interpreter()
    out = run_live_script(it, "C1", folder)
    ns = it.namespace
    fs, f0 = 1000, 5 / 128 * 1000
    # The cosine sits exactly on bin 5: two peaks, at f0 and fs - f0.
    np.testing.assert_allclose(ns["locs"], [[f0], [fs - f0]])
    np.testing.assert_allclose(ns["pks"], [[0.032], [0.032]], rtol=1e-9)
    assert np.shape(ns["pks"]) == (2, 1)            # a column, like abs(tfx)
    # transffourier.m: f is a row, the transform a column.
    assert np.shape(ns["f2"]) == (4096,) and np.shape(ns["tfx2"]) == (4096, 1)
    # Off-bin (f0 = 5.7/128 fs) the energy leaks; the peaks are the bins
    # nearest f0 and its alias, as scipy finds them too.
    from scipy.signal import find_peaks
    t = np.arange(128)
    spectrum = np.abs(np.fft.fft(0.5 * np.cos(2 * np.pi * 5.7 / 128 * t
                                              + np.pi / 2))) / fs
    expected = find_peaks(spectrum, height=0.1 * spectrum.max())[0]
    np.testing.assert_allclose(ns["locsd"].ravel(), expected / 128 * fs)
    np.testing.assert_allclose(ns["locsd"].ravel(), [46.875, 953.125])
    assert "Imaginary parts of complex X and/or Y arguments ignored" in out
    assert len(sink.figures) == 8                  # one per plot call


def test_c2_audio_codec_round_trip(sink, folder, silent):
    played, waited = silent
    it = Interpreter()
    out = run_live_script(it, "C2", folder)
    ns = it.namespace
    assert ns["Fs"] == 44100 and np.shape(ns["y"]) == (300000, 1)
    assert ns["info"].BitsPerSample == 16 and ns["info"].NumChannels == 1
    assert "TotalSamples: 300000" in out
    # codeur.m wrote a two-channel file next to the script, in compressed\.
    written = folder / "compressed" / "musique.wav"
    assert written.is_file()
    assert not (FIXTURES / "compressed").exists()
    # decodeur.m rebuilt the signal from the band below 8 kHz.
    y, yd = ns["y"].reshape(-1), ns["yd"].reshape(-1)
    assert yd.shape == y.shape and np.isrealobj(yd)
    spectrum = np.fft.fft(y)
    k = np.arange(y.size)
    band = (np.minimum(k, y.size - k) <= round(y.size * 8000 / 44100))
    expected = np.real(np.fft.ifft(np.where(band, spectrum, 0)))
    assert np.max(np.abs(yd - expected)) < 2e-3
    assert ns["bitsd"] == 16 and ns["fsd"] == 44100
    # Both sound() calls played; pause() waited the clip's length.
    assert len(played) == 2 and played[0][1] == 44100
    assert waited == [pytest.approx(300000 / 44100 + 0.5)]


def test_c3_discretised_resonator(sink, folder):
    it = Interpreter()
    out = run_live_script(it, "C3", folder)
    numd = it.namespace["numd"]
    w0, ts = 2, 0.1
    # zoh of w0²/(s²+w0²): (1-cos w0T)(z+1)/(z²-2cos(w0T)z+1)
    c = np.cos(w0 * ts)
    np.testing.assert_allclose(numd, [0, 1 - c, 1 - c], atol=1e-12)
    np.testing.assert_allclose(it.namespace["dend"], [1, -2 * c, 1],
                               atol=1e-12)
    assert "Sample time: 0.1000 seconds" in out
