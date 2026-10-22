"""
The help pages: hand-written, one Markdown file per function.

The website builds its command reference from docstrings; these pages are
written for the app alone, and the help window (:mod:`evans.ui.help`) shows
them. This module knows nothing about Qt, so the tests can read, check and
run every page headless.

A page lives in ``pages/<name>.md``, and ``<name>`` is its **topic**: the
function's own name, as typed (``step``, ``zeros``). That is what
``open_help(topic)`` receives, from F1 or from a Ctrl+click on a word in the
editor. A function page has exactly these parts, in this order::

    # step

    One sentence: what it does.

    ## Syntax

        step(sys)
        [y, t] = step(sys)

    ## Description

    Prose, lists, `code`, [links](impulse).

    ## Example

    ```matlab
    G = tf(1, [1 2 1]);
    step(G)
    ```

    ## See also

    [impulse](impulse) · [stepinfo](stepinfo)

A guide (:data:`GUIDES`) has the title and the sentence, then any ``##``
sections it likes. Anywhere, a fenced ``matlab`` block is an example: the
window gives it a Run button and the tests run it. A link whose target has
no ``:`` is another page's topic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..console import api

PAGES = Path(__file__).parent / "pages"

#: The landing page: what F1 opens with nothing under the cursor.
HOME = "index"

#: Pages that explain rather than document one function.
GUIDES: tuple[str, ...] = ("index", "s", "python")

#: The function pages, grouped as the index tree shows them. The control
#: groups are the console's own (``api._GROUPS``), so a command added there
#: without a page fails a test; after them come the control functions only
#: the MATLAB runtime has, and the MATLAB basics scripts lean on.
GROUPS: dict[str, tuple[str, ...]] = {
    **api._GROUPS,
    "Model data": ("tfdata", "zpkdata", "ssdata", "evalfr", "freqresp",
                   "isstable"),
    "Plot options": ("bodeoptions", "nyquistoptions", "timeoptions",
                     "pzoptions"),
    "Arrays": ("zeros", "ones", "eye", "rand", "linspace", "logspace",
               "size", "length", "numel", "reshape", "repmat"),
    "Maths": ("abs", "sqrt", "exp", "sum", "mean", "max", "min", "sort",
              "find", "cumsum", "diff", "roots", "poly", "polyval", "conv",
              "inv", "det", "eig"),
    "Plotting": ("plot", "figure", "subplot", "hold", "grid", "title",
                 "xlabel", "ylabel", "legend", "axis", "xlim", "ylim",
                 "semilogx"),
    "Text": ("disp", "fprintf", "sprintf", "num2str"),
    "Session": ("clc", "clear", "tic", "toc"),
}

#: The parts of a function page, in order.
SECTIONS = ("Syntax", "Description", "Example", "See also")

_FENCE = re.compile(r"^```(\w*)\s*$")


class PageError(ValueError):
    """A page that does not follow the format."""


@dataclass
class Page:
    """One page, parsed."""
    topic:    str
    title:    str
    summary:  str
    #: ``(heading, blocks)`` in order. A block is ``("text", markup)``,
    #: ``("code", source)`` for an indented block, or ``("example", source)``
    #: for a fenced ``matlab`` block.
    sections: list[tuple[str, list[tuple[str, str]]]] = field(
        default_factory=list)

    @property
    def examples(self) -> list[str]:
        return [text for _, blocks in self.sections
                for kind, text in blocks if kind == "example"]

    @property
    def links(self) -> list[str]:
        """Every other page this one links to."""
        out = [self.summary] + [text for _, blocks in self.sections
                                for kind, text in blocks if kind == "text"]
        return [url for chunk in out
                for url in re.findall(r"\]\(([^)]+)\)", chunk)
                if ":" not in url]

    def section(self, heading: str) -> list[tuple[str, str]]:
        for name, blocks in self.sections:
            if name == heading:
                return blocks
        return []

    def text(self) -> str:
        """Everything a search should match, as plain text."""
        parts = [self.topic, self.title, self.summary]
        for heading, blocks in self.sections:
            parts.append(heading)
            parts += [text for _, text in blocks]
        return "\n".join(parts)


def topics() -> list[str]:
    """Every topic with a page, guides first, then in the index's order."""
    listed = [*GUIDES, *(n for names in GROUPS.values() for n in names)]
    on_disk = {p.stem for p in PAGES.glob("*.md")}
    return [n for n in listed if n in on_disk] + sorted(on_disk - set(listed))


def group_of(topic: str) -> str | None:
    for group, names in GROUPS.items():
        if topic in names:
            return group
    return "Guides" if topic in GUIDES else None


def path(topic: str) -> Path:
    return PAGES / f"{topic}.md"


def load(topic: str) -> Page | None:
    """The page for ``topic``, or None when there is none."""
    if not re.fullmatch(r"[A-Za-z_][\w-]*", topic or ""):
        return None
    file = path(topic)
    if not file.is_file():
        return None
    return parse(file.read_text(encoding="utf-8"), topic)


def parse(source: str, topic: str) -> Page:
    """Read a page. A function page must have :data:`SECTIONS`, in order."""
    lines = source.replace("\r\n", "\n").split("\n")
    i = _skip_blank(lines, 0)
    if i >= len(lines) or not lines[i].startswith("# "):
        raise PageError(f"{topic}: the first line must be '# title'")
    title = lines[i][2:].strip()
    i = _skip_blank(lines, i + 1)
    summary_lines = []
    while i < len(lines) and lines[i].strip() and \
            not lines[i].startswith("#"):
        summary_lines.append(lines[i].strip())
        i += 1
    if not summary_lines:
        raise PageError(f"{topic}: no one-sentence summary under the title")
    page = Page(topic, title, " ".join(summary_lines))

    while True:
        i = _skip_blank(lines, i)
        if i >= len(lines):
            break
        line = lines[i]
        if not line.startswith("## "):
            raise PageError(f"{topic}: line {i + 1}: expected a '## ' "
                            f"heading, found {line!r}")
        heading = line[3:].strip()
        i, blocks = _blocks(lines, i + 1, topic)
        page.sections.append((heading, blocks))

    if topic not in GUIDES:
        headings = tuple(h for h, _ in page.sections)
        if headings != SECTIONS:
            raise PageError(f"{topic}: sections are {headings}, "
                            f"expected {SECTIONS}")
        if not page.examples:
            raise PageError(f"{topic}: the Example section has no "
                            f"```matlab block")
    return page


def _skip_blank(lines: list[str], i: int) -> int:
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i


def _blocks(lines: list[str], i: int, topic: str):
    """The blocks of one section, up to the next ``##`` or the end."""
    blocks: list[tuple[str, str]] = []
    while True:
        i = _skip_blank(lines, i)
        if i >= len(lines) or lines[i].startswith("## "):
            return i, blocks
        line = lines[i]
        if line.startswith("#"):
            raise PageError(f"{topic}: line {i + 1}: only '#' and '##' "
                            f"headings are allowed")
        fence = _FENCE.match(line)
        if fence:
            if fence.group(1) not in ("matlab", ""):
                raise PageError(f"{topic}: line {i + 1}: a fenced block "
                                f"is 'matlab' or plain")
            end = i + 1
            while end < len(lines) and not lines[end].startswith("```"):
                end += 1
            if end >= len(lines):
                raise PageError(f"{topic}: line {i + 1}: unclosed ```")
            body = "\n".join(lines[i + 1:end]).strip("\n")
            blocks.append(("example" if fence.group(1) == "matlab"
                           else "code", body))
            i = end + 1
        elif line.startswith("    "):
            end = i
            while end < len(lines) and (lines[end].startswith("    ")
                                        or not lines[end].strip()):
                end += 1
            body = "\n".join(text[4:] for text in lines[i:end])
            blocks.append(("code", body.strip("\n")))
            i = end
        else:
            end = i
            while end < len(lines) and lines[end].strip() \
                    and not lines[end].startswith(("#", "```", "    ")):
                end += 1
            # A list keeps its line breaks; a paragraph's are joined later.
            blocks.append(("text", "\n".join(lines[i:end])))
            i = end
