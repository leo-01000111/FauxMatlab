"""
What the completion popup offers, and in what order — no widgets here.

A *request* is what the text before the cursor asks for: the word being
typed (``prefix``, replaced on accepting), a ``key`` naming the pool it
completes from, and that pool (``items``). :func:`code_request` reads MATLAB
and Python; :mod:`.latex` reads LaTeX. The popup ranks the pool against the
prefix with :func:`rank` — exact-case prefix matches first, then
case-insensitive ones, then fuzzy (the letters in order, gaps allowed) — and
while the key stays the same and the prefix only grows, it narrows the list
it already has rather than asking again: every match of ``"ste"`` is also a
match of ``"st"``.

The pools that never change (the MATLAB library, the console's commands,
Python's builtins) are built once, on a background thread
(:func:`warm_up`). Until they are ready a request built while typing leaves
them out rather than wait; Tab and Ctrl+Space ask with ``wait=True``.
Descriptions and signatures that need ``inspect`` are filled in only for the
rows the popup draws (:meth:`Completion.resolved`).
"""

from __future__ import annotations

import builtins
import inspect
import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .highlighter import MATLAB_KEYWORDS, PYTHON_KEYWORDS, tokenize_line
from .signatures import SIGNATURES

#: Characters that make up the word being completed (dots join attributes).
WORD_CHARS = "_."

#: Parameters that are plumbing, not part of the call a user writes.
_HIDDEN_PARAMS = {"self", "nargout", "names", "plot"}


@dataclass(eq=False)
class Completion:
    """One entry in the popup."""

    #: The name shown, matched against the prefix, and (by default) inserted.
    text: str
    #: variable, function, command, keyword, constant, module, class,
    #: attribute, file, latex, environment or label.
    kind: str = ""
    #: The whole call, ``step(sys, t)``; empty for a plain name.
    signature: str = ""
    #: One line on what it is.
    detail: str = ""
    #: What accepting inserts in place of the prefix (default: ``text``).
    insert: str | None = None
    #: Where the cursor lands in ``insert`` (default: after it).
    cursor: int | None = None
    #: Fills in ``signature`` / ``detail`` the first time the row is drawn.
    resolve: Callable[[Completion], None] | None = field(default=None,
                                                         repr=False)

    def resolved(self) -> Completion:
        fill, self.resolve = self.resolve, None
        if fill is not None:
            try:
                fill(self)
            except Exception:                              # noqa: BLE001
                pass
        return self

    @property
    def insertion(self) -> str:
        return self.text if self.insert is None else self.insert


@dataclass
class Request:
    """What the text before the cursor asks to complete."""

    #: The typed text accepting replaces.
    prefix: str
    #: Same key, longer prefix: the popup narrows its list instead of asking.
    key: Any
    #: The unranked pool; ``wait`` lets slow pools finish building.
    items: Callable[[bool], list[Completion]]
    #: How long the prefix must be before typing opens the popup by itself.
    auto_min: int = 2


# ──────────────────────────────────────────────────────────────
#  Ranking
# ──────────────────────────────────────────────────────────────

def match(prefix: str, name: str) -> tuple[int, int] | None:
    """
    ``(tier, gaps)`` for ``name`` against ``prefix``, or ``None``.

    Tier 0: ``name`` starts with ``prefix``; 1: it does ignoring case;
    2: the prefix's letters appear in it in order. ``gaps`` orders the fuzzy
    tier: how many letters were skipped to find them.
    """
    if name.startswith(prefix):
        return 0, -1 if name == prefix else 0     # typed in full: first
    low, lname = prefix.lower(), name.lower()
    if lname.startswith(low):
        return 1, 0
    at, gaps = -1, 0
    for char in low:
        found = lname.find(char, at + 1)
        if found < 0:
            return None
        gaps += found - at - 1
        at = found
    return 2, gaps


def rank_scored(prefix: str, items: Iterable[Completion]
                ) -> list[tuple[int, Completion]]:
    """``(tier, item)`` for every match, best first; ties keep pool order."""
    scored = []
    for index, item in enumerate(items):
        m = match(prefix, item.text)
        if m is not None:
            scored.append((m[0], m[1], index, item))
    scored.sort(key=lambda s: (s[0], s[1], s[2]))
    return [(tier, item) for tier, _gaps, _index, item in scored]


def rank(prefix: str, items: Iterable[Completion]) -> list[Completion]:
    return [item for _tier, item in rank_scored(prefix, items)]


def common_prefix(items: list[str]) -> str:
    if not items:
        return ""
    first = items[0]
    for i, char in enumerate(first):
        if any(len(other) <= i or other[i] != char for other in items[1:]):
            return first[:i]
    return first


# ──────────────────────────────────────────────────────────────
#  Describing Python objects
# ──────────────────────────────────────────────────────────────

def first_line(doc: str | None) -> str:
    """A docstring's first sentence-line, without its markup."""
    for line in (doc or "").strip().splitlines():
        line = line.strip().replace("``", "")
        if line:
            return line if len(line) <= 120 else line[:117] + "…"
    return ""


def doc_summary(name: str, obj: Any) -> tuple[str, str]:
    """
    ``(signature, description)`` from a docstring. numpy's begin with the
    call itself (``sqrt(x, /, out=None, …)``): that is kept as the signature
    and the next line is the description.
    """
    lines = [ln.strip() for ln in (getattr(obj, "__doc__", None) or "")
             .strip().splitlines() if ln.strip()]
    head = lines[0] if lines else ""
    if "." in head.split("(", 1)[0]:          # numpy's methods: a.reshape(…)
        head = head.split(".", 1)[1]
    if head.startswith(name + "(") and head.endswith(")"):
        sig = head if len(head) <= 80 else head[:77] + "…)"
        return sig, first_line(lines[1] if len(lines) > 1 else "")
    return "", first_line(lines[0] if lines else "")


def python_signature(name: str, obj: Any) -> str:
    """``name(a, b=1, …)`` from ``obj``'s signature, plumbing left out."""
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        return ""
    parts = []
    for p in sig.parameters.values():
        if p.name in _HIDDEN_PARAMS or p.name.startswith("_"):
            continue
        if p.kind is p.VAR_POSITIONAL:
            parts.append(f"{p.name}…" if name.isidentifier() else p.name)
        elif p.kind is p.VAR_KEYWORD:
            continue
        elif p.default is p.empty:
            parts.append(p.name)
        else:
            parts.append(f"{p.name}={_short_repr(p.default)}")
    text = f"{name}({', '.join(parts)})"
    return text if len(text) <= 80 else text[:77] + "…)"


def _short_repr(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 12 else "…"


def describe_value(value: Any) -> str:
    """A variable's type, and its shape or value when that is short."""
    kind = type(value).__name__
    shape = getattr(value, "shape", None)
    if isinstance(shape, tuple) and shape:
        return f"{kind} {'×'.join(str(n) for n in shape)}"
    if isinstance(value, (bool, int, float, complex)):
        return f"{kind} = {value!r}"[:60]
    if isinstance(value, str):
        return f"str = {value!r}"[:60]
    if isinstance(value, (list, tuple, dict, set)):
        text = repr(value)
        return f"{kind} {text}" if len(text) <= 40             else f"{kind}, {len(value)} items"
    return kind


def _kind_of(obj: Any) -> str:
    if inspect.ismodule(obj):
        return "module"
    if inspect.isclass(obj):
        return "class"
    if callable(obj):
        return "function"
    return "constant"


def _describer(name: str, obj: Any, matlab: bool) -> Callable[[Completion],
                                                                 None]:
    """Fill a completion from the curated table, else from ``obj``."""
    def fill(item: Completion) -> None:
        documented = callable(obj) or inspect.ismodule(obj)
        doc_sig, doc = doc_summary(name, obj) if documented else ("", "")
        curated = SIGNATURES.get(name) if matlab else None
        if curated is not None:
            item.signature = curated[0]
            item.detail = curated[1] or doc
            return
        if callable(obj) and not inspect.isclass(obj):
            item.signature = python_signature(name, obj) or doc_sig
        item.detail = doc if documented else describe_value(obj)
    return fill


# ──────────────────────────────────────────────────────────────
#  The pools that never change
# ──────────────────────────────────────────────────────────────

class _Pool:
    """A list built once, on a background thread or on first demand."""

    def __init__(self, build: Callable[[], list[Completion]]) -> None:
        self._build = build
        self._value: list[Completion] | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def ready(self) -> bool:
        return self._value is not None

    def get(self, wait: bool = True) -> list[Completion]:
        if self._value is not None:
            return self._value
        if not wait:
            self.warm()
            return []
        with self._lock:
            if self._value is None:
                self._value = self._build()
        return self._value

    def warm(self) -> None:
        if self._value is None and self._thread is None:
            self._thread = threading.Thread(target=self.get, daemon=True,
                                            name="evans-completion")
            self._thread.start()


def _library() -> list[Completion]:
    """The MATLAB runtime's builtins (its ``f_*`` methods and constants)."""
    from ...console.matlab_runtime import _Library
    out = []
    for attr in sorted(dir(_Library), key=str.lower):
        if not attr.startswith("f_"):
            continue
        name = attr[2:]
        obj = getattr(_Library, attr)
        out.append(Completion(name, _kind_of(obj),
                              resolve=_describer(name, obj, True)))
    return out


def _commands() -> list[Completion]:
    """The console's MATLAB-shaped commands first, then its other presets."""
    from ...console import api
    namespace = api.build_namespace()
    out, seen = [], set()
    commands = [n for names in api._GROUPS.values()      # noqa: SLF001
                for n in names]
    for name in sorted(commands, key=str.lower):
        seen.add(name)
        out.append(Completion(name, "command",
                              resolve=_describer(name, namespace[name],
                                                 True)))
    for name in sorted(namespace, key=str.lower):
        if name in seen or name.startswith("_"):
            continue
        obj = namespace[name]
        out.append(Completion(name, _kind_of(obj),
                              resolve=_describer(name, obj, True)))
    return out


def _python_builtins() -> list[Completion]:
    out = []
    for name in sorted(dir(builtins), key=str.lower):
        if name.startswith("_"):
            continue
        obj = getattr(builtins, name)
        out.append(Completion(name, _kind_of(obj),
                              resolve=_describer(name, obj, False)))
    return out


_LIBRARY = _Pool(_library)
_COMMANDS = _Pool(_commands)
_BUILTINS = _Pool(_python_builtins)


def warm_up(wait: bool = False) -> None:
    """Build the fixed pools — in the background unless ``wait``."""
    for pool in (_LIBRARY, _COMMANDS, _BUILTINS):
        pool.get(True) if wait else pool.warm()


def pools_ready() -> bool:
    return all(p.ready for p in (_LIBRARY, _COMMANDS, _BUILTINS))


def library_names() -> frozenset[str]:
    """The MATLAB library's function and constant names."""
    return frozenset(c.text for c in _LIBRARY.get())


def keyword_items(language: str) -> list[Completion]:
    words = MATLAB_KEYWORDS if language == "matlab" else PYTHON_KEYWORDS
    return [Completion(w, "keyword", detail="keyword") for w in sorted(words)]


# ──────────────────────────────────────────────────────────────
#  The pools that change: the workspace, attributes, files
# ──────────────────────────────────────────────────────────────

def _scope(interpreter) -> dict:
    paused = interpreter.tracer.paused
    return paused.scope if paused is not None else interpreter.namespace


def workspace_items(interpreter) -> list[Completion]:
    """The workspace's variables (the paused scope while debugging)."""
    if interpreter is None:
        return []
    out = []
    for name, value in sorted(interpreter.variables().items(),
                              key=lambda kv: kv[0].lower()):
        if getattr(value, "_ml_function", False) or (
                callable(value) and inspect.isfunction(value)):
            out.append(Completion(name, "function",
                                  resolve=_describer(name, value, False)))
        else:
            out.append(Completion(
                name, "variable",
                resolve=lambda item, v=value: setattr(item, "detail",
                                                      describe_value(v))))
    return out


def lookup(interpreter, dotted: str) -> Any:
    """
    The object ``a.b.c`` names, by attribute lookup — never ``eval``: the
    popup opens while typing, and must not run half-typed code.
    """
    parts = dotted.split(".")
    if not all(p.isidentifier() for p in parts):
        raise LookupError(dotted)
    scope = _scope(interpreter) if interpreter is not None else {}
    namespace = interpreter.namespace if interpreter is not None else {}
    head = parts[0]
    for source in (scope, namespace, vars(builtins)):
        if head in source:
            obj = source[head]
            break
    else:
        raise LookupError(dotted)
    for part in parts[1:]:
        obj = getattr(obj, part)
    return obj


def attribute_items(interpreter, head: str) -> list[Completion]:
    """``head``'s attributes, public ones only."""
    try:
        obj = lookup(interpreter, head)
        names = dir(obj)
    except Exception:                                      # noqa: BLE001
        return []
    out = []
    for name in sorted(names, key=str.lower):
        if name.startswith("_"):
            continue
        out.append(Completion(name, "attribute",
                              resolve=_attribute_describer(obj, name)))
    return out


def _attribute_describer(owner: Any, name: str):
    def fill(item: Completion) -> None:
        # Look on the class first: a property is described, not computed.
        static = inspect.getattr_static(owner, name, None)
        if isinstance(static, property):
            item.kind = "attribute"
            item.detail = first_line(static.__doc__) or "property"
            return
        obj = getattr(owner, name)
        item.kind = _kind_of(obj) if callable(obj) else "attribute"
        if callable(obj) and not inspect.isclass(obj):
            doc_sig, item.detail = doc_summary(name, obj)
            item.signature = python_signature(name, obj) or doc_sig
        elif inspect.isclass(obj) or inspect.ismodule(obj):
            item.detail = first_line(obj.__doc__)
        else:
            item.detail = describe_value(obj)
    return fill


_M_FILES: dict[str, tuple[float, list[str]]] = {}


def m_file_names(folder: str | Path | None = None) -> list[str]:
    """Names of the ``.m`` files in ``folder`` (a script runs by its name)."""
    path = str(folder or os.getcwd())
    cached = _M_FILES.get(path)
    now = time.monotonic()
    if cached is not None and now - cached[0] < 2.0:
        return cached[1]
    try:
        names = sorted(e[:-2] for e in os.listdir(path) if e.endswith(".m"))
    except OSError:
        names = []
    _M_FILES[path] = (now, names)
    return names


def m_file_items(folder: str | Path | None = None) -> list[Completion]:
    return [Completion(n, "file", detail=f"{n}.m — runs the script")
            for n in m_file_names(folder)]


# ──────────────────────────────────────────────────────────────
#  Requests for code
# ──────────────────────────────────────────────────────────────

def word_before(text: str) -> str:
    """The identifier (dots included) that ends ``text``."""
    i = len(text)
    while i > 0 and (text[i - 1].isalnum() or text[i - 1] in WORD_CHARS):
        i -= 1
    return text[i:]


def in_string_or_comment(line: str, language: str) -> bool:
    """Is the end of ``line`` inside a string or a comment?"""
    lang = "matlab" if language == "matlab" else "python"
    spans, _state = tokenize_line(line, language=lang)
    n = len(line)
    for start, length, kind in spans:
        if kind in ("comment", "section") and start < n:
            return True
        if kind == "string" and start < n <= start + length \
                and not _closed_string(line[start:start + length]):
            return True
    return False


def _closed_string(text: str) -> bool:
    return len(text) >= 2 and text[-1] == text[0] and text[0] in "'\""


#: Which pools each kind of code completes from, in order.
PROFILES = {
    # A MATLAB script or live-script cell.
    "matlab": ("workspace", "keywords", "library", "commands", "files"),
    # A Python script.
    "python": ("workspace", "keywords", "commands", "builtins"),
    # The console prompt: Python, with MATLAB's vocabulary.
    "console": ("workspace", "keywords", "commands", "library", "builtins",
                "files"),
}


def code_items(profile: str, interpreter=None, folder=None, *,
               wait: bool = True) -> list[Completion]:
    """Every name ``profile`` completes from, best source first, once each."""
    language = "matlab" if profile == "matlab" else "python"
    groups = []
    for source in PROFILES[profile]:
        if source == "workspace":
            groups.append(workspace_items(interpreter))
        elif source == "keywords":
            groups.append(keyword_items(language))
        elif source == "library":
            groups.append(_LIBRARY.get(wait))
        elif source == "commands":
            groups.append(_COMMANDS.get(wait))
        elif source == "builtins":
            groups.append(_BUILTINS.get(wait))
        elif source == "files":
            groups.append(m_file_items(folder))
    seen: set[str] = set()
    out = []
    for group in groups:
        for item in group:
            if item.text not in seen and not item.text.startswith("_"):
                seen.add(item.text)
                out.append(item)
    return out


def code_request(before: str, profile: str = "matlab", interpreter=None,
                 folder: str | Path | None = None) -> Request | None:
    """
    What to complete at the end of ``before`` (the text before the cursor)
    in MATLAB or Python code; ``None`` in a string, a comment or a number.
    """
    line = before.rpartition("\n")[2]
    language = "matlab" if profile == "matlab" else "python"
    word = word_before(line)
    if word[:1].isdigit() or in_string_or_comment(line, language):
        return None
    if "." in word:
        head, _, tail = word.rpartition(".")
        if not head or not all(p.isidentifier() for p in head.split(".")):
            return None
        return Request(tail, ("attr", head),
                       lambda _wait: attribute_items(interpreter, head),
                       auto_min=0)
    return Request(word, ("code", profile, pools_ready()),
                   lambda wait: code_items(profile, interpreter, folder,
                                           wait=wait))


def completion_candidates(prefix: str, interpreter=None, *,
                          folder: str | Path | None = None,
                          language: str = "matlab") -> list[str]:
    """
    Every completion of ``prefix`` as plain names, best first — what Tab
    offers, without the popup. ``a.b`` completes attributes of ``a``.
    """
    if not prefix:
        return []
    request = code_request(prefix, language, interpreter, folder)
    if request is None:
        return []
    names = [c.text for c in rank(request.prefix, request.items(True))]
    if request.key[0] == "attr":
        head = request.key[1]
        return [f"{head}.{n}" for n in names]
    return names
