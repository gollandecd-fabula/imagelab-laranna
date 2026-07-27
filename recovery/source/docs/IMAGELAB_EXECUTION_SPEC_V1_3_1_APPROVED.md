# ImageLab EXECUTION SPEC v1.3.1 — APPROVED

## Approval and precedence

Approved by the user on 2026-07-27:

> Утверждаю ImageLab EXECUTION SPEC v1.3.1 и разрешаю подготовить PILOT_DELTA_RTM без изменения кода.

This file is the normative repository representation of the approved v1.3.1 scope amendment. It changes only the explicitly defined pilot order and pilot slice. All non-conflicting requirements of `ImageLab_FINAL_EXECUTION_SPEC_v1.2_APPROVED.docx`, the M2A RTM, PROTOCOL LOCK and Zero-Trust Release Gate remain mandatory.

Priority:
1. Direct current user decision.
2. Approved v1.3.1.
3. Approved v1.2 outside the amended pilot scope.
4. Approved RTMs and change registers.
5. PROTOCOL LOCK / Evidence Lock.
6. Factual state of the exact code SHA.

Conflict result: `PROTOCOL_CONFLICT_REGISTER / PILOT_BLOCKED / RELEASE_BLOCKED`.

## Exact baseline at approval

- Repository: `gollandecd-fabula/imagelab-laranna`
- Parent PR: `#11`
- Parent branch: `redteam/imagelab-complete-audit-20260725-v2`
- Exact baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- M1 baseline: `35dd66bca9b31f2e9c098063a5382cd4f1c09cd6`
- State: `M2A_IN_PROGRESS / M2B_FULL_NOT_STARTED / RELEASE_BLOCKED`

The exact head must be rechecked immediately before every first mutation of a new implementation batch. A changed head requires rebaseline and fail-close.

## Mandatory locks

- `NO-REWRITE`: change the existing repository and current code only. No new program, parallel frontend/backend, new repository, separate SaaS fork or greenfield rewrite.
- `SOURCE-IMMUTABILITY`: never overwrite the uploaded source. Every operation creates a new asset version with lineage.
- `NO-TEXT-TO-IMAGE`: ImageLab processes only an uploaded source image. No blank-canvas or prompt-only image generation.
- `SINGLE-CANDIDATE`: CI, traces, screenshots, outputs, reports and installer evidence must refer to one exact candidate SHA.
- `NO-RUNTIME-TRAINING`: the user runtime must not train, fine-tune, promote or roll back model weights.
- `LOCAL-FIRST`: no hidden cloud processing. Any future cloud provider requires explicit provider/data/cost notice and consent.
- `EVIDENCE-LOCK`: no PASS beyond actual evidence.
- `TOOLING-LOCK`: connector, transport or message limits may not change product architecture, file structure or test design.
- `NO-FALSE-PILOT-CLAIM`: Pilot Alpha/Beta never equals public release or full M2A/M2B completion.

## Selected strategy

Use the existing M2A foundation to create one controlled vertical pilot:

1. **Pilot Alpha** — real source runtime, live FastAPI, real ProjectStore/filesystem, real processing and outputs. No installer.
2. **Pilot Beta** — the same route on one exact Windows installer candidate after Alpha PASS.
3. **Full local product** — complete M2A–M7 and Zero-Trust release gates.
4. **Online platform** — evolve the same domain/core through adapters after the local product is proven.

Allowed status after Alpha: `PILOT_ALPHA_PASS` only.
Allowed status after Beta: `PILOT_BETA_VALIDATED` only.
Release remains blocked until the full release protocol passes.

## Explicit M2B-PILOT slice

Only these limited actions are authorized for the pilot; full M2B remains `NOT_STARTED`:

- `PIL-BG-001`: current-engine background removal plus manual mask, preview and new version. No production-grade segmentation claim.
- `PIL-PEX-001`: one basic print-extraction path with edge/halo review. No universal extraction claim.
- `PIL-CLN-001`: conservative deterministic cleanup. No AI-restoration-complete claim.
- `PIL-SZ-001`: shared Size/PPI/Canvas controller with requested/actual results.
- `PIL-QA-001`: deterministic integrity, lineage, decode, px, PPI, alpha and mask-boundary checks.
- `PIL-EXP-001`: real PNG export with manifest.
- `PIL-DTF-001`: basic PNG DTF profile only; no production halftone/master claim.

Color, Palette, production Halftone, Smart Vector, DTF Master, Masters, Logo, CardLab, full M3/M4 AI integration, marketplace writes and public release remain prohibited.

## Pilot patch boundary

Allowed in Alpha:
- existing app/API/store/UI modules;
- current pilot processing paths;
- tests, fixtures, pilot docs and pilot CI;
- minimal fixes for reproduced defects;
- live E2E and runtime-training fail-close.

Allowed only in Beta:
- exact installer/launcher/uninstaller work needed for the frozen Beta candidate.

Prohibited:
- Genesis or public installer publication;
- SaaS infrastructure, billing, OIDC, Kubernetes, Temporal, S3/PostgreSQL migration before Alpha PASS;
- new external AI models in Alpha/Beta;
- mass refactoring or architecture changes caused only by tool limitations.

Pilot work must use a stacked branch/PR from the frozen M2A head. Every product change must map to a requirement and a reproduced defect.

## Pilot Alpha mandatory route

1. Create or open a project.
2. Upload a real supported raster file.
3. Select the active asset and verify factual metadata.
4. Create or correct a mask.
5. Remove the background or extract the print.
6. Apply conservative cleanup.
7. Set size, PPI and canvas.
8. Run mandatory Pilot QA.
9. Create PNG and basic PNG DTF as new versions.
10. Download and binary-validate outputs.
11. Restart the source runtime and reopen the project.
12. Verify history, active version and unchanged source.

`LIVE-E2E-01` must start real FastAPI and use the real URL, ProjectStore, filesystem, processing, preview and export. Route mocks are allowed only in component tests and are not Pilot Alpha evidence.

## Alpha P0 order

Before product processing changes:
1. Record this approved spec, approved RTM, full change register, exact baseline manifest and executable scope guard in one governance-first commit.
2. Create Frozen Pilot Set v1: five representative and three adversarial fixtures with immutable hashes, expected properties and thresholds fixed before benchmark execution.
3. Add `LIVE-E2E-01` against the real backend.
4. Reproduce and minimally fix runtime training/rollback exposure.
5. Reproduce and minimally fix visual reachability at 800, 1024, 1280, 1440 and 1920 px.
6. Open only the explicit M2B-PILOT route.
7. Add deterministic Pilot QA and binary output validation.
8. Create one candidate SHA and run all exact-head evidence.

## Frozen Pilot Set and visual gates

Frozen Pilot Set v1 must cover at least:
- transparency;
- difficult edge;
- text/logo;
- low resolution;
- non-uniform background;
- large file;
- two additional adversarial failure cases.

Each fixture has a hash, expected properties and thresholds recorded before processing.

Visual checks:
- 800: all modules and the full route reachable by scroll.
- 1024: drawer and last mandatory control reachable.
- 1280: no clipped fields, buttons or table rows.
- 1440: no three-column overlap.
- 1920: no excessive stretch, empty interactive zones or lost focus states.

Automated overflow/size checks do not replace manual screenshot review.

## Minimum Pilot QA

PASS requires:
- source bytes/hash unchanged;
- correct source/result lineage;
- output decodes;
- requested and actual px/PPI/mm agree with the binary file;
- alpha state matches the selected profile;
- masked operations do not modify forbidden outside-mask regions;
- failing required checks block ready claims.

## Runtime AI policy

Alpha/Beta add no new external models.
Existing engines may be used only with honest limitations and deterministic fallback.
User feedback may be stored without changing weights.
Training, fine-tuning, promotion and rollback entry points are fail-closed in user runtime.
Model Manager and frozen pretrained providers are deferred to M3/M4 after the pilot.

## Beta

Beta starts only after `PILOT_ALPHA_PASS`.

- Freeze one Beta source SHA.
- Build the installer once and record SHA-256.
- Clean-install on Windows 10/11 x64.
- Run the same live route through the installed UI.
- Validate outputs and manifests.
- Restart and verify projects/history/presets/active version.
- Uninstall while preserving user projects.
- Run the physical user pilot on the exact candidate.
- Produce the Pilot Defect Register.

Any source change creates a new candidate and requires a full evidence rerun.

## Future online platform

No SaaS implementation before Alpha PASS.
Before Alpha, new code must avoid new direct LocalAppData/user-name coupling and new global mutable state.
After Alpha, add `schema_version`, then `tenant_id="local"` only through reversible migration and regression tests.
Introduce one port/adapter seam at a time around the existing implementation: metadata store, object store, identity, jobs, models and export.
Hosted single-tenant comes after the full local product; multi-tenant isolation, roles, quotas, audit, retention and billing come later.
Kubernetes/Triton/KServe are allowed only after measured load justifies them.

## Execution protocol

1. Read v1.3.1, v1.2, M2A RTM and protocol.
2. Recheck exact head and parallel mutation.
3. Record approved Pilot RTM/change register before product code.
4. Track only genuinely open requirements.
5. One change-register row per requirement/defect.
6. Reproduce a defect before changing product code; an evidence gap does not authorize a product fix.
7. Apply a minimal reversible patch to existing code.
8. Do not restructure because of tool limitations.
9. Run focused and existing regression tests.
10. Create one candidate SHA.
11. Run CI on exactly that SHA.
12. Review live E2E, screenshots and real output files.
13. Update RTM only from exact evidence.
14. Do not declare PASS while any mandatory row is open.

## Definition of Done

`PILOT_ALPHA_PASS` requires PIL-001–PIL-016 closed on one SHA, live E2E without mocks, all eight fixtures validated, five-width visual review, no runtime training/hidden cloud calls and no open P0.

`PILOT_BETA_VALIDATED` additionally requires exact installer, clean install, restart, data preservation and physical user validation.

Prohibited claims before full release:
`M2A_COMPLETE`, `M2B_COMPLETE`, `PRODUCTION_READY`, `RELEASE_AUTHORIZED`, `GENESIS_RELEASE_AUTHORIZED`.

Any missing mandatory evidence results in:
`PILOT_BLOCKED / MILESTONE_NOT_COMPLETE / RELEASE_BLOCKED`.
