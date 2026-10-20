"""
The program was FauxMatlab until 0.9. Files and settings from then still work.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtCore import QSettings

from evans.sim.model import FORMAT, LEGACY_FORMATS, SimModel
from evans.ui import persist


def test_a_model_saved_before_the_rename_still_opens(tmp_path):
    model = SimModel("old")
    model.add("Step", "r")
    model.add("Gain", "k", gain=2.0)
    model.connect("r", "k")
    data = model.to_dict()
    assert data["format"] == FORMAT == "evans-model"
    data["format"] = LEGACY_FORMATS[0]
    path = tmp_path / "old.fmdl"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = SimModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert set(loaded.blocks) == {"r", "k"}


def test_a_file_of_another_format_is_still_refused():
    with pytest.raises(Exception, match="not an Evans model file"):
        SimModel.from_dict({"format": "something-else", "blocks": []})


def test_settings_are_carried_over_once_and_never_overwritten():
    stores = {("EvansTestOld", "Old"): ("EvansTestNew", "New")}
    old, new = QSettings("EvansTestOld", "Old"), QSettings("EvansTestNew", "New")
    old.clear(); new.clear()
    try:
        old.setValue("appearance/theme", "night")
        old.sync()
        assert persist.migrate_legacy_settings(stores) == 1
        assert QSettings("EvansTestNew", "New").value("appearance/theme") == "night"
        # Already migrated: a later change under the new name is kept.
        new.setValue("appearance/theme", "day")
        new.sync()
        assert persist.migrate_legacy_settings(stores) == 0
        assert QSettings("EvansTestNew", "New").value("appearance/theme") == "day"
    finally:
        old.clear(); new.clear()
