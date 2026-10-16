"""
The MATLAB library behind the Script tab, beyond control: function files on
the path, spectra and filters, peaks, audio, ODEs and optimisation, .mat
files, and the plots MATLAB draws differently from a line.

Expected values are MATLAB's own where they are short enough to know
(``fft([1 2 3 4])``, ``butter(2, 0.5)``, ``conv(…, 'same')``), and numpy or
scipy references otherwise.
"""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

from fakematlab.console import Interpreter, matlab_runtime, set_figure_sink
from fakematlab.console.figures import recording_sink
from fakematlab.console.matlab_runtime import Cell, Struct


@pytest.fixture
def sink():
    recorder = recording_sink()
    previous = set_figure_sink(recorder)
    yield recorder
    set_figure_sink(previous)


@pytest.fixture
def it(sink):
    return Interpreter()


def run(it, source: str, folder=None):
    """Run MATLAB, insist it succeeded, return the console transcript."""
    results = it.run_script(source, "matlab",
                            folder=str(folder) if folder else None)
    failed = [r for r in results if r.error]
    assert not failed, f"{failed[0].source!r} → {failed[0].error}"
    return "\n".join(r.display() for r in results)


def fails(it, source: str, folder=None) -> str:
    results = it.run_script(source, "matlab",
                            folder=str(folder) if folder else None)
    assert results[-1].error, "expected an error"
    return results[-1].error


def val(it, name):
    return it.namespace[name]


# ──────────────────────────────────────────────────────────────
#  Function files and the current folder
# ──────────────────────────────────────────────────────────────

def test_function_file_in_the_script_folder(it, tmp_path):
    (tmp_path / "twice.m").write_text(
        "function [y, n] = twice(x)\n"
        "% a comment\n"
        "y = helper(x);\n"
        "n = nargin;\n"
        "end\n"
        "function y = helper(x)\n"
        "y = 2*x;\n"
        "end\n")
    run(it, "[a, k] = twice([1 2 3]);\nb = twice(5);", tmp_path)
    np.testing.assert_allclose(val(it, "a"), [2, 4, 6])
    assert val(it, "k") == 1 and val(it, "b") == 10
    # The local function is the file's own business.
    assert "helper" in fails(it, "helper(1)", tmp_path)


def test_function_file_sees_none_of_the_callers_variables(it, tmp_path):
    (tmp_path / "peek.m").write_text("function y = peek()\ny = secret;\n")
    assert "secret" in fails(it, "secret = 3;\npeek()", tmp_path)


def test_function_file_is_reloaded_when_it_changes(it, tmp_path):
    path = tmp_path / "answer.m"
    path.write_text("function y = answer()\ny = 1;\nend\n")
    run(it, "a = answer();", tmp_path)
    path.write_text("function y = answer()\ny = 2;\nend\n")
    stamp = time.time() + 5            # a distinct mtime, however coarse
    os.utime(path, (stamp, stamp))
    run(it, "b = answer();", tmp_path)
    assert (val(it, "a"), val(it, "b")) == (1, 2)


def test_script_file_runs_in_the_workspace(it, tmp_path):
    (tmp_path / "setup_vars.m").write_text("k = 7;\nm = k + 1;\n")
    run(it, "setup_vars\nr = m * 2;", tmp_path)
    assert val(it, "r") == 16


def test_file_shadows_a_builtin_as_in_matlab(it, tmp_path):
    (tmp_path / "max.m").write_text("function y = max(x)\ny = -1;\nend\n")
    run(it, "a = max([1 5 3]);", tmp_path)
    assert val(it, "a") == -1


def test_cd_pwd_addpath_and_exist(it, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "triple.m").write_text("function y = triple(x)\ny = 3*x;\nend\n")
    run(it, "here = pwd;\ne0 = exist('triple');\naddpath('lib');\n"
            "a = triple(2);\ne1 = exist('triple');\ncd lib\nthere = pwd;\n"
            "e7 = exist('../lib');", tmp_path)
    assert val(it, "here") == str(tmp_path)
    assert val(it, "there") == str(lib)
    assert (val(it, "e0"), val(it, "e1"), val(it, "e7")) == (0, 2, 7)
    assert val(it, "a") == 6
    assert "Cannot CD" in fails(it, "cd nowhere", tmp_path)


def test_relative_paths_use_the_script_folder_not_the_process(it, tmp_path):
    (tmp_path / "data").mkdir()
    run(it, "x = [1 2 3];\nsave data\\saved x", tmp_path)
    assert (tmp_path / "data" / "saved.mat").is_file()


def test_process_folder_when_no_script_folder(it, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "one.m").write_text("function y = one()\ny = 1;\n")
    run(it, "a = one();")
    assert val(it, "a") == 1


# ──────────────────────────────────────────────────────────────
#  Spectra
# ──────────────────────────────────────────────────────────────

def test_fft_of_a_row_a_column_and_a_matrix(it):
    run(it, "a = fft([1 2 3 4]);\nb = fft([1; 2; 3; 4]);\n"
            "c = fft([1 2; 3 4]);\nd = fft([1 2; 3 4], [], 2);\n"
            "e = fft([1 2 3], 5);\nf = fft([1 2 3 4], 2);")
    np.testing.assert_allclose(val(it, "a"), [10, -2 + 2j, -2, -2 - 2j])
    assert val(it, "a").shape == (4,)
    assert val(it, "b").shape == (4, 1)
    np.testing.assert_allclose(val(it, "c"), [[4, 6], [-2, -2]])
    np.testing.assert_allclose(val(it, "d"), [[3, -1], [7, -1]])
    np.testing.assert_allclose(val(it, "e"), np.fft.fft([1, 2, 3, 0, 0]))
    np.testing.assert_allclose(val(it, "f"), [3, -1])


def test_ifft_returns_real_for_a_symmetric_spectrum(it):
    run(it, "x = [1 2 3 4 5];\ny = ifft(fft(x));\nz = ifft([1 2 3]);\n"
            "w = ifft([1 2 3], 'symmetric');\nv = ifft(fft([1;2;3]), 4);")
    assert np.isrealobj(val(it, "y"))
    np.testing.assert_allclose(val(it, "y"), [1, 2, 3, 4, 5])
    assert np.iscomplexobj(val(it, "z"))
    np.testing.assert_allclose(val(it, "w"), np.fft.irfft([1, 2], 3))
    assert val(it, "v").shape == (4, 1)


def test_fftshift_and_ifftshift(it):
    run(it, "a = fftshift([1 2 3 4 5]);\nb = ifftshift([1 2 3 4 5]);\n"
            "c = fftshift([1 2; 3 4]);\nd = fftshift([1 2 3; 4 5 6], 2);\n"
            "e = fftshift([1; 2; 3; 4]);")
    np.testing.assert_allclose(val(it, "a"), [4, 5, 1, 2, 3])
    np.testing.assert_allclose(val(it, "b"), [3, 4, 5, 1, 2])
    np.testing.assert_allclose(val(it, "c"), [[4, 3], [2, 1]])
    np.testing.assert_allclose(val(it, "d"), [[3, 1, 2], [6, 4, 5]])
    np.testing.assert_allclose(val(it, "e"), [[3], [4], [1], [2]])


# ──────────────────────────────────────────────────────────────
#  Peaks
# ──────────────────────────────────────────────────────────────

def test_findpeaks_basics_plateaus_and_ends(it):
    run(it, "[p, l] = findpeaks([1 3 2 5 4 4 6 1]);\n"
            "[q, m] = findpeaks([1 2 2 1 3]);\n"
            "[r, n] = findpeaks([1; 3; 1], [10; 20; 30]);")
    np.testing.assert_allclose(val(it, "p"), [3, 5, 6])
    np.testing.assert_allclose(val(it, "l"), [2, 4, 7])
    # A plateau counts once, at its left edge; the last sample never does.
    np.testing.assert_allclose(val(it, "q"), [2])
    np.testing.assert_allclose(val(it, "m"), [2])
    assert val(it, "r").shape == (1, 1) or val(it, "r") == 3
    assert val(it, "n") == 20


def test_findpeaks_options(it):
    data = "[0 5 0 4 0 6 0]"
    run(it, f"[a, la] = findpeaks({data}, 'MinPeakDistance', 2);\n"
            f"[b, lb] = findpeaks({data}, 'SortStr', 'descend');\n"
            f"[c, lc] = findpeaks({data}, 'NPeaks', 2);\n"
            f"[d, ld] = findpeaks({data}, 'MinPeakHeight', 4);\n"
            "[e, le] = findpeaks([0 5 4.5 0 3 0], 'Threshold', 1);\n"
            f"[f, lf] = findpeaks({data}, 0:10:60, 'MinPeakDistance', 25);")
    np.testing.assert_allclose(val(it, "a"), [5, 6])
    np.testing.assert_allclose(val(it, "la"), [2, 6])
    np.testing.assert_allclose(val(it, "b"), [6, 5, 4])
    np.testing.assert_allclose(val(it, "lb"), [6, 2, 4])
    np.testing.assert_allclose(val(it, "c"), [5, 4])
    np.testing.assert_allclose(val(it, "d"), [5, 6])    # strictly above
    np.testing.assert_allclose(val(it, "e"), [3])
    np.testing.assert_allclose(val(it, "le"), [5])
    np.testing.assert_allclose(val(it, "lf"), [10, 50])


def test_findpeaks_prominence_matches_scipy(it):
    from scipy.signal import find_peaks
    x = np.sin(np.linspace(0, 20, 400)) + 0.3 * np.sin(np.linspace(0, 97, 400))
    it.namespace["x"] = x
    run(it, "[p, l] = findpeaks(x, 'MinPeakProminence', 0.5);")
    expected = find_peaks(x, prominence=0.5)[0] + 1
    np.testing.assert_allclose(val(it, "l"), expected)


def test_findpeaks_without_outputs_plots(it, sink):
    run(it, "findpeaks([0 2 0 3 0])")
    spec = sink.last
    assert [t.style for t in spec.traces] == ["line", "scatter"]
    np.testing.assert_allclose(spec.traces[1].y, [2, 3])


# ──────────────────────────────────────────────────────────────
#  Filters and polynomials
# ──────────────────────────────────────────────────────────────

def test_filter(it):
    run(it, "a = filter(1, [1 -0.5], [1 1 1]);\n"
            "b = filter([1 1]/2, 1, [2; 4; 6]);\n"
            "c = filter(1, [1 -0.5], [1 0; 0 1; 0 0]);\n"
            "[d, zf] = filter(1, [1 -0.5], [1 1]);\n"
            "e = filter(1, [1 -0.5], [1 1], zf);")
    np.testing.assert_allclose(val(it, "a"), [1, 1.5, 1.75])
    np.testing.assert_allclose(val(it, "b"), [[1], [3], [5]])
    np.testing.assert_allclose(val(it, "c"), [[1, 0], [0.5, 1], [0.25, 0.5]])
    # Continuing from the final state is the same as one long run.
    np.testing.assert_allclose(np.concatenate([val(it, "d"), val(it, "e")]),
                               [1, 1.5, 1.75, 1.875])


def test_conv_shapes(it):
    run(it, "a = conv([1 2], [1 3]);\nb = conv([1 2 3 4], [1 1], 'same');\n"
            "c = conv([1 2 3 4], [1 1], 'valid');\nd = conv([1; 2; 3], [1 1]);"
            "\n[q, r] = deconv([1 5 6], [1 2]);")
    np.testing.assert_allclose(val(it, "a"), [1, 5, 6])
    np.testing.assert_allclose(val(it, "b"), [3, 5, 7, 4])
    np.testing.assert_allclose(val(it, "c"), [3, 5, 7])
    assert val(it, "d").shape == (4, 1)
    np.testing.assert_allclose(val(it, "q"), [1, 3])
    np.testing.assert_allclose(val(it, "r"), [0, 0, 0])


def test_butter_and_cheby1(it):
    from scipy import signal
    run(it, "[b, a] = butter(2, 0.5);\n[bh, ah] = butter(3, 0.2, 'high');\n"
            "[z, p, k] = butter(2, [0.2 0.4]);\n"
            "[bc, ac] = cheby1(4, 1, 0.3);\n[bs, a2] = butter(2, 10, 's');")
    # MATLAB: b = [0.2929 0.5858 0.2929], a = [1 0 0.1716]
    np.testing.assert_allclose(val(it, "b"), [0.2929, 0.5858, 0.2929],
                               atol=1e-4)
    np.testing.assert_allclose(val(it, "a"), [1, 0, 0.1716], atol=1e-4)
    ref = signal.butter(3, 0.2, "highpass")
    np.testing.assert_allclose(val(it, "bh"), ref[0])
    np.testing.assert_allclose(val(it, "ah"), ref[1])
    assert val(it, "p").shape == (4, 1)                # bandpass doubles
    np.testing.assert_allclose(val(it, "ac"), signal.cheby1(4, 1, 0.3)[1])
    np.testing.assert_allclose(val(it, "a2"), [1, np.sqrt(2) * 10, 100])


def test_freqz(it, sink):
    run(it, "[h, w] = freqz([1 1], 1, 4);\n[g, f] = freqz(1, [1 -0.5], 8, 100);"
            "\nfreqz([1 1], 1)")
    w = val(it, "w").ravel()
    np.testing.assert_allclose(w, [0, np.pi / 4, np.pi / 2, 3 * np.pi / 4])
    np.testing.assert_allclose(val(it, "h").ravel(), 1 + np.exp(-1j * w))
    assert val(it, "h").shape == (4, 1)
    np.testing.assert_allclose(val(it, "f").ravel(), np.arange(8) * 50 / 8)
    # With no outputs: magnitude over phase, one figure.
    spec = sink.last
    assert spec.kind == "subplot"
    labels = [p["spec"].ylabel for p in spec.extra["panes"]]
    assert labels == ["Magnitude (dB)", "Phase (degrees)"]


def test_trapz_cumtrapz_cumsum(it):
    run(it, "a = trapz([1 2 3]);\nb = trapz([0 1 3], [1 2 3]);\n"
            "c = trapz([1 2; 3 4; 5 6]);\nd = cumtrapz([1 2 3]);\n"
            "e = cumtrapz([0; 2], [1; 3]);\nf = cumsum([1 2 3]);\n"
            "g = cumsum([1 2; 3 4]);\nh = trapz(0.5, [1 2 3]);")
    assert val(it, "a") == 4
    assert val(it, "b") == pytest.approx(1.5 + 5)
    np.testing.assert_allclose(val(it, "c"), [6, 8])
    np.testing.assert_allclose(val(it, "d"), [0, 1.5, 4])
    np.testing.assert_allclose(val(it, "e"), [[0], [4]])
    np.testing.assert_allclose(val(it, "f"), [1, 3, 6])
    np.testing.assert_allclose(val(it, "g"), [[1, 2], [4, 6]])
    assert val(it, "h") == 2


def test_interp1(it):
    from scipy.interpolate import CubicSpline, PchipInterpolator
    run(it, "x = [1 2 3 4];\ny = [10 20 15 40];\n"
            "a = interp1(x, y, 2.5);\nb = interp1(x, y, [0 5]);\n"
            "c = interp1(x, y, 5, 'linear', 'extrap');\n"
            "d = interp1(x, y, [1.4 1.6], 'nearest');\n"
            "e = interp1(x, y, [0.5 2.5], 'spline');\n"
            "f = interp1(x, y, 2.5, 'pchip');\n"
            "g = interp1(y, 1.5);\nh = interp1(x, y, 9, 'linear', 0);\n"
            "k = interp1(x, y, [1.5; 3.5]);")
    assert val(it, "a") == 17.5
    assert np.all(np.isnan(val(it, "b")))
    assert val(it, "c") == pytest.approx(65)
    np.testing.assert_allclose(val(it, "d"), [10, 20])
    np.testing.assert_allclose(val(it, "e"),
                               CubicSpline([1, 2, 3, 4], [10, 20, 15, 40])(
                                   [0.5, 2.5]))
    assert val(it, "f") == pytest.approx(
        float(PchipInterpolator([1, 2, 3, 4], [10, 20, 15, 40])(2.5)))
    assert val(it, "g") == 15
    assert val(it, "h") == 0
    assert val(it, "k").shape == (2, 1)


def test_polyfit_polyval_meshgrid_linspace(it):
    run(it, "p = polyfit([1 2 3], [2 4 6], 1);\nv = polyval([1 0 -1], 3);\n"
            "[X, Y] = meshgrid(1:3, 1:2);\nl = linspace(0, 1, 5);")
    np.testing.assert_allclose(val(it, "p"), [2, 0], atol=1e-12)
    assert val(it, "v") == 8
    np.testing.assert_allclose(val(it, "X"), [[1, 2, 3], [1, 2, 3]])
    np.testing.assert_allclose(val(it, "Y"), [[1, 1, 1], [2, 2, 2]])
    np.testing.assert_allclose(val(it, "l"), [0, 0.25, 0.5, 0.75, 1])


# ──────────────────────────────────────────────────────────────
#  ODEs and optimisation
# ──────────────────────────────────────────────────────────────

def test_ode45_decay_and_oscillator(it):
    run(it, "[t, y] = ode45(@(t, y) -y, [0 1], 1);\n"
            "[t2, y2] = ode45(@(t, y) [y(2); -y(1)], [0 pi], [1; 0]);\n"
            "[t3, y3] = ode23(@(t, y) -2*y, [0 0.5 1], 1);\n"
            "opts = odeset('RelTol', 1e-8, 'AbsTol', 1e-10);\n"
            "[t4, y4] = ode45(@(t, y) -y, [0 1], 1, opts);\n"
            "sol = ode45(@(t, y) -y, [0 1], 1);")
    t, y = val(it, "t"), val(it, "y")
    assert t.shape[1] == 1 and y.shape == (t.shape[0], 1)
    assert t[0, 0] == 0 and t[-1, 0] == 1
    assert (t.shape[0] - 1) % 4 == 0               # ode45 refines by 4
    np.testing.assert_allclose(y[:, 0], np.exp(-t[:, 0]), atol=1e-3)
    y2 = val(it, "y2")
    assert y2.shape[1] == 2
    np.testing.assert_allclose(y2[-1], [-1, 0], atol=1e-2)
    np.testing.assert_allclose(val(it, "t3").ravel(), [0, 0.5, 1])
    np.testing.assert_allclose(val(it, "y3").ravel(), np.exp(-2 * np.array(
        [0, 0.5, 1])), atol=1e-2)
    np.testing.assert_allclose(val(it, "y4")[-1, 0], np.exp(-1), atol=1e-8)
    sol = val(it, "sol")
    assert sol.solver == "ode45" and sol.x[-1] == 1


def test_fzero_fminsearch_fminbnd(it):
    run(it, "a = fzero(@(x) x^2 - 2, 1);\nb = fzero(@cos, [1 2]);\n"
            "[c, fc] = fzero(@(x) x^3 - 8, 0);\n"
            "f = @(x) 100*(x(2) - x(1)^2)^2 + (1 - x(1))^2;\n"
            "[x, fval] = fminsearch(f, [-1.2, 1]);\n"
            "m = fminbnd(@(x) (x - 2)^2, 0, 5);")
    assert val(it, "a") == pytest.approx(np.sqrt(2), abs=1e-12)
    assert val(it, "b") == pytest.approx(np.pi / 2, abs=1e-12)
    assert val(it, "c") == pytest.approx(2, abs=1e-10)
    assert abs(val(it, "fc")) < 1e-9
    # MATLAB's documented result: x = [1.0000 1.0000], fval = 8.1777e-10.
    np.testing.assert_allclose(val(it, "x"), [1, 1], atol=1e-3)
    assert val(it, "x").shape == (2,)
    assert val(it, "fval") < 1e-8
    assert val(it, "m") == pytest.approx(2, abs=1e-4)
    assert "differ in sign" in fails(it, "fzero(@(x) x^2 + 1, [0 1])")


# ──────────────────────────────────────────────────────────────
#  Audio
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bits", [8, 16, 24, 32])
def test_audiowrite_audioread_round_trip(it, tmp_path, bits):
    run(it, "t = (0:999)'/8000;\ny = [0.5*sin(2*pi*440*t), -0.25*cos("
            f"2*pi*220*t)];\naudiowrite('tone.wav', y, 8000, 'BitsPerSample',"
            f" {bits});\n[z, fs] = audioread('tone.wav');\n"
            "info = audioinfo('tone.wav');", tmp_path)
    y, z = val(it, "y"), val(it, "z")
    assert z.shape == (1000, 2) and val(it, "fs") == 8000
    np.testing.assert_allclose(z, y, atol=2.0 ** (1 - bits) * 1.01)
    info = val(it, "info")
    assert (info.BitsPerSample, info.NumChannels, info.SampleRate,
            info.TotalSamples) == (bits, 2, 8000, 1000)
    assert info.Duration == pytest.approx(0.125)
    assert info.Filename == str(tmp_path / "tone.wav")


def test_audio_clips_ranges_and_native(it, tmp_path):
    run(it, "audiowrite('c.wav', [-2; -1; 0; 0.5; 2], 100);\n"
            "a = audioread('c.wav');\nb = audioread('c.wav', [2 3]);\n"
            "n = audioread('c.wav', 'native');", tmp_path)
    np.testing.assert_allclose(val(it, "a").ravel(),
                               [-1, -1, 0, 0.5, 32767 / 32768])
    np.testing.assert_allclose(val(it, "b").ravel(), [-1, 0])
    assert val(it, "n").dtype == np.int16
    assert "not found" in fails(it, "audioread('missing.wav')", tmp_path)


def test_24_bit_file_from_scipy_reads_the_same(it, tmp_path):
    """A 24-bit WAV written by hand reads back to the same doubles."""
    import struct
    samples = np.array([-(1 << 23), -1, 0, 1, (1 << 23) - 1], dtype=np.int32)
    payload = samples.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3]
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 48000 * 3, 3, 24)
    body = (b"fmt " + struct.pack("<I", 16) + fmt + b"data"
            + struct.pack("<I", payload.size) + payload.tobytes() + b"\0")
    (tmp_path / "x.wav").write_bytes(b"RIFF" + struct.pack(
        "<I", 4 + len(body)) + b"WAVE" + body)
    run(it, "[y, fs] = audioread('x.wav');\ni = audioinfo('x.wav');",
        tmp_path)
    np.testing.assert_allclose(val(it, "y").ravel(), samples / 2.0 ** 23)
    assert val(it, "i").BitsPerSample == 24 and val(it, "fs") == 48000


def test_sound_plays_asynchronously_and_warns_once_without_output(
        it, monkeypatch):
    played = []
    monkeypatch.setattr(matlab_runtime, "_play",
                        lambda data, rate: played.append((data, rate)) or True)
    run(it, "sound([0 2 -2], 8000, 16)\nsoundsc([0 0.5 -0.25], 100)\n"
            "sound([0.1; 0.2])")
    data, rate = played[0]
    assert rate == 8000 and data.shape == (3, 1)
    np.testing.assert_allclose(data.ravel(), [0, 1, -1])      # clipped
    np.testing.assert_allclose(played[1][0].ravel(), [0, 1, -0.5])
    assert played[2][1] == 8192
    monkeypatch.setattr(matlab_runtime, "_play", lambda data, rate: False)
    out = run(it, "sound([0 1])\nsound([0 1])")
    assert out.count("No audio output") == 1


def test_pause_waits_only_when_given_a_time(it, monkeypatch):
    waited = []
    monkeypatch.setattr(matlab_runtime, "_pause_for", waited.append)
    run(it, "pause\npause(0.25)\npause(0)\npause('on')")
    assert waited == [0.25]


# ──────────────────────────────────────────────────────────────
#  .mat files
# ──────────────────────────────────────────────────────────────

def test_save_and_load_round_trip(it, tmp_path):
    run(it, "a = [1 2 3];\nb = [1; 2];\nM = [1 2; 3 4];\nn = 5;\n"
            "s = 'text';\nst.x = 1;\nst.y = [1 2];\nc = {1, 'two'};\n"
            "save('all.mat')\nsave part a n\n"
            "clear all\nload all\nS = load('part');", tmp_path)
    np.testing.assert_allclose(val(it, "a"), [1, 2, 3])
    assert val(it, "a").shape == (3,)
    assert val(it, "b").shape == (2, 1)
    np.testing.assert_allclose(val(it, "M"), [[1, 2], [3, 4]])
    assert val(it, "n") == 5 and val(it, "s") == "text"
    assert isinstance(val(it, "st"), Struct) and val(it, "st").x == 1
    np.testing.assert_allclose(val(it, "st").y, [1, 2])
    assert isinstance(val(it, "c"), Cell) and val(it, "c")[1] == "two"
    S = val(it, "S")
    assert sorted(S) == ["a", "n"]
    assert "not found" in fails(it, "save x.mat nosuch", tmp_path)


def test_load_text_file_and_selected_variables(it, tmp_path):
    (tmp_path / "data.txt").write_text("1 2\n3 4\n")
    run(it, "x = 1; y = 2;\nsave xy\nclear all\nload xy y\n"
            "load data.txt\nD = load('data.txt');", tmp_path)
    np.testing.assert_allclose(val(it, "data"), [[1, 2], [3, 4]])
    np.testing.assert_allclose(val(it, "D"), [[1, 2], [3, 4]])
    assert val(it, "y") == 2 and "x" not in it.namespace


# ──────────────────────────────────────────────────────────────
#  Plots
# ──────────────────────────────────────────────────────────────

def test_stem_and_stairs_are_not_lines(it, sink):
    run(it, "stem([1 2 3], [4 5 6])\nstairs([1 2 3], [4 5 6])")
    stem, stairs = sink.figures[-2:]
    assert stem.traces[0].style == "stem"
    trace = stairs.traces[0]
    np.testing.assert_allclose(trace.x, [1, 2, 2, 3, 3])
    np.testing.assert_allclose(trace.y, [4, 4, 5, 5, 6])


def test_complex_y_plots_the_real_part_and_warns(it, sink):
    out = run(it, "plot([1 2], [1+2i, 3-1i])")
    assert "Imaginary parts of complex X and/or Y arguments ignored" in out
    np.testing.assert_allclose(sink.last.traces[0].y, [1, 3])


def test_subplot_lays_out_one_figure(it, sink):
    run(it, "subplot(2, 1, 1)\nplot([1 2 3])\ntitle('top')\n"
            "subplot(2, 1, 2)\nplot([3 2 1])\nhold on\nplot([1 1 1])\n"
            "subplot(2, 1, 1)\nylabel('again')\nsgtitle('both')\n"
            "figure\nplot([0 1])")
    grid, plain = sink.figures[-2:]
    assert grid.kind == "subplot" and grid.title == "both"
    top, bottom = (p["spec"] for p in grid.extra["panes"])
    assert top.title == "top" and top.ylabel == "again"
    assert len(top.traces) == 1 and len(bottom.traces) == 2
    assert plain.kind == "xy" and len(sink.figures) == 2


def test_subplot_spanning_cells_and_three_digit_form(it, sink):
    run(it, "subplot(221)\nplot(1:3)\nsubplot(2, 2, [3 4])\nplot(1:3)")
    panes = sink.last.extra["panes"]
    assert [p["cells"] for p in panes] == [(1,), (3, 4)]
    assert "exceeds" in fails(it, "subplot(2, 2, 5)")


def test_bar_and_histogram(it, sink):
    run(it, "bar([3 1 2])\nh = histogram([1 2 2 3 3 3], [0.5 1.5 2.5 3.5]);"
            "\n[N, edges] = histcounts([1 2 2 3 3 3], 3);")
    bar = sink.figures[-2]
    assert bar.traces[0].style == "bar"
    np.testing.assert_allclose(bar.traces[0].y, [3, 1, 2])
    np.testing.assert_allclose(val(it, "h").Values, [1, 2, 3])
    np.testing.assert_allclose(val(it, "N"), [1, 2, 3])
    np.testing.assert_allclose(val(it, "edges"), [1, 5 / 3, 7 / 3, 3])


def test_zpkdata_still_answers(it):
    run(it, "[z, p, k] = zpkdata(tf([2 2], [1 3 2]), 'v');")
    np.testing.assert_allclose(val(it, "z"), [[-1]])
    assert val(it, "k") == 2


def test_tfdata_pads_the_numerator(it):
    run(it, "[n, d] = tfdata(tf(1, [1 2 1]), 'v');")
    np.testing.assert_allclose(val(it, "n"), [0, 0, 1])


# ──────────────────────────────────────────────────────────────
#  Saving figures
# ──────────────────────────────────────────────────────────────

def test_saveas_and_print_write_images(it, tmp_path):
    pytest.importorskip("PySide6", reason="Qt not available")
    run(it, "plot([1 2 3], [3 1 2])\nsaveas(gcf, 'line.png')\n"
            "print('-dpng', 'printed')\n"
            "h = figure;\nsubplot(1, 2, 1)\nstem(1:3)\nsubplot(1, 2, 2)\n"
            "bar(1:3)\nsaveas(h, 'grid.png')", tmp_path)
    for name in ("line.png", "printed.png", "grid.png"):
        data = (tmp_path / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
    assert "no figure" in fails(it, "close all\nsaveas(gcf, 'x.png')",
                                tmp_path)


def test_saveas_uses_the_figure_uis_exporter_when_there_is_one(
        it, tmp_path, monkeypatch):
    pytest.importorskip("PySide6", reason="Qt not available")
    from fakematlab.ui.console import figure_view
    calls = []
    monkeypatch.setattr(figure_view, "export_figure",
                        lambda view, path: calls.append((view, path)),
                        raising=False)
    run(it, "plot(1:3)\nsaveas(gcf, 'out.svg')", tmp_path)
    assert len(calls) == 1 and calls[0][1] == str(tmp_path / "out.svg")
    assert isinstance(calls[0][0], figure_view.FigureView)
