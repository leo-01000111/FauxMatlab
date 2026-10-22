"""
A page as the HTML a ``QTextBrowser`` shows.

Qt's rich text is a small subset of HTML 4 and CSS, so the page is built from
what it does draw well: headings, paragraphs, lists, ``<pre>`` inside a
one-cell table for a code block's background, and links. Prose goes through
the live script's own Markdown (:mod:`evans.console.live.markup`), so the
two dialects stay one.

Links speak three schemes, all handled by the window rather than followed:
``help:<topic>`` for another page, ``run:<n>`` for the n-th example on the
page, ``copy:<n>`` to copy it. Anything else (``https:``) opens outside.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from ..console.live import markup
from . import Page


@dataclass(frozen=True)
class Colours:
    """What the page is painted with — the window passes the theme's."""
    ink:       str = "#1d1d1b"
    ink_muted: str = "#5f5e5a"
    rule:      str = "#c9c7c0"
    code_bg:   str = "#e8e6e0"
    link:      str = "#1f5fa8"


def to_html(page: Page, colours: Colours = Colours(), *,
            mono: str = "monospace", mono_pt: float | None = None,
            run: bool = True) -> str:
    """
    The page, with Run and Copy links on its examples when ``run``.
    ``mono_pt`` sizes code: a monospace face runs wider than the prose.
    """
    c = colours
    size = f"font-size:{mono_pt:g}pt; " if mono_pt else ""
    out = [f'<h1 style="margin-bottom:2px">{html.escape(page.title)}</h1>',
           f'<p style="color:{c.ink_muted}">{_prose(page.summary)}</p>']
    example = 0
    for heading, blocks in page.sections:
        out.append(f'<h3 style="margin-top:18px">{html.escape(heading)}</h3>')
        for kind, text in blocks:
            if kind == "text":
                out.append(_text(text))
                continue
            if kind == "example":
                actions = [f'<a href="copy:{example}">Copy</a>']
                if run:
                    actions.insert(0, f'<a href="run:{example}">'
                                      f'&#9654;&nbsp;Run</a>')
                out.append(f'<p align="right" style="margin:6px 0 0 0">'
                           f'{"&nbsp;&nbsp;&nbsp;".join(actions)}</p>')
                example += 1
            out.append(
                f'<table width="100%" cellpadding="8" cellspacing="0" '
                f'bgcolor="{c.code_bg}" style="margin:2px 0 8px 0">'
                f'<tr><td><pre style="font-family:\'{mono}\'; {size}'
                f'margin:0">{html.escape(text)}</pre></td></tr></table>')
    style = (f"body {{ color:{c.ink}; }} a {{ color:{c.link}; "
             f"text-decoration:none; }} code {{ font-family:'{mono}'; {size}}}")
    return f"<html><head><style>{style}</style></head><body>" \
           f"{''.join(out)}</body></html>"


def _text(text: str) -> str:
    """A text block: a paragraph or a list, through the live dialect."""
    return markup.to_html(_link_topics(text))


def _prose(text: str) -> str:
    return markup.inline_html(_link_topics(text))


def _link_topics(text: str) -> str:
    """``[x](step)`` → ``[x](help:step)``; a URL with a scheme stays."""
    return re.sub(r"\]\(([^):]+)\)", r"](help:\1)", text)
