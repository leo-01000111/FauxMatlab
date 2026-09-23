"""
The self-test behind ``python app.py --check``.

A packaged build ships without the test suite, so there has to be some way for
a user — or an installer, or a CI job — to ask "is this copy working?" and get
an answer that means something.

The payload is deliberately *not* a set of smoke checks. It runs the course
lessons' :class:`~fakematlab.core.lessons.Claim` objects, which are already
analytic statements with known answers spanning the whole classical half:
exact critical gains, closed-form margins, the waterbed integral. If those
hold, the numbers this build produces are the numbers the theory predicts.
On top of that it builds the whole window offscreen and checks that no panel
reported an error.

Exit code is the number of failures, so ``app.py --check && ./deploy`` does
what it looks like it does.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field


@dataclass
class Report:
    """What the self-test found."""

    checks: int = 0
    failures: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failures

    def record(self, passed: bool, detail: str = "") -> None:
        self.checks += 1
        if not passed:
            self.failures.append(detail)

    def summary(self) -> str:
        head = (f"{self.checks - len(self.failures)}/{self.checks} checks "
                f"passed in {self.seconds:.1f}s")
        if self.ok:
            return f"OK — {head}"
        lines = [f"FAILED — {head}", ""]
        lines += [f"  · {detail}" for detail in self.failures]
        return "\n".join(lines)


def _printer(verbose: bool):
    """
    A ``say`` that cannot fail.

    The report is full of ζ, ω, − and the tab icons, and a Windows console
    defaults to cp1252, which cannot encode any of them. Printing then raises
    ``UnicodeEncodeError`` from inside a check's ``try`` block — so a *display*
    problem gets recorded as a *correctness* failure, which is a lie about the
    build. Found by running the frozen executable, where the source tree never
    hits it because the development shell is UTF-8.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                           # noqa: BLE001
        pass                    # older streams, or a redirected pipe

    encoding = getattr(sys.stdout, "encoding", None) or "ascii"

    def say(text: str) -> None:
        if not verbose:
            return
        try:
            print(text)
        except (UnicodeEncodeError, UnicodeError):
            print(text.encode(encoding, errors="replace").decode(encoding))

    return say


def run(verbose: bool = True, include_ui: bool = True) -> Report:
    """Run the self-test. Returns a :class:`Report`; raises nothing."""
    report = Report()
    started = time.perf_counter()
    say = _printer(verbose)

    say("FauxMatlab self-test")
    say("=" * 60)

    _check_core(report, say)
    _check_lessons(report, say)
    _check_simulation(report, say)
    if include_ui:
        _check_ui(report, say)

    report.seconds = time.perf_counter() - started
    say("=" * 60)
    say(report.summary())
    return report


# ──────────────────────────────────────────────────────────────

def _check_core(report: Report, say) -> None:
    """The twelve closed-loop transfer functions derive from the graph."""
    say("\n[1/4] exact block algebra")
    try:
        import control as ctl

        from .core.architecture import (
            ALL_SIGNALS,
            INPUT_SIGNALS,
            OUTPUT_SIGNALS,
            CourseArchitecture,
        )

        arch = CourseArchitecture(
            G=ctl.tf([1], [1, 1]), K2=ctl.tf([2, 1], [1, 0]),
            K1=ctl.tf([1], [1]), H=ctl.tf([1], [1]))
        derived = arch.all_closed_loop_tfs()
        expected = len(INPUT_SIGNALS) * len(OUTPUT_SIGNALS)
        report.record(len(derived) == expected,
                      f"expected {expected} closed-loop transfer functions, "
                      f"derived {len(derived)}")
        say(f"      {len(derived)} of {expected} transfer functions derived "
            f"over {len(ALL_SIGNALS)} signals")

        # S + T = 1 is an identity, not an approximation.
        residual = abs(complex(arch.sensitivity()(1j))
                       + complex(arch.compl_sensitivity()(1j)) - 1.0)
        report.record(residual < 1e-9,
                      f"S + T should be exactly 1; residual {residual:.2e}")
        say(f"      S + T = 1 to {residual:.1e}")
    except Exception as exc:                                    # noqa: BLE001
        report.record(False, f"block algebra raised {type(exc).__name__}: {exc}")
        say(f"      FAILED: {exc}")


def _check_lessons(report: Report, say) -> None:
    """Every analytic claim the course lessons make."""
    say("\n[2/4] course lessons — analytic claims")
    try:
        from .core.lessons import all_lessons

        for lesson in all_lessons():
            results = lesson.check()
            held = sum(1 for _, _, ok in results if ok)
            for claim, measured, ok in results:
                report.record(ok, (
                    f"ch{lesson.chapter} {claim.text!r}: predicted "
                    f"{claim.mode} {claim.expected:.6g} {claim.units}, "
                    f"measured {measured:.6g}"))
            say(f"      ch{lesson.chapter}  {held}/{len(results)}  "
                f"{lesson.title[:46]}")
    except Exception as exc:                                    # noqa: BLE001
        report.record(False, f"lessons raised {type(exc).__name__}: {exc}")
        say(f"      FAILED: {exc}")


def _check_simulation(report: Report, say) -> None:
    """The block-diagram solver runs and integrates correctly."""
    say("\n[3/4] simulation engine")
    try:
        import numpy as np

        from .sim import simulate
        from .sim.model import SimModel

        # ẋ = −x + 1, x(0) = 0 → x(t) = 1 − e^{−t}. A first-order lag driven
        # by a step, which has an answer that can be written down.
        model = SimModel("selftest")
        model.add("Step", "r", step_time=0.0)
        model.add("TransferFcn", "G", num="1", den="1,1")
        model.connect("r", "G")

        result = simulate(model, t_end=5.0, n_points=1000,
                          rtol=1e-9, atol=1e-11)
        exact = 1.0 - np.exp(-np.asarray(result.t))
        error = float(np.max(np.abs(
            np.asarray(result.trace("G.out")).ravel() - exact)))
        report.record(error < 1e-5,
                      f"first-order lag step response off by {error:.2e}")
        say(f"      1/(s+1) step response matches 1 − e^(−t) to {error:.1e}")
    except Exception as exc:                                    # noqa: BLE001
        report.record(False, f"simulation raised {type(exc).__name__}: {exc}")
        say(f"      FAILED: {exc}")


def _check_ui(report: Report, say) -> None:
    """Every tab builds, and no panel reports an error."""
    say("\n[4/4] user interface (offscreen)")
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication

        from .core.architecture import CourseArchitecture
        from .ui.guard import ErrorBanner
        from .ui.mainwindow import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow(CourseArchitecture())
        window.resize(1400, 850)
        window.show()
        for _ in range(20):
            app.processEvents()

        for index in range(window._tabs.count()):
            window._tabs.setCurrentIndex(index)
            for _ in range(5):
                app.processEvents()
            name = window._tabs.tabText(index)
            broken = [b.message for b in
                      window._tabs.widget(index).findChildren(ErrorBanner)
                      if b.has_error]
            report.record(not broken, f"tab {name!r}: {broken[0] if broken else ''}")
            say(f"      {name:16s} {'clean' if not broken else broken[0][:44]}")

        window.hide()
    except Exception as exc:                                    # noqa: BLE001
        report.record(False, f"UI raised {type(exc).__name__}: {exc}")
        say(f"      FAILED: {exc}")


def main(argv: list[str] | None = None) -> int:
    """``python -m fakematlab.selftest`` — exit code is the failure count."""
    argv = list(sys.argv[1:] if argv is None else argv)
    report = run(verbose="--quiet" not in argv,
                 include_ui="--no-ui" not in argv)
    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(main())
