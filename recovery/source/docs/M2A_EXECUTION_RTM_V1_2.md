# ImageLab v1.2 — M2A EXECUTION RTM

## Authorization and source of truth

- Approved specification: `ImageLab_FINAL_EXECUTION_SPEC_v1.2_APPROVED.docx`.
- User authorization: M2A `Scope и UI completeness` only.
- Approved baseline before M2A: `35dd66bca9b31f2e9c098063a5382cd4f1c09cd6`.
- M2B–M7 remain outside scope and `NOT STARTED`.
- Release remains `FAIL-CLOSED / RELEASE BLOCKED`.

## Capability Gate

| Gate | Result | Evidence / restriction |
|---|---|---|
| Exact M1 baseline is active | PASS | PR head was restored to `35dd66b...` before M2A authorization. |
| Repository write path is available | PASS | Changes are limited to the authorised PR branch. |
| Real-browser testing is available | PASS | Playwright/Chromium is supported in GitHub Actions. |
| Screenshot matrix is available | PASS | Artifacts can be generated at 800, 1024, 1280, 1440 and 1920 px. |
| M2A can be isolated from production M2B logic | PASS | Visible module shells may be added; production-ready claims and M2B algorithms are prohibited. |
| Physical Windows L5 is available in this stage | NOT APPLICABLE TO M2A | Hosted browser evidence cannot be claimed as L5. |
| Release/merge/Genesis authorization | BLOCKED | Explicitly outside M2A and prohibited by GOV-010. |

## Evidence policy

A row may become `PASS` only when all listed implementation, automated test, browser evidence and artifact criteria are satisfied on one frozen M2A code SHA. Static presence alone is not PASS. Visual review is mandatory for VIS/PV/SZ surface requirements. Claims cannot exceed evidence.

## Traceability matrix

| Requirement | M2A action | Test | Evidence | Artifact | PASS criterion | Status |
|---|---|---|---|---|---|---|
| GOV-001 | Keep v1.2 as the only implementation source | Static governance test | Repository contract | This RTM | No conflicting scope/source statement | IN PROGRESS |
| GOV-002 | Give every M2A requirement an RTM row | RTM completeness test | ID coverage | This RTM | VIS, PRJ, PV, SZ and M2A slices of AUTO/SET covered | IN PROGRESS |
| GOV-003 | Maintain action/test/evidence/artifact/PASS/status before code | Static RTM test | Commit order and document | This RTM | RTM commit precedes implementation commits | IN PROGRESS |
| GOV-004 | Start M2A only from explicit user authorization | Governance record | PR history | PR comment + RTM | Authorization is recorded; no earlier work is claimed | IN PROGRESS |
| GOV-005 | Expose confirmed modules separately | Browser navigation test | Real DOM and screenshots | UI matrix artifact | No confirmed module is hidden inside Export | IN PROGRESS |
| GOV-006 | Separate CI/browser evidence from physical L5 | Claim test | RTM wording | This RTM | No hosted check is labelled L5 | IN PROGRESS |
| GOV-007 | Preserve RELEASE BLOCKED | Static and browser status tests | UI/RTM | This RTM | Any incomplete later gate keeps release blocked | IN PROGRESS |
| GOV-008 | Do not invoke code-freeze rules during M2A | Scope test | Diff review | M2A change register | No code-freeze claim | IN PROGRESS |
| GOV-009 | Do not assign release identity before M2C | Static test | Source review | M2A change register | No new version/Build ID/installer SHA assignment | IN PROGRESS |
| GOV-010 | Block merge, installer publication and Genesis | Workflow/static test | PR state and source review | PR metadata | No release action is added or executed | IN PROGRESS |
| VIS-001 | Desktop layout for 1280–1920 without window horizontal scroll | Playwright viewport matrix | DOM sizes + screenshots | 1280/1440/1920 PNGs | No clipped mandatory areas or body horizontal overflow | IN PROGRESS |
| VIS-002 | Convert right panel to accessible drawer/tab at 1024–1279 | Playwright keyboard/focus test | 1024 screenshot + focus trace | 1024 PNG | Drawer/tab opens, closes and returns focus | IN PROGRESS |
| VIS-003 | Preserve access to all modules at 800–1023 | Playwright navigation test | 800 screenshot + item count | 800 PNG | Every module is reachable without hidden tail items | IN PROGRESS |
| VIS-004 | Keep dark theme mandatory | Computed-style test | Browser style evidence | Screenshot matrix | Dark theme active at all required widths | IN PROGRESS |
| VIS-005 | Keep light theme deferred | Static UI test | Absence of release-blocking light-theme control | Test log | No light-theme completion claim | IN PROGRESS |
| VIS-006 | Replace navigation Unicode symbols with one SVG icon set | Static + browser icon test | DOM icon inventory | Screenshot matrix | One SVG icon per navigation item; no symbol-only nav icons | IN PROGRESS |
| VIS-007 | Distinguish focus, disabled, busy, error, warning, PASS and BLOCKED | Browser state test | Computed styles/screenshots | State screenshots | Each required state is visually and semantically distinct | IN PROGRESS |
| PRJ-001 | Create/open/rename/close/select projects | API + browser lifecycle test | Persisted project list after reload | Test log | All actions work without fixed single project | IN PROGRESS |
| PRJ-002 | Persist sources, derivatives, masks, masters, exports, presets and QA reports in project model | Integration round-trip | Serialized project contract | Test log | Typed collections survive save/reload | IN PROGRESS |
| PRJ-003 | Remove TS-001 as the only active user project | Static + browser bootstrap test | Dynamic active project ID | Screenshot/test log | User can operate with a non-TS-001 project | IN PROGRESS |
| PRJ-004 | Show typed history cards | Browser/history test | Type labels in DOM | Screenshot | Required history types are distinguishable | IN PROGRESS |
| PRJ-005 | Implement undo/redo by active-version switching | Integration + browser test | History remains intact | Test log | Undo/redo changes active asset without deleting records | IN PROGRESS |
| PRJ-006 | Show autosave saved/saving/error states | Browser mutation test | State transitions | Screenshot/test log | All three states are observable | IN PROGRESS |
| PRJ-007 | Save module parameters, engine policy, QA policy and export profile without secrets | Preset round-trip test | Persisted preset JSON | Test log | Values restore; secret-like fields are absent | IN PROGRESS |
| PRJ-008 | Apply one preset to a file queue and create a final report | Batch integration test | Queue/report records | Test log | Completed batch contains per-item and summary results | IN PROGRESS |
| PRJ-009 | Support pause/cancel without corrupting completed results | Batch lifecycle test | Completed items preserved | Test log | Pause/cancel leaves prior PASS items and active asset valid | IN PROGRESS |
| PRJ-010 | Keep Autoparams distinct from the one-button route | Browser semantics test | Separate controls and descriptions | Screenshot | No control aliases the two modes | IN PROGRESS |
| PRJ-011 | Add “Подготовить принт” and show future stages before run | Browser plan test | Pre-run stage list | Screenshot | Route name and ordered plan visible before execution | IN PROGRESS |
| PV-001 | Add Original, Result, Mask, Split, Overlay and Difference | Browser interaction test | Mode state and rendered surface | Preview screenshots | All modes are selectable and produce distinct view state | IN PROGRESS |
| PV-002 | Add transparent/white/black/gray preview backgrounds | Computed-style test | Four background states | Preview screenshots | All four states are distinct | IN PROGRESS |
| PV-003 | Implement real Zoom In/Out/Fit/1:1/Pan | Browser geometry test | Transform and runtime zoom | Test log | Controls alter actual transform, not labels only | IN PROGRESS |
| PV-004 | Make zoom label factual | Browser assertion | Label vs runtime scale | Test log | Fit never displays static 100% unless actual scale is 1 | IN PROGRESS |
| PV-005 | Isolate manual masks by asset ID | Multi-asset browser test | Asset switch/reload | Test log | Mask edits never appear on another asset | IN PROGRESS |
| PV-006 | Add Add/Subtract/Eraser/Lasso/Rectangle/Clear/Invert | Deterministic mask test | Tool-state and mask changes | Test log | Every required tool is reachable and changes only selected mask | IN PROGRESS |
| PV-007 | Show actual brush diameter cursor | Browser computed-size test | Cursor diameter | Screenshot/test log | Rendered cursor matches selected diameter within tolerance | IN PROGRESS |
| PV-008 | Add draggable/resizable crop box on image | Browser drag test | Changed crop coordinates | Screenshot/test log | Move and resize update values without creating an asset | IN PROGRESS |
| PV-009 | Add four draggable perspective points with live preview | Browser drag test | Point positions + transform | Screenshot/test log | Each point moves and preview updates before apply | IN PROGRESS |
| PV-010 | Provide reduced-copy preview before heavy operation | Browser/API count test | Preview response and unchanged asset count | Test log | Preview does not create a project version | IN PROGRESS |
| SZ-001 | Use mm only for physical dimensions | Static/browser test | Field labels and absent unit selector | Screenshot | No cm/inch/px physical-unit selector | IN PROGRESS |
| SZ-002 | Add Photoshop-like chain in Improve and Size & Canvas | Browser test | Two chain controls | Screenshot | Both locations expose keyboard-accessible linked/unlinked state | IN PROGRESS |
| SZ-003 | Live-sync linked width/height | Browser input test | Immediate paired-field update | Test log | Changing either field updates the other | IN PROGRESS |
| SZ-004 | Allow independent unlinked fields | Browser input test | Unchanged opposite field | Test log | Width and height remain independent | IN PROGRESS |
| SZ-005 | Persist chain state in preset and project history | Round-trip test | Reloaded state | Test log | Linked state and size values restore | IN PROGRESS |
| SZ-006 | Use one shared Size Controller in both locations | Cross-panel browser test | Matched values/state | Test log | Improve and Size & Canvas cannot diverge | IN PROGRESS |
| SZ-007 | Resample Off changes print size/PPI without pixel resize | Geometry integration test | Exact px/PPI | Test log | Pixel dimensions unchanged | IN PROGRESS |
| SZ-008 | Resample On creates a new raster version | Geometry integration test | Exact output dimensions and lineage | Test log | New version with requested pixels is created | IN PROGRESS |
| SZ-009 | Add independent canvas margins in mm | Geometry/browser test | Exact padding + UI persistence | Test log | Four margins are independent and correctly converted | IN PROGRESS |
| SZ-010 | Block invalid proportion/PPI/memory before execution | Unit + browser no-request test | Validation message and request count | Test log | Invalid operation never reaches processing endpoint | IN PROGRESS |
| AUTO-001 (M2A UI slice) | Show ordered “Подготовить принт” route before start | Browser plan test | Visible stage plan | Screenshot | Plan is visible before execution | IN PROGRESS |
| AUTO-002 (M2A UI slice) | Allow optional-stage toggles but lock mandatory QA | Browser control test | QA control state | Screenshot/test log | QA cannot be disabled | IN PROGRESS |
| AUTO-003 (M2A UI slice) | Show progress UI: percent, stage, engine, elapsed and cancel | Browser state test | Progress surface | Screenshot | All fields and cancel control exist and update in M2A simulation/contracts | IN PROGRESS |
| AUTO-004 | Preserve active asset on cancel | Integration test | Project state after cancel | Test log | No partial active asset is created | IN PROGRESS |
| SET-001 (M2A UI slice) | Show CPU/GPU/runtime/providers/models/disk diagnostics surface | API + browser test | Real endpoint values | Screenshot/test log | Required categories are visible; unavailable values are explicit | IN PROGRESS |
| SET-002 (M2A UI slice) | Add model-pack, folder, preset and privacy controls | Browser/persistence test | Reloaded settings | Screenshot/test log | Controls persist without storing secrets | IN PROGRESS |
| SET-003 | Prohibit text-to-image and blank-canvas modes | Static/browser prohibited-surface test | DOM/source scan | Test log | No such entry point exists | IN PROGRESS |
| SET-004 | Generate safe diagnostics report | API/download test | Report content scan | Diagnostics JSON artifact | Report excludes image bytes/content and secrets | IN PROGRESS |

## M2A completion gate

M2A may be marked complete only when:

1. Every row above is `PASS` or an explicitly approved scope change exists.
2. Real-browser interaction tests pass.
3. Screenshot review at 800, 1024, 1280, 1440 and 1920 px has no blocking defect.
4. Mandatory CI is green on one frozen M2A code SHA.
5. Diff review confirms no M2B–M7 implementation or release authorization was introduced.
6. Release remains blocked and M2B remains `NOT STARTED`.

Current stage status:

```text
M0_COMPLETE
M1_COMPLETE
M2A_IN_PROGRESS
M2B_NOT_STARTED
M2C_NOT_STARTED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
```
