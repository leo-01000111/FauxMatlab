"""
LaTeX completion for live-script text cells — no widgets here.

After a backslash: the commands a report needs (``\\frac``, ``\\alpha``,
``\\sum``, ``\\section`` …), inserted with their braces and the cursor in the
first one. After ``\\begin{``: an environment, closed with its ``\\end{…}``.
After ``\\end{``: the environment still open. Inside ``\\ref{`` (and
``\\eqref{``, ``\\autoref{`` …): the labels the document defines.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from .completion import Completion, Request

# name | arguments as inserted ("{}" each) | description
_COMMANDS = r"""
frac|{}{}|Fraction \frac{num}{den}
dfrac|{}{}|Display-size fraction
tfrac|{}{}|Text-size fraction
sqrt|{}|Square root \sqrt[n]{x}
sum||Summation ∑
prod||Product ∏
int||Integral ∫
iint||Double integral
oint||Contour integral
lim||Limit
infty||Infinity ∞
partial||Partial derivative ∂
nabla||Nabla ∇
cdot||Centred dot ·
times||Times ×
div||Division ÷
pm||Plus-minus ±
mp||Minus-plus ∓
le||Less than or equal ≤
leq||Less than or equal ≤
ge||Greater than or equal ≥
geq||Greater than or equal ≥
ne||Not equal ≠
neq||Not equal ≠
approx||Approximately ≈
equiv||Equivalent ≡
sim||Similar ∼
propto||Proportional to ∝
to||Right arrow →
rightarrow||Right arrow →
leftarrow||Left arrow ←
Rightarrow||Implies ⇒
Leftrightarrow||If and only if ⇔
mapsto||Maps to ↦
in||Element of ∈
notin||Not an element of ∉
subset||Subset ⊂
cup||Union ∪
cap||Intersection ∩
forall||For all ∀
exists||There exists ∃
ldots||Low dots …
cdots||Centred dots ⋯
vdots||Vertical dots
ddots||Diagonal dots
alpha||Greek α
beta||Greek β
gamma||Greek γ
Gamma||Greek Γ
delta||Greek δ
Delta||Greek Δ
epsilon||Greek ϵ
varepsilon||Greek ε
zeta||Greek ζ
eta||Greek η
theta||Greek θ
Theta||Greek Θ
kappa||Greek κ
lambda||Greek λ
Lambda||Greek Λ
mu||Greek μ
nu||Greek ν
xi||Greek ξ
pi||Greek π
Pi||Greek Π
rho||Greek ρ
sigma||Greek σ
Sigma||Greek Σ
tau||Greek τ
phi||Greek ϕ
varphi||Greek φ
Phi||Greek Φ
chi||Greek χ
psi||Greek ψ
Psi||Greek Ψ
omega||Greek ω
Omega||Greek Ω
sin||Sine
cos||Cosine
tan||Tangent
arctan||Arctangent
exp||Exponential
log||Logarithm
ln||Natural logarithm
max||Maximum
min||Minimum
det||Determinant
angle||Angle ∠
left||Left delimiter, sized: \left( … \right)
right||Right delimiter
big||Bigger delimiter
quad||Wide space
qquad||Wider space
hat|{}|Hat accent x̂
bar|{}|Bar accent x̄
dot|{}|Dot accent ẋ
ddot|{}|Double dot accent ẍ
tilde|{}|Tilde accent x̃
vec|{}|Vector arrow
overline|{}|Line over
underline|{}|Line under
mathrm|{}|Upright text in math
mathbf|{}|Bold in math
mathit|{}|Italic in math
mathcal|{}|Calligraphic letter
mathbb|{}|Blackboard bold (ℝ, ℂ)
text|{}|Text inside math
operatorname|{}|An operator's name, upright
textbf|{}|Bold text
textit|{}|Italic text
emph|{}|Emphasised text
texttt|{}|Typewriter text
underbrace|{}|Brace under
overbrace|{}|Brace over
section|{}|Numbered section heading
subsection|{}|Numbered subsection heading
subsubsection|{}|Numbered sub-subsection heading
paragraph|{}|Run-in paragraph heading
section*|{}|Unnumbered section heading
subsection*|{}|Unnumbered subsection heading
label|{}|A label to \ref
ref|{}|Reference a label's number
eqref|{}|Reference an equation's number, in parentheses
autoref|{}|Reference with its name ("Figure 2")
pageref|{}|Page a label is on
cite|{}|Cite a reference
footnote|{}|Footnote
url|{}|A URL
href|{}{}|A link with text
begin|{}|Start an environment
end|{}|End an environment
item||A list item
caption|{}|Caption of a figure or table
includegraphics|{}|Include an image file
centering||Centre the contents
newline||Line break
newpage||Page break
noindent||No paragraph indent
hline||Horizontal rule in a table
vspace|{}|Vertical space
hspace|{}|Horizontal space
"""

# environment | description
_ENVIRONMENTS = """
equation|Numbered display equation
equation*|Unnumbered display equation
align|Aligned equations, numbered (& aligns, \\\\ breaks)
align*|Aligned equations, unnumbered
gather|Centred equations
cases|Piecewise cases
matrix|Matrix, no delimiters
pmatrix|Matrix in parentheses
bmatrix|Matrix in brackets
vmatrix|Determinant bars
itemize|Bulleted list
enumerate|Numbered list
description|Description list
figure|Floating figure
table|Floating table
tabular|Table body
center|Centred block
quote|Quotation
verbatim|Text as typed
array|Array in math
"""

#: Commands whose argument is a label.
REF_COMMANDS = ("ref", "eqref", "autoref", "cref", "Cref", "pageref",
                "nameref")

_CMD = re.compile(r"(?<!\\)\\([A-Za-z]*\*?)$")     # not after \\ (a break)
_ENV = re.compile(r"\\(begin|end)\{([A-Za-z*]*)$")
_REF = re.compile(r"\\(" + "|".join(REF_COMMANDS) + r")\{([^{}\s]*)$")
_BEGIN_END = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")
_LABEL = re.compile(r"\\label\{([^{}\s]+)\}")


def _signature(name: str, args: str, description: str) -> str:
    shown = re.search(r"\\" + re.escape(name) + r"(\[[^\]]*\])?(\{[^}]*\})+",
                      description)
    if shown:
        return shown.group(0)
    return "\\" + name + args


def _command_items() -> list[Completion]:
    out = []
    for line in _COMMANDS.strip().splitlines():
        name, args, description = line.split("|", 2)
        text = "\\" + name
        out.append(Completion(
            text, "latex", signature=_signature(name, args, description),
            detail=description, insert=text + args,
            cursor=len(text) + 1 if args else None))
    return out


def _environment_names() -> list[tuple[str, str]]:
    return [tuple(line.split("|", 1))
            for line in _ENVIRONMENTS.strip().splitlines()]


COMMANDS: list[Completion] = _command_items()


def open_environments(text: str) -> list[str]:
    """Environments begun in ``text`` and not yet ended, innermost last."""
    stack: list[str] = []
    for kind, name in _BEGIN_END.findall(text):
        if kind == "begin":
            stack.append(name)
        elif name in stack:
            del stack[len(stack) - 1 - stack[::-1].index(name)]
    return stack


def labels_in(texts: Iterable[str]) -> list[str]:
    """``\\label{…}`` names defined in ``texts``."""
    out = []
    for text in texts:
        out.extend(_LABEL.findall(text))
    return out


def latex_request(before: str,
                  labels: Callable[[], Iterable[str]] | None = None
                  ) -> Request | None:
    """What to complete at the end of ``before`` in LaTeX markup."""
    m = _REF.search(before)
    if m:
        def items(_wait, labels=labels):
            seen, out = set(), []
            for label in (labels() if labels else []):
                if label and label not in seen:
                    seen.add(label)
                    out.append(Completion(label, "label",
                                          detail=f"\\{m.group(1)}{{{label}}}",
                                          insert=label + "}"))
            return out
        return Request(m.group(2), ("ref",), items, auto_min=0)
    m = _ENV.search(before)
    if m:
        if m.group(1) == "end":
            still_open = open_environments(before)[::-1]
            return Request(m.group(2), ("end", tuple(still_open)),
                           lambda _wait: [
                               Completion(n, "environment",
                                          detail="close the open "
                                                 "environment",
                                          insert=n + "}")
                               for n in still_open], auto_min=0)

        def environments(_wait):
            out = []
            for name, description in _environment_names():
                body = f"{name}}}\n\n\\end{{{name}}}"
                out.append(Completion(name, "environment",
                                      signature=f"\\begin{{{name}}} … "
                                                f"\\end{{{name}}}",
                                      detail=description, insert=body,
                                      cursor=len(name) + 2))
            return out
        return Request(m.group(2), ("begin",), environments, auto_min=0)
    m = _CMD.search(before)
    if m:
        return Request("\\" + m.group(1), ("latex",),
                       lambda _wait: list(COMMANDS), auto_min=1)
    return None
