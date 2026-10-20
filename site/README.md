# The Evans site

The documentation and download site, served at
[www.leongorecki.eu/evans](https://www.leongorecki.eu/evans/). It is plain HTML on the
Holding Point design system, the same CSS and fonts as leongorecki.eu, so the docs read as
part of that site.

Build it from the repository root, with Evans's dependencies installed (`pip install -e .`):

```bash
python site/build.py
```

That writes `site/_build/`. Open `site/_build/index.html`, or serve the folder with
`python -m http.server -d site/_build` to see it as it will be published.

| Path | What it is |
| --- | --- |
| `build.py` | The page template, the navigation and the build |
| `reference.py` | The generated pages: console commands, simulator blocks, lessons |
| `pages/` | The hand-written pages (home, install, tour, MATLAB compatibility) as HTML fragments |
| `assets/` | `site.css`, plus `tokens.css`, `components.css`, `theme.js` and the fonts copied from the website's repository |

The command, block and lesson pages are read out of the code (`api._GROUPS` and the
commands' docstrings, the block registry and each block's `params_spec`, the lessons and
their claims), so they cannot drift from it. The build exits non-zero if a lesson claim no
longer holds, and `tests/test_site.py` builds the site and checks that every command,
block and lesson is on it. In the hand-written pages, `@@version@@`, `@@n_commands@@`,
`@@n_blocks@@`, `@@n_lessons@@`, `@@releases@@` and `@@repo@@` are filled in from the code.

`.github/workflows/pages.yml` builds the site on every push and pull request and deploys it
from `main`, which needs the repository's Pages source set to **GitHub Actions**.
