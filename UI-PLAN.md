# UI plan — from "v1's layout with seven phases bolted on" to something usable

The engine grew from 6 modules to 28 and from 6 tabs to 8 tabs + 3 docks + 3 app
windows. The **layout never changed**. It is still the shape chosen when this was a
six-tab classical-control viewer: a fixed left column, a flat tab bar, and a status
line. Every phase since has added a surface to the edges of that shape rather than
reconsidering it.

This document is measured first and opinionated second. Part 0 is what I reproduced;
everything after it is a proposal.

---

## Part 0 — What is actually wrong, measured

### 0.1 The window does not fit on a normal screen

```
MainWindow.minimumSizeHint() = 2038 × 643
```

`resize(1366, 768)` → the window comes back **2038 px wide**. So does `resize(1920, …)`.
It is not a preference; the layout physically cannot be made narrower. On a 1920×1080
monitor 118 px hang off the edge. On a 1366×768 laptop, a third of the app is
unreachable.

The cause is one widget:

| Tab | minimum width |
|---|---|
| System | 384 |
| Time | 448 |
| Frequency | 383 |
| Stability | 393 |
| Performance | 394 |
| Design | 354 |
| **Simulink** | **1602** |
| Modern | 820 |

`SimTab._build_toolbar` ([sim_tab.py:114](fakematlab/ui/sim/sim_tab.py:114)) is a single
`QHBoxLayout` that cannot wrap, holding: Run, Stop, "Stop time" + spin box, "Solver" +
combo, "Step" + spin box, Undo, Redo, Fit, Up, a breadcrumb label, Linearise, a stretch,
a progress bar and more buttons. 1602 px in one unbreakable row. Add the 420 px left
column and the splitter handles and you get 2038.

A tab bar makes every tab as wide as the widest one, so **the Simulink toolbar sets the
minimum size of the entire application**, including for someone who only ever opens the
Bode plot.

### 0.2 A fifth of the window is spent on something most tabs do not use

At 2038 px:

| Region | Size | Share |
|---|---|---|
| Fixed 2-DOF diagram | 420 × 260 | 7.0 % |
| Block editor | 420 × 457 | 12.3 % |
| Snapshot bar | 1606 × 22 | 2.3 % |
| Tab area | 1606 × 695 | 71.3 % |

The left column is **420 px minimum, 760 px maximum, on every tab** — 21 % of the
window. It shows the ch.5 architecture and an editor for its four blocks.

That is the right thing to show on System, Time, Frequency, Stability, Performance and
Design. It is **irrelevant on Simulink** (a different model entirely) and **irrelevant
on Modern** (which has its own state-space entry). So two of eight tabs pay a 21 %
tax for a picture of something they are not showing.

### 0.3 Eight sibling tabs that are not siblings

The tab bar presents eight peers. They are three different things:

- **Six views of one architecture** — System, Time, Frequency, Stability, Performance,
  Design all analyse the same `CourseArchitecture` and change together.
- **A block-diagram editor** with its own `SimModel`, its own undo stack, its own file
  format, connected to the rest only through `linearize()`.
- **A state-space workbench** with its own model and its own send-back-to-analysis
  bridge.

Putting them on one strip implies they are alternatives to one another. They are not:
you use Simulink *to produce* something the other six analyse. The flat list also gives
no answer to "where do the three app windows live?", which is why they ended up as
separate top-level windows.

### 0.4 Seven top-level surfaces, none of which remember anything

Main window, console dock, figure dock, lesson dock, LTI Viewer, Control System
Designer, PID Tuner. All can be open at once, in front of each other, on a window that
is already wider than the screen.

```
QSettings         False
saveGeometry      False
restoreGeometry   False
saveState         False
restoreState      False
closeEvent        False
```

Nothing is persisted. Every launch puts the splitter back at 420 px, hides the console,
forgets which tab you were on, and drops every dock you had arranged.

### 0.5 Density varies by an order of magnitude

| Tab | buttons | labels |
|---|---|---|
| Frequency | 3 | 7 |
| Design | 6 | 12 |
| **Modern** | **27** | **35** |

The Modern tab is a five-view sub-tab widget wearing the same chrome as a tab with one
plot and three buttons. There is no shared rhythm — each tab was laid out by whatever
phase built it.

### 0.6 Small things that compound

- **Emoji tab labels** (`🔬 System`, `⛓ Simulink`) render as empty boxes wherever the
  emoji font is missing — as they do in every screenshot from this project's own
  headless renderer. They also cannot be searched or read aloud.
- **The status bar is the only "what am I looking at" indicator**, and it shows
  `G=[1, 2]/[1, 3, 3, 1]  K₂=[4]/[1]` — coefficient lists, not a factored transfer
  function, and no stability verdict.
- **The snapshot bar is always visible** on every tab, spending 22 px of vertical space
  on a feature used a few times per session.
- **Simulink parameters are modal dialogs** on double-click, so you cannot see a block's
  parameters and the diagram at the same time, and you cannot compare two blocks.
- **Nothing on screen says how to draw a wire.** The status label says it *after* you
  click a port.

### 0.7 Fixed already, while investigating this

**Wiring was genuinely broken, not just awkward.** Reproduced with synthetic mouse
events on the real handlers:

| Gesture | Before | After |
|---|---|---|
| Drag port → port | connects | connects |
| **Click port, click port** | **nothing happens** | connects |
| Click port, release on empty space, click target | **nothing happens** | connects |
| Click input first, then output | — | connects |
| 10 abandoned attempts | **10 dashed lines left in the scene** | clean |

`mousePressEvent` called `_start_wire` unconditionally, so the *second* click restarted
the wire instead of finishing it, and orphaned the first rubber band in the scene. Only
press-drag-release ever worked.

It survived the test suite because every existing wiring test called `_start_wire` and
`_finish_wire` **directly** — the event handlers themselves had no test. Fixed in
[canvas.py](fakematlab/ui/sim/canvas.py), with six tests that synthesise real mouse
events.

---

## Part 1 — What the UI should be

One sentence: **one subject, three workspaces, panels that the user arranges and the
app remembers.**

The subject is the control system. Simulink and the state-space editor are *ways of
producing* one; the analysis views are *ways of looking at* one; the console is a way of
doing either by typing. The layout should say that.

### D1 — Three perspectives, not eight tabs

A narrow icon rail on the left with three destinations, `Ctrl+1/2/3`:

| Perspective | Contains |
|---|---|
| **Analyse** | The current system: response panels, the design tools, the lessons |
| **Model** | The Simulink canvas, its palette, its scopes |
| **Console** | Command window, workspace, figures — at full size, not a 200 px dock |

Each perspective owns a dock layout and restores it. Switching does not destroy state.

*Why not keep tabs:* a tab bar's meaning is "these are alternatives". Six of the eight
are not alternatives to each other, they are simultaneous views — which is exactly why
users end up wanting two at once and cannot have it.

### D2 — A context bar instead of a left column

One strip across the top of **Analyse**, always visible, showing what is loaded:

```
G(s) = 4/(s² + 1.2s + 4)     K₂ = 2 + 1/s     ●  stable   PM 60.0°  GM 11.9 dB   [⌄]
```

- The small 2-DOF schematic collapses into it; click a block to edit that block.
- Clicking the chevron expands the full block editor as a popover, not a permanent 21 %
  column.
- The stability dot is the single most useful thing the app knows and currently is not
  shown until you open a tab.

This reclaims the 420 px column on every view and replaces the coefficient-soup status
line.

### D3 — Analysis is a pane grid, and the LTI Viewer *is* that grid

Inside **Analyse**, choose 1 / 2 / 4 panes; each pane picks its content from one list
(step, impulse, Bode, Nyquist, Nichols, pole-zero, root locus, metrics, Routh,
performance, state space, …). Panes share the current system and update together.

This is what `LTIViewer` already does over a `SystemCollection`
([core/viewer.py](fakematlab/core/viewer.py)). Fold it in rather than keeping it as a
separate window: the viewer becomes "the analysis area with more than one system
loaded". Six tabs collapse into a grid the user configures, and the seventh window
disappears.

### D4 — The apps become panels

Control System Designer and PID Tuner become dockable panels inside **Analyse**, beside
the pane grid, not free-floating windows. They already emit `compensator_applied` /
`controller_applied` into the shared architecture — as panels that becomes visibly a
live edit of the thing on screen instead of a change in another window.

Seven top-level surfaces → one, with docks.

### D5 — Nothing may set a minimum wider than 1280

A hard budget, enforced by a test. Concretely:

- The Simulink toolbar becomes a real `QToolBar` with overflow (or two collapsing rows).
- The palette's `setMinimumWidth(180)` becomes a *preferred* width with a collapse
  button.
- Every panel gets a `minimumSizeHint` that reflects what it needs to be *legible*, not
  what it needs to show every control at once.
- Long control rows scroll or overflow rather than dictating window size.

### D6 — Persist the layout

`QSettings` on `closeEvent`: window geometry, dock state per perspective, current
perspective, splitter positions, last-used solver settings. Restore on launch, with
"Reset layout" in the View menu for when it goes wrong.

### D7 — One visual rhythm

- Tab/rail labels: words, with an icon **from a bundled icon set**, not emoji.
- One spacing scale (4/8/12/16), one heading style, one place for a panel's actions.
- The Modern tab's 27 buttons get grouped into the same pane-grid idea rather than five
  sub-tabs of dense forms.

---

## Part 2 — Phases

Ordered so that each one is shippable on its own and the most painful problem goes
first. Estimates are focused days.

### UI-1 — Make it fit (0.5–1 d) · highest value per hour

The only phase that fixes a *defect* rather than a design.

1. Rebuild `SimTab._build_toolbar` as a `QToolBar` with overflow.
2. Audit every `setMinimumWidth` / `setFixedWidth` in `fakematlab/ui/`.
3. Give the left column a collapse toggle (`Ctrl+\`) and remember it.

**Acceptance.** A test asserting `MainWindow.minimumSizeHint()` fits inside 1280 × 720,
and that every tab renders clean at that size. This is a regression test the project
does not currently have and would have caught the 2038 px minimum the day it appeared.

### UI-2 — Context bar, and reclaim the left column (1–1.5 d)

Build the context bar (D2), move the block editor into a popover, make the diagram
collapsible. Delete the permanent left column.

**Acceptance.** The analysis area is ≥ 85 % of the window width at 1280 px (currently
79 % at 2038 px and unavailable below that). The stability verdict is visible without
opening a tab.

### UI-3 — Perspectives (1–2 d)

The icon rail, three perspectives, `QSettings` persistence (D1, D6). Tabs inside
**Analyse** remain for now — this phase is about the top-level shape and about layout
memory, not about the grid.

**Acceptance.** Switching perspectives preserves state; closing and reopening the app
restores geometry, perspective and dock arrangement; "Reset layout" works.

### UI-4 — The pane grid, and fold in the LTI Viewer (2–3 d)

D3. The six analysis tabs become pane *contents*; the viewer's collection becomes "how
many systems are loaded". This is the largest change and the one that most needs
UI-1..3 done first.

**Acceptance.** Every response type that exists today is reachable as a pane; a 2×2 grid
of step + Bode + root locus + metrics updates together from one architecture change;
snapshots appear as additional curves rather than a separate window.

### UI-5 — Apps as panels (1 d)

D4. Designer and PID Tuner move into docks. Delete the separate-window plumbing in
`MainWindow._show`.

**Acceptance.** No app opens a top-level window; `open_app` docks instead; the console
commands `sisotool`/`pidtuner` still work and now reveal the panel.

### UI-6 — Simulink ergonomics (1–1.5 d)

- A **properties panel** docked beside the canvas, replacing modal parameter dialogs.
- Larger port hit areas and a persistent hint strip ("drag between ports, or click one
  then the other").
- Wire routing that avoids blocks instead of drawing straight through them.
- Rubber-band selection, and align/distribute.

**Acceptance.** Parameters editable with the diagram visible; a wire between two blocks
with a third between them does not cross it.

### UI-7 — Visual polish (1 d)

D7. Icon set, spacing scale, consistent panel headers, the Modern tab regrouped.

**Total ≈ 8–11 focused days.**

---

## Part 3 — What I would do if there were only two days

**UI-1 and UI-2.** They remove the two measured problems — the app not fitting on a
screen, and a fifth of the window spent on something most views do not use — and they
do not require restructuring anything. Everything after that is genuinely a design
improvement rather than a defect fix, and can wait.

## Part 4 — What I would not do

- **A full theming pass / custom stylesheet.** Qt's native look is fine and a hand-rolled
  dark theme is a maintenance burden that fights the platform.
- **A ribbon.** The command surface is not wide enough to need one.
- **Floating tool windows as the default.** They are the current problem, not the fix.
- **Rewriting the plot layer.** pyqtgraph is doing its job; the panels around it are the
  problem.
