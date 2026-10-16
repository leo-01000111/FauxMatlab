"""
Code sections: ``%%`` splits a script into cells that run on their own.

A section starts at its ``%%`` line and runs to the line before the next one;
lines above the first ``%%`` are a section too. In Python text ``# %%`` does
the same, the convention other editors use.
"""

from __future__ import annotations

from dataclasses import dataclass

from .highlighter import is_section_header


@dataclass(frozen=True)
class Section:
    """Lines ``start`` to ``end`` (1-based, inclusive) and the header's title."""
    start: int
    end:   int
    title: str = ""

    def __contains__(self, line: int) -> bool:
        return self.start <= line <= self.end


def split_sections(text: str) -> list[Section]:
    """The sections of ``text``, in order; one section if it has no ``%%``."""
    lines = text.split("\n")
    sections: list[Section] = []
    start, title = 1, ""
    in_block = False
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if in_block:
            in_block = stripped != "%}"
            continue
        if stripped == "%{":
            in_block = True
            continue
        if is_section_header(line) and number > 1:
            sections.append(Section(start, number - 1, title))
            start, title = number, _title(line)
        elif is_section_header(line):
            title = _title(line)
    sections.append(Section(start, len(lines), title))
    return sections


def _title(line: str) -> str:
    return line.strip().lstrip("#").strip().removeprefix("%%").strip()


def section_at(sections: list[Section], line: int) -> Section:
    """The section holding ``line`` (the last one past the end)."""
    for section in sections:
        if line in section:
            return section
    return sections[-1]


def section_source(text: str, section: Section) -> str:
    """
    The section's source, padded with blank lines to its real position, so
    errors, interrupts and breakpoints name the line the editor shows.
    """
    lines = text.split("\n")
    return "\n" * (section.start - 1) + "\n".join(
        lines[section.start - 1:section.end])
