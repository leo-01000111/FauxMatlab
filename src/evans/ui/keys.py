"""
Shortcuts as the user's keyboard names them.

Qt already maps ``Ctrl`` in a shortcut to ⌘ on macOS, so the keys work
there unchanged. The words do not: a tooltip that says "Ctrl+Enter" sends a
Mac user to the Control key, which does something else. :func:`label`
rewrites every shortcut in a piece of text into the Mac's own notation —
"⇧⌘↩" — and leaves it alone everywhere else.

No Qt in here, so the rewriting is tested on any platform.
"""

from __future__ import annotations

import re
import sys

#: ``Ctrl``, then any of Shift and Alt, then one key.
_SHORTCUT = re.compile(
    r"Ctrl((?:\+(?:Shift|Alt))*)\+(Enter|Return|Space|[A-Z0-9`\\])")

#: The Mac's modifier order is fixed: ⌃ ⌥ ⇧ ⌘, then the key.
_MAC_MODIFIERS = (("Alt", "⌥"), ("Shift", "⇧"))
_MAC_KEYS = {"Enter": "↩", "Return": "↩", "Space": "Space"}


def is_mac(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "darwin"


def label(text: str, platform: str | None = None) -> str:
    """Every ``Ctrl+…`` in ``text``, in this platform's notation."""
    if not is_mac(platform):
        return text

    def mac(match: re.Match) -> str:
        held = match.group(1)
        mods = "".join(glyph for name, glyph in _MAC_MODIFIERS
                       if f"+{name}" in held)
        key = match.group(2)
        return f"{mods}⌘{_MAC_KEYS.get(key, key)}"

    return _SHORTCUT.sub(mac, text)
