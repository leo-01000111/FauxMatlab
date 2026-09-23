"""
Side-door diagnostic runner.
Exercises every core computation path that the UI triggers,
with the same calls and same default architecture.

Run: python debug_runner.py
"""

import os
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"

import traceback
import numpy as np
import control as ctl

from fakematlab.core.tf_utils      import (first_order, second_order, unity,
                                            from_coefficients, from_expression,
                                            from_zpk, integrator, PRESETS,
                                            pure_delay_pade,
                                            factored_str, analyse)
from fakematlab.core.architecture  import CourseArchitecture
from fakematlab.core.timeresp      import (step_response, impulse_response,
                                            ramp_response, compute_step_metrics,
                                            parameter_sweep)
from fakematlab.core.freqresp      import bode, nyquist, nichols
from fakematlab.core.stability     import (routh_table, routh_from_closed_loop,
                                            root_locus)
from fakematlab.core.performance   import analyse_performance
from fakematlab.core.tuning        import (PIDParams, pid_tf, lead_tf, lag_tf,
                                            LeadLagParams, zn_step, zn_ultimate,
                                            ControllerType)

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

    bd = check(f"bode({pname} L)",  lambda l=L: bode(l),
               "gm_dB", "pm_deg")
    if bd:
        print(f"    GM={bd.gm_dB:.2f}dB  PM={bd.pm_deg:.2f}°  "
              f"wc={bd.wc:.3g}  bw3dB={bd.bw_3dB:.3g}  stable={bd.stable}")

    ny = check(f"nyquist({pname} L)", lambda l=L: nyquist(l),
               "encirclements", "P", "Z", "modulus_margin")
    if ny:
        print(f"    N={ny.encirclements}  P={ny.P}  Z={ny.Z}  mod_margin={ny.modulus_margin:.3g}")

    check(f"nichols({pname} L)", lambda l=L: nichols(l))
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
               lambda l=L: analyse_performance(l))
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
