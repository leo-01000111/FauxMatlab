"""
Block editor panel — shown below the diagram when a block is clicked.
=====================================================================
Lets the user enter/modify a TF in several input modes:
  • Polynomial coefficients (num / den)
  • Expression string: (s+1)/(s^2+2s+1)
  • Zero-Pole-Gain (ZPK)
  • 1st-order preset (K, τ)
  • 2nd-order preset (K, ζ, ωn)

Always shows the factored form and a mini pole-zero map.
Emits tf_changed(block_id, tf) when the user applies a new TF.
"""

from __future__ import annotations

import control as ctl
import numpy as np

from PySide6.QtCore    import Signal, Qt
from PySide6.QtGui     import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QGroupBox, QSizePolicy, QTabWidget, QDoubleSpinBox,
)

from ..core.tf_utils import (
    from_coefficients, from_expression, from_zpk,
    first_order, second_order, unity, analyse, factored_str,
    pure_delay_pade,
)
from .plots import make_plot, draw_pz_map


# ──────────────────────────────────────────────────────────────

class BlockEditor(QWidget):
    """
    Compact editor panel for one TF block.
    Lives in the left panel below the diagram.
    """

    tf_changed = Signal(str, object)   # (block_id, TransferFunction)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._block_id: str | None = None
        self._current_tf: ctl.TransferFunction = unity()
        self._build_ui()

    # ── Public API ────────────────────────────────────────────

    def load_block(self, block_id: str,
                   tf: ctl.TransferFunction,
                   label: str = "") -> None:
        """Show this block in the editor."""
        self._block_id = block_id
        self._current_tf = tf
        self._group.setTitle(f"Edit: {label or block_id}")
        self._populate_from_tf(tf)
        self._refresh_info()

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        self._group = QGroupBox("Edit block")
        grp_lay = QVBoxLayout(self._group)

        # Input mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(
            ["Coefficients", "Expression", "ZPK",
             "1st-order preset", "2nd-order preset",
             "Pure delay (Padé)", "FOPDT (delay + lag)"]
        )
        self._mode_combo.currentIndexChanged.connect(self._on_mode_change)
        mode_row.addWidget(self._mode_combo)
        grp_lay.addLayout(mode_row)

        # Stacked input areas (simple show/hide, not QStackedWidget)
        self._coeff_widget  = self._build_coeff_widget()
        self._expr_widget   = self._build_expr_widget()
        self._zpk_widget    = self._build_zpk_widget()
        self._fo_widget     = self._build_first_order_widget()
        self._so_widget     = self._build_second_order_widget()
        self._delay_widget  = self._build_delay_widget()
        self._fopdt_widget  = self._build_fopdt_widget()

        for w in self._mode_widgets():
            grp_lay.addWidget(w)

        self._on_mode_change(0)

        # Apply / Reset buttons
        btn_row = QHBoxLayout()
        self._apply_btn = QPushButton("Apply ↵")
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._apply)
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._reset_btn)
        grp_lay.addLayout(btn_row)

        # Info display: factored form + stability
        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        self._info_label.setTextFormat(Qt.PlainText)
        font = QFont("Courier New", 9)
        self._info_label.setFont(font)
        grp_lay.addWidget(self._info_label)

        root.addWidget(self._group)

    # ── Per-mode widgets ──────────────────────────────────────

    def _build_coeff_widget(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self._num_edit = QLineEdit("1")
        self._den_edit = QLineEdit("1, 1")
        self._num_edit.setPlaceholderText("e.g. 1")
        self._den_edit.setPlaceholderText("e.g. 1, 2, 1")
        f.addRow("Num:", self._num_edit)
        f.addRow("Den:", self._den_edit)
        return w

    def _build_expr_widget(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self._expr_edit = QLineEdit("1/(s+1)")
        self._expr_edit.setPlaceholderText("(s+2)/(s^2+2*s+1)")
        f.addRow("G(s) =", self._expr_edit)
        return w

    def _build_zpk_widget(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self._zpk_z = QLineEdit("")
        self._zpk_p = QLineEdit("-1")
        self._zpk_k = QLineEdit("1")
        self._zpk_z.setPlaceholderText("-1, -2  (leave empty for none)")
        self._zpk_p.setPlaceholderText("-1, -2+j, -2-j")
        f.addRow("Zeros:", self._zpk_z)
        f.addRow("Poles:", self._zpk_p)
        f.addRow("Gain:",  self._zpk_k)
        return w

    def _build_first_order_widget(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self._fo_K   = self._make_spin(1.0, -1e6, 1e6)
        self._fo_tau = self._make_spin(1.0, 1e-6, 1e6)
        f.addRow("K:",  self._fo_K)
        f.addRow("τ:",  self._fo_tau)
        f.addRow(QLabel("  G(s) = K / (τs + 1)"))
        return w

    def _build_second_order_widget(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self._so_K    = self._make_spin(1.0,   -1e6, 1e6)
        self._so_zeta = self._make_spin(0.5,   0.0,  10.0, step=0.05)
        self._so_wn   = self._make_spin(1.0,   1e-6, 1e6)
        f.addRow("K:",  self._so_K)
        f.addRow("ζ:",  self._so_zeta)
        f.addRow("ωn:", self._so_wn)
        f.addRow(QLabel("  G(s) = K·ωn² / (s²+2ζωn·s+ωn²)"))
        return w

    def _build_delay_widget(self) -> QWidget:
        """
        Padé approximation of a pure transport delay ``e^{−Ts}``.

        Delay is what makes the Ziegler–Nichols reaction-curve method
        applicable at all: with no dead time the tangent construction gives
        infinite gains. v1 had ``pure_delay_pade`` in the core but never
        exposed it, so that button could never succeed.
        """
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self._delay_T     = self._make_spin(0.5, 0.0, 1e4, step=0.1)
        self._delay_order = self._make_spin(2, 1, 10, step=1)
        self._delay_order.setDecimals(0)
        f.addRow("T (delay, s):", self._delay_T)
        f.addRow("Padé order:",   self._delay_order)
        f.addRow(QLabel("  G(s) ≈ e^(−Ts)   (all-pass, non-min-phase)"))
        return w

    def _build_fopdt_widget(self) -> QWidget:
        """First order plus dead time — the reaction-curve model of ch.8."""
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        self._fopdt_K     = self._make_spin(1.0, -1e6, 1e6)
        self._fopdt_tau   = self._make_spin(1.0, 1e-6, 1e6)
        self._fopdt_L     = self._make_spin(0.5, 0.0, 1e4, step=0.1)
        self._fopdt_order = self._make_spin(3, 1, 10, step=1)
        self._fopdt_order.setDecimals(0)
        f.addRow("K:",          self._fopdt_K)
        f.addRow("τ (lag, s):", self._fopdt_tau)
        f.addRow("L (delay, s):", self._fopdt_L)
        f.addRow("Padé order:", self._fopdt_order)
        f.addRow(QLabel("  G(s) = K·e^(−Ls)/(τs+1)"))
        return w

    def _mode_widgets(self) -> list[QWidget]:
        """Per-mode input panels, in the same order as the mode combo."""
        return [self._coeff_widget, self._expr_widget, self._zpk_widget,
                self._fo_widget, self._so_widget,
                self._delay_widget, self._fopdt_widget]

    @staticmethod
    def _make_spin(value: float, lo: float, hi: float,
                   step: float = 0.1) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setDecimals(4)
        sp.setValue(value)
        return sp

    # ── Mode switch ───────────────────────────────────────────

    def _on_mode_change(self, idx: int) -> None:
        for i, w in enumerate(self._mode_widgets()):
            w.setVisible(i == idx)

    # ── Parsing ───────────────────────────────────────────────

    def _parse(self) -> ctl.TransferFunction:
        mode = self._mode_combo.currentIndex()
        if mode == 0:   # Coefficients
            num = [float(x) for x in self._num_edit.text().split(",")]
            den = [float(x) for x in self._den_edit.text().split(",")]
            return from_coefficients(num, den)
        elif mode == 1: # Expression
            return from_expression(self._expr_edit.text().strip())
        elif mode == 2: # ZPK
            def parse_cplx(s: str) -> list[complex]:
                if not s.strip():
                    return []
                results = []
                for tok in s.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    try:
                        results.append(complex(tok.replace("j", "j")))
                    except ValueError:
                        results.append(complex(float(tok)))
                return results
            z = parse_cplx(self._zpk_z.text())
            p = parse_cplx(self._zpk_p.text())
            k = float(self._zpk_k.text())
            return from_zpk(z, p, k)
        elif mode == 3: # 1st-order
            return first_order(K=self._fo_K.value(),
                               tau=self._fo_tau.value())
        elif mode == 4: # 2nd-order
            return second_order(K=self._so_K.value(),
                                zeta=self._so_zeta.value(),
                                wn=self._so_wn.value())
        elif mode == 5: # Pure delay
            return pure_delay_pade(self._delay_T.value(),
                                   int(self._delay_order.value()))
        elif mode == 6: # FOPDT
            lag = first_order(K=self._fopdt_K.value(),
                              tau=self._fopdt_tau.value())
            delay = pure_delay_pade(self._fopdt_L.value(),
                                    int(self._fopdt_order.value()))
            return lag * delay
        raise ValueError(f"unknown editor mode {mode}")

    # ── Apply / Reset ─────────────────────────────────────────

    def _apply(self) -> None:
        if self._block_id is None:
            return
        try:
            tf = self._parse()
        except Exception as exc:
            self._info_label.setText(f"❌ Parse error: {exc}")
            return
        self._current_tf = tf
        self._refresh_info()
        self.tf_changed.emit(self._block_id, tf)

    def _reset(self) -> None:
        if self._current_tf is not None:
            self._populate_from_tf(self._current_tf)

    # ── Helpers ───────────────────────────────────────────────

    def _populate_from_tf(self, tf: ctl.TransferFunction) -> None:
        """Fill the coefficient editor from an existing TF."""
        num = tf.num[0][0]
        den = tf.den[0][0]
        self._num_edit.setText(", ".join(f"{c:.6g}" for c in num))
        self._den_edit.setText(", ".join(f"{c:.6g}" for c in den))
        # Also switch to coeff mode
        self._mode_combo.setCurrentIndex(0)
        self._on_mode_change(0)

    def _refresh_info(self) -> None:
        """Update the factored form and stability badge."""
        try:
            info = analyse(self._current_tf)
            fstr = factored_str(self._current_tf)
            stab = "✓ Stable" if info.stable else "✗ Unstable"
            mp   = "Min-phase" if info.minimum_phase else "Non-min-phase"
            dc   = f"{info.dc_gain:.4g}" if not np.isinf(info.dc_gain) else "∞"
            text = (f"G(s) = {fstr}\n"
                    f"{stab} | {mp} | DC = {dc} | Type {info.system_type}")
            self._info_label.setText(text)
        except Exception as exc:
            self._info_label.setText(f"(error: {exc})")
