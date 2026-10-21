"""Shortcut labels: the Mac's notation there, the text unchanged elsewhere."""

from __future__ import annotations

from evans.ui.keys import label


def test_other_platforms_keep_the_text_as_written():
    text = "Run the section (Ctrl+Enter); Ctrl+Shift+Enter moves on"
    assert label(text, "win32") == text
    assert label(text, "linux") == text


def test_a_mac_gets_command_and_its_symbols():
    assert label("Run this cell (Ctrl+Enter)", "darwin") == "Run this cell (⌘↩)"
    assert label("Undo (Ctrl+Z)", "darwin") == "Undo (⌘Z)"
    assert label("Ctrl+\\", "darwin") == "⌘\\"


def test_modifiers_come_in_the_macs_fixed_order():
    # ⌥ before ⇧ before ⌘, whatever order the text names them in.
    assert label("Ctrl+Shift+Enter", "darwin") == "⇧⌘↩"
    assert label("Ctrl+Alt+P", "darwin") == "⌥⌘P"
    assert label("Ctrl+Shift+Alt+P", "darwin") == "⌥⇧⌘P"


def test_keys_that_are_not_shortcuts_are_left_alone():
    # Shift+F5 has no Ctrl; "Ctrl" alone names the key, not a combination.
    text = "Stop (Ctrl+C here, or Shift+F5); hold Ctrl to snap"
    assert label(text, "darwin") == "Stop (⌘C here, or Shift+F5); hold Ctrl to snap"
