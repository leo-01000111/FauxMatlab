"""MinPhaseView: builds, draws, and reports both cases without failing."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

import control as ctl
from PySide6.QtWidgets import QApplication

from fakematlab.ui.minphase_view import MinPhaseView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_non_minimum_phase(app):
    v = MinPhaseView()
    v.resize(450, 350)
    v.show_system(ctl.tf([-1, 1], [1, 3, 2]), "G")
    assert not v._error_banner.has_error, v._error_banner.message
    assert not v.split.is_minimum_phase
    assert "NON-minimum" in v._status.text()
    assert "RHP zeros" in v._text.text() and "G_allpass" in v._text.text()
    assert len(v._mag.getPlotItem().listDataItems()) == 2
    assert len(v._phase.getPlotItem().listDataItems()) == 3


def test_already_minimum_phase_still_plots(app):
    v = MinPhaseView()
    v.show_system(ctl.tf([1, 2], [1, 3, 2]), "P")
    assert not v._error_banner.has_error
    assert "already minimum phase" in v._status.text()
    assert len(v._phase.getPlotItem().listDataItems()) == 3


def test_mimo_is_reported_not_swallowed(app):
    v = MinPhaseView()
    v.show_system(ctl.tf([[[1], [1]]], [[[1, 1], [1, 2]]]), "M")
    assert v._error_banner.has_error and "SISO" in v._error_banner.message
