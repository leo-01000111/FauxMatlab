"""
The self-test behind ``python app.py --check``.

A packaged build ships without the test suite, so there has to be some way for
a user — or an installer, or a CI job — to ask "is this copy working?" and get
an answer that means something.

The payload is deliberately *not* a set of smoke checks. It checks results
with known closed forms across the classical half: exact critical gains,
margins, second-order overshoot, the waterbed integral. If those hold, the
numbers this build produces are the numbers the theory predicts.
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

    say("Evans self-test")
    say("=" * 60)

    _check_core(report, say)
    _check_analysis(report, say)
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


def _check_analysis(report: Report, say) -> None:
    """Analysis results that have a closed form to compare against."""
    say("\n[2/4] analysis — closed-form results")
    try:
        import control as ctl
        import numpy as np

        from .core.freqresp import bode
        from .core.performance import waterbed
        from .core.stability import marginal_gain
        from .core.timeresp import compute_step_metrics, step_response

        def close(name: str, measured: float, expected: float,
                  tol: float = 0.01) -> None:
            ok = abs(measured - expected) <= tol * max(1.0, abs(expected))
            report.record(ok, f"{name}: expected {expected:.6g}, "
                              f"measured {measured:.6g}")
            say(f"      {name:28s} {measured:.6g}"
                f"{'' if ok else f'  (expected {expected:.6g})'}")

        # L = 2/(s+1)³: |L(j√3)| = 1/4, and |L| = 1 at ωc = √(2^⅔ − 1).
        bd = bode(ctl.tf([2.0], [1.0, 3.0, 3.0, 1.0]))
        wc = float(np.sqrt(2.0 ** (2.0 / 3.0) - 1.0))
        close("gain margin (dB)", float(bd.gm_dB), 20 * np.log10(4.0))
        close("phase crossover (rad/s)", float(bd.w180), np.sqrt(3.0))
        close("gain crossover (rad/s)", float(bd.wc), wc)
        close("phase margin (°)", float(bd.pm_deg),
              180.0 - 3.0 * float(np.degrees(np.arctan(wc))))

        # 1 + K/(s+1)³ = 0 crosses the axis at K = 8, ω = √3, exactly.
        ku, wu = marginal_gain(ctl.tf([1.0], [1.0, 3.0, 3.0, 1.0]))
        close("critical gain", float(ku), 8.0, tol=1e-6)
        close("critical frequency (rad/s)", float(wu), np.sqrt(3.0), tol=1e-6)

        # Mp = exp(−πζ/√(1−ζ²)) for the canonical second order.
        zeta, wn = 0.3, 2.0
        metrics = compute_step_metrics(step_response(
            ctl.tf([wn ** 2], [1.0, 2 * zeta * wn, wn ** 2])))
        close("second-order overshoot (%)", float(metrics.Mp_pct),
              100 * np.exp(-np.pi * zeta / np.sqrt(1 - zeta ** 2)), tol=0.02)

        # A stable loop of relative degree 2: ∫ln|S| dω = 0.
        integral = float(waterbed(ctl.tf([2.0], [1.0, 3.0, 2.0])).integral)
        close("waterbed integral", integral, 0.0, tol=0.06)
    except Exception as exc:                                    # noqa: BLE001
        report.record(False, f"analysis raised {type(exc).__name__}: {exc}")
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

        # Every pane kind, in the first pane — the Tabs view is gone, and
        # the pane picker is now the one way to reach each workflow.
        from .ui.panes import PANE_KINDS

        pane = window._grid.panes[0]
        for entry in PANE_KINDS:
            pane.set_kind(entry.key)
            for _ in range(5):
                app.processEvents()
            broken = [b.message for b in pane.findChildren(ErrorBanner)
                      if b.has_error]
            report.record(not broken,
                          f"pane {entry.label!r}: {broken[0] if broken else ''}")
            say(f"      {entry.label[:28]:28s} "
                f"{'clean' if not broken else broken[0][:44]}")

        window.hide()
        _check_pdf_view(report, say)
        _check_completion(report, say)
    except Exception as exc:                                    # noqa: BLE001
        report.record(False, f"UI raised {type(exc).__name__}: {exc}")
        say(f"      FAILED: {exc}")


def _check_pdf_view(report: Report, say) -> None:
    """
    QtPdf is bundled and works: the live preview loads a PDF Qt writes.
    A frozen build missing the QtPdf libraries would build every other
    widget fine and fail only when the preview is first opened.
    """
    import tempfile
    from pathlib import Path

    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
    from PySide6.QtPdf import QPdfDocument

    from .ui.console.live_preview import LivePreview

    with tempfile.TemporaryDirectory(prefix="evans-check-") as tmp:
        path = Path(tmp) / "check.pdf"
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.A4))
        painter = QPainter(writer)
        painter.drawText(100, 100, "Evans")
        writer.newPage()
        painter.end()
        preview = LivePreview()
        preview._show_pdf(path)
        ok = (preview.pdf.status() == QPdfDocument.Status.Ready
              and preview.page_count == 2)
        report.record(ok, f"PDF preview: status {preview.pdf.status()}, "
                          f"{preview.page_count} pages")
        say(f"      {'PDF preview':28s} {'clean' if ok else 'FAILED'}")
        preview.pdf.close()
        preview.deleteLater()


def _check_completion(report: Report, say) -> None:
    r"""
    The completion popup has what it shows: call signatures, descriptions
    read from docstrings (a build run with ``-OO`` would strip them) and the
    LaTeX list.
    """
    from .ui.code import code_request, latex_request, rank, warm_up

    warm_up(wait=True)
    items = {c.text: c.resolved()
             for c in code_request("st", "matlab").items(True)}
    step, linspace = items.get("step"), items.get("linspace")
    tex = latex_request(r"\fr")
    ok = (step is not None and step.signature == "step(sys, t)"
          and linspace is not None and bool(linspace.detail)
          and bool(items.get("feedback") and items["feedback"].detail)
          and tex is not None
          and rank(tex.prefix, tex.items(True))[0].text == r"\frac")
    report.record(ok, "completion: signatures, descriptions or LaTeX missing")
    say(f"      {'code completion':28s} {'clean' if ok else 'FAILED'}")


def main(argv: list[str] | None = None) -> int:
    """``python -m evans.selftest`` — exit code is the failure count."""
    argv = list(sys.argv[1:] if argv is None else argv)
    report = run(verbose="--quiet" not in argv,
                 include_ui="--no-ui" not in argv)
    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(main())
