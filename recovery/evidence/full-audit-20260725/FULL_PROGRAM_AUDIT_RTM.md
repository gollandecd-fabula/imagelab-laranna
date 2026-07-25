# ImageLab by LarannA — Full Program Audit RTM

Date: 2026-07-26  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Branch: `redteam/imagelab-complete-audit-20260725-v2`  
Base: `bootstrap/zero-trust-gate` at `12208d708f3870fc2323ad351b3a2abe14fa672a`

## Scope lock

This audit corrects the current application and delivery chain without changing the selected product specification:

- uploaded-image processing only; no text-to-image mode;
- physical dimensions in millimetres; edge softness in pixels; no mm/cm toggle;
- background removal and print extraction remain separate operations;
- exact candidate identity and evidence are not relabelled or weakened;
- no installer publication, protected-branch merge or release authorization;
- hosted runners cannot replace physical user-machine L5;
- new AI engines are not integrated before M0-M2 stabilization and code freeze.

## Capability Gate

| Capability | Supported method | Gate result |
|---|---|---|
| Inspect repository source, tests, workflows and evidence | GitHub connector, exact refs and workflow artifacts | PASS |
| Modify the authorized audit branch | GitHub contents API | PASS |
| Execute Linux and Windows automated checks | GitHub Actions plus local exact-source reproduction | PASS |
| Execute a real browser contract | Playwright Chromium on hosted Ubuntu | PASS FOR M1 CONTRACT |
| Maintain the one-time Genesis policy | Manual fail-closed workflows | PASS FOR IMPLEMENTATION; NOT RUN |
| Perform physical user-machine L5 | Dmitry's actual Windows computer | BLOCKED UNTIL FINAL CANDIDATE |
| Publish or authorize a release | Forbidden while a release gate is blocked | BLOCKED BY SPEC |

## M0 execution record — governance baseline cleanup

User authorization: granted on 2026-07-26.  
Baseline inspected: `ceb2b112e2fb16cb8a451f572a69ac4538b05a95`.

Implemented:

1. Deleted the temporary automatic write workflow and its binary payload/trigger.
2. Restored the executable manual root Genesis workflow.
3. Restored green governance, bootstrap, dependency, snapshot and evidence-hardening CI.

Evidence:

| Evidence | Result |
|---|---|
| Local governance contracts | PASS — 4/4 |
| Local Genesis contracts | PASS — 12/12 |
| Local complete source suite | PASS — 194/194 |
| Remote Governance `30172617537` | PASS |
| Remote Evidence Hardening `30172617543` | PASS |
| Remote Bootstrap `30172617572` | PASS |
| Remote Dependency Audit `30172617538` | PASS |
| Remote Source Snapshot `30172617551` | PASS |

**M0 status: PASS.**

## M1 execution record — application, UI and Windows lifecycle hardening

User authorization: granted on 2026-07-26.  
M1 code head verified: `8034d400ac45b1c48591d9ec76b46ec96fed05c7`.

### Implemented corrections

1. **Responsive UI**
   - removed the effective fixed-width clipping through an audited responsive CSS layer;
   - added layouts for 1300, 1100 and 800 px widths;
   - preserved the original UI source and served the hardening layer through `app.entry`.
2. **Operation-mode truthfulness**
   - fast and check-only modes visually uncheck and disable global auto-repair;
   - professional mode restores the stored user preference;
   - busy state cannot be silently undone by `syncLocks`.
3. **Browser critical path**
   - covered navigation through all nine modules;
   - covered 1024/800 width overflow;
   - covered per-asset mask isolation;
   - covered cancelled AI training confirmation;
   - covered malformed JSON and visible fail-closed error state.
4. **Launcher process ownership**
   - deduplicated case-insensitive environment variables;
   - timeout or identity failure terminates the launcher-owned process tree;
   - the process is waited/reaped and cleanup failure is reported.
5. **Uninstaller safety**
   - validates install root and `install-manifest.json` identity before deletion;
   - passes paths through environment variables instead of PowerShell source interpolation;
   - stops only processes whose executable path belongs to the installation root;
   - verifies process exit and directory deletion;
   - writes `uninstall-status.json` and preserves user projects.
6. **Mandatory gates**
   - added a real Chromium job;
   - added Windows launcher and uninstaller Go tests;
   - retained the complete Python suite, JavaScript syntax, ZIP and PowerShell gates.

### M1 verification

| Evidence | Result |
|---|---|
| Local complete Python suite excluding separately executed browser test | PASS |
| Local Chromium browser contract | PASS — 2/2 |
| Local JavaScript syntax | PASS |
| Local Windows Go package cross-compilation | PASS |
| Remote Workflow Governance run `30174283262` | PASS |
| Remote Dependency Security Audit run `30174283184` | PASS |
| Remote Bootstrap Verifier run `30174283181` | PASS |
| Remote Full Audit Source Snapshot run `30174283185` | PASS |
| Remote Evidence Hardening run `30174283224` | PASS |
| Remote Python complete suite job `89720511214` | PASS |
| Remote Browser UI M1 job `89720511145` | PASS |
| Remote Windows launcher/uninstaller job `89720511191` | PASS |
| Remote Windows installer ZIP job `89720511210` | PASS |
| Remote PowerShell parser job `89720511188` | PASS |

**M1 status: PASS for the authorized M1 scope.**  
**M2 status: NOT STARTED / NOT AUTHORIZED IN THIS EXECUTION.**

M1 does not assign a new release identity. The current historical version/build identity remains invalid for release after source changes. New version, Build ID, source SHA and installer SHA belong to M2 code freeze.

## Requirements Traceability Matrix

| ID | Requirement / risk domain | Required verification | PASS criterion | Current status |
|---|---|---|---|---|
| AUD-001 | Product-scope compliance | Static scan and source contracts | No text-to-image, cm toggle, merged background/print operation or legal claim | PASS IN CURRENT COMPLETE SUITE; RECHECK AT FREEZE |
| AUD-002 | Exact identity and deterministic build | Frozen source/build/manifest test | New exact identity propagated everywhere | BLOCKED FOR M2 — OLD IDENTITY INVALIDATED |
| AUD-003 | Archive/package admission | Adversarial Windows ZIP tests | Hostile archive rejected before installation | PASS FOR CURRENT INSTALLER ZIP POLICY; FINAL PACKAGE RECHECK M2 |
| AUD-004 | Installer atomicity and recovery | Installer/update/rollback lifecycle | No mixed or falsely healthy installation | PARTIAL — LAUNCHER/UNINSTALLER PASS; UPDATE/ROLLBACK IS M2 |
| AUD-005 | Local service exposure | Host/origin/runtime tests | Loopback only; cross-origin mutation blocked | PASS IN CURRENT SOURCE SUITE |
| AUD-006 | Upload validation and resource exhaustion | Malformed/oversized upload tests | Rejected before expensive processing | PASS IN CURRENT SOURCE SUITE |
| AUD-007 | SVG/XML safety | Adversarial SVG tests | Active/external content rejected | PASS IN CURRENT SOURCE SUITE |
| AUD-008 | Project-store integrity | Concurrency and atomic JSON tests | No lost update, partial state or project mismatch | PASS IN CURRENT SOURCE SUITE |
| AUD-009 | Temporary/output lifecycle | Failure cleanup tests and scan | No stale sensitive temp files | PASS FOR M0/M1 CHANGED PATHS; FINAL RECHECK M2 |
| AUD-010 | Command/process execution | Windows launcher/uninstaller tests | No injection; owned process trees terminate | M1 FIXED/PASS — JOB `89720511191` |
| AUD-011 | Output correctness | PNG/SVG/lineage tests | Output matches declared operation and source lineage | CURRENT TESTS PASS; FULL PROCESSING FREEZE GATE IS M2 |
| AUD-012 | Update/rollback project preservation | Multi-project mixed raster/SVG Windows gate | Update preserves all state; rollback restores baseline | BLOCKED FOR M2 |
| AUD-013 | Release authorization and physical L5 | Genesis contracts plus actual physical run | No authorization without exact valid L5 | IMPLEMENTATION PASS; ACTUAL L5 BLOCKED |
| AUD-014 | Dependency and action supply chain | Governance and dependency audit | Immutable actions and bounded dependencies | PASS ON M1 HEAD; RECHECK AFTER EVERY CHANGE |
| AUD-015 | Workflow trigger/permission matrix | Parse every root workflow | Automatic validation is read-only | PASS ON M1 HEAD |
| AUD-016 | Privacy and evidence leakage | Artifact/log/release scan | No secrets or user content leakage | PARTIAL; FINAL RELEASE SCAN M2/M11 |
| AUD-017 | Error contracts and false success | API and browser failure tests | Failure remains visible/non-success | M1 FIXED/PASS INCLUDING MALFORMED JSON |
| AUD-018 | Concurrency and denial of service | Limits/concurrency/process tests | Bounded failure without corruption | PARTIAL PASS; RELEASE STRESS GATE M2/M11 |
| AUD-019 | Browser/UI safety and critical flow | Real Chromium test | Required flow works; state does not leak | M1 FIXED/PASS — JOB `89720511145` |
| AUD-020 | Test/evidence trustworthiness | Independent review and final rerun | Claims do not exceed evidence | CURRENT CI PASS; INDEPENDENT REVIEW REMAINS M11 |

## Remaining blockers after M1

1. **M2 code freeze and identity:** assign a new version/Build ID only after all M2 source corrections are frozen.
2. **M2 update/rollback preservation:** prove multi-project mixed raster/SVG state preservation on Windows.
3. **M2 processing/output freeze:** rerun full output, lineage, export and package gates on the frozen candidate.
4. **Later independent review:** final remote commits require an independent red-team review.
5. **Physical boundary:** hosted Windows and parser tests do not replace physical user-machine L5.
6. **Release boundary:** Genesis and installer publication remain forbidden.

## Stage completion status

### M0 — PASS

- governance baseline clean;
- temporary write mechanism removed;
- mandatory M0 CI green.

### M1 — PASS

- responsive and fail-closed UI behavior verified in Chromium;
- launcher failure cleanup verified on Windows;
- uninstaller ownership, quoting and deletion contracts verified on Windows;
- complete source suite and all mandatory CI green.

### Program completion — NOT MET

The program is not a release candidate and is not authorized. M2, independent review, exact release packaging, physical L5 and Genesis remain incomplete.

Current state:

`M0_COMPLETE`  
`M1_COMPLETE`  
`M2_NOT_STARTED`  
`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
