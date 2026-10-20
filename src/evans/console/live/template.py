"""
The report template: how a live script is laid out as LaTeX.

One :class:`ReportTemplate` drives both the live PDF preview and *Export
report*, so the two always agree. It comes from one of three levels, the
first that is set winning:

1. the document's own override, saved with the live script;
2. the user's template, kept in the app's settings;
3. :data:`DEFAULT`, which writes what *Export report* always wrote.

The preamble is generated from the fields (document class, paper, margins,
font, header and footer). ``extra_preamble`` is appended to it, and an
advanced user can replace it wholesale with ``raw_preamble``.

Qt-free: the settings store is reached through the UI, which hands the
stored dict to :meth:`ReportTemplate.from_dict`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace

#: Font choices: name → the preamble lines that select it. Every one is a
#: package MiKTeX and TeX Live ship (MiKTeX fetches it on first use).
FONTS: dict[str, str] = {
    "Computer Modern": "",
    "Latin Modern": "\\usepackage{lmodern}",
    "Times": "\\usepackage{mathptmx}",
    "Palatino": "\\usepackage{mathpazo}",
    "Charter": "\\usepackage{charter}",
    "Helvetica": ("\\usepackage[scaled]{helvet}\n"
                  "\\renewcommand{\\familydefault}{\\sfdefault}"),
}

DOCUMENT_CLASSES = ("article", "report")
FONT_SIZES = ("10pt", "11pt", "12pt")
PAPERS = ("a4paper", "letterpaper", "a5paper")
#: Float placement: H keeps a figure under the code that drew it, as in the
#: live script; the others let LaTeX move it.
PLACEMENTS = ("H", "htbp", "t", "b")

LISTINGS_STYLE = r"""\lstset{language=Matlab, basicstyle=\ttfamily\small, breaklines=true,
  frame=single, rulecolor=\color{black!40}, columns=fullflexible,
  keywordstyle=\color{blue!60!black}, commentstyle=\color{green!40!black},
  stringstyle=\color{red!60!black}, upquote=true}"""


@dataclass
class ReportTemplate:
    # ── page ────────────────────────────────────────────────────
    document_class: str = "article"
    font_size:      str = "11pt"
    paper:          str = "a4paper"
    margin:         str = "2.5cm"
    #: Latin Modern is Computer Modern drawn as outlines: with T1 encoding,
    #: plain Computer Modern makes pdflatex fall back to bitmap fonts, which
    #: look blurred in any PDF viewer.
    font:           str = "Latin Modern"
    # ── title ───────────────────────────────────────────────────
    title_page:     bool = False
    author:         str = ""
    date:           str = ""
    contents:       bool = False         # a table of contents after the title
    # ── header and footer (raw LaTeX; empty everywhere = plain page numbers)
    header_left:    str = ""
    header_center:  str = ""
    header_right:   str = ""
    footer_left:    str = ""
    footer_center:  str = ""
    footer_right:   str = ""
    # ── content ─────────────────────────────────────────────────
    number_sections: bool = False
    show_code:      bool = True
    show_output:    bool = True
    #: Text cells are LaTeX (with the Markdown marks still understood);
    #: off, they are the Markdown dialect with every special character
    #: escaped, as before.
    latex_text:     bool = True
    figure_width:   str = "0.8\\linewidth"
    figure_placement: str = "H"
    # ── preamble ────────────────────────────────────────────────
    extra_preamble: str = ""
    #: When not blank, the whole preamble, as written — the fields above
    #: that shape the preamble are then ignored.
    raw_preamble:   str = ""

    # ── storage ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Only what differs from the default: small, and future-proof."""
        default = asdict(DEFAULT)
        return {k: v for k, v in asdict(self).items() if default[k] != v}

    @classmethod
    def from_dict(cls, data) -> ReportTemplate:
        """Unknown keys and wrongly typed values are ignored, not fatal."""
        template = cls()
        if not isinstance(data, dict):
            return template
        for f in fields(cls):
            if f.name not in data:
                continue
            value, current = data[f.name], getattr(template, f.name)
            if isinstance(current, bool):
                if isinstance(value, str):
                    value = value.lower() in ("true", "1")
                setattr(template, f.name, bool(value))
            elif isinstance(value, str):
                setattr(template, f.name, value)
        return template

    def copy(self, **changes) -> ReportTemplate:
        return replace(self, **changes)

    # ── LaTeX ───────────────────────────────────────────────────

    @property
    def has_header_footer(self) -> bool:
        return any(getattr(self, f"{where}_{side}").strip()
                   for where in ("header", "footer")
                   for side in ("left", "center", "right"))

    def class_options(self) -> str:
        options = [self.font_size, self.paper]
        if self.title_page:
            options.append("titlepage")
        return ",".join(o for o in options if o)

    def generated_preamble(self) -> str:
        """The preamble the fields describe (``raw_preamble`` aside)."""
        lines = [
            f"\\documentclass[{self.class_options()}]"
            f"{{{self.document_class or 'article'}}}",
            "\\usepackage{iftex}",
            "\\ifPDFTeX",
            "  \\usepackage[utf8]{inputenc}",
            "  \\usepackage[T1]{fontenc}",
            "\\fi",
        ]
        font = FONTS.get(self.font, "")
        if font:
            lines.append(font)
        lines += [
            f"\\usepackage[margin={self.margin or '2.5cm'}]{{geometry}}",
            "\\usepackage{amsmath,amssymb}",
            "\\usepackage{graphicx}",
            "\\usepackage{float}",
            "\\usepackage{xcolor}",
            "\\usepackage{listings}",
        ]
        if self.has_header_footer:
            lines += ["\\usepackage{fancyhdr}", "\\pagestyle{fancy}",
                      "\\fancyhf{}"]
            for where, command in (("header", "fancyhead"),
                                   ("footer", "fancyfoot")):
                for side, letter in (("left", "L"), ("center", "C"),
                                     ("right", "R")):
                    text = getattr(self, f"{where}_{side}").strip()
                    if text:
                        lines.append(f"\\{command}[{letter}]{{{text}}}")
            if not any(getattr(self, f"header_{s}").strip()
                       for s in ("left", "center", "right")):
                lines.append("\\renewcommand{\\headrulewidth}{0pt}")
        if self.extra_preamble.strip():
            lines.append(self.extra_preamble.strip("\n"))
        # hyperref last, as its documentation asks.
        lines += ["\\usepackage[hidelinks]{hyperref}", LISTINGS_STYLE,
                  "\\setlength{\\parindent}{0pt}",
                  "\\setlength{\\parskip}{0.6em}"]
        return "\n".join(lines) + "\n"

    def preamble(self) -> str:
        if self.raw_preamble.strip():
            return self.raw_preamble.strip("\n") + "\n"
        return self.generated_preamble()

    def section_command(self, level: int) -> str:
        """``\\section`` for level 1 … ``\\subsubsection`` for 3, starred
        unless sections are numbered."""
        name = {1: "section", 2: "subsection", 3: "subsubsection"}[
            max(1, min(level, 3))]
        return f"\\{name}" + ("" if self.number_sections else "*")


DEFAULT = ReportTemplate()


def resolve_template(document_template: ReportTemplate | None,
                     user_template: ReportTemplate | None) -> ReportTemplate:
    """The template in force: the document's, else the user's, else the default."""
    return document_template or user_template or DEFAULT
