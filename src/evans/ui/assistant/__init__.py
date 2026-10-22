"""
The assistant side panel: ask a free OpenRouter model about the code at hand.

The model, context and reply format are :mod:`evans.assistant`; this is the
dockable panel and the adapter that lets it read from, and apply edits to,
a text editor.
"""

from .panel import AssistantDock, AssistantPanel, EditorSource, Source

__all__ = ["AssistantDock", "AssistantPanel", "EditorSource", "Source"]
