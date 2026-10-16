"""
MATLAB scripts, translated to Python.
=====================================
Decision D4 kept the *console* Python: a prompt is typed line by line, and
silently guessing at ``[1 -2]`` there would make a dialect that works until
it doesn't. A pasted course script is different — it is already written, it
is valid MATLAB, and asking someone to hand-convert forty lines before they
can run them is the dead end D4 warned about. So the Script tab translates.

This module is the front half: a lexer and a recursive-descent parser for the
part of MATLAB that control-course scripts use, emitting Python that calls the
runtime in :mod:`.matlab_runtime` for everything whose meaning differs —
``*`` as a matrix product, 1-based indexing with ``end``, ``a:b:c`` ranges,
``[y, t] = step(G)`` counting its outputs.

What is covered
---------------
Matrices ``[1 2; 3 4]`` (spaces, commas, newlines), cells ``{…}``, strings in
both quotes, ``'`` as transpose, every arithmetic and logical operator,
``a:b:c``, indexing and indexed assignment with ``end`` (including growing an
array), struct fields, ``if/elseif/else``, ``for``, ``while``, ``switch``,
``try/catch``, ``break/continue/return``, function handles ``@(x) …``,
local functions (with or without ``end``), command syntax (``hold on``,
``close all``), ``%`` and ``%{ … %}`` comments, ``...`` continuations, and
``;`` deciding whether a result is echoed.

What is not
-----------
Classes, ``eval``, nested functions, ``global`` sharing, and symbolic
``syms`` — the runtime says so by name rather than failing obscurely.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field

# ──────────────────────────────────────────────────────────────
#  Public surface
# ──────────────────────────────────────────────────────────────


class MatlabSyntaxError(Exception):
    """A script the translator cannot read, with the MATLAB line it stopped on."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


@dataclass
class Chunk:
    """
    One top-level statement (or block), translated.

    ``matlab`` is the original text, shown at the prompt as it runs;
    ``python`` is what executes; ``lines`` maps each Python line (1-based) to
    the MATLAB line it came from, so a runtime error names the line the user
    wrote rather than the one generated for them.
    """
    matlab:   str
    python:   str
    lines:    list[int]
    first:    int
    function: bool = False


def translate(source: str) -> list[Chunk]:
    """Translate a MATLAB script into executable chunks, functions first."""
    tokens = _Lexer(_command_syntax(source)).tokens()
    program = _Parser(tokens).program()
    source_lines = source.splitlines()
    chunks: list[Chunk] = []
    for group in _group(program):
        emitter = _Emitter(_assigned_names(program, top=True))
        for stmt in group:
            emitter.statement(stmt, 0)
        first = group[0].line
        last = max(_last_line(s) for s in group)
        text = "\n".join(source_lines[first - 1:last]).strip("\n")
        chunks.append(Chunk(text, emitter.code(), emitter.line_map(), first,
                            function=isinstance(group[0], _Function)))
    # MATLAB lets a script call local functions defined at its bottom; Python
    # needs them defined first.
    chunks.sort(key=lambda c: not c.function)
    return chunks


def to_python(source: str) -> str:
    """The whole translation as one Python source — for reading and tests."""
    return "\n".join(c.python for c in translate(source))


_MATLAB_MARKERS = (
    re.compile(r"^\s*%", re.M),
    re.compile(r"^\s*(end|endif|endfor|endwhile|endfunction)\s*;?\s*(%.*)?$",
               re.M),
    re.compile(r"^\s*(function|elseif|switch|otherwise)\b", re.M),
    re.compile(r";\s*(%.*)?$", re.M),
    re.compile(r"[\w)\]]\s*\.?\^"),
    re.compile(r"\[[^\],\n]*[\w.)]\s+[-+]?[\w.(]"),
    re.compile(r"~="),
    re.compile(r"\.[*/^]"),
    re.compile(r"^\s*(hold|grid|clc|clear|close|format|clf)\b(\s+\w+)?\s*;?\s*$",
               re.M),
    re.compile(r"\b(disp|fprintf|num2str|sprintf)\s*\("),
    re.compile(r"^\s*for\s+\w+\s*=", re.M),
    re.compile(r"^\s*(if|while)\b[^:\n]*$", re.M),
)

_PYTHON_MARKERS = (
    re.compile(r"^\s*(def|import|from|class|elif|with|lambda)\b", re.M),
    re.compile(r"^\s*(if|for|while|else|try|except)\b.*:\s*(#.*)?$", re.M),
    re.compile(r"\*\*"),
    re.compile(r"^\s*#", re.M),
    re.compile(r"\bprint\s*\("),
    re.compile(r"\bnp\.\w"),
)


def looks_like_matlab(source: str) -> bool:
    """
    Guess the language of a script.

    Some MATLAB is also valid Python — ``s^2`` parses, as bitwise XOR — so
    "does it parse?" is not the test. Count the habits each language has and
    the other does not; parsing only breaks a tie.
    """
    matlab = sum(bool(p.search(source)) for p in _MATLAB_MARKERS)
    python = sum(bool(p.search(source)) for p in _PYTHON_MARKERS)
    if matlab != python:
        return matlab > python
    import ast
    try:
        ast.parse(source)
        return False
    except SyntaxError:
        return True


# ──────────────────────────────────────────────────────────────
#  Command syntax:  hold on  →  hold('on')
# ──────────────────────────────────────────────────────────────

_KEYWORDS = {
    "if", "elseif", "else", "end", "for", "while", "switch", "case",
    "otherwise", "function", "return", "break", "continue", "try", "catch",
    "global", "persistent", "endif", "endfor", "endwhile", "endfunction",
    "endswitch", "end_try_catch", "parfor",
}

_COMMAND = re.compile(
    r"^(?P<indent>\s*)(?P<name>[A-Za-z_]\w*)[ \t]+"
    r"(?P<args>(?![-+*/^\\=<>&|~:.]\s|=|\()[A-Za-z0-9'\-][^;,%\n]*?)"
    r"\s*(?P<end>[;,]?)\s*(?P<comment>%.*)?$")


def _command_syntax(source: str) -> str:
    """
    Rewrite MATLAB's command form into a call, line by line.

    MATLAB reads ``name word word`` as ``name('word', 'word')``. The test is
    lexical, the way MATLAB's own is: a name, whitespace, then something that
    neither assigns nor starts a binary operator followed by a space.
    """
    out = []
    in_block_comment = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped in ("%{", "#{"):
            in_block_comment = True
        if in_block_comment:
            out.append(line)
            if stripped in ("%}", "#}"):
                in_block_comment = False
            continue
        out.append("".join(_command_form(seg) for seg in _segments(line)))
    return "\n".join(out)


def _command_form(segment: str) -> str:
    m = _COMMAND.match(segment)
    if not m or m.group("name") in _KEYWORDS or "'" in m.group("args")[1:-1]:
        return segment
    words = m.group("args").split()
    args = ", ".join(repr(w.strip("'")) for w in words)
    comment = f" {m.group('comment')}" if m.group("comment") else ""
    return (f"{m.group('indent')}{m.group('name')}({args})"
            f"{m.group('end')}{comment}")


def _segments(line: str) -> list[str]:
    """
    Split a line at its top-level ``;`` and ``,`` (each kept with its
    statement), stopping at a comment — so ``clc; close all`` is two
    statements, each of which may be in command form.
    """
    segments, start, depth, quote = [], 0, 0, None
    for k, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch == '"' or (ch == "'" and not (k and (line[k - 1].isalnum()
                                                   or line[k - 1] in ")]}_.'"))):
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch in "%#":
            break
        elif ch in ";," and depth == 0:
            segments.append(line[start:k + 1])
            start = k + 1
    segments.append(line[start:])
    return segments


# ──────────────────────────────────────────────────────────────
#  Lexer
# ──────────────────────────────────────────────────────────────

@dataclass
class _Tok:
    kind:  str          # num str id kw op sep end-of-file
    text:  str
    line:  int
    space_before: bool = False


_NUMBER = re.compile(
    r"(\d+(\.(?![*/^\\'])\d*)?|\.\d+)([eEdD][+-]?\d+)?([ij](?![\w]))?")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_OPS = (".^", ".*", "./", ".\\", ".'", "==", "~=", "!=", "<=", ">=", "&&",
        "||", "+", "-", "*", "/", "\\", "^", "<", ">", "&", "|", "~", "!",
        "=", ":", "(", ")", "[", "]", "{", "}", ".", "@", ",", ";")
_VALUE_END = {"num", "str", "id"}


class _Lexer:
    def __init__(self, source: str) -> None:
        self.src = source
        self.i = 0
        self.line = 1
        self.out: list[_Tok] = []
        self.stack: list[str] = []

    # helpers --------------------------------------------------------------

    def _prev_is_value(self) -> bool:
        if not self.out:
            return False
        t = self.out[-1]
        if t.kind in _VALUE_END:
            return True
        if t.kind == "kw" and t.text == "end" and self.stack:
            return True
        return t.kind == "op" and t.text in (")", "]", "}", "'", ".'")

    def _in_matrix(self) -> bool:
        return bool(self.stack) and self.stack[-1] in "[{"

    def _emit(self, kind: str, text: str, space: bool = False) -> None:
        self.out.append(_Tok(kind, text, self.line, space))

    def _error(self, message: str):
        raise MatlabSyntaxError(message, self.line)

    # main loop ------------------------------------------------------------

    def tokens(self) -> list[_Tok]:
        src = self.src
        space = False
        at_line_start = True
        while self.i < len(src):
            c = src[self.i]

            if at_line_start:
                end = src.find("\n", self.i)
                end = len(src) if end < 0 else end
                if src[self.i:end].strip() in ("%{", "#{"):
                    self._skip_block_comment()
                    continue
                at_line_start = False

            if c == "\n":
                self.i += 1
                if self._in_matrix():
                    if not (self.out and self.out[-1].text in (";", "[", "{")):
                        self._emit("op", ";")
                elif not self.stack:
                    self._emit("sep", "\n")
                self.line += 1
                at_line_start = True
                space = False
                continue

            if c in " \t\r":
                self.i += 1
                space = True
                continue

            if src.startswith("...", self.i):
                nl = src.find("\n", self.i)
                self.i = len(src) if nl < 0 else nl + 1
                self.line += 1
                space = True
                continue

            if c in "%#":
                nl = src.find("\n", self.i)
                self.i = len(src) if nl < 0 else nl
                continue

            # Inside [ ] and { }, whitespace between two values separates
            # elements: [1 -2] is two numbers, [1 - 2] is one.
            if space and self._in_matrix() and self._prev_is_value() \
                    and self._starts_value(c):
                self._emit("op", ",")

            if c == "'" :
                if self._prev_is_value() and not space:
                    self.i += 1
                    self._emit("op", "'")
                else:
                    self._string("'")
                space = False
                continue
            if c == '"':
                self._string('"')
                space = False
                continue

            m = _NUMBER.match(src, self.i)
            if m and (c.isdigit() or (c == "." and src[self.i + 1:self.i + 2]
                                      .isdigit())):
                self.i = m.end()
                self._emit("num", m.group(0), space)
                space = False
                continue

            m = _IDENT.match(src, self.i)
            if m:
                word = m.group(0)
                self.i = m.end()
                if word in _KEYWORDS and not (word == "end" and self.stack):
                    self._emit("kw", word, space)
                elif word == "end":
                    self._emit("kw", "end", space)
                else:
                    self._emit("id", word, space)
                space = False
                continue

            for op in _OPS:
                if src.startswith(op, self.i):
                    break
            else:
                self._error(f"unexpected character {c!r}")
            self.i += len(op)
            if op in "([{":
                self.stack.append(op)
            elif op in ")]}":
                if not self.stack:
                    self._error(f"unbalanced {op!r}")
                self.stack.pop()
            if op in (",", ";") and not self.stack:
                self._emit("sep", op)
            else:
                self._emit("op", op, space)
            space = False

        if self.stack:
            self._error(f"unclosed {self.stack[-1]!r}")
        self._emit("sep", "\n")
        self._emit("eof", "")
        return self.out

    def _starts_value(self, c: str) -> bool:
        src, i = self.src, self.i
        nxt = src[i + 1:i + 2]
        if c.isalnum() or c in "_([{'\"@":
            return True
        if c == "." and nxt.isdigit():
            return True
        if c in "+-" and nxt not in (" ", "\t", "=") and nxt != "":
            return True
        if c in "~!" and nxt != "=":
            return True
        return False

    def _string(self, quote: str) -> None:
        src = self.src
        self.i += 1
        chars = []
        while True:
            if self.i >= len(src) or src[self.i] == "\n":
                self._error("unterminated string")
            ch = src[self.i]
            if ch == quote:
                if src[self.i + 1:self.i + 2] == quote:
                    chars.append(quote)
                    self.i += 2
                    continue
                self.i += 1
                break
            chars.append(ch)
            self.i += 1
        self._emit("str", "".join(chars))

    def _skip_block_comment(self) -> None:
        src = self.src
        depth = 0
        while self.i < len(src):
            end = src.find("\n", self.i)
            end = len(src) if end < 0 else end
            text = src[self.i:end].strip()
            if text in ("%{", "#{"):
                depth += 1
            elif text in ("%}", "#}"):
                depth -= 1
            self.i = end + 1
            self.line += 1
            if depth == 0:
                return
        self._error("unterminated %{ block comment")


# ──────────────────────────────────────────────────────────────
#  Syntax tree
# ──────────────────────────────────────────────────────────────

@dataclass
class _Node:
    line: int


@dataclass
class _Num(_Node):
    text: str


@dataclass
class _Str(_Node):
    value: str


@dataclass
class _Name(_Node):
    name: str


@dataclass
class _End(_Node):
    pass


@dataclass
class _Colon(_Node):
    """A bare ``:`` as an index — all of that dimension."""


@dataclass
class _Bin(_Node):
    op: str
    left: _Node
    right: _Node


@dataclass
class _Unary(_Node):
    op: str
    operand: _Node


@dataclass
class _Postfix(_Node):
    op: str            # ' or .'
    operand: _Node


@dataclass
class _Range(_Node):
    start: _Node
    step: _Node | None
    stop: _Node


@dataclass
class _Index(_Node):
    """``x(args)`` — a call or an index; only the runtime can tell which."""
    target: _Node
    args: list[_Node]


@dataclass
class _CellIndex(_Node):
    target: _Node
    args: list[_Node]


@dataclass
class _Field(_Node):
    target: _Node
    name: str | _Node


@dataclass
class _Matrix(_Node):
    rows: list[list[_Node]]
    cell: bool = False


@dataclass
class _Lambda(_Node):
    params: list[str]
    body: _Node


@dataclass
class _Handle(_Node):
    name: str


# statements ---------------------------------------------------------------

@dataclass
class _Stmt(_Node):
    end_line: int = 0


@dataclass
class _ExprStmt(_Stmt):
    expr: _Node = None
    echo: bool = True


@dataclass
class _Assign(_Stmt):
    targets: list[_Node] = field(default_factory=list)   # 1 = plain
    value: _Node = None
    echo: bool = True
    multi: bool = False


@dataclass
class _If(_Stmt):
    branches: list[tuple[_Node, list[_Stmt]]] = field(default_factory=list)
    orelse: list[_Stmt] | None = None


@dataclass
class _For(_Stmt):
    var: str = ""
    iterable: _Node = None
    body: list[_Stmt] = field(default_factory=list)


@dataclass
class _While(_Stmt):
    cond: _Node = None
    body: list[_Stmt] = field(default_factory=list)


@dataclass
class _Switch(_Stmt):
    subject: _Node = None
    cases: list[tuple[_Node, list[_Stmt]]] = field(default_factory=list)
    otherwise: list[_Stmt] | None = None


@dataclass
class _Try(_Stmt):
    body: list[_Stmt] = field(default_factory=list)
    var: str | None = None
    handler: list[_Stmt] = field(default_factory=list)


@dataclass
class _Simple(_Stmt):
    word: str = ""     # break continue return


@dataclass
class _Function(_Stmt):
    name: str = ""
    params: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    body: list[_Stmt] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
#  Parser
# ──────────────────────────────────────────────────────────────

_BLOCK_END = {"end", "endif", "endfor", "endwhile", "endfunction",
              "endswitch", "end_try_catch"}


class _Parser:
    def __init__(self, tokens: list[_Tok]) -> None:
        self.toks = tokens
        self.p = 0

    # token helpers ----------------------------------------------------

    @property
    def tok(self) -> _Tok:
        return self.toks[self.p]

    def _peek(self, n: int = 1) -> _Tok:
        return self.toks[min(self.p + n, len(self.toks) - 1)]

    def _advance(self) -> _Tok:
        t = self.toks[self.p]
        self.p += 1
        return t

    def _is(self, kind: str, text: str | None = None) -> bool:
        t = self.tok
        return t.kind == kind and (text is None or t.text == text)

    def _is_op(self, *texts: str) -> bool:
        return self.tok.kind == "op" and self.tok.text in texts

    def _expect_op(self, text: str) -> _Tok:
        if not self._is_op(text):
            self._error(f"expected {text!r}")
        return self._advance()

    def _error(self, message: str):
        t = self.tok
        got = {"sep": "end of statement", "eof": "end of script"}.get(
            t.kind, repr(t.text))
        raise MatlabSyntaxError(f"{message}, found {got}", t.line)

    def _skip_seps(self) -> None:
        while self.tok.kind == "sep":
            self.p += 1

    def _end_statement(self) -> tuple[bool, int]:
        """Consume the terminator; return (echo, line)."""
        t = self.tok
        if t.kind == "sep":
            self.p += 1
            return t.text != ";", t.line
        if t.kind in ("eof", "kw"):
            return True, t.line
        self._error("unexpected text after the statement")

    # program and blocks -----------------------------------------------

    def program(self) -> list[_Stmt]:
        body = self._block(stop=set())
        if not self._is("eof"):
            self._error("unexpected keyword")
        return body

    def _block(self, stop: set[str]) -> list[_Stmt]:
        body: list[_Stmt] = []
        while True:
            self._skip_seps()
            t = self.tok
            if t.kind == "eof":
                return body
            if t.kind == "kw" and t.text in stop:
                return body
            if t.kind == "kw" and t.text in _BLOCK_END:
                self._error("'end' with no block to close")
            body.append(self._statement())

    def _close_block(self, what: str, line: int) -> int:
        if self.tok.kind == "kw" and self.tok.text in _BLOCK_END:
            end = self._advance().line
            if self.tok.kind == "sep":
                self.p += 1
            return end
        raise MatlabSyntaxError(f"'{what}' opened here is never closed with "
                                f"'end'", line)

    # statements -------------------------------------------------------

    def _statement(self) -> _Stmt:
        t = self.tok
        if t.kind == "kw":
            handler = {
                "if": self._if, "for": self._for, "parfor": self._for,
                "while": self._while, "switch": self._switch,
                "try": self._try, "function": self._function,
            }.get(t.text)
            if handler:
                return handler()
            if t.text in ("break", "continue", "return"):
                self._advance()
                _, line = self._end_statement()
                return _Simple(t.line, end_line=t.line, word=t.text)
            if t.text in ("global", "persistent"):
                while not self._is("sep") and not self._is("eof"):
                    self._advance()
                return _Simple(t.line, end_line=t.line, word="pass")
            self._error(f"'{t.text}' is not valid here")
        return self._simple_statement()

    def _simple_statement(self) -> _Stmt:
        line = self.tok.line
        # [a, b] = f(...)
        if self._is_op("["):
            save = self.p
            targets = self._try_multi_targets()
            if targets is not None:
                value = self._expr()
                echo, end = self._end_statement()
                return _Assign(line, end_line=end, targets=targets,
                               value=value, echo=echo, multi=True)
            self.p = save
        # x = ..., x(i) = ..., s.f = ...
        if self._is("id"):
            save = self.p
            try:
                target = self._postfix(lvalue=True)
            except MatlabSyntaxError:
                target = None
            if target is not None and self._is_op("=") and _is_lvalue(target):
                self._advance()
                value = self._expr()
                echo, end = self._end_statement()
                return _Assign(line, end_line=end, targets=[target],
                               value=value, echo=echo)
            self.p = save
        expr = self._expr()
        if self._is_op("="):
            self._error("cannot assign to this expression")
        echo, end = self._end_statement()
        return _ExprStmt(line, end_line=end, expr=expr, echo=echo)

    def _try_multi_targets(self) -> list[_Node] | None:
        """``[a, ~, c] =`` — or None if this bracket is a matrix after all."""
        self._advance()                       # [
        targets: list[_Node] = []
        while not self._is_op("]"):
            if self._is_op(","):
                self._advance()
                continue
            if self._is_op("~"):
                targets.append(_Name(self.tok.line, "~"))
                self._advance()
                continue
            if not self._is("id"):
                return None
            try:
                target = self._postfix(lvalue=True)
            except MatlabSyntaxError:
                return None
            if not _is_lvalue(target):
                return None
            targets.append(target)
        self._advance()                       # ]
        if not self._is_op("="):
            return None
        self._advance()
        return targets

    def _if(self) -> _If:
        start = self._advance().line
        node = _If(start)
        cond = self._expr()
        body = self._block({"elseif", "else"} | _BLOCK_END)
        node.branches.append((cond, body))
        while self._is("kw", "elseif"):
            self._advance()
            cond = self._expr()
            node.branches.append(
                (cond, self._block({"elseif", "else"} | _BLOCK_END)))
        if self._is("kw", "else"):
            self._advance()
            node.orelse = self._block(_BLOCK_END)
        node.end_line = self._close_block("if", start)
        return node

    def _for(self) -> _For:
        start = self._advance().line
        paren = self._is_op("(")
        if paren:
            self._advance()
        if not self._is("id"):
            self._error("expected a loop variable")
        var = self._advance().text
        self._expect_op("=")
        iterable = self._expr()
        if paren:
            self._expect_op(")")
        body = self._block(_BLOCK_END)
        node = _For(start, var=var, iterable=iterable, body=body)
        node.end_line = self._close_block("for", start)
        return node

    def _while(self) -> _While:
        start = self._advance().line
        cond = self._expr()
        body = self._block(_BLOCK_END)
        node = _While(start, cond=cond, body=body)
        node.end_line = self._close_block("while", start)
        return node

    def _switch(self) -> _Switch:
        start = self._advance().line
        node = _Switch(start, subject=self._expr())
        self._skip_seps()
        while self._is("kw", "case"):
            self._advance()
            value = self._expr()
            node.cases.append(
                (value, self._block({"case", "otherwise"} | _BLOCK_END)))
        if self._is("kw", "otherwise"):
            self._advance()
            node.otherwise = self._block(_BLOCK_END)
        node.end_line = self._close_block("switch", start)
        return node

    def _try(self) -> _Try:
        start = self._advance().line
        node = _Try(start, body=self._block({"catch"} | _BLOCK_END))
        if self._is("kw", "catch"):
            catch_line = self._advance().line
            if self._is("id") and self.tok.line == catch_line:
                node.var = self._advance().text
            node.handler = self._block(_BLOCK_END)
        node.end_line = self._close_block("try", start)
        return node

    def _function(self) -> _Function:
        start = self._advance().line
        outputs: list[str] = []
        # function [a, b] = name(...)   function a = name(...)   function name
        if self._is_op("["):
            self._advance()
            while not self._is_op("]"):
                if self._is_op(","):
                    self._advance()
                    continue
                if not self._is("id"):
                    self._error("expected an output name")
                outputs.append(self._advance().text)
            self._advance()
            self._expect_op("=")
            name = self._ident("a function name")
        else:
            first = self._ident("a function name")
            if self._is_op("="):
                self._advance()
                outputs = [first]
                name = self._ident("a function name")
            else:
                name = first
        params: list[str] = []
        if self._is_op("("):
            self._advance()
            while not self._is_op(")"):
                if self._is_op(","):
                    self._advance()
                    continue
                if self._is_op("~"):
                    self._advance()
                    params.append(f"_unused{len(params)}")
                    continue
                params.append(self._ident("a parameter name"))
            self._advance()
        body = self._block({"function"} | _BLOCK_END)
        node = _Function(start, name=name, params=params, outputs=outputs,
                         body=body)
        if self.tok.kind == "kw" and self.tok.text in _BLOCK_END:
            node.end_line = self._close_block("function", start)
        else:      # file-terminated function: runs to the next 'function'
            node.end_line = self.toks[self.p - 1].line
        return node

    def _ident(self, what: str) -> str:
        if not self._is("id"):
            self._error(f"expected {what}")
        return self._advance().text

    # expressions — lowest precedence first ----------------------------

    def _expr(self) -> _Node:
        return self._oror()

    def _binary_level(self, ops: tuple[str, ...], nxt) -> _Node:
        left = nxt()
        while self._is_op(*ops):
            t = self._advance()
            left = _Bin(t.line, t.text, left, nxt())
        return left

    def _oror(self):
        return self._binary_level(("||",), self._andand)

    def _andand(self):
        return self._binary_level(("&&",), self._or)

    def _or(self):
        return self._binary_level(("|",), self._and)

    def _and(self):
        return self._binary_level(("&",), self._compare)

    def _compare(self):
        return self._binary_level(("==", "~=", "!=", "<", "<=", ">", ">="),
                                  self._range)

    def _range(self) -> _Node:
        if self._is_op(":") and self._index_context():
            t = self._advance()
            return _Colon(t.line)
        start = self._additive()
        if not self._is_op(":"):
            return start
        line = self._advance().line
        second = self._additive()
        if self._is_op(":"):
            self._advance()
            return _Range(line, start, second, self._additive())
        return _Range(line, start, None, second)

    def _index_context(self) -> bool:
        """A lone ':' is 'all of this dimension' when an argument is just it."""
        nxt = self._peek()
        return nxt.kind == "op" and nxt.text in (",", ")", "}")

    def _additive(self):
        return self._binary_level(("+", "-"), self._multiplicative)

    def _multiplicative(self):
        return self._binary_level(("*", "/", "\\", ".*", "./", ".\\"),
                                  self._unary)

    def _unary(self) -> _Node:
        if self._is_op("-", "+", "~", "!"):
            t = self._advance()
            op = "~" if t.text == "!" else t.text
            return _Unary(t.line, op, self._unary())
        return self._power()

    def _power(self) -> _Node:
        base = self._postfix()
        while self._is_op("^", ".^"):
            t = self._advance()
            # 2^-1 is legal: the exponent may carry its own sign.
            if self._is_op("-", "+", "~", "!"):
                u = self._advance()
                exponent = _Unary(u.line, "~" if u.text == "!" else u.text,
                                  self._postfix())
            else:
                exponent = self._postfix()
            base = _Bin(t.line, t.text, base, exponent)
        return base

    def _postfix(self, lvalue: bool = False) -> _Node:
        node = self._primary(lvalue)
        while True:
            t = self.tok
            if t.kind != "op":
                return node
            # In a matrix, "a (1)" is two elements; the lexer has already put
            # a comma there, so any '(' reaching here belongs to the value.
            if t.text == "(":
                self._advance()
                node = _Index(t.line, node, self._args(")"))
            elif t.text == "{":
                self._advance()
                node = _CellIndex(t.line, node, self._args("}"))
            elif t.text == "." and self._peek().kind == "id":
                self._advance()
                node = _Field(t.line, node, self._advance().text)
            elif t.text == "." and self._peek().kind == "op" \
                    and self._peek().text == "(":
                self._advance()
                self._advance()
                name = self._expr()
                self._expect_op(")")
                node = _Field(t.line, node, name)
            elif t.text in ("'", ".'") and not lvalue:
                self._advance()
                node = _Postfix(t.line, t.text, node)
            else:
                return node

    def _args(self, close: str) -> list[_Node]:
        args: list[_Node] = []
        while not self._is_op(close):
            if self._is_op(","):
                self._advance()
                continue
            if self._is_op(":") and self._peek().kind == "op" \
                    and self._peek().text in (",", close):
                args.append(_Colon(self._advance().line))
                continue
            args.append(self._expr())
            if not self._is_op(",", close):
                self._error(f"expected ',' or {close!r}")
        self._advance()
        return args

    def _primary(self, lvalue: bool = False) -> _Node:
        t = self.tok
        if lvalue and t.kind != "id":
            self._error("expected a variable name")
        if t.kind == "num":
            self._advance()
            return _Num(t.line, t.text)
        if t.kind == "str":
            self._advance()
            return _Str(t.line, t.text)
        if t.kind == "id":
            self._advance()
            return _Name(t.line, t.text)
        if t.kind == "kw" and t.text == "end":
            self._advance()
            return _End(t.line)
        if t.kind == "op":
            if t.text == "(":
                self._advance()
                inner = self._expr()
                self._expect_op(")")
                return inner
            if t.text in ("[", "{"):
                return self._matrix()
            if t.text == "@":
                return self._handle()
            if t.text == ":":
                self._advance()
                return _Colon(t.line)
        self._error("expected a value")

    def _matrix(self) -> _Matrix:
        open_tok = self._advance()
        close = "]" if open_tok.text == "[" else "}"
        rows: list[list[_Node]] = [[]]
        while not self._is_op(close):
            if self._is_op(";"):
                self._advance()
                rows.append([])
                continue
            if self._is_op(","):
                self._advance()
                continue
            rows[-1].append(self._expr())
        self._advance()
        rows = [r for r in rows if r]
        return _Matrix(open_tok.line, rows, cell=(close == "}"))

    def _handle(self) -> _Node:
        t = self._advance()                    # @
        if self._is_op("("):
            self._advance()
            params = []
            while not self._is_op(")"):
                if self._is_op(","):
                    self._advance()
                    continue
                params.append(self._ident("a parameter name"))
            self._advance()
            return _Lambda(t.line, params, self._expr())
        return _Handle(t.line, self._ident("a function name after '@'"))


def _is_lvalue(node: _Node) -> bool:
    while isinstance(node, (_Index, _CellIndex, _Field)):
        node = node.target
    return isinstance(node, _Name)


# ──────────────────────────────────────────────────────────────
#  Emitter
# ──────────────────────────────────────────────────────────────

_RT = "__ml__"
_PY_RESERVED = set(keyword.kwlist) | {"print", "exec", "eval", "type", "id",
                                      "len", "list", "dict", "str", "int",
                                      "float", "range", "object", "super",
                                      "locals", "globals"}
_PY_RESERVED -= {"if", "else"}       # never reach here as names anyway


def _py_name(name: str) -> str:
    """A MATLAB name that is a Python keyword or builtin gets a suffix."""
    return f"{name}_" if name in _PY_RESERVED or name == _RT else name


def _assigned_names(body: list[_Stmt], top: bool = False) -> set[str]:
    """Every name a block binds — those are variables, never commands."""
    names: set[str] = set()

    def visit(stmts):
        for s in stmts:
            if isinstance(s, _Assign):
                for t in s.targets:
                    while isinstance(t, (_Index, _CellIndex, _Field)):
                        t = t.target
                    if isinstance(t, _Name) and t.name != "~":
                        names.add(t.name)
            elif isinstance(s, _For):
                names.add(s.var)
                visit(s.body)
            elif isinstance(s, (_While,)):
                visit(s.body)
            elif isinstance(s, _If):
                for _, b in s.branches:
                    visit(b)
                if s.orelse:
                    visit(s.orelse)
            elif isinstance(s, _Switch):
                for _, b in s.cases:
                    visit(b)
                if s.otherwise:
                    visit(s.otherwise)
            elif isinstance(s, _Try):
                visit(s.body)
                visit(s.handler)
                if s.var:
                    names.add(s.var)
            elif isinstance(s, _Function) and top:
                names.add(s.name)

    visit(body)
    return names


class _Emitter:
    def __init__(self, variables: set[str]) -> None:
        self.vars = set(variables)
        self.lines: list[tuple[int, str, int]] = []   # indent, text, mline
        self._switch_count = 0
        self._outputs: list[str] | None = None        # inside a function

    def code(self) -> str:
        return "\n".join("    " * i + t for i, t, _ in self.lines) + "\n"

    def line_map(self) -> list[int]:
        return [m for _, _, m in self.lines]

    def _put(self, indent: int, text: str, line: int) -> None:
        self.lines.append((indent, text, line))

    def _block(self, stmts: list[_Stmt], indent: int, line: int) -> None:
        if not stmts:
            self._put(indent, "pass", line)
        for s in stmts:
            self.statement(s, indent)

    # statements -------------------------------------------------------

    def statement(self, s: _Stmt, i: int) -> None:
        if isinstance(s, _Assign):
            self._assign(s, i)
        elif isinstance(s, _ExprStmt):
            self._expr_stmt(s, i)
        elif isinstance(s, _If):
            for n, (cond, body) in enumerate(s.branches):
                word = "if" if n == 0 else "elif"
                self._put(i, f"{word} {_RT}.truth({self.expr(cond)}):",
                          cond.line)
                self._block(body, i + 1, cond.line)
            if s.orelse is not None:
                self._put(i, "else:", s.line)
                self._block(s.orelse, i + 1, s.line)
        elif isinstance(s, _For):
            var = _py_name(s.var)
            self._put(i, f"for {var} in {_RT}.iterate("
                         f"{self.expr(s.iterable)}):", s.line)
            self._block(s.body, i + 1, s.line)
        elif isinstance(s, _While):
            self._put(i, f"while {_RT}.truth({self.expr(s.cond)}):", s.line)
            self._block(s.body, i + 1, s.line)
        elif isinstance(s, _Switch):
            self._switch_count += 1
            subject = f"_switch{self._switch_count}"
            self._put(i, f"{subject} = {self.expr(s.subject)}", s.line)
            for n, (value, body) in enumerate(s.cases):
                word = "if" if n == 0 else "elif"
                self._put(i, f"{word} {_RT}.case_matches({subject}, "
                             f"{self.expr(value)}):", value.line)
                self._block(body, i + 1, value.line)
            if s.otherwise is not None:
                if s.cases:
                    self._put(i, "else:", s.line)
                    self._block(s.otherwise, i + 1, s.line)
                else:
                    self._block(s.otherwise, i, s.line)
        elif isinstance(s, _Try):
            self._put(i, "try:", s.line)
            self._block(s.body, i + 1, s.line)
            name = _py_name(s.var) if s.var else "_err"
            self._put(i, f"except Exception as {name}:", s.line)
            if s.var:
                self._put(i + 1, f"{name} = {_RT}.MException.wrap({name})",
                          s.line)
            self._block(s.handler, i + 1, s.line)
        elif isinstance(s, _Simple):
            if s.word == "return":
                self._put(i, self._return_text(), s.line)
            else:
                self._put(i, s.word, s.line)
        elif isinstance(s, _Function):
            self._function(s, i)
        else:                                            # pragma: no cover
            raise MatlabSyntaxError("unsupported statement", s.line)

    def _return_text(self) -> str:
        if self._outputs is None:
            return f"raise {_RT}.ScriptReturn()"
        if not self._outputs:
            return "return None"
        names = ", ".join(_py_name(o) for o in self._outputs)
        return f"return {_RT}.outputs(({names},), nargout)"

    def _function(self, f: _Function, i: int) -> None:
        inner = _Emitter(_assigned_names(f.body) | set(f.params)
                         | set(f.outputs) | {f.name})
        inner._outputs = f.outputs
        params = [p for p in f.params if p != "varargin"]
        sig = [f"{_py_name(p)}=None" for p in params]
        if "varargin" in f.params:
            sig.append("*varargin")
        sig.append("nargout=1")
        self._put(i, f"@{_RT}.function", f.line)
        self._put(i, f"def {_py_name(f.name)}({', '.join(sig)}):", f.line)
        body_indent = i + 1
        if params:
            count = " + ".join(f"({_py_name(p)} is not None)" for p in params)
            self._put(body_indent, f"nargin = {count}", f.line)
        if "varargin" in f.params:
            self._put(body_indent, "varargin = list(varargin)", f.line)
            if params:
                self._put(body_indent, "nargin += len(varargin)", f.line)
            else:
                self._put(body_indent, "nargin = len(varargin)", f.line)
        for out in f.outputs:
            if out not in f.params:
                self._put(body_indent, f"{_py_name(out)} = None", f.line)
        for stmt in f.body:
            inner.statement(stmt, body_indent)
        if not f.body:
            inner._put(body_indent, "pass", f.line)
        inner._put(body_indent, inner._return_text(), f.end_line or f.line)
        self.lines.extend(inner.lines)
        self.vars.add(f.name)

    def _assign(self, s: _Assign, i: int) -> None:
        if s.multi:
            n = len(s.targets)
            value = self.expr(s.value, nargout=n)
            temps = [f"_out{k}" for k in range(n)]
            self._put(i, f"{', '.join(temps)} = {_RT}.unpack({value}, {n})",
                      s.line)
            for target, temp in zip(s.targets, temps):
                if isinstance(target, _Name) and target.name == "~":
                    continue
                self._store(target, temp, i, s.line)
                if s.echo:
                    self._echo(target, i, s.line)
            return
        target = s.targets[0]
        self._store(target, self.expr(s.value, nargout=1), i, s.line)
        if s.echo:
            self._echo(target, i, s.line)

    def _echo(self, target: _Node, i: int, line: int) -> None:
        base = target
        while isinstance(base, (_Index, _CellIndex, _Field)):
            base = base.target
        self._put(i, f"{_RT}.show({base.name!r}, {_py_name(base.name)})",
                  line)

    def _store(self, target: _Node, value: str, i: int, line: int) -> None:
        if isinstance(target, _Name):
            self.vars.add(target.name)
            self._put(i, f"{_py_name(target.name)} = {value}", line)
            return
        path = []
        node = target
        while isinstance(node, (_Index, _CellIndex, _Field)):
            if isinstance(node, _Field):
                key = (repr(node.name) if isinstance(node.name, str)
                       else self.expr(node.name))
                path.append(f"('.', {key})")
            else:
                kind = "()" if isinstance(node, _Index) else "{}"
                path.append(f"({kind!r}, ({self._arglist(node.args)}))")
            node = node.target
        path.reverse()
        name = _py_name(node.name)
        self.vars.add(node.name)
        self._put(i, f"{name} = {_RT}.assign({_RT}.existing({name!r}, locals()), "
                     f"[{', '.join(path)}], {value})", line)

    def _expr_stmt(self, s: _ExprStmt, i: int) -> None:
        e = s.expr
        if isinstance(e, _Name) and e.name in self.vars:
            if s.echo:
                self._put(i, f"{_RT}.show({e.name!r}, {_py_name(e.name)})",
                          s.line)
            else:
                self._put(i, f"{_py_name(e.name)}", s.line)
            return
        self._put(i, f"{_RT}.statement({self.expr(e, nargout=0)}, "
                     f"{s.echo})", s.line)

    # expressions --------------------------------------------------------

    def _arglist(self, args: list[_Node]) -> str:
        parts = [self._arg(a, k, len(args)) for k, a in enumerate(args)]
        return "".join(p + ", " for p in parts)

    def _arg(self, node: _Node, k: int, n: int) -> str:
        if isinstance(node, _Colon):
            return f"{_RT}.COLON"
        return self.expr(node, end_dim=(k, n))

    def _name_ref(self, name: str) -> str:
        """A bare name: a variable as is; a function is called with no args."""
        if name in self.vars:
            return _py_name(name)
        return f"{_RT}.value({_RT}.lookup({name!r}, globals(), locals()))"

    def _callee(self, name: str) -> str:
        if name in self.vars:
            return _py_name(name)
        return f"{_RT}.lookup({name!r}, globals(), locals())"

    def expr(self, node: _Node, nargout: int = 1,
             end_dim: tuple[int, int] | None = None) -> str:
        e = lambda n: self.expr(n, end_dim=end_dim)            # noqa: E731
        if isinstance(node, _Num):
            text = node.text.replace("d", "e").replace("D", "e")
            if text[-1] in "ij":
                return f"{text[:-1]}j"
            return text
        if isinstance(node, _Str):
            return repr(node.value)
        if isinstance(node, _Name):
            if nargout != 1 and node.name not in self.vars:
                return (f"{_RT}.call({self._callee(node.name)}, (), "
                        f"nargout={nargout})")
            return self._name_ref(node.name)
        if isinstance(node, _End):
            if end_dim is None:
                raise MatlabSyntaxError("'end' used outside an index",
                                        node.line)
            return f"{_RT}.End({end_dim[0]}, {end_dim[1]})"
        if isinstance(node, _Colon):
            return f"{_RT}.COLON"
        if isinstance(node, _Bin):
            return self._binary(node, e)
        if isinstance(node, _Unary):
            fn = {"-": "uminus", "+": "uplus", "~": "logical_not"}[node.op]
            return f"{_RT}.{fn}({e(node.operand)})"
        if isinstance(node, _Postfix):
            fn = "ctranspose" if node.op == "'" else "transpose"
            return f"{_RT}.{fn}({e(node.operand)})"
        if isinstance(node, _Range):
            step = e(node.step) if node.step is not None else "1"
            return (f"{_RT}.colon({e(node.start)}, {step}, "
                    f"{e(node.stop)})")
        if isinstance(node, _Index):
            target = node.target
            args = self._arglist(node.args)
            if isinstance(target, _Name):
                # A plot names its curves after the variables passed, the way
                # MATLAB's legend does — so pass those names along.
                names = ""
                if nargout == 0 and target.name not in self.vars and any(
                        isinstance(a, _Name) for a in node.args):
                    names = ", names=(" + "".join(
                        f"{a.name!r}, " if isinstance(a, _Name) else "None, "
                        for a in node.args) + ")"
                return (f"{_RT}.call({self._callee(target.name)}, ({args}), "
                        f"nargout={nargout}{names})")
            return f"{_RT}.call({e(target)}, ({args}), nargout={nargout})"
        if isinstance(node, _CellIndex):
            return (f"{_RT}.cell_index({e(node.target)}, "
                    f"({self._arglist(node.args)}))")
        if isinstance(node, _Field):
            key = (repr(node.name) if isinstance(node.name, str)
                   else e(node.name))
            return f"{_RT}.field({e(node.target)}, {key})"
        if isinstance(node, _Matrix):
            rows = ", ".join("[" + ", ".join(e(x) for x in row) + "]"
                             for row in node.rows)
            fn = "cell" if node.cell else "concat"
            return f"{_RT}.{fn}([{rows}])"
        if isinstance(node, _Lambda):
            inner = _Emitter(self.vars | set(node.params))
            params = ", ".join(_py_name(p) for p in node.params)
            return f"(lambda {params}: {inner.expr(node.body)})"
        if isinstance(node, _Handle):
            return self._callee(node.name)
        raise MatlabSyntaxError("unsupported expression", node.line)

    def _binary(self, node: _Bin, e) -> str:
        a, b = e(node.left), e(node.right)
        if node.op == "&&":
            return f"({_RT}.truth({a}) and {_RT}.truth({b}))"
        if node.op == "||":
            return f"({_RT}.truth({a}) or {_RT}.truth({b}))"
        fn = {
            "+": "plus", "-": "minus", "*": "mtimes", "/": "mrdivide",
            "\\": "mldivide", "^": "mpower", ".*": "times", "./": "rdivide",
            ".\\": "ldivide", ".^": "power", "==": "eq", "~=": "ne",
            "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge",
            "&": "logical_and", "|": "logical_or",
        }[node.op]
        return f"{_RT}.{fn}({a}, {b})"


# ──────────────────────────────────────────────────────────────
#  Chunking
# ──────────────────────────────────────────────────────────────

def _last_line(s: _Stmt) -> int:
    return max(s.end_line or s.line, s.line)


def _group(program: list[_Stmt]) -> list[list[_Stmt]]:
    """Statements sharing a source line run (and echo) as one chunk."""
    groups: list[list[_Stmt]] = []
    for s in program:
        if groups and not isinstance(s, _Function) \
                and not isinstance(groups[-1][0], _Function) \
                and s.line <= max(_last_line(x) for x in groups[-1]):
            groups[-1].append(s)
        else:
            groups.append([s])
    return groups
