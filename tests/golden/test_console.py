"""
The command window: the MATLAB-shaped API, the REPL, and the workspace.

The API is tested headless, against the same core functions the tabs use — a
console command that disagrees with the tab showing the same quantity would be
worse than having no console.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.console import Interpreter, set_figure_sink
from fakematlab.console.api import build_namespace, command_names, describe_api
from fakematlab.console.figures import recording_sink


@pytest.fixture
def sink():
    recorder = recording_sink()
    previous = set_figure_sink(recorder)
    yield recorder
    set_figure_sink(previous)


@pytest.fixture
def it(sink):
    return Interpreter()


def _run(interpreter, *lines):
    results = [interpreter.run(line) for line in lines]
    failed = [r for r in results if r.error]
    assert not failed, f"{failed[0].source!r} → {failed[0].error}"
    return results[-1]


# ──────────────────────────────────────────────────────────────
#  The namespace
# ──────────────────────────────────────────────────────────────

def test_every_advertised_command_exists():
    """
    The help listing must not promise a command the namespace lacks.

    Checked against the group table rather than by parsing the printed text —
    the group headings contain spaces, so word-splitting the prose reads
    "State space" as a command called ``space``.
    """
    from fakematlab.console.api import _GROUPS

    namespace = build_namespace()
    for group, names in _GROUPS.items():
        for name in names:
            assert name in namespace, f"{group} lists {name}, which is missing"
            assert callable(namespace[name]), f"{name} is not callable"


def test_help_text_mentions_every_group():
    from fakematlab.console.api import _GROUPS

    text = describe_api()
    for group in _GROUPS:
        assert group in text


def test_laplace_variable_builds_systems(it):
    _run(it, "G = 1/(s**2 + 2*s + 1)")
    poles = np.atleast_1d(ctl.poles(it.namespace["G"]))
    assert np.allclose(np.sort(poles.real), [-1.0, -1.0])


def test_tf_of_s_is_the_same_variable(it):
    _run(it, "x = tf('s')")
    assert np.allclose(np.atleast_1d(it.namespace["x"].num[0][0]), [1.0, 0.0])


# ──────────────────────────────────────────────────────────────
#  MATLAB-shaped results
# ──────────────────────────────────────────────────────────────

def test_stepinfo_uses_matlab_field_names(it):
    result = _run(it, "G = tf([4], [1, 1.2, 4])", "info = stepinfo(G)")
    info = it.namespace["info"]
    for field in ("RiseTime", "SettlingTime", "Overshoot", "Peak",
                  "PeakTime", "SteadyState"):
        assert field in info
    # ζ = 0.3 gives Mp ≈ 37%.
    assert info["Overshoot"] == pytest.approx(37.2, abs=1.0)


def test_margin_returns_matlabs_order(it):
    """
    ``[Gm, Pm, Wcg, Wcp]`` — gain-margin frequency *before* phase-margin
    frequency, and ``Gm`` in absolute units rather than dB.
    """
    _run(it, "L = tf([1], [1, 3, 3, 1])", "Gm, Pm, Wcg, Wcp = margin(L)")
    assert it.namespace["Gm"] == pytest.approx(8.0, rel=1e-6)
    assert it.namespace["Wcg"] == pytest.approx(np.sqrt(3.0), rel=1e-6)


def test_allmargin_includes_the_modulus_margin(it):
    _run(it, "L = tf([1], [1, 3, 3, 1])", "m = allmargin(L)")
    m = it.namespace["m"]
    assert m["GainMargin_dB"] == pytest.approx(20 * np.log10(8.0), rel=1e-6)
    assert "ModulusMargin" in m and np.isfinite(m["ModulusMargin"])


def test_damp_displays_a_table_and_still_unpacks(it):
    """
    MATLAB picks between printing and returning by counting outputs, which
    Python cannot see — so the result is a tuple whose repr is the table.
    """
    result = _run(it, "G = tf([1], [1, 2, 2])", "damp(G)")
    shown = result.display()
    assert "Damping" in shown and "Frequency" in shown

    _run(it, "wn, zeta, p = damp(G)")
    assert it.namespace["wn"].shape == (2,)
    assert it.namespace["zeta"][0] == pytest.approx(1 / np.sqrt(2), rel=1e-6)


def test_errconst_matches_the_performance_tab(it):
    from fakematlab.core.performance import analyse_performance

    _run(it, "L = tf([1], [1, 1, 0])", "e = errconst(L)")
    reference = analyse_performance(ctl.tf([1], [1, 1, 0]))
    assert it.namespace["e"]["Kv"] == pytest.approx(reference.Kv)
    assert it.namespace["e"]["Type"] == reference.system_type


def test_d2c_returns_the_type_it_was_given(it):
    """``d2c(c2d(G))`` should come back comparable with ``G``."""
    _run(it, "G = tf([1], [1, 2, 1])", "d = c2d(G, 0.1)", "back = d2c(d)")
    back = it.namespace["back"]
    assert isinstance(back, ctl.TransferFunction)
    w = np.logspace(-2, 1, 40)
    original = np.squeeze(ctl.frequency_response(ctl.tf([1], [1, 2, 1]),
                                                 w).response)
    assert np.allclose(np.squeeze(ctl.frequency_response(back, w).response),
                       original, atol=1e-9)


def test_lqr_matches_the_core_module(it):
    from fakematlab.core.statefbk import lqr as core_lqr
    from fakematlab.core.statespace import state_space

    _run(it,
         "sys = ss([[0, 1], [0, 0]], [[0], [1]], [[1, 0]])",
         "K, P, e = lqr(sys, eye(2), 1)")
    expected = core_lqr(state_space([[0, 1], [0, 0]], [[0], [1]], [[1, 0]]),
                        np.eye(2), 1.0)
    assert np.allclose(it.namespace["K"], expected.K)


# ──────────────────────────────────────────────────────────────
#  Plotting
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command,kind", [
    ("step(G)", "time"),
    ("impulse(G)", "time"),
    ("bode(G)", "bode"),
    ("nyquist(G)", "nyquist"),
    ("pzmap(G)", "pzmap"),
    ("rlocus(G)", "rlocus"),
])
def test_plot_commands_emit_a_figure(it, sink, command, kind):
    _run(it, "G = tf([1], [1, 2, 1])", command)
    assert sink.last is not None
    assert sink.last.kind == kind
    assert sink.last.traces


def test_plot_commands_echo_a_summary_not_the_raw_arrays(it, sink):
    """
    ``step(T)`` at a prompt should not print two thousand numbers.

    The data is still returned — it is the *display* that is short.
    """
    result = _run(it, "G = tf([1], [1, 2, 1])", "step(G)")
    shown = result.display()
    assert len(shown.splitlines()) == 1
    assert "time response" in shown

    _run(it, "t, y = step(G)")
    assert len(it.namespace["t"]) > 100


def test_plot_false_suppresses_the_figure(it, sink):
    _run(it, "G = tf([1], [1, 2, 1])", "t, y = step(G, plot=False)")
    assert sink.last is None


def test_bode_reports_the_frequency_span(it, sink):
    result = _run(it, "G = tf([1], [1, 2, 1])", "bode(G)")
    assert "rad/s" in result.display()


def test_several_systems_on_one_figure(it, sink):
    _run(it, "G1 = tf([1], [1, 1])", "G2 = tf([1], [1, 2])",
         "step(G1, G2)")
    assert len(sink.last.traces) == 2


# ──────────────────────────────────────────────────────────────
#  The REPL
# ──────────────────────────────────────────────────────────────

def test_namespace_persists_between_commands(it):
    _run(it, "a = 2", "b = a * 3")
    assert it.namespace["b"] == 6


def test_trailing_semicolon_suppresses_the_echo(it):
    loud = it.run("1 + 1")
    quiet = it.run("1 + 1;")
    assert loud.display() == "2"
    assert quiet.display() == ""
    # ...but the value is still computed and bound to `ans`.
    assert it.namespace["ans"] == 2


def test_percent_is_accepted_as_a_comment(it):
    """
    Only where it cannot mean modulo: the rewrite is attempted just when the
    line does not already parse.
    """
    assert it.run("x = 1  % a comment").ok
    assert it.namespace["x"] == 1
    # A real modulo must survive untouched.
    _run(it, "y = 7 % 3")
    assert it.namespace["y"] == 1


def test_ans_holds_the_last_unassigned_value(it):
    _run(it, "41 + 1", "z = ans + 1")
    assert it.namespace["z"] == 43


def test_multi_statement_block_runs(it):
    result = it.run("total = 0\nfor i in range(4):\n    total += i\ntotal")
    assert result.ok
    assert result.value == 6


def test_print_output_is_captured(it):
    result = it.run("print('hello')")
    assert result.display() == "hello"


# ──────────────────────────────────────────────────────────────
#  Errors, and the hints that go with them
# ──────────────────────────────────────────────────────────────

def test_an_error_does_not_kill_the_session(it):
    assert it.run("1/0").error
    _run(it, "ok = 5")
    assert it.namespace["ok"] == 5


@pytest.mark.parametrize("source,expected", [
    ("x = [1 2 3]", "needs commas"),
    ("def f()\n    pass", ""),          # plain syntax error, no special hint
])
def test_matlab_spellings_get_an_explanation(it, source, expected):
    result = it.run(source)
    assert result.error
    if expected:
        assert expected in result.hint


def test_caret_is_explained_at_run_time(it):
    """
    ``s^2`` is valid Python — bitwise XOR — so it fails at run time and the
    syntax hints never see it.
    """
    result = _run_expect_error(it, "G = s^2")
    assert "**" in result.hint


def test_unknown_name_suggests_help(it):
    result = _run_expect_error(it, "nosuchthing")
    assert "help_fm()" in result.hint


def test_a_case_slip_is_named(it):
    _run(it, "Gain = 3")
    result = _run_expect_error(it, "gain + 1")
    assert "case-sensitive" in result.hint


def _run_expect_error(interpreter, source):
    result = interpreter.run(source)
    assert result.error, f"{source!r} was expected to fail"
    return result


# ──────────────────────────────────────────────────────────────
#  Workspace
# ──────────────────────────────────────────────────────────────

def test_workspace_shows_user_variables_not_commands(it):
    _run(it, "G = tf([1], [1, 1])", "k = 3")
    variables = it.variables()
    assert {"G", "k"} <= set(variables)
    # The fifty-odd command names must not clutter the list.
    assert not (command_names() - {"s"}) & set(variables)


def test_clear_empties_the_workspace(it):
    _run(it, "a = 1", "b = 2")
    it.clear("a")
    assert "a" not in it.variables() and "b" in it.variables()
    it.clear()
    assert not it.variables()


def test_completion_offers_user_names_first(it):
    _run(it, "steady = 1")
    completions = it.completions("ste")
    assert completions[0] == "steady"
    assert "step" in completions


def test_completion_walks_attributes(it):
    _run(it, "G = tf([1], [1, 1])")
    assert any(c.endswith(".poles") or c.endswith(".num")
               for c in it.completions("G."))


# ──────────────────────────────────────────────────────────────
#  Scripts
# ──────────────────────────────────────────────────────────────

def test_a_script_runs_statement_by_statement(it):
    results = it.run_script("a = 1\nb = a + 1\nb * 2")
    assert len(results) == 3
    assert results[-1].value == 4


def test_a_script_stops_at_the_failing_statement(it):
    """
    Running statement by statement means the report names *which* line
    stopped it, and the statements before it have already taken effect.
    """
    results = it.run_script("a = 1\nboom\nc = 3")
    assert len(results) == 2
    assert results[1].error
    assert it.namespace["a"] == 1
    assert "c" not in it.namespace
