# UI Redesign Plan

## Purpose

FauxMatlab already has a strong functional foundation: classical and modern control analysis, a block-diagram simulator, a MATLAB-shaped command window, lessons, plotting, design tools, and packaged builds. The main weakness is not missing functionality; it is that the interface has grown organically around an older six-tab layout.

This plan redesigns the application around a clearer mental model:

> **One control system, three workspaces, arrangeable panels, and a UI that remembers how the user works.**

The redesign should preserve the numerical engine and existing capabilities while making the application easier to understand, more usable on ordinary screens, and more coherent as a desktop engineering tool.

## Current problems

The current UI is centered on a permanent left-hand architecture panel and a flat tab bar in `fakematlab/ui/mainwindow.py`. This causes several measurable problems:

- The application can require approximately 2038 px of horizontal space because the Simulink toolbar is one unbreakable row.
- The permanent architecture/BlockEditor column consumes space on every analysis screen, including Simulink and Modern Control.
- Eight top-level tabs mix three different concepts: views of one analysis model, a block-diagram modeling environment, and a state-space workbench.
- LTI Viewer, Control System Designer, and PID Tuner behave as separate top-level windows instead of parts of one workflow.
- Emoji tab labels can render as missing-glyph boxes and are not a reliable accessible navigation mechanism.
- Important model and stability information is hidden in the status bar and displayed as coefficient arrays rather than readable transfer functions.
- The snapshot bar is always visible despite being an occasional workflow feature.
- Simulink block parameters use modal interactions, making it difficult to edit a block while keeping the diagram visible.
- Window geometry, dock positions, splitter sizes, and workspace state are not persisted.
- Panels do not follow one consistent spacing, typography, or density system.

## Design principles

1. **Preserve functionality.** This is a UI redesign, not a numerical rewrite. Existing analysis, simulation, console, lesson, export, and design features must remain available.
2. **Make the current model obvious.** The user should always know what plant/controller is loaded and whether the system is stable.
3. **Optimize for normal screens.** The application must work at 1280×720 and remain comfortable at 1920×1080.
4. **Use progressive disclosure.** Frequently used actions remain visible; advanced settings live in expandable panels, menus, or docks.
5. **Prefer one main window.** Related tools should be dockable panels rather than disconnected windows.
6. **Use one visual rhythm.** Shared spacing, panel headers, controls, icons, status badges, and error states should be implemented centrally.
7. **Keep state alive.** Switching workspaces or panels should not destroy the user's current analysis or model.
8. **Make errors actionable.** A failed calculation should explain what happened and how to recover; blank panels are not acceptable.

## Target information architecture

Replace the current eight-peer tab structure with three top-level workspaces.

```text
FauxMatlab
├── Analyse   Current control system: plots, metrics, stability, design, lessons
├── Model     Simulink-style block-diagram editor and simulation
└── Console   Command window, workspace, scripts, and figures
```

Suggested navigation:

- A compact left navigation rail or sidebar.
- Text labels plus bundled icons; no emoji as the primary navigation mechanism.
- `Ctrl+1` — Analyse
- `Ctrl+2` — Model
- `Ctrl+3` — Console
- A `View → Reset layout` action.

Each workspace owns its panel arrangement and restores it independently.

## Analyse workspace

Analyse is the primary workspace. It represents the currently loaded control system and provides multiple views of that same system.

### Model context bar

Replace the permanent left architecture column with a compact context bar across the top of Analyse.

Example:

```text
G(s) = 4 / (s² + 1.2s + 4)    K₂(s) = 2 + 1/s
● Stable    PM 60.0°    GM 11.9 dB                    [Edit model ▾]
```

The context bar should:

- Show readable factored transfer functions.
- Show the stability verdict using a clear status badge.
- Show useful headline metrics such as phase margin, gain margin, and bandwidth when defined.
- Provide a compact diagram or block summary.
- Open the detailed block editor in a popover or dock when requested.
- Make block selection and editing discoverable without permanently consuming 20–30% of the window.

### Analysis pane grid

Replace the six fixed analysis tabs with configurable content panes. The existing views remain available as pane types:

- System overview
- Step response
- Impulse and ramp response
- Bode magnitude and phase
- Nyquist
- Nichols
- Root locus
- Pole-zero map
- Stability and Routh analysis
- Performance metrics
- Sensitivity and complementary sensitivity
- Modern control
- Lessons

Support one-, two-, and four-pane layouts.

Example:

```text
┌─────────────────────────┬─────────────────────────┐
│ Step response            │ Bode plot               │
├─────────────────────────┼─────────────────────────┤
│ Root locus              │ Performance metrics     │
└─────────────────────────┴─────────────────────────┘
```

Every pane reads the same live architecture. Editing `G`, `K₁`, `K₂`, or `H` updates all visible panes consistently.

The existing `core/viewer.py` and LTI Viewer collection model should be reused where practical. LTI Viewer should become the multi-system form of the same analysis area rather than a separate conceptual application.

### Design and learning panels

Move the following into dockable Analyse panels:

- Control System Designer
- PID Tuner
- LTI Viewer controls
- Snapshot comparison
- Lessons
- Detailed model/block editor

The panels should remain connected to the shared architecture. Existing signals such as `compensator_applied` and `controller_applied` should continue to synchronize edits.

## Model workspace

The Model workspace should provide a dedicated, uncluttered Simulink workflow.

```text
┌──────────────┬─────────────────────────────┬───────────────┐
│ Block palette│ Canvas                      │ Properties    │
│              │                             │               │
│ Sources      │                             │ Selected block│
│ Continuous   │                             │ parameters    │
│ Discrete     │                             │               │
│ Math         │                             │               │
├──────────────┴─────────────────────────────┴───────────────┤
│ Scope / simulation output                                  │
└─────────────────────────────────────────────────────────────┘
```

### Toolbar

Refactor `SimTab._build_toolbar` in `fakematlab/ui/sim/sim_tab.py` into a real `QToolBar` or an equivalent responsive command surface.

Group actions into:

- Run / Stop
- Simulation settings
- Undo / Redo
- Canvas navigation
- Subsystem navigation
- Linearise
- Open / Save

Secondary commands should move into overflow menus rather than forcing the entire application to become wider.

### Canvas and properties

- Add a right-side properties panel.
- Replace modal parameter dialogs with an inspector that keeps the canvas visible.
- Show the selected block's parameters, validation state, and description.
- Add larger port hit areas.
- Keep a persistent hint strip explaining wiring: “Drag between ports, or click one port and then the other.”
- Add rubber-band selection, multi-selection, align, and distribute actions.
- Improve wire routing so wires avoid blocks where practical.
- Keep the scope/output view dockable and resizable.
- Preserve subsystem breadcrumbs and make the current hierarchy visually clear.

## Console workspace

The existing command window, workspace browser, figures, and script editor should form a complete Console workspace rather than appearing as secondary docks that are hidden by default without a broader navigation model.

Recommended arrangement:

```text
┌───────────────────────────────┬───────────────────────────┐
│ Command transcript             │ Workspace                 │
│                               │ Variables                 │
│                               │ Systems                   │
├───────────────────────────────┴───────────────────────────┤
│ Figures / script editor                                    │
└────────────────────────────────────────────────────────────┘
```

Requirements:

- Preserve the live relationship between console variables and the GUI model.
- Keep command history and completion prominent.
- Allow figures to open as tabs or docked panels in the Console workspace.
- Make script execution and its errors easy to trace to a line.
- Support a compact mode for users who prefer the command window as a dock beside Analyse.

## Modern Control redesign

The Modern Control surface currently has a high control density. Reorganize it by user task rather than exposing many unrelated controls together.

### Model

- State-space matrices
- Transfer-function conversion
- Similarity transforms
- Canonical forms
- Minimal realization

### Structural analysis

- Controllability
- Observability
- PBH tests
- Stabilizability and detectability
- Gramians
- Balanced realization and reduction

### Controller design

- Pole placement
- Ackermann
- LQR and LQI
- Reference scaling
- Control effort

### Estimation

- Luenberger observer
- Reduced-order observer
- Kalman filter
- Observer-based compensator
- Separation principle

### Discrete systems

- Continuous/discrete conversion
- Jury stability
- Deadbeat control
- Sampling-rate sweeps
- Discrete pole maps

Use a consistent two-column layout where inputs and parameters are separated from results and plots. Avoid presenting all controls at once.

## Visual design system

Create shared UI primitives and styling rather than styling each tab independently.

### Spacing and layout

Use a small spacing scale:

- 4 px — compact internal spacing
- 8 px — standard control spacing
- 12 px — section spacing
- 16 px — major panel spacing

Prefer layouts that can shrink gracefully. Avoid fixed widths unless they are required for legibility.

### Shared components

Create reusable components such as:

- `PanelHeader`
- `SectionCard`
- `MetricCard`
- `StatusBadge`
- `ToolbarGroup`
- `ContextBar`
- `EmptyState`
- `ErrorBanner`
- `PropertyEditor`

### Typography and labels

- Use consistent heading levels.
- Use plain-language action labels.
- Keep technical notation in plot labels and model summaries where it helps.
- Replace coefficient-array summaries with factored, readable expressions.
- Do not rely on emoji to communicate meaning.

### Status and severity

Use consistent visual states:

- Neutral / informational
- Success / stable
- Warning / incomplete or undefined
- Error / failed computation
- Critical / unstable system

Color should not be the only indicator; pair badges with text and accessible symbols.

## Error and feedback behavior

The existing guarded-panel/error-banner foundation should be extended consistently.

Every analysis panel should provide:

- A useful empty state before the first calculation.
- Inline validation for invalid inputs.
- A clear explanation when a metric is undefined.
- A recoverable error message instead of a blank plot.
- An expandable technical-details section for debugging.
- Progress and cancellation feedback for long simulations.

Example:

```text
Phase margin is undefined

The selected system does not cross 0 dB, so no phase-margin crossover exists.

[Show details] [Change signal]
```

## Layout persistence

Use `QSettings` to persist:

- Window geometry
- Current workspace
- Dock visibility and positions
- Splitter sizes
- Selected pane layout
- Last-used solver settings
- Recent sessions
- Optional panel visibility

Restore layout on startup, but provide a reliable reset action when a saved layout becomes unusable.

## Accessibility and usability requirements

- Keyboard navigation for all major actions.
- Tooltips for icon-only buttons.
- Meaningful accessible names for controls.
- No emoji-only labels.
- Sufficient contrast for statuses, warnings, and plot annotations.
- Focus order that follows the visual order.
- Do not encode important information only through color.
- Ensure the application remains usable without a mouse for common analysis and simulation tasks.

## Implementation phases

Each phase should be independently reviewable and should preserve existing functionality.

### UI-1 — Make it fit

**Scope:** Responsive sizing and toolbar cleanup.

- Rebuild the Simulink toolbar as a responsive toolbar with overflow.
- Audit `setMinimumWidth`, `setMaximumWidth`, and fixed-size constraints in `fakematlab/ui/`.
- Make the model/editor panel collapsible.
- Add a regression test for minimum-size behavior.

**Acceptance:** The application can open and render the main workspaces at 1280×720. No single tab or toolbar forces a multi-thousand-pixel window.

### UI-2 — Context bar and model panel

**Scope:** Replace the permanent architecture column in Analyse.

- Build the model context bar.
- Display readable transfer functions and stability status.
- Move detailed block editing into a popover or dock.
- Keep a compact architecture preview available.

**Acceptance:** Analyse gives at least 85% of the window to analysis content at 1280 px width, and the stability verdict is visible without opening a separate analysis tab.

### UI-3 — Workspaces and persistence

**Scope:** Add Analyse, Model, and Console navigation.

- Add the navigation rail/sidebar.
- Establish workspace-specific layouts.
- Add `QSettings` save/restore.
- Add `View → Reset layout`.
- Preserve each workspace's live widget state when switching.

**Acceptance:** Switching workspaces does not lose model, simulation, console, or analysis state. Closing and reopening restores geometry and layout.

### UI-4 — Analysis pane grid

**Scope:** Replace the flat classical tab experience.

- Create configurable analysis panes.
- Migrate existing System, Time, Frequency, Stability, Performance, and Design content into pane types.
- Support one-, two-, and four-pane layouts.
- Reuse the LTI Viewer collection model for multiple systems.

**Acceptance:** A two-by-two layout containing step response, Bode, root locus, and metrics updates together after one architecture edit. Every existing response type remains reachable.

### UI-5 — Dockable applications

**Scope:** Integrate LTI Viewer, Control System Designer, PID Tuner, Lessons, and snapshots.

- Replace top-level windows with dockable panels where appropriate.
- Ensure console commands reveal the relevant panel.
- Keep existing app sinks and synchronization signals working.

**Acceptance:** No required workflow opens an uncontrolled secondary window. Clicking a controller/design action visibly updates the shared Analyse workspace.

### UI-6 — Simulink ergonomics

**Scope:** Improve Model workspace interactions.

- Add properties inspector.
- Improve wiring instructions and hit areas.
- Add selection, alignment, and distribution tools.
- Improve wire routing.
- Make scope output a first-class dock/panel.

**Acceptance:** Block parameters can be edited with the diagram visible. Common wiring and selection workflows are discoverable and testable.

### UI-7 — Modern Control regrouping

**Scope:** Reduce density and organize by task.

- Group the existing Modern views into Model, Structure, Design, Estimation, and Discrete sections.
- Standardize forms and results panels.
- Preserve the shared `ModernContext` behavior and model bridges.

**Acceptance:** Existing Modern Control features remain available, but a new user can identify where to enter a model, design a controller, or configure an observer without scanning a dense form.

### UI-8 — Visual polish and hardening

**Scope:** Apply the design system everywhere.

- Replace remaining emoji navigation.
- Apply shared panel headers, spacing, controls, status badges, and empty states.
- Add accessibility names and keyboard shortcuts.
- Add UI smoke tests for major layouts and workspace transitions.
- Test at 1280×720, 1366×768, and 1920×1080.

**Acceptance:** The interface feels like one application rather than separately built feature areas, and UI regressions are caught by automated tests.

## Recommended first milestone

The highest-value initial implementation should be UI-1 plus the most visible parts of UI-2:

1. Make the application fit at 1280×720.
2. Replace the oversized Simulink toolbar.
3. Make the model panel collapsible.
4. Replace emoji navigation labels with icons or clear text.
5. Add shared panel/spacing styling.
6. Add a readable model context bar.
7. Add UI regression tests.
8. Preserve all numerical behavior and existing features.

This milestone should be delivered as a focused pull request before attempting the larger Analyse pane-grid migration.

## Out of scope

This plan does not require:

- Rewriting the numerical/control engine.
- Replacing pyqtgraph.
- Adding a custom theme solely for visual novelty.
- Building a ribbon interface.
- Adding MATLAB `.m` parsing.
- Removing or hiding advanced functionality.
- Replacing native Qt behavior where it is already reliable.

The goal is a clearer, more professional, more responsive interface around the existing capabilities.

---

## Implementation status

Tracked here rather than by editing the phases above, so the plan stays as written.

| Phase | State | Notes |
|---|---|---|
| UI-1 — Make it fit | **done** | Simulink toolbar is a `QToolBar` with overflow. Window minimum 2038×643 → 840×685; the app resizes to 1280×720. Regression test asserts the budget and that no single panel dictates the window width. |
| UI-2 — Context bar and model panel | **done** | `ui/context_bar.py`: factored transfer functions, internal-stability badge, PM/GM/ωc. Diagram and block editor moved to a dock behind Ctrl+\. Analysis area is 99 % of the width at 1280 px. |
| UI-3 — Workspaces and persistence | **done** | `ui/workspace.py`: Analyse / Model / Console on a rail, Ctrl+1/2/3. `QStackedWidget`, so switching preserves live state. `QSettings` on close; View ▸ Reset layout. The console and figures stopped being hidden docks and became the Console workspace. |
| UI-4 — Analysis pane grid | **done** | `ui/panes.py`: 1 / 1×2 / 2×2, fourteen pane kinds. Plot panes *are* `LTIViewer` in compact mode, so the viewer is the multi-system form of the same renderer. Root locus added to `core/viewer.py` as a response kind. The classic tabs remain beside the grid. |
| UI-5 — Dockable applications | **done** | LTI Viewer, Control System Designer and PID Tuner are tabbed docks in Analyse. Opening one from the console navigates to the workspace its edits land in. One top-level window with all three open. |
| UI-6 — Simulink ergonomics | **done** | Click-click wiring fixed; `ui/sim/inspector.py` replaces the modal parameter dialog; port hit areas widened without changing the drawn mark; a standing wiring hint; rubber-band selection; align and distribute as one undo step. Wire routing still draws straight lines. |
| UI-7 — Modern Control regrouping | **done** | The five views renamed to the plan's vocabulary (Model / Structure / Design / Estimation / Discrete), each with a tooltip and accessible name saying what it is for. Control columns scroll instead of dictating width. |
| UI-8 — Visual polish and hardening | **mostly** | Emoji gone from every button and tab label, enforced by a test. `ui/design.py` primitives used by all new surfaces. Tested at 1280×720, 1366×768 and 1920×1080. Still outstanding: retrofitting the six classic analysis tabs onto the design system, and a bundled icon set. |

### Where it ended up

```
MainWindow.minimumSizeHint()   2038 × 643   →   920 × 344
SimTab minimum width                 1602   →       152
Top-level windows with every app open   7   →         1
Analysis area at 1280 px               —    →       99 %
Tests                                 598   →       674
```

### Things found while implementing

**Qt flattens a `str`-mixin enum through `QVariant`.** `QComboBox.currentData()` returns a
plain `str` that compares and hashes equal to the member, so every dict lookup keeps working
and the only symptom is `.value` raising somewhere else entirely. It bit the LTI Viewer's
response picker and then the pane's source picker; both now rebuild the member from the
combo's text.

**A non-proper closed loop has no time response.** Closing the unity-feedback loop around the
course's non-minimum-phase plant `(1−s)/(1+s)` gives `T = (1−s)/2` — more zeros than poles, no
state-space realisation, no step response. It is reachable from the Presets menu, and it used
to surface as a raw `ValueError` in an error banner. It is a property of the system, not a
failure to compute, so `core/viewer.py` now says so and the pane shows an empty state with the
reason.

**Word-wrapped help text is taller the narrower it gets.** The classic analysis tabs fit at
1400 px and then wanted 748 px of window height at 1280 px, because their control columns wrap.
A height-for-width effect, not a fixed size, and invisible to any check that measures at one
width only. They are scrolled now, so a secondary view cannot set the application's minimum.

**A test that shares a window has to put it back.** The resolution tests measure minimum sizes,
so a pane another test left showing the Modern tab, or an app dock left open, changes the next
test's answer. The reset fixture now restores the workspace, the view, the pane layout *and*
the pane kinds.
