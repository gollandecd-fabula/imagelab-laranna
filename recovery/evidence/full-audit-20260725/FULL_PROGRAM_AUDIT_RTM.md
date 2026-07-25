# ImageLab by LarannA — Full Program Audit RTM

Date: 2026-07-26  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Branch: `redteam/imagelab-complete-audit-20260725-v2`  
Base: `bootstrap/zero-trust-gate` at `12208d708f3870fc2323ad351b3a2abe14fa672a`

## Scope lock

This audit assesses and, where supported, corrects the complete current program and delivery chain without changing the selected product specification:

- uploaded-image processing only; no text-to-image mode;
- physical dimensions in millimetres; edge softness in pixels; no mm/cm toggle;
- background removal and print extraction remain separate operations;
- exact candidate identity and evidence are not relabelled or weakened;
- no installer publication, `main` modification or merge to the protected release line;
- no fabricated historical authorization baseline;
- hosted runners cannot replace physical user-machine L5;
- new AI engines are not integrated before M0-M2 stabilization and code freeze.

## Capability Gate

| Capability | Supported method | Gate result |
|---|---|---|
| Read and inspect repository source, tests, workflows and evidence | GitHub connector, exact branch refs and exact workflow artifacts | PASS |
| Modify source, tests, workflows and documentation | GitHub contents API on the authorized audit branch | PASS |
| Execute Linux/Windows automated checks | GitHub Actions plus local exact-source reproduction | PASS |
| Maintain the approved one-time Genesis policy | Manual root Genesis workflow plus reviewed request gate, both fail-closed | PASS FOR IMPLEMENTATION; NO AUTHORIZATION RUN |
| Perform physical user-machine L5 | Dmitry's real Windows machine and witnessed evidence | BLOCKED — external physical action pending final candidate |
| Publish installer or authorize release | Forbidden while any release gate is blocked | BLOCKED BY SPEC |

Supported audit and correction work proceeds. External prerequisites cannot be simulated.

## M0 execution record — governance baseline cleanup

User authorization: granted on 2026-07-26.  
Baseline head inspected: `ceb2b112e2fb16cb8a451f572a69ac4538b05a95`.

Implemented changes:

1. Deleted temporary automatic write workflow `.github/workflows/apply-full-audit-ui-patch.yml` (`5cc3c204f62af87d637b059989ee8d137d0c5319`).
2. Deleted failed binary patch payload `.audit/ui.patch.gz.b64` (`3e9759469ee671e6b47386b836f8eec3ae5923a4`).
3. Deleted obsolete patch trigger `.audit/ui.trigger` (`ae45b095c8804455ba294632ba829387cc14a896`).
4. Restored the executable root manual Genesis workflow with `recovery/source` working directories and root-relative authorized-output paths (`30a97f4357f80532a4755fdc4a6702210cbc3ae6`).

Verification on the exact M0 change set:

| Evidence | Result |
|---|---|
| Local workflow governance contracts | PASS — 4/4 |
| Local Genesis release/request contracts | PASS — 12/12 |
| Local complete application source suite | PASS — 194/194 |
| Remote Workflow Governance CI run `30172617537` | PASS |
| Remote Evidence Hardening CI run `30172617543` | PASS — Python complete suite, Windows ZIP admission and PowerShell parser |
| Remote Bootstrap Verifier run `30172617572` | PASS |
| Remote Dependency Security Audit run `30172617538` | PASS |
| Remote Full Audit Source Snapshot run `30172617551` | PASS |

**M0 status: PASS.**  
**Next stage: M1 — NOT STARTED / NOT AUTHORIZED IN THIS EXECUTION.**

## Requirements Traceability Matrix

| ID | Requirement / risk domain | Required action | Verification | PASS criterion | Current status |
|---|---|---|---|---|---|
| AUD-001 | Product-scope compliance | Search UI/API/config for text-to-image, cm toggle, merged operations or legal claims | Static scan + targeted tests | No prohibited function or terminology; separate operations remain | PENDING M1 |
| AUD-002 | Exact identity and deterministic build | Verify version/build/source/installer identity propagation and reproducibility | Manifest/code/workflow inspection + tests | No mutable or filename-only identity path; exact SHA propagated | OLD 1.4.9 IDENTITY INVALIDATED; NEW IDENTITY REQUIRED AFTER M2 FREEZE |
| AUD-003 | Archive/package admission | Check traversal, duplicate names, symlinks, CRC, decompression size, privacy denylist and atomic extraction | Adversarial tests | Every malformed or oversized archive fails before publication | PARTIAL PASS — current Windows ZIP admission tests PASS; broader package gate remains M1/M2 |
| AUD-004 | Installer atomicity and recovery | Check staging, pre/post self-test, promotion, process shutdown, rollback and partial-install cleanup | Source inspection + Windows tests | Failure cannot leave mixed or falsely healthy installation | PENDING M1 |
| AUD-005 | Local service exposure | Check bind address, port discovery, CORS, Host handling, browser launch and cross-origin write surface | Static + runtime tests | Loopback-only; untrusted origins/hosts cannot mutate state | PARTIAL; complete M1 review pending |
| AUD-006 | Upload validation and resource exhaustion | Check extension/MIME/signature, bytes/pixels/frames, decompression bombs and malformed images | Adversarial upload tests | Invalid or oversized inputs fail before expensive processing | PARTIAL; complete M1 review pending |
| AUD-007 | SVG/XML safety | Check DTD/entity, script/event/external references, CSS/URL, canonicalization and path injection | Adversarial SVG tests | Dangerous active/external content rejected; canonical bytes deterministic | PARTIAL; complete M1 review pending |
| AUD-008 | Project-store integrity | Prevent stale AI snapshots from overwriting concurrent project state; preserve locks and atomic JSON | Concurrency regression plus complete suite | No traversal, lost update, partial JSON or asset/project mismatch | CODE AND REGRESSION PASS IN CURRENT COMPLETE SUITE |
| AUD-009 | Temporary/output file lifecycle | Check unique paths, cleanup on success/failure, collision resistance and permissions | Tests + static scan | No stale sensitive temp files or cross-request collisions | M0 TEMP PATCH FILES REMOVED; APPLICATION TEMP LIFECYCLE PENDING M1 |
| AUD-010 | Command/process execution | Check shell use, quoting, inherited environment, executable resolution and timeout tree termination | Static scan + Windows tests | No user-controlled command injection; child trees terminate | PENDING M1 |
| AUD-011 | Output correctness | Verify PNG PPI/size/alpha, halftone, SVG and lineage/history selection | Existing and added tests | Binary outputs match declared operation and source lineage | PARTIAL; complete M1 review pending |
| AUD-012 | Update/rollback project preservation | Establish invariant over multiple projects with raster/SVG, history, presets, titles and active selections | Windows before/update/rollback snapshots | Update preserves all state; rollback restores complete baseline | PENDING M1 — physical/Windows evidence incomplete |
| AUD-013 | Release authorization and physical L5 provenance | Bind exact source/installer/version/build/install to external physical record and witness | Parser/adversarial tests plus genuine physical run | No authorized output without exact valid record and all gates | ROOT GENESIS WORKFLOW RESTORED; CONTRACTS PASS; ACTUAL PHYSICAL L5 NOT VERIFIED |
| AUD-014 | Dependency and action supply chain | Pin actions/tool versions and audit packages | Governance + dependency audit | Immutable action refs and bounded dependencies | M0 PASS FOR CURRENT ROOT WORKFLOWS AND DEPENDENCIES; RECHECK REQUIRED AFTER EVERY CHANGE |
| AUD-015 | Workflow trigger and permission matrix | Classify every workflow; reject automatic repository-write workflows | Parse every root workflow | Automatic validation read-only; release/authorization manual-only | M0 FIXED/PASS — GOVERNANCE RUN `30172617537` |
| AUD-016 | Privacy and evidence leakage | Search logs/artifacts/source bundles for user data, paths, tokens and retention | Static/adversarial tests | No secrets or real user content; retention bounded | PENDING M1 |
| AUD-017 | Error contracts and false success | Check API statuses, UI messages, evidence fields and exception handling | Tests | Failure cannot appear or finalize as PASS | PARTIAL; complete M1 review pending |
| AUD-018 | Concurrency and denial of service | Check limits, simultaneous writes, audit locking, process count and queues | Stress/concurrency tests | Bounded resources and deterministic failure without corruption | PARTIAL; wider audit pending M1 |
| AUD-019 | Browser/UI safety and critical flow | Check selectors, disabled states, upload/operation/history/export and identity display | Browser/source tests | Required user path executable and errors visible | PENDING M1 |
| AUD-020 | Test/evidence trustworthiness | Find string-only tests, self-asserted PASS, stale evidence and unexecuted critical code | Red-team review + CI | Critical behavior has runtime/adversarial coverage; claims bounded | M0 CI BASELINE PASS; INDEPENDENT FULL REVIEW PENDING M11 |

## Confirmed remaining findings after M0

1. **P1 — launcher failure cleanup:** timeout or identity mismatch must terminate and reap the process started by the launcher.
2. **P1 — uninstaller safety:** quoting, ownership, verified deletion and user-project preservation require Windows coverage.
3. **P1 — browser/UI gaps:** responsive widths, stale mask isolation, confirmation cancellation, malformed JSON and busy-state coverage remain incomplete.
4. **P1 — update/rollback generalization gap:** multi-project and raster/mixed-state evidence remains incomplete.
5. **Identity boundary:** all application-source corrections require a new version/build/source/installer identity after M2 code freeze.
6. **Physical boundary:** hosted/parser tests cannot establish real physical provenance.

## Stage completion criteria

### M0 — PASS

- temporary write applier and payloads removed;
- root executable Genesis workflow restored without authorizing a release;
- governance, dependency, bootstrap, snapshot and evidence-hardening checks green;
- local complete source suite green;
- release remains fail-closed.

### Program completion — NOT MET

1. Every AUD row ends as PASS, FIXED/PASS, BLOCKED or FAIL with exact evidence.
2. Every correction has focused automated tests.
3. Complete source suite and production self-test run after final corrections.
4. Windows-specific corrections receive Windows execution evidence.
5. Independent review is performed on the actual final remote commits.
6. No protected-branch merge, publication or authorization occurs before all required evidence.
7. Final report separates hosted PASS, actual physical L5 and Genesis/normal authorization state.

Current state:

`M0_COMPLETE`  
`M1_NOT_STARTED`  
`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
