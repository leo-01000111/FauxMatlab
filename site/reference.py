"""
The generated pages: console commands and simulator blocks.
===========================================================
Each page is read out of the code that defines it — the console's ``_GROUPS``
and the commands' docstrings, the block registry and each block's
``params_spec`` — so the site cannot describe a command or block that does
not exist, or miss one that does.
"""

from __future__ import annotations

import html
import inspect
import re

_INLINE = re.compile(
    r"``(?P<lit>.+?)``"
    r"|:[a-z]+:`~?(?P<role>[^`]+)`"
    r"|`(?P<tick>[^`]+)`"
    r"|\*\*(?P<strong>.+?)\*\*"
    r"|\*(?P<em>[^\s*](?:[^*]*[^\s*])?)\*"
)
_UNDERLINE = re.compile(r"[=\-~^]{3,}")


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def inline(text: str) -> str:
    """The reStructuredText inline markup the docstrings use, as HTML."""
    def sub(m: re.Match) -> str:
        if m["lit"] is not None:
            return f"<code>{m['lit']}</code>"
        if m["role"] is not None:
            return f"<code>{m['role']}</code>"
        if m["tick"] is not None:
            return f"<code>{m['tick']}</code>"
        if m["strong"] is not None:
            return f"<strong>{m['strong']}</strong>"
        return f"<em>{m['em']}</em>"
    return _INLINE.sub(sub, esc(text))


def rst(text: str) -> str:
    """
    A docstring as HTML paragraphs.

    Covers what the source actually contains: paragraphs, indented literal
    blocks, ``- `` bullet lists, underlined section titles and inline
    literals, roles, emphasis and strong. It is not a reStructuredText parser.
    """
    out = []
    for block in re.split(r"\n[ \t]*\n", text.strip("\n")):
        lines = block.split("\n")
        if not block.strip():
            continue
        if all(line.startswith("    ") or not line.strip() for line in lines):
            body = "\n".join(line[4:] for line in lines)
            out.append(f"<pre><code>{esc(body)}</code></pre>")
            continue
        if len(lines) >= 2 and _UNDERLINE.fullmatch(lines[1].strip()):
            out.append(f'<p class="label">{inline(lines[0].strip())}</p>')
            lines = lines[2:]
            if not lines:
                continue
        if lines[0].lstrip().startswith(("- ", "* ")):
            items: list[str] = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("- ", "* ")):
                    items.append(stripped[2:])
                elif items:
                    items[-1] += " " + stripped
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            continue
        out.append(f"<p>{inline(' '.join(line.strip() for line in lines))}</p>")
    return "\n".join(out)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _card(title: str, body: str, anchor: str = "") -> str:
    ident = f' id="{anchor}"' if anchor else ""
    return (f'<section class="proj-section"{ident}><div class="card prose">'
            f"<h2>{esc(title)}</h2>\n{body}\n</div></section>")


def _hero(kicker: str, title: str, lede: str) -> str:
    return (f'<section class="proj-hero"><p class="label">{esc(kicker)}</p>'
            f"<h1>{esc(title)}</h1><p class=\"lede\">{lede}</p></section>")


# ──────────────────────────────────────────────────────────────
#  Console commands
# ──────────────────────────────────────────────────────────────

def _signature(name: str, fn) -> str:
    """``name(arg, kw=default)``, without the type annotations."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return f"{name}(…)"
    params = [p.replace(annotation=inspect.Parameter.empty)
              for p in sig.parameters.values()]
    sig = sig.replace(parameters=params,
                      return_annotation=inspect.Signature.empty)
    return f"{name}{sig}"


def command_groups() -> dict[str, list[tuple[str, object]]]:
    from evans.console import api
    return {group: [(name, getattr(api, name)) for name in names]
            for group, names in api._GROUPS.items()}


def commands_page() -> tuple[str, dict]:
    groups = command_groups()
    count = sum(len(v) for v in groups.values())
    index = "".join(
        f"<dt>{esc(group)}</dt><dd>"
        + "".join(f'<a href="#{esc(name)}">{esc(name)}</a>' for name, _ in names)
        + "</dd>"
        for group, names in groups.items())
    parts = [
        _hero("Reference · generated from the code", "Console commands",
              f"Every command the console installs, {count} in "
              f"{len(groups)} groups. The prompt speaks MATLAB, as the Script "
              "tab does; <code>s</code> is the Laplace variable. This page is built from "
              "<code>evans/console/api.py</code> and its docstrings."),
        _card("Index", f'<dl class="ref-index">{index}</dl>'),
        _card("Always available", (
            "<p>Besides the commands, a session starts with "
            "<code>np</code> (numpy) and <code>ctl</code> (python-control), "
            "<code>s</code>, <code>pi</code>, <code>inf</code> and "
            "<code>j</code>, and numpy's <code>linspace</code>, "
            "<code>logspace</code>, <code>zeros</code>, <code>ones</code>, "
            "<code>eye</code>, <code>roots</code>, <code>poly</code> and "
            "<code>conv</code>. <code>help_fm</code> prints the grouped "
            "list at the prompt.</p>"
            "<pre><code>G = 1/(s^2 + 2*s + 1)\nstepinfo(G)\n"
            "[Gm, Pm, Wcg, Wcp] = margin(G)\nbode(G)</code></pre>")),
    ]
    missing = []
    for group, names in groups.items():
        entries = []
        for name, fn in names:
            doc = inspect.getdoc(fn)
            if not doc:
                missing.append(name)
            body = rst(doc) if doc else '<p class="ref__none">No description in the source yet.</p>'
            entries.append(
                f'<article class="ref" id="{esc(name)}">'
                f'<p class="ref__sig">{esc(_signature(name, fn))}'
                f'<a href="#{esc(name)}" aria-label="Link to {esc(name)}">#</a></p>'
                f'<div class="ref__body">{body}</div></article>')
        parts.append(_card(group, "\n".join(entries), "group-" + _slug(group)))
    return "\n".join(parts), {"commands": count, "undocumented": missing}


# ──────────────────────────────────────────────────────────────
#  Simulator blocks
# ──────────────────────────────────────────────────────────────

def _default(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "on" if value else "off"
    if value == "":
        return "(empty)"
    return str(value)


def _ports(names) -> str:
    return ", ".join(f"<code>{esc(n)}</code>" for n in names) or "none"


def blocks_page() -> tuple[str, dict]:
    from evans.sim import block_types, by_category, create
    grouped = by_category()
    count = len(block_types())
    index = "".join(
        f"<dt>{esc(cat)}</dt><dd>"
        + "".join(f'<a href="#{esc(c.type_name)}">{esc(c.type_name)}</a>' for c in blocks)
        + "</dd>"
        for cat, blocks in grouped.items())
    parts = [
        _hero("Reference · generated from the code", "Simulator blocks",
              f"The {count} block types in the Model workspace's palette, "
              "by palette group, with their ports and every editable "
              "parameter and its default. This page is built from the block "
              "registry in <code>evans/sim</code>."),
        _card("Index", f'<dl class="ref-index">{index}</dl>'),
    ]
    for cat, blocks in grouped.items():
        entries = []
        for cls in blocks:
            name = cls.type_name
            try:
                inst = create(name, "b")
                ins, outs = inst.inputs, inst.outputs
            except Exception:                                   # noqa: BLE001
                ins, outs = cls.default_inputs, cls.default_outputs
            rows = "".join(
                f"<tr><td><code>{esc(p.name)}</code></td><td>{esc(p.label)}</td>"
                f'<td class="num">{esc(_default(p.default))}</td>'
                f"<td>{esc(p.kind)}"
                + (f": {', '.join(f'<code>{esc(c)}</code>' for c in p.choices)}" if p.choices else "")
                + f"</td><td>{inline(p.help) if p.help else ''}</td></tr>"
                for p in cls.params_spec)
            table = (
                '<div class="table-wrap"><table><thead><tr><th>Parameter</th>'
                "<th>Label</th><th>Default</th><th>Kind</th><th>Notes</th></tr>"
                f"</thead><tbody>{rows}</tbody></table></div>"
                if rows else '<p class="muted">No parameters.</p>')
            entries.append(
                f'<article class="ref" id="{esc(name)}">'
                f'<p class="ref__sig">{esc(name)}'
                f'<a href="#{esc(name)}" aria-label="Link to {esc(name)}">#</a></p>'
                f'<div class="ref__body"><p>{inline(cls.description)}</p>'
                f'<p class="muted small">Inputs {_ports(ins)} · outputs {_ports(outs)}</p>'
                f"{table}</div></article>")
        parts.append(_card(cat, "\n".join(entries), "cat-" + _slug(cat)))
    return "\n".join(parts), {"blocks": count}
