"""
The modern-control (DYBAC) half of the UI.

Grouped as sub-tabs under one top-level tab rather than five of their own:
the window already carries seven, and a tab bar you have to read carefully is
worse than one level of nesting.
"""

from .modern_tab import ModernTab

__all__ = ["ModernTab"]
