"""
Golden tests: results checked against closed-form theory and an independent
oracle, not against whatever the code currently happens to produce.

v1 shipped 64 green tests while six of its twelve closed-loop transfer
functions were wrong, every Bode plot was truncated below ω = 1, and the
root-locus branch tracking was broken. Those tests asserted shapes and types.
These assert *values*:

* against hand-derived algebra and the ch.4 closed-form formulas,
* against ``control.stability_margins`` and the numerical
  :class:`~fakematlab.core.signal_graph.SignalGraph` solver, which reach the
  same answers by an entirely different route.
"""
