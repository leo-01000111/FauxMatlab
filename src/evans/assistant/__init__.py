"""
The coding assistant: a free model on OpenRouter, asked about the code at hand.

No Qt in here, so all of it is tested without a window; the side panel is
:mod:`evans.ui.assistant`. Three parts:

* :mod:`.client` — the HTTP side: the free-model list, a streamed reply, the
  day's remaining requests. The key comes from ``OPENROUTER_API_KEY`` and
  nowhere else, and is never written down.
* :mod:`.context` — what one request may carry: the selection (or the ``%%``
  section at the cursor), the workspace by name, type and size but never by
  value, and the last error. Never the whole script.
* :mod:`.protocol` — the instructions the model gets, and the reply read back
  as text, proposed edits and proposed commands.
"""
