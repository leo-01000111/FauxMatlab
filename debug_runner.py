"""
Side-door diagnostic runner.
Exercises every core computation path that the UI triggers,
with the same calls and same default architecture.

Run: python debug_runner.py
"""

import os

os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"

import control as ctl
import numpy as np

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.freqresp import bode, nichols, nyquist
from fakematlab.core.performance import analyse_performance
from fakematlab.core.stability import root_locus, routh_from_closed_loop, routh_table
from fakematlab.core.tf_utils import (
    PRESETS,
    analyse,
    factored_str,
    first_order,
    from_coefficients,
    from_expression,
    from_zpk,
    integrator,
    pure_delay_pade,
    second_order,
    unity,
)
from fakematlab.core.timeresp import (
    compute_step_metrics,
    impulse_response,
    parameter_sweep,
    ramp_response,
    step_response,
)
from fakematlab.core.tuning import (
    LeadLagParams,
    PIDParams,
    lag_tf,
    lead_tf,
    pid_tf,
    zn_step,
    zn_ultimate,
)

PASS = "  [OK]"
FAIL = "  [!!]"

results = []

def check_raises(label, fn, exc_type):
    """A correct refusal is a pass: assert fn() raises exc_type."""
    try:
        fn()
    except exc_type as exc:
        print(f"{PASS} {label}")
        print(f"       refused: {str(exc)[:66]}...")
        results.append((label, True, []))
        return True
    except Exception as exc:
        print(f"{FAIL} {label}  (wrong exception {type(exc).__name__})")
        results.append((label, False, [str(exc)]))
        return False
    print(f"{FAIL} {label}  (expected {exc_type.__name__}, nothing raised)")
    results.append((label, False, ["no exception raised"]))
    return False


def check(label, fn, *expect_keys):
    """Run fn(), print result, flag NaN/inf/exception."""
    try:
        val = fn()
        issues = []
        if expect_keys and isinstance(val, object):
            for k in expect_keys:
                v = getattr(val, k, None)
                if v is None:
                    issues.append(f"{k}=missing")
                elif isinstance(v, float) and np.isnan(v):
                    issues.append(f"{k}=nan")
                elif isinstance(v, np.ndarray) and np.any(np.isnan(v)):
                    issues.append(f"{k} has NaN")
        tag = FAIL if issues else PASS
        detail = f"  [{', '.join(issues)}]" if issues else ""
        print(f"{tag} {label}{detail}")
        results.append((label, True, issues))
        return val
    except Exception as exc:
        print(f"{FAIL} {label}")
        print(f"       {type(exc).__name__}: {exc}")
        results.append((label, False, [str(exc)]))
        return None


# ─────────────────────────────────────────────────────────────
print("\n══ 1. TF CONSTRUCTION ════════════════════════════════")
# ─────────────────────────────────────────────────────────────

G1  = check("first_order(1, 1)",        lambda: first_order(1.0, 1.0))
G2  = check("second_order(1, 0.5, 2)",  lambda: second_order(1.0, 0.5, 2.0))
G3  = check("integrator(2)",            lambda: integrator(2.0))
G4  = check("from_coefficients",        lambda: from_coefficients([1], [1, 2, 1]))
G5  = check("from_expression K/(s^2+s+1)",
            lambda: from_expression("1/(s^2+s+1)"))
G6  = check("from_zpk zeros=[-1] poles=[-2,-3] k=6",
            lambda: from_zpk([-1], [-2, -3], 6.0))
G_unstable = check("unstable 1/(s-1)",  lambda: ctl.TransferFunction([1],[1,-1]))
G_dbl_int  = check("double integrator", lambda: ctl.TransferFunction([1],[1,0,0]))
G_nmp      = check("NMP (-s+1)/(s+1)",  lambda: ctl.TransferFunction([-1,1],[1,1]))

print("\nfactored_str samples:")
for name, g in [("1st-order", G1), ("2nd-order", G2), ("double-int", G_dbl_int)]:
    try:
        s = factored_str(g)
        print(f"  {name}: {s}")
    except Exception as exc:
        print(f"  {FAIL} factored_str({name}): {exc}")

print("\nanalyse() samples:")
for name, g in [("1st-order", G1), ("2nd-order", G2), ("unstable", G_unstable)]:
    try:
        info = analyse(g)
        print(f"  {name}: poles={[f'{p.value:.3g}' for p in info.poles]}  stable={info.stable}")
    except Exception as exc:
        print(f"  {FAIL} analyse({name}): {exc}")


# ─────────────────────────────────────────────────────────────
print("\n══ 2. ARCHITECTURE / CLOSED-LOOP TFs ════════════════")
# ─────────────────────────────────────────────────────────────

PLANTS = [
    ("1st-order",   first_order(1.0, 1.0)),
    ("2nd-order",   second_order(1.0, 0.5, 2.0)),
    ("double-int",  ctl.TransferFunction([1],[1,0,0])),
    ("unstable",    ctl.TransferFunction([1],[1,-1])),
    ("NMP",         ctl.TransferFunction([-1,1],[1,1])),
]
INPUTS  = ["r", "di", "do", "n"]
OUTPUTS = ["y", "u", "e"]

for pname, G in PLANTS:
    arch = CourseArchitecture(G=G, K2=unity(), K1=unity(), H=unity())
    for inp in INPUTS:
        for out in OUTPUTS:
            label = f"arch({pname}) {inp}→{out}"
            check(label, lambda i=inp, o=out, a=arch: a.get_closed_loop_tf(i, o))


# ─────────────────────────────────────────────────────────────
print("\n══ 3. TIME RESPONSES ══════════════════════════════════")
# ─────────────────────────────────────────────────────────────

arch_default = CourseArchitecture(
    G=second_order(1.0, 0.5, 2.0), K2=unity(), K1=unity(), H=unity())

for inp, out in [("r","y"), ("r","u"), ("r","e"), ("di","y"), ("do","y"), ("n","y")]:
    tf_cl = arch_default.get_closed_loop_tf(inp, out)
    check(f"step_response  {inp}→{out}",
          lambda t=tf_cl: step_response(t), "t", "y")
    check(f"impulse_response {inp}→{out}",
          lambda t=tf_cl: impulse_response(t), "t", "y")
    check(f"ramp_response  {inp}→{out}",
          lambda t=tf_cl: ramp_response(t), "t", "y")

print("\nStep metrics (r→y, 2nd-order underdamped):")
tf_ry = arch_default.get_closed_loop_tf("r", "y")
resp  = step_response(tf_ry)
m = check("compute_step_metrics", lambda: compute_step_metrics(resp),
          "y_inf", "Mp_pct", "tp", "ts_2pct", "ts_5pct")
if m:
    for k, v in m.as_dict().items():
        flag = "  *NaN*" if (isinstance(v, float) and np.isnan(v)) else ""
        print(f"    {k:<30} {v:.5g}{flag}")

print("\nStep metrics — edge cases:")
# Type 1 system (integrator in plant)
arch_int = CourseArchitecture(G=integrator(2.0), K2=unity(), K1=unity(), H=unity())
tf_int   = arch_int.get_closed_loop_tf("r", "y")
resp_int = check("step_response(integrator plant)", lambda: step_response(tf_int))
if resp_int:
    m2 = check("metrics(integrator plant)", lambda: compute_step_metrics(resp_int))

# Unstable open-loop (stable CL with K2=5)
arch_ust = CourseArchitecture(G=G_unstable, K2=ctl.TransferFunction([5],[1]), K1=unity(), H=unity())
tf_ust   = arch_ust.get_closed_loop_tf("r", "y")
resp_ust = check("step_response(stabilised unstable plant)", lambda: step_response(tf_ust))
if resp_ust:
    m3 = check("metrics(stabilised unstable)", lambda: compute_step_metrics(resp_ust))

print("\nParameter sweep (K2 gain 0.5,1,2,5 on r→y):")
def make_tf_sweep(val):
    a = CourseArchitecture(G=second_order(1,0.5,2), K2=ctl.TransferFunction([val],[1]),
                           K1=unity(), H=unity())
    return a.get_closed_loop_tf("r","y")
check("parameter_sweep step", lambda: parameter_sweep(make_tf_sweep, [0.5,1,2,5]))


# ─────────────────────────────────────────────────────────────
print("\n══ 4. FREQUENCY RESPONSES ════════════════════════════")
# ─────────────────────────────────────────────────────────────

for pname, G in PLANTS:
    arch = CourseArchitecture(G=G, K2=unity(), K1=unity(), H=unity())
    L    = arch.loop_tf()
    S    = arch.sensitivity()
    T    = arch.compl_sensitivity()

    bd = check(f"bode({pname} L)",  lambda loop=L: bode(loop),
               "gm_dB", "pm_deg")
    if bd:
        print(f"    GM={bd.gm_dB:.2f}dB  PM={bd.pm_deg:.2f}°  "
              f"wc={bd.wc:.3g}  bw3dB={bd.bw_3dB:.3g}  stable={bd.stable}")

    ny = check(f"nyquist({pname} L)", lambda loop=L: nyquist(loop),
               "encirclements", "P", "Z", "modulus_margin")
    if ny:
        print(f"    N={ny.encirclements}  P={ny.P}  Z={ny.Z}  mod_margin={ny.modulus_margin:.3g}")

    check(f"nichols({pname} L)", lambda loop=L: nichols(loop))
    check(f"bode(S {pname})",    lambda s=S: bode(s), "gm_dB", "pm_deg")
    check(f"bode(T {pname})",    lambda t=T: bode(t), "gm_dB", "pm_deg")


# ─────────────────────────────────────────────────────────────
print("\n══ 5. STABILITY ══════════════════════════════════════")
# ─────────────────────────────────────────────────────────────

# Routh – various characteristic polynomials
ROUTH_CASES = [
    ("stable 3rd-order",   [1, 6, 11, 6]),
    ("marginally stable",  [1, 0, 1, 0]),   # all-imaginary poles
    ("unstable",           [1, -2, 1]),
    ("all-zero row",       [1, 2, 8, 12, 20, 16, 16]),  # classic textbook case
]
for name, coeffs in ROUTH_CASES:
    r = check(f"routh_table({name})", lambda c=coeffs: routh_table(c))
    if r:
        fc = [f"{float(v):.3g}" if hasattr(v,'__float__') else str(v) for v in r.first_col]
        print(f"    stable={r.stable}  n_RHP={r.n_rhp_poles}  K_range='{r.K_stable_range}'  fc={fc}")

print()
# Symbolic K in Routh
import sympy

K = sympy.Symbol("K", positive=True)
arch_sym = CourseArchitecture(G=second_order(1,0.5,2), K2=unity(), K1=unity(), H=unity())
r_sym = check("routh_from_closed_loop (symbolic K)",
              lambda: routh_from_closed_loop(second_order(1,0.5,2), unity(), K_sym=K))
if r_sym:
    print(f"    K_stable_range={r_sym.K_stable_range}")

print()
# Root locus
for pname, G in PLANTS[:3]:  # skip unstable/NMP for now — root locus still valid
    rl = check(f"root_locus({pname})",
               lambda g=G: root_locus(g, unity(), K_min=0, K_max=50))
    if rl:
        km = rl.K_marginal
        wm = rl.omega_marginal
        print(f"    K_marginal={km:.3g}  omega_marginal={wm:.3g}  "
              f"asymptote_angles={[f'{a:.1f}°' for a in rl.asymptote_angles]}")

# CL pole map check
print("\nClosed-loop poles for default arch:")
tf_cl = arch_default.get_closed_loop_tf("r","y")
try:
    poles = ctl.poles(tf_cl)
    print(f"  poles={[f'{p:.4g}' for p in poles]}")
    unstable = [p for p in poles if p.real > 1e-6]
    if unstable:
        print(f"  WARNING: unstable CL poles: {unstable}")
    else:
        print("  All poles in LHP ✓")
except Exception as exc:
    print(f"  {FAIL} pole computation: {exc}")


# ─────────────────────────────────────────────────────────────
print("\n══ 6. PERFORMANCE ════════════════════════════════════")
# ─────────────────────────────────────────────────────────────

for pname, G in PLANTS:
    arch = CourseArchitecture(G=G, K2=unity(), K1=unity(), H=unity())
    L    = arch.loop_tf()
    pr = check(f"analyse_performance({pname})",
               lambda loop=L: analyse_performance(loop))
    if pr:
        print(f"    sys_type={pr.system_type}  Kp={pr.Kp:.4g}  "
              f"Kv={pr.Kv:.4g}  Ka={pr.Ka:.4g}  "
              f"e_step={pr.ess_step:.4g}  e_ramp={pr.ess_ramp:.4g}")

# Type 2 (double integrator) — e_step=0, e_ramp=0, e_parabola=finite
arch_t2 = CourseArchitecture(G=G_dbl_int, K2=unity(), K1=unity(), H=unity())
pr2 = check("analyse_performance(double integrator)",
            lambda: analyse_performance(arch_t2.loop_tf()))
if pr2:
    print(f"    sys_type={pr2.system_type}  e_step={pr2.ess_step}  "
          f"e_ramp={pr2.ess_ramp}  e_para={pr2.ess_parabola:.4g}")


# ─────────────────────────────────────────────────────────────
print("\n══ 7. CONTROLLER TUNING ══════════════════════════════")
# ─────────────────────────────────────────────────────────────

PID_CASES = [
    ("P  Kp=2",              PIDParams(Kp=2.0)),
    ("PI Kp=2 Ki=1",         PIDParams(Kp=2.0, Ki=1.0)),
    ("PD Kp=2 Kd=0.5",       PIDParams(Kp=2.0, Kd=0.5)),
    ("PID ideal",            PIDParams(Kp=2.0, Ki=1.0, Kd=0.5)),
    ("PID filtered Tf=0.1",  PIDParams(Kp=2.0, Ki=1.0, Kd=0.5, Tf=0.1)),
]
for name, p in PID_CASES:
    tf_pid = check(f"pid_tf({name})", lambda pp=p: pid_tf(pp))
    if tf_pid:
        poles = ctl.poles(tf_pid)
        print(f"    poles={[f'{x:.3g}' for x in poles]}")

# Lead / lag
for name, params in [
    ("Lead α=0.1 τ=1", LeadLagParams(K=1,alpha=0.1,tau=1.0,is_lead=True)),
    ("Lag  α=10  τ=1", LeadLagParams(K=1,alpha=10, tau=1.0,is_lead=False)),
]:
    tf_ll = check(f"lead/lag_tf({name})",
                  lambda p=params: lead_tf(p) if p.is_lead else lag_tf(p))

print()
# Z-N applies to plants the methods were designed for. A 1st- or 2nd-order
# plant with no dead time has no ultimate gain and no measurable reaction-curve
# delay, so both methods correctly refuse — those refusals are asserted here
# rather than counted as failures.
G_zn = first_order(1.0, 1.0) * pure_delay_pade(0.5, 3)   # FOPDT: lag + delay
zn_s = check("zn_step(FOPDT, delay 0.5s)", lambda: zn_step(G_zn))
if zn_s:
    print(f"    L={zn_s.L:.4g} (true 0.5)  T={zn_s.T:.4g}  dc={zn_s.dc_gain:.4g}  "
          f"PID: Kp={zn_s.PID_params.Kp:.4g} Ki={zn_s.PID_params.Ki:.4g} "
          f"Kd={zn_s.PID_params.Kd:.4g}")

G_u = ctl.TransferFunction([1], [1, 3, 3, 1])            # 1/(s+1)^3 : Ku=8, wu=sqrt3
zn_u = check("zn_ultimate(1/(s+1)^3)", lambda: zn_ultimate(G_u))
if zn_u:
    print(f"    Ku={zn_u.Ku:.6g} (exact 8)  Tu={zn_u.Tu:.6g} "
          f"(exact {2*np.pi/np.sqrt(3):.6g})  "
          f"PID: Kp={zn_u.PID_params.Kp:.4g} Ki={zn_u.PID_params.Ki:.4g}")

G_u2 = ctl.TransferFunction([1], [1, 3, 2, 0])           # 1/(s(s+1)(s+2)) : Ku=6
zn_u2 = check("zn_ultimate(1/(s(s+1)(s+2)))", lambda: zn_ultimate(G_u2))
if zn_u2:
    print(f"    Ku={zn_u2.Ku:.6g} (exact 6)  Tu={zn_u2.Tu:.6g} "
          f"(exact {2*np.pi/np.sqrt(2):.6g})")

check_raises("zn_ultimate refuses a 2nd-order plant (none exists)",
             lambda: zn_ultimate(second_order(1, 0.5, 2)), ValueError)
check_raises("zn_step refuses a plant with no dead time",
             lambda: zn_step(first_order(1.0, 1.0)), ValueError)


# ─────────────────────────────────────────────────────────────
print("\n══ 8. PRESETS ════════════════════════════════════════")
# ─────────────────────────────────────────────────────────────

for name, (label, tf_preset) in PRESETS.items():
    check(f"PRESET: {name} ({label})", lambda t=tf_preset: analyse(t))


# ─────────────────────────────────────────────────────────────
print("\n══ 9. THE APPS ═══════════════════════════════════════")
# ─────────────────────────────────────────────────────────────

from fakematlab.core.collection import (
    SnapshotStore,
    SystemCollection,
    restore_snapshot,
    take_snapshot,
)
from fakematlab.core.designer import (
    Compensator,
    closed_loop_poles,
    evaluate,
    gain_for_damping,
    gain_for_overshoot,
    point_to_gain,
)
from fakematlab.core.pidtune import PIDKind, tune, tune_by_sliders
from fakematlab.core.viewer import CHARACTERISTICS, ResponseKind
from fakematlab.core.viewer import compute as viewer_compute


def check_true(label, condition, why):
    """Assert a plain condition, so a broken invariant reads as a failure."""
    return check(label, lambda: True if condition else _raise(why))


def _raise(why):
    raise AssertionError(why)


# ── LTI Viewer: every response kind, with every characteristic it admits ──
viewer_set = SystemCollection()
viewer_set.add("2nd order", second_order(1.0, 0.3, 2.0))
viewer_set.add("1st order", first_order(1.0, 1.0))
for kind in ResponseKind:
    data = check(f"viewer: {kind.value}",
                 lambda k=kind: viewer_compute(viewer_set, k,
                                               set(CHARACTERISTICS[k])))
    if data is not None:
        print(f"       {len(data.curves)} curves, {len(data.marks)} marks")

# ── Designer ──
L_locus = ctl.TransferFunction([1], [1, 3, 2, 0])
known_pole = max(closed_loop_poles(L_locus, 1.5), key=lambda p: p.imag)
dp = check("designer: point_to_gain round trip",
           lambda: point_to_gain(L_locus, known_pole))
if dp:
    print(f"       asked for K=1.5, got K={dp.K:.6g}, "
          f"distance {dp.distance:.2e}")

zeta_point = check("designer: gain for zeta = 0.5",
                   lambda: gain_for_damping(L_locus, 0.5))
if zeta_point:
    print(f"       K={zeta_point.K:.6g} (exact 28/27 = {28 / 27:.6g})  "
          f"zeta={zeta_point.zeta:.4f}  wn={zeta_point.wn:.4g}")

mp_point = check("designer: gain for 16.3% overshoot",
                 lambda: gain_for_overshoot(L_locus, 16.303))
if mp_point and zeta_point:
    print(f"       K={mp_point.K:.6g} — agrees with the zeta route to "
          f"{abs(mp_point.K - zeta_point.K):.2e}")

lead_design = check("designer: evaluate (lead section)",
                    lambda: evaluate(L_locus,
                                     Compensator(2.0, [-1.0], [-10.0])),
                    "gm_dB", "pm_deg", "wc")
if lead_design:
    print("       " + lead_design.describe().replace("\n", "\n       "))

quiet = evaluate(L_locus, Compensator(gain=1.0))
loud = evaluate(L_locus, Compensator(gain=25.0))
check_true("designer: the locus does not move when only the gain does",
           np.allclose(quiet.locus.roots, loud.locus.roots, equal_nan=True),
           "the locus moved with the gain")

# ── PID tuner: the achieved crossover and margin are the requested ones ──
G_pid = ctl.TransferFunction([1], [1, 3, 3, 1])
for kind_name, wc_target, pm_target in (("PI", 0.5, 60.0),
                                        ("PID", 1.2, 50.0),
                                        ("PD", 1.2, 50.0)):
    r = check(f"pidtune {kind_name}: wc={wc_target}, PM={pm_target}",
              lambda k=kind_name, w=wc_target, p=pm_target:
              tune(G_pid, k, wc=w, pm_deg=p))
    if r and r.feasible:
        print(f"       achieved wc={r.achieved_wc:.6g} "
              f"(error {abs(r.achieved_wc - wc_target):.2e}), "
              f"PM={r.achieved_pm_deg:.4f} "
              f"(error {abs(r.achieved_pm_deg - pm_target):.2e})")

impossible = check("pidtune PI at a crossover it cannot reach",
                   lambda: tune(G_pid, PIDKind.PI, wc=1.2, pm_deg=50.0))
if impossible is not None:
    print(f"       feasible={impossible.feasible} — {impossible.note[:62]}...")

for speed, transient in ((-0.2, 0.0), (0.0, 0.5), (0.2, 1.0)):
    r = check(f"pidtune sliders: speed={speed:+.1f} transient={transient:.1f}",
              lambda s=speed, t=transient:
              tune_by_sliders(G_pid, PIDKind.PID, speed=s, transient=t))
    if r and r.metrics:
        print(f"       wc={r.achieved_wc:.4g}  PM={r.achieved_pm_deg:.1f}  "
              f"Mp={r.metrics.Mp_pct:.1f}%  ts={r.metrics.ts_2pct:.3g}s")

# ── Snapshots ──
arch_snap = CourseArchitecture(G=first_order(1.0, 1.0))
frozen = take_snapshot(arch_snap, "before")
arch_snap.set_block("G", ctl.TransferFunction([99], [1, 7]))
check_true("snapshot: frozen against later edits",
           np.allclose(np.atleast_1d(frozen.tf("G").num[0][0]), [1.0]),
           "the snapshot followed the edit")

restore_snapshot(arch_snap, frozen)
check_true("snapshot: restore puts the blocks back",
           np.allclose(np.atleast_1d(arch_snap.block_tf("G").den[0][0]),
                       [1.0, 1.0]),
           "restore did nothing")

store = SnapshotStore()
for _ in range(12):
    store.take(arch_snap, "design")
check_true("snapshot store: bounded, labels stay unique",
           len(store) == 8 and len(set(store.labels)) == len(store),
           f"{len(store)} snapshots, {len(set(store.labels))} distinct labels")


# ─────────────────────────────────────────────────────────────
print("\n══ SUMMARY ═══════════════════════════════════════════")
# ─────────────────────────────────────────────────────────────

passed   = [r for r in results if r[1] and not r[2]]
warnings = [r for r in results if r[1] and r[2]]
failed   = [r for r in results if not r[1]]

print(f"\n  Passed:   {len(passed)}")
print(f"  Warnings: {len(warnings)}  (NaN/inf in a metric)")
print(f"  Errors:   {len(failed)}")

if warnings:
    print("\nWarnings detail:")
    for label, _, issues in warnings:
        print(f"  {label}  →  {issues}")

if failed:
    print("\nErrors detail:")
    for label, _, issues in failed:
        print(f"  {label}  →  {issues}")
