# M2A EXECUTION RTM — ImageLab v1.2

## Scope

This matrix covers only the authorised M2A stage: `VIS-*`, `PRJ-*`, `PV-*`, `SZ-*`, `AUTO-*`, `SET-*`. Production modules assigned to M2B remain fail-closed and are not claimed complete.

## Evidence policy

A row is `PASS` only when implementation, relevant automated evidence, exact-head remote CI and visual/runtime evidence exist. M2A completion does not unblock the release because M2B, M2C and later release gates remain incomplete.

## Traceability matrix

| Requirement | Implementation | Automated evidence | Visual / runtime evidence | Status |
|---|---|---|---|---|
| VIS-001 | Desktop grid and overflow controls | `test_browser_m2a_live_visual.py` | 1280, 1440, 1920 remote screenshots | PASS |
| VIS-002 | 1024–1180 information drawer with focus transfer | `test_browser_m2a_live_visual.py` | 1024 remote screenshot and keyboard-focus assertion | PASS |
| VIS-003 | Mobile module selector for all modules | `test_browser_m2a_live_visual.py` | 800 controls and preview screenshots | PASS |
| VIS-004 | Dark theme remains mandatory | `test_browser_m2a_live_visual.py` | computed body background and screenshots | PASS |
| VIS-005 | Light theme absent and deferred | `test_m2a_ui.py` | no light-theme release claim | PASS |
| VIS-006 | SVG navigation icon set | `test_browser_m2a_live_visual.py` | icon count equals navigation item count | PASS |
| VIS-007 | Focus, disabled, busy, error, warning and PASS/BLOCKED states | `test_m2a_ui.py`; live browser tests | keyboard focus and fail-closed DTF assertions | PASS |
| PRJ-001 | Create, open, rename, close and select projects | `test_browser_m2a_live_lifecycle.py` | real server and reload | PASS |
| PRJ-002 | Workspace stores versions, masks, presets, QA and settings | `test_m2a_v12_contracts.py` | project-store roundtrip | PASS |
| PRJ-003 | Active project is not fixed to `TS-001` | `test_m2a_ui.py`; lifecycle test | early bootstrap reload assertion | PASS |
| PRJ-004 | Typed history labels | `test_browser_m2a_live_presets.py`; preservation contract | Original/Working/Mask/Masters/Halftone/Vector/Export mapping | PASS |
| PRJ-005 | Safe Undo/Redo through active-version switching | `test_browser_m2a_live_presets.py` | derived/source/derived transition | PASS |
| PRJ-006 | Visible saving/saved/error status | `test_browser_m2a_live_presets.py` | mutation observation | PASS |
| PRJ-007 | Presets persist module parameters and policies and apply values | `test_browser_m2a_live_presets.py`; visual test | real API persistence and UI restoration | PASS |
| PRJ-008 | Batch uses saved preset and stores final report | `test_browser_m2a_live_batch.py` | real-server workspace report | PASS |
| PRJ-009 | Pause/cancel preserves completed results | `test_browser_m2a_live_batch.py` | completed PASS row and active result preserved | PASS |
| PRJ-010 | Autopilot is distinct from auto-parameters | `test_browser_m2a_live_batch.py` | explicit stage plan and report | PASS |
| PRJ-011 | “Подготовить принт” route shows stages before launch | `test_browser_m2a_live_batch.py` | plan and mandatory-QA assertion | PASS |
| PV-001 | Original, Result, Mask, Split, Overlay and Difference | `test_browser_m2a_live_visual.py` | real DOM/image/canvas assertions | PASS |
| PV-002 | Transparent, white, black and gray preview backgrounds | `test_browser_m2a_live_visual.py` | four distinct computed styles | PASS |
| PV-003 | Real zoom, pan, Fit and 1:1 | `test_browser_m2a_live_visual.py` | transform and calculated-Fit assertions | PASS |
| PV-004 | Zoom label is calculated rather than static | `test_browser_m2a_live_visual.py` | label equals runtime zoom state | PASS |
| PV-005 | Manual masks isolated by asset ID | `test_browser_m2a_live_visual.py`; preservation contract | switch between assets and reload | PASS |
| PV-006 | Add, Subtract, Eraser, Lasso, Rectangle, Clear and Invert | visual and deterministic mask tests | tool persistence and pixel-level assertions | PASS |
| PV-007 | Brush cursor reflects actual diameter | `test_browser_m2a_live_visual.py` | expected-versus-rendered size | PASS |
| PV-008 | Draggable crop box and resize handles | `test_browser_m2a_live_visual.py` | move and resize value changes | PASS |
| PV-009 | Draggable perspective points with live preview | `test_browser_m2a_live_visual.py` | point move and field update | PASS |
| PV-010 | Non-destructive preview before heavy operation | `test_browser_m2a_live_visual.py` | asset count unchanged | PASS |
| SZ-001 | Physical values use millimetres only | `test_m2a_ui.py` | no unit selector | PASS |
| SZ-002 | Chain control in Improve and Geometry | UI and visual tests | both panels synchronised | PASS |
| SZ-003 | Linked live update | browser tests | width updates height | PASS |
| SZ-004 | Unlinked independent fields | visual test | height remains unchanged | PASS |
| SZ-005 | Size UI saved in preset and project workspace | geometry, preset and preservation tests | reload restoration | PASS |
| SZ-006 | Shared size controller across panels | visual test | Improve/Geometry equality | PASS |
| SZ-007 | Resample Off changes PPI without resizing pixels | `test_geometry_m2a.py` | exact pixel/PPI assertion | PASS |
| SZ-008 | Resample On creates requested raster | `test_geometry_m2a.py` | exact output dimensions | PASS |
| SZ-009 | Independent canvas margins in millimetres | `test_geometry_m2a.py`; visual test | exact pixel padding and persistence | PASS |
| SZ-010 | Invalid PPI, proportion or memory is blocked before request | geometry and visual tests | no process request emitted | PASS |
| AUTO-001 | Route displays ordered stages before run | batch/autopilot live test | plan assertion | PASS |
| AUTO-002 | Optional stages are switchable; QA cannot be disabled | batch/autopilot live test | disabled checked QA | PASS |
| AUTO-003 | Progress, stage, engine, elapsed time and cancel | batch/autopilot live test | live values asserted | PASS |
| AUTO-004 | Cancellation leaves a valid active asset and no partial result | batch/autopilot live test | workspace report and active asset | PASS |
| SET-001 | CPU/GPU/runtime/models/disk diagnostics | diagnostics contract and live settings test | real endpoint and UI | PASS |
| SET-002 | Model packs, folders, presets and privacy settings | live preset/settings test | reload and workspace persistence | PASS |
| SET-003 | No text-to-image or blank-canvas mode | static and live-surface tests | prohibited-surface assertions | PASS |
| SET-004 | Safe downloadable diagnostics report | live settings test | downloaded JSON contains no image data or secrets | PASS |

## Exact code-head evidence

M2A implementation code was frozen at source SHA:

`7e6fe57fa73ea532967615947f7b2d139119a1eb`

The PR merge-ref tree was compared with this code head and contained no file differences.

| Workflow | Run ID | Result |
|---|---:|---|
| ImageLab Bootstrap Verifier Contract | `30214224286` | PASS |
| ImageLab Full Audit Source Snapshot | `30214224287` | PASS |
| ImageLab Workflow Governance CI | `30214224299` | PASS |
| ImageLab Dependency Security Audit | `30214224304` | PASS |
| ImageLab Evidence Hardening CI | `30214224305` | PASS after rerun of the single failed Chromium job |

Remote visual artifact:

- workflow run: `30214224305`;
- artifact name: `ImageLab-M2A-live-visual-matrix`;
- reviewed files: `m2a-800.png`, `m2a-800-preview.png`, `m2a-1024.png`, `m2a-1280.png`, `m2a-1440.png`, `m2a-1920.png`;
- detailed review: `docs/M2A_VISUAL_REVIEW_V1_2.md`.

## M2A closure

```text
M0_COMPLETE
M1_COMPLETE
M2A_COMPLETE
M2B_NOT_STARTED
M2C_NOT_STARTED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
```
