"""
Packaging: the self-test, the entry points, and the build definitions.

The self-test is what a packaged build ships *instead of* this suite, so it
has to be worth something on its own — and it has to be able to fail.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from fakematlab.selftest import Report, run

ROOT = Path(__file__).resolve().parents[2]


# ──────────────────────────────────────────────────────────────
#  The self-test
# ──────────────────────────────────────────────────────────────

def test_the_self_test_passes_without_a_display():
    report = run(verbose=False, include_ui=False)
    assert report.ok, "\n".join(report.failures)
    assert report.checks >= 25, "too few checks to mean anything"


def test_the_self_test_covers_every_lesson_claim():
    """
    Its payload is the lessons, so its check count must track them. A
    self-test that silently stopped running half the claims would still
    report OK.
    """
    from fakematlab.core.lessons import all_lessons

    claims = sum(len(lesson.claims) for lesson in all_lessons())
    report = run(verbose=False, include_ui=False)
    assert report.checks >= claims


def test_a_report_can_fail_and_says_what():
    report = Report()
    report.record(True)
    report.record(False, "the margin was wrong")
    assert not report.ok
    assert "1/2 checks passed" in report.summary()
    assert "the margin was wrong" in report.summary()


def test_a_passing_report_reads_as_ok():
    report = Report()
    report.record(True)
    assert report.ok and report.summary().startswith("OK")


def test_the_self_test_reports_a_broken_build_rather_than_raising(monkeypatch):
    """
    If a whole subsystem is broken the self-test must still finish and name
    it. An exception escaping here would leave the exit code meaningless.
    """
    import fakematlab.selftest as selftest

    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated breakage")

    monkeypatch.setattr(selftest, "_check_simulation", explode)
    with pytest.raises(RuntimeError):
        # The guard is inside each check, so replacing the whole function
        # bypasses it — this pins that the guards are per-subsystem.
        selftest.run(verbose=False, include_ui=False)


def test_the_report_survives_a_console_that_cannot_encode_it(capsys):
    """
    A Windows console is cp1252, and the report is full of ζ, ω, − and tab
    icons. Printing used to raise inside a check's ``try`` block, so a display
    problem was recorded as a *correctness* failure — a lie about the build.
    """
    import io

    import fakematlab.selftest as selftest

    narrow = io.TextIOWrapper(io.BytesIO(), encoding="cp1252",
                              errors="strict", newline="")
    real_stdout = sys.stdout
    sys.stdout = narrow
    try:
        report = selftest.run(verbose=True, include_ui=False)
    finally:
        sys.stdout = real_stdout
    assert report.ok, "\n".join(report.failures)


def test_a_broken_subsystem_is_recorded_not_raised(monkeypatch):
    import control as ctl

    import fakematlab.selftest as selftest

    monkeypatch.setattr(ctl, "tf", lambda *a, **k: 1 / 0)
    report = selftest.run(verbose=False, include_ui=False)
    assert not report.ok
    assert any("block algebra raised" in f or "lessons raised" in f
               for f in report.failures), report.failures


# ──────────────────────────────────────────────────────────────
#  The entry points
# ──────────────────────────────────────────────────────────────

def test_version_flag_prints_and_exits_zero():
    result = subprocess.run(
        [sys.executable, "app.py", "--version"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0
    assert "FauxMatlab" in result.stdout


def test_check_flag_exits_zero_on_a_healthy_tree():
    """
    The contract ``app.py --check && deploy`` relies on: the exit code is the
    number of failures.
    """
    result = subprocess.run(
        [sys.executable, "app.py", "--check", "--quiet"],
        cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_check_does_not_need_a_gui_before_it_decides():
    """
    ``--check`` has to work on a headless machine, so ``app.py`` must not
    import Qt or open a display at module level — only inside ``main()``
    after the flags have been read.
    """
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    header = source.split("def main(")[0]
    for forbidden in ("import pyqtgraph", "from PySide6", "QApplication"):
        assert forbidden not in header, \
            f"{forbidden!r} runs at import time, before --check is handled"


# ──────────────────────────────────────────────────────────────
#  The build definitions
# ──────────────────────────────────────────────────────────────

def test_the_ci_workflow_runs_lint_tests_and_the_self_test():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")
    for step in ("ruff check .", "pytest -q", "python app.py --check"):
        assert step in text, f"CI does not run {step!r}"


def test_the_spec_excludes_the_other_qt_bindings():
    """
    All three bindings are installed here. Bundling more than one puts two
    sets of Qt DLLs in the same folder, which is the conflict ``app.py`` pins
    the binding to avoid — and it would only show up in the packaged build.
    """
    text = (ROOT / "packaging" / "fauxmatlab.spec").read_text(encoding="utf-8")
    assert '"PyQt5"' in text and '"PyQt6"' in text


def test_the_spec_builds_a_console_entry_point_for_the_self_test():
    """A windowed exe has no stdout, so --check there would print nothing."""
    text = (ROOT / "packaging" / "fauxmatlab.spec").read_text(encoding="utf-8")
    assert "FauxMatlab-check" in text
    assert "console=True" in text


def test_the_spec_installs_the_missing_stdio_runtime_hook():
    """
    A windowed build has ``sys.stdout is None`` and ``sys.stderr is None``.
    numpy's ``f2py.cfuncs`` does ``errmess = sys.stderr.write`` at import
    time — reached from ``scipy.linalg`` — so without the hook the launch
    dies with ``AttributeError: 'NoneType' object has no attribute 'write'``
    before the window appears. The console build never sees it.
    """
    spec = (ROOT / "packaging" / "fauxmatlab.spec").read_text(encoding="utf-8")
    assert "rthook_stdio.py" in spec
    assert "runtime_hooks=[]" not in spec
    assert (ROOT / "packaging" / "rthook_stdio.py").exists()


def test_the_stdio_hook_replaces_missing_streams():
    """Run the hook with the streams knocked out, as a windowed build has."""
    probe = (
        "import sys, runpy;"
        "sys.stdout = None; sys.stderr = None;"
        "runpy.run_path(r'{hook}');"
        "ok = sys.stdout is not None and sys.stderr is not None;"
        "sys.stdout.write('');"
        "sys.stderr.write('');"
        "import numpy.f2py.cfuncs;"       # the import that used to crash
        "sys.__stdout__.write('OK' if ok else 'STILL NONE')"
    ).format(hook=ROOT / "packaging" / "rthook_stdio.py")
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


def test_ci_self_tests_the_windowed_build_too():
    """
    The verification hole that let the crash ship: only the console entry
    point was being checked, and the bug exists only in the windowed one.
    """
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")
    assert "FauxMatlab-check.exe --check" in text
    assert "FauxMatlab.exe" in text and "windowed" in text


def test_the_spec_excludes_nothing_the_app_imports_at_startup():
    """
    The mistake this pins down was made once already.

    ``matplotlib`` and python-control's plotting modules look excludable —
    this application draws with pyqtgraph and never calls them. But
    ``control/__init__.py`` imports ``ctrlplot``, ``freqplot``, ``timeplot``
    and friends unconditionally, and those import matplotlib at module level.
    Excluding any of them turns ``import control`` into a
    ``ModuleNotFoundError`` that only appears in the frozen build.
    """
    import ast
    import json
    import os

    spec = (ROOT / "packaging" / "fauxmatlab.spec").read_text(encoding="utf-8")
    excluded: set[str] = set()
    for node in ast.walk(ast.parse(spec)):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "EXCLUDES" for t in node.targets)):
            excluded = {e.value for e in node.value.elts
                        if isinstance(e, ast.Constant)
                        and isinstance(e.value, str)}
    assert excluded, "could not read EXCLUDES out of the spec"

    # A clean interpreter, because this test is about what *the application*
    # imports. Asking the pytest process would also count pytest's own imports
    # and whatever the rest of the suite has pulled in, which is how the first
    # version of this test produced a false alarm.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYQTGRAPH_QT_LIB": "PySide6", "PYTHONPATH": str(ROOT)}
    probe = ("import sys, json;"
             "import fakematlab.ui.mainwindow, fakematlab.selftest;"
             "print(json.dumps(sorted(sys.modules)))")
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    loaded = set(json.loads(result.stdout.strip().splitlines()[-1]))

    clashes = sorted(
        name for name in excluded
        if name in loaded or any(m.startswith(name + ".") for m in loaded))
    assert not clashes, (
        f"the spec excludes {clashes}, which importing this app actually "
        f"loads — the frozen build would fail where the source tree works")


def test_the_course_material_is_not_packaged_or_committed():
    """
    The lecture decks are the lecturers' copyright. The repository is public.
    """
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "COURSE MATERIAL/" in gitignore
