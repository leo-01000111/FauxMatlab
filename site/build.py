"""
Build the Evans documentation and download site.
================================================
::

    python site/build.py            # writes site/_build/
    python site/build.py --out DIR  # somewhere else

Plain HTML on the Holding Point design system, the same files leongorecki.eu
is built from, so the docs read as part of that site (they are served from
it, at /evans/). The hand-written pages are HTML fragments in ``pages/``; the
reference pages are generated from the code by :mod:`reference`, from the
checkout's ``src/`` rather than whatever copy of Evans happens to be
installed. Every link is relative, so the output works from a local folder,
``python -m http.server`` or any subpath.

Needs Evans's own dependencies (``pip install -e .``) and nothing else.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SITE))

import reference  # noqa: E402

from evans import __version__  # noqa: E402

REPO = "https://github.com/leo-01000111/evans"
RELEASES = f"{REPO}/releases/latest"
HOME = "https://www.leongorecki.eu/"
URL = "https://www.leongorecki.eu/evans/"

ARROW = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><g transform="rotate({r} 12 12)" '
         'fill="none" stroke="currentColor" stroke-width="3.4" stroke-linecap="square" '
         'stroke-linejoin="miter"><path d="M3.5 12H18.5"></path><path d="M12 5.2L18.8 12L12 18.8"></path></g></svg>')

#: (file, nav label, page title, description, source). A source is a fragment
#: in pages/ or the name of a generator in reference.py.
PAGES = [
    ("index.html", "Home", "A control-systems workbench",
     "Classical and modern control, a block-diagram simulator and a MATLAB-shaped "
     "command window in one desktop app. Free for Windows, or run it from source.",
     "home.html"),
    ("install.html", "Install", "Install Evans",
     "Download the Windows build, get past SmartScreen, or run Evans from source.",
     "install.html"),
    ("tour.html", "Tour", "A tour of Evans",
     "The workspaces, the pane grid, the console, scripts, figures, the simulator, "
     "the design apps and snapshots.", "tour.html"),
    ("commands.html", "Commands", "Console commands",
     "Every console command, generated from the code.", "commands_page"),
    ("blocks.html", "Blocks", "Simulator blocks",
     "Every simulator block and its parameters, generated from the code.", "blocks_page"),
    ("matlab.html", "MATLAB scripts", "MATLAB compatibility",
     "What a MATLAB script or live script can use in Evans.", "matlab.html"),
    ("patch-notes.html", "Patch notes", "Patch notes",
     "Every change to Evans since the first build, and a form to report an issue.",
     "patch-notes.html"),
]

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} · Evans</title>
  <meta name="description" content="{description}" />
  <meta name="theme-color" content="#e7e8e3" media="(prefers-color-scheme: light)" />
  <meta name="theme-color" content="#0e0f11" media="(prefers-color-scheme: dark)" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="{title} · Evans" />
  <meta property="og:description" content="{description}" />
  <meta property="og:url" content="{url}" />
  <link rel="canonical" href="{url}" />
  <link rel="icon" href="assets/evans.svg" type="image/svg+xml" />
  <link rel="preload" href="assets/fonts/archivo-latin-wdth-normal.woff2" as="font" type="font/woff2" crossorigin />
  <script src="assets/theme.js"></script>
  <script src="assets/download.js" defer></script>
  <link rel="stylesheet" href="assets/tokens.css" />
  <link rel="stylesheet" href="assets/components.css" />
  <link rel="stylesheet" href="assets/site.css" />
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
  <header class="site-header">
    <div class="header-inner">
      <nav class="hp-signarray" aria-label="Site">
        <a class="hp-sign hp-sign--direction hp-sign--sm" href="{home}">{back}<span>Leon Górecki</span></a>
        <span class="hp-sign hp-sign--location hp-sign--sm"><span>Evans</span></span>
      </nav>
      <div class="header-tools">
        <div class="hp-lang" role="group" aria-label="Theme" data-theme-toggle hidden><button type="button" data-set-theme="light" aria-pressed="false">Day</button><button type="button" data-set-theme="dark" aria-pressed="false">Night</button></div>
        <a class="hp-btn hp-btn--secondary hp-btn--sm" href="{releases}" data-download data-download-short><span>Download</span></a>
      </div>
    </div>
    <nav class="docs-nav" aria-label="Documentation"><div class="hp-signarray">{nav}</div></nav>
  </header>

  <main id="main" class="wrap">
{body}
  </main>

  <footer class="site-footer" aria-label="Site footer">
    <div role="separator"><svg class="hp-marking" width="100%" height="28" aria-hidden="true" focusable="false"><defs><pattern id="hp-mk-evans" width="36" height="28" patternUnits="userSpaceOnUse"><rect class="edge" x="0.5" y="11.5" width="20" height="5" fill="currentColor" stroke-width="1"></rect></pattern></defs><rect x="0" y="0" width="100%" height="28" fill="url(#hp-mk-evans)"></rect></svg></div>
    <div class="site-footer__row">
      <p class="site-footer__copy data">Evans {version} · MIT licence · © Leon Górecki</p>
      <p class="site-footer__links data"><a href="{repo}">GitHub</a> · <a href="{releases}">Releases</a> · <a href="patch-notes.html">Patch notes</a> · <a href="patch-notes.html#report">Report an issue</a> ·<a href="{home}">leongorecki.eu</a></p>
    </div>
    <p class="site-footer__note">MATLAB and Simulink are registered trademarks of The MathWorks, Inc. Evans is an independent project, not affiliated with or endorsed by MathWorks.</p>
  </footer>
</body>
</html>
"""


def nav(current: str) -> str:
    items = []
    for file, label, *_ in PAGES:
        if file == current:
            items.append(f'<span class="hp-sign hp-sign--location hp-sign--sm" aria-current="page"><span>{label}</span></span>')
        else:
            items.append(f'<a class="hp-sign hp-sign--direction hp-sign--sm" href="{file}"><span>{label}</span></a>')
    return "".join(items)


def build(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE / "assets", out / "assets")
    shutil.copy(ROOT / "src/evans/ui/icons/app.svg", out / "assets/evans.svg")
    (out / "assets/shots").mkdir()
    for shot in ("theme-day.png", "theme-night.png"):
        shutil.copy(ROOT / "docs" / shot, out / "assets/shots" / shot)

    generated: dict[str, tuple[str, dict]] = {}
    stats: dict = {}
    for _, _, _, _, source in PAGES:
        if not source.endswith(".html"):
            generated[source] = getattr(reference, source)()
            stats.update(generated[source][1])

    from evans.sim import block_types
    fields = {
        "version": __version__,
        "n_commands": str(stats["commands"]),
        "n_blocks": str(len(block_types())),
        "releases": RELEASES,
        "repo": REPO,
    }
    for file, _, title, description, source in PAGES:
        if source in generated:
            body = generated[source][0]
        else:
            body = (SITE / "pages" / source).read_text(encoding="utf-8")
            for key, value in fields.items():
                body = body.replace(f"@@{key}@@", value)
        page = TEMPLATE.format(
            title=reference.esc(title), description=reference.esc(description),
            url=URL + ("" if file == "index.html" else file), home=HOME,
            back=ARROW.format(r=180), releases=RELEASES, repo=REPO,
            version=__version__, nav=nav(file), body=body)
        if "@@" in page:
            raise SystemExit(f"{file}: unfilled placeholder near "
                             f"{page[page.index('@@'):][:40]!r}")
        (out / file).write_text(page, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--out", type=Path, default=SITE / "_build")
    args = parser.parse_args(argv)
    stats = build(args.out)
    print(f"Built {len(PAGES)} pages into {args.out}: {stats['commands']} commands, "
          f"{stats['blocks']} blocks.")
    if stats["undocumented"]:
        print("Commands with no docstring: " + ", ".join(stats["undocumented"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
