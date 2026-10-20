"""
MATLAB scripts in the Script tab: the translator and the runtime behind it.

The acceptance test is a real course script (``LEON_SCRIPT`` below, pasted
from the course work): fourteen systems, a seven-curve step plot with a
legend, a struct array filled in a loop and shown with ``struct2table``, and a
phase-matched Bode plot set through ``bodeoptions``. Everything else pins one
MATLAB rule each — the ones where Python means something else.
"""

from __future__ import annotations

import numpy as np
import pytest

from evans.console import Interpreter, set_figure_sink
from evans.console.figures import recording_sink
from evans.console.matlab import (
    MatlabSyntaxError,
    looks_like_matlab,
    to_python,
    translate,
)
from evans.console.matlab_runtime import Struct, StructArray


@pytest.fixture
def sink():
    recorder = recording_sink()
    previous = set_figure_sink(recorder)
    yield recorder
    set_figure_sink(previous)


@pytest.fixture
def it(sink):
    return Interpreter()


def run(it, source: str):
    """Run MATLAB, insist it succeeded, return the console transcript."""
    results = it.run_script(source, "matlab")
    failed = [r for r in results if r.error]
    assert not failed, f"{failed[0].source!r} → {failed[0].error}"
    return "\n".join(r.display() for r in results)


def val(it, name):
    return it.namespace[name]


LEON_SCRIPT = r"""
s = tf('s')
G = 1 / ((s+1)*(0.5*s+1))

t = linspace(0, 6, 1000)

%step(G, t)
c1 = -10
Gc1 = (-s+c1) / (c1*(s+1)*(0.5*s+1))
%step(Gc1, t)
c2 = -0.25
Gc2 = (-s+c2) / (c2*(s+1)*(0.5*s+1))
c3 = -0.1
Gc3 = (-s+c3) / (c3*(s+1)*(0.5*s+1))
c4 = 0.1
Gc4 = (-s+c4) / (c4*(s+1)*(0.5*s+1))
c5 = 0.25
Gc5 = (-s+c5) / (c5*(s+1)*(0.5*s+1))
c6 = 10
Gc6 = (-s+c6) / (c6*(s+1)*(0.5*s+1))
%step(Gc6, t)

step(G, Gc1, Gc2, Gc3, Gc4, Gc5, Gc6, t); grid on
legend('G', 'Gc1', 'Gc2', 'Gc3', 'Gc4', 'Gc5', 'Gc6')
grid off
sys = {G, Gc1, Gc2, Gc3, Gc4, Gc5, Gc6};
for k = 1:numel(sys)
    info(k) = stepinfo(sys{k});
end
struct2table(info)


opts = bodeoptions;
opts.Grid = 'on';
opts.PhaseMatching = 'on';
opts.PhaseMatchingFreq = 0.0001;
opts.PhaseMatchingvalue = 0;
bode(G, Gc1, Gc2, Gc3, Gc4, Gc5, Gc6, opts); grid on
legend('G', 'Gc1', 'Gc2', 'Gc3', 'Gc4', 'Gc5', 'Gc6')
grid off
"""

NAMES = ["G", "Gc1", "Gc2", "Gc3", "Gc4", "Gc5", "Gc6"]


# ──────────────────────────────────────────────────────────────
#  The acceptance script
# ──────────────────────────────────────────────────────────────

def test_course_script_runs_end_to_end(it, sink):
    out = run(it, LEON_SCRIPT)
    assert "Continuous-time transfer function." in out
    assert "<TransferFunction>" not in out          # no python-control header
    assert "RiseTime" in out and "SettlingTime" in out   # struct2table shown

    step_fig, bode_fig = sink.figures[-2:]
    assert step_fig.kind == "time"
    assert [t.label for t in step_fig.traces] == NAMES
    assert step_fig.traces[0].x[-1] == pytest.approx(6.0)  # the t given
    assert bode_fig.kind == "bode"
    assert [t.label for t in bode_fig.traces] == NAMES
    # As in MATLAB: one shared frequency axis, and no margin markers.
    assert all(np.array_equal(t.x, bode_fig.traces[0].x)
               for t in bode_fig.traces)
    assert "margins" not in bode_fig.extra


def test_course_script_struct_array(it, sink):
    run(it, LEON_SCRIPT)
    info = val(it, "info")
    assert isinstance(info, StructArray) and len(info) == 7
    assert info[2]["Overshoot"] > 100            # zero at -0.25: big overshoot
    assert info[4]["Undershoot"] > 1             # RHP zero: undershoot
    # MATLAB's SettlingMin is after the rise, never the starting zero.
    assert all(row["SettlingMin"] > 0.85 for row in info)
    # Settling is measured, not clipped at the end of the plot window.
    assert info[3]["SettlingTime"] > 6.0


def test_course_script_phase_matching(it, sink):
    run(it, LEON_SCRIPT)
    phases = sink.figures[-1].extra["phase"]
    for _omega, degrees, label in phases:
        assert abs(degrees[0]) < 5, label           # matched to 0° at low ω
    by_name = {label: degrees for _, degrees, label in phases}
    # The right-half-plane zeros (c > 0) add 90° of lag, not lead.
    assert by_name["Gc6"][-1] == pytest.approx(-270, abs=5)
    assert by_name["Gc1"][-1] == pytest.approx(-90, abs=5)


def test_course_script_is_detected_as_matlab():
    assert looks_like_matlab(LEON_SCRIPT)


# ──────────────────────────────────────────────────────────────
#  Syntax MATLAB has and Python does not
# ──────────────────────────────────────────────────────────────

def test_matrix_literals_and_spacing(it):
    run(it, "a = [1 -2 3]; b = [1 - 2 3]; c = [1, 2; 3, 4]; d = [a' a'];")
    assert np.allclose(val(it, "a"), [1, -2, 3])
    assert np.allclose(val(it, "b"), [-1, 3])
    assert np.allclose(val(it, "c"), [[1, 2], [3, 4]])
    assert val(it, "d").shape == (3, 2)


def test_newline_rows_and_continuation(it):
    run(it, "A = [1 2\n3 4];\nx = 1 + ...\n  2;")
    assert np.allclose(val(it, "A"), [[1, 2], [3, 4]])
    assert val(it, "x") == 3


def test_transpose_versus_string(it):
    run(it, "v = [1 2 3]'; w = v'; s = 'it''s';")
    assert val(it, "v").shape == (3, 1)
    assert val(it, "w").shape == (3,)
    assert val(it, "s") == "it's"


def test_power_and_matrix_product(it):
    run(it, "s = tf('s'); G = 1/(s^2 + 2*s + 1);"
            "A = [1 2; 3 4]; B = A*A; C = A.*A; D = A^2; e = 2^-1;")
    assert np.allclose(val(it, "B"), [[7, 10], [15, 22]])
    assert np.allclose(val(it, "C"), [[1, 4], [9, 16]])
    assert np.allclose(val(it, "D"), val(it, "B"))
    assert val(it, "e") == 0.5
    assert np.allclose(val(it, "G").den[0][0], [1, 2, 1])


def test_comments(it):
    run(it, "% a comment\nx = 1; % trailing\n%{\nx = 99;\n%}\ny = x + 1")
    assert val(it, "y") == 2


def test_command_syntax(it, sink):
    run(it, "clc; clear all; close all\nformat short\nhold on\n"
            "G = tf(1, [1 1]); step(G); grid on")
    assert sink.figures[-1].kind == "time"


# ──────────────────────────────────────────────────────────────
#  Indexing
# ──────────────────────────────────────────────────────────────

def test_one_based_indexing_with_end(it):
    run(it, "x = [10 20 30 40]; a = x(1); b = x(end); c = x(end-1);"
            "d = x(2:end); e = x([1 end]); f = x(x > 15);")
    assert val(it, "a") == 10 and val(it, "b") == 40 and val(it, "c") == 30
    assert np.allclose(val(it, "d"), [20, 30, 40])
    assert np.allclose(val(it, "e"), [10, 40])
    assert np.allclose(val(it, "f"), [20, 30, 40])


def test_matrix_indexing(it):
    run(it, "A = [1 2 3; 4 5 6]; a = A(2, 3); r = A(1, :); c = A(:, 2);"
            "n = A(end, end); l = A(4);")
    assert val(it, "a") == 6 and val(it, "n") == 6
    assert np.allclose(val(it, "r"), [1, 2, 3])
    assert val(it, "c").shape == (2, 1)
    assert val(it, "l") == 5                       # column-major linear index


def test_growing_and_deleting(it):
    run(it, "x(3) = 7; y = []; for k = 1:4, y(end+1) = k^2; end;"
            "z = [1 2 3 4]; z(2) = []; M(2, 3) = 1;")
    assert np.allclose(val(it, "x"), [0, 0, 7])
    assert np.allclose(val(it, "y"), [1, 4, 9, 16])
    assert np.allclose(val(it, "z"), [1, 3, 4])
    assert val(it, "M").shape == (2, 3)


def test_index_out_of_range_names_the_line(it):
    results = it.run_script("x = [1 2 3];\ny = 2;\nz = x(5);", "matlab")
    assert "line 3" in results[-1].error
    assert "must not exceed 3" in results[-1].error


def test_cells_and_structs(it):
    run(it, "c = {1, 'two', [3 4]}; a = c{2}; n = numel(c);"
            "s.name = 'plant'; s.gain = 2; g = s.gain;"
            "p(2).x = 5; m = p(2).x;")
    assert val(it, "a") == "two" and val(it, "n") == 3
    assert isinstance(val(it, "s"), Struct) and val(it, "g") == 2
    assert val(it, "m") == 5


# ──────────────────────────────────────────────────────────────
#  Control flow and functions
# ──────────────────────────────────────────────────────────────

def test_if_while_switch_try(it):
    run(it, """
total = 0;
k = 0;
while k < 5
    k = k + 1;
    if mod(k, 2) == 0
        continue
    elseif k == 5
        break
    else
        total = total + k;
    end
end
switch 'lead'
    case {'lag', 'pi'}
        kind = 1;
    case 'lead'
        kind = 2;
    otherwise
        kind = 3;
end
try
    error('bad %d', 7);
catch err
    msg = err.message;
end
""")
    assert val(it, "total") == 4                   # 1 + 3, then break at 5
    assert val(it, "kind") == 2
    assert val(it, "msg") == "bad 7"


def test_local_functions_defined_below_their_use(it):
    run(it, """
[a, b] = twice(3);
c = twice(4);
function [y, z] = twice(x)
    y = 2*x;
    z = nargin;
end
""")
    assert val(it, "a") == 6 and val(it, "b") == 1 and val(it, "c") == 8


def test_function_handles(it):
    run(it, "f = @(x) x.^2 + 1; y = f(3); g = @sin; z = g(0);")
    assert val(it, "y") == 10 and val(it, "z") == 0


# ──────────────────────────────────────────────────────────────
#  Output counts and the control toolbox
# ──────────────────────────────────────────────────────────────

def test_step_with_outputs_returns_y_then_t_and_does_not_plot(it, sink):
    before = len(sink.figures)
    run(it, "G = tf(1, [1 1]); t = 0:0.1:5; [y, tt] = step(G, t);")
    assert len(sink.figures) == before
    y, tt = val(it, "y"), val(it, "tt")
    assert y.shape == (51, 1) and tt.shape == (51, 1)
    assert y[-1, 0] == pytest.approx(1 - np.exp(-5), abs=1e-3)


def test_margin_outputs_and_plot(it, sink):
    run(it, "G = tf(4, [1 3 3 1]); [Gm, Pm, Wcg, Wcp] = margin(G);")
    assert val(it, "Gm") == pytest.approx(2.0, rel=1e-3)
    out = run(it, "margin(G)")
    assert "Gm =" in out and sink.figures[-1].kind == "bode"


def test_several_systems_share_one_time_axis(it, sink):
    run(it, "step(tf(1, [1 1]), tf(1, [10 1]))")
    fast, slow = sink.figures[-1].traces
    assert np.array_equal(fast.x, slow.x)
    assert fast.x[-1] > 20                         # long enough for τ = 10 s


def test_wide_tables_wrap_by_column_not_by_row(it):
    out = run(it, "s = tf('s'); info(1) = stepinfo(1/(s+1));"
                  "info(2) = stepinfo(1/(s+2)); struct2table(info)")
    widest = max(len(line) for line in out.splitlines())
    assert widest < 100
    assert "SteadyState" in out


def test_hold_on_overlays_and_title_amends(it, sink):
    run(it, "G = tf(1, [1 1]); H = tf(1, [1 2]);"
            "figure; step(G); hold on; step(H); title('both');"
            "xlabel('time'); legend('slow', 'fast')")
    fig = sink.figures[-1]
    assert [t.label for t in fig.traces] == ["slow", "fast"]
    assert fig.title == "both"


def test_plot_family(it, sink):
    run(it, "t = linspace(0, 1, 11); plot(t, t.^2, 'r--', t, t, 'b');"
            "semilogx(logspace(-1, 1, 5), 1:5)")
    xy, logfig = sink.figures[-2:]
    assert len(xy.traces) == 2 and xy.traces[0].style == "dashed"
    assert logfig.extra.get("logx")


def test_echo_and_semicolons(it):
    out = run(it, "a = 5\nb = 6;\nc = [1 2 3]\na + b")
    assert "a = 5" in out
    assert "b = 6" not in out
    assert "ans = 11" in out
    assert "c =" in out


def test_fprintf_and_num2str(it):
    out = run(it, "fprintf('k = %d, x = %.2f\\n', 3, pi);"
                  "fprintf('%d ', [1 2 3]); fprintf('\\n');"
                  "s = ['Kp = ' num2str(2.5)]; disp(s)")
    assert "k = 3, x = 3.14" in out
    assert "1 2 3" in out
    assert "Kp = 2.5" in out


def test_matlab_zeros_is_square_python_console_untouched(it):
    run(it, "Z = zeros(3); r = zeros(1, 3);")
    assert val(it, "Z").shape == (3, 3)
    assert val(it, "r").shape == (3,)
    # The console stays numpy: zeros(3) there is still length 3.
    assert it.run("q = zeros(3)").ok and it.namespace["q"].shape == (3,)


def test_clear_all_keeps_script_functions(it):
    run(it, "clear all\nx = sq(3);\nfunction y = sq(a)\n  y = a^2;\nend")
    assert val(it, "x") == 9


def test_python_scripts_still_run_as_python(it):
    results = it.run_script("a = 1\nb = a + 1\nprint(b ** 3)")
    assert all(r.ok for r in results)
    assert it.namespace["b"] == 2


# ──────────────────────────────────────────────────────────────
#  Errors and detection
# ──────────────────────────────────────────────────────────────

def test_syntax_error_names_the_line():
    with pytest.raises(MatlabSyntaxError) as info:
        translate("x = 1;\ny = [1 2;\nz = 3")
    assert info.value.line >= 2


def test_unclosed_block_is_reported(it):
    results = it.run_script("for k = 1:3\n  disp(k)\n", "matlab")
    assert "never closed" in results[-1].error


def test_undefined_name_is_reported_in_matlab_words(it):
    results = it.run_script("x = 1;\ny = undefined_thing + 1;", "matlab")
    assert "Unrecognized function or variable 'undefined_thing'" \
        in results[-1].error
    assert "line 2" in results[-1].error


def test_syms_explains_itself(it):
    results = it.run_script("syms s\nG = 1/(s+1);", "matlab")
    assert "tf('s')" in results[-1].error


@pytest.mark.parametrize("source, expected", [
    ("G = tf([1], [1 2 1]);\nstep(G)", True),
    ("s = tf('s')\nG = 1/(s^2+1)", True),
    ("% comment\nx = 1", True),
    ("for k = 1:3\n  disp(k)\nend", True),
    ("import numpy as np\nx = np.zeros(3)", False),
    ("G = tf([1], [1, 2, 1])\nstep(G)\nprint(G ** 2)", False),
    ("def f(x):\n    return x\n", False),
])
def test_language_detection(source, expected):
    assert looks_like_matlab(source) is expected


def test_translation_is_readable_python():
    code = to_python("x = [1 2 3];\ny = x(end);")
    compile(code, "<test>", "exec")
    assert "__ml__.End" in code
