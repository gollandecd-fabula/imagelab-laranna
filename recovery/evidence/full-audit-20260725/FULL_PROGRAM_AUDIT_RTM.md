# ImageLab by LarannA — Full Program Audit RTM

Date: 2026-07-25  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Branch: `redteam/imagelab-full-audit-clean-20260725`  
Base: `bootstrap/zero-trust-gate` at `12208d708f3870fc2323ad351b3a2abe14fa672a`

## Scope lock

This audit assesses and, where supported, corrects the complete current program and delivery chain without changing the selected product specification:

- uploaded-image processing only; no text-to-image mode;
- physical dimensions in millimetres; edge softness in pixels; no mm/cm toggle;
- background removal and print extraction remain separate operations;
- exact candidate identity and evidence are not relabelled or weakened;
- no installer publication, `main` modification or PR #2 merge;
- no fabricated historical authorization baseline;
- hosted runners cannot replace physical user-machine L5.

## Capability Gate

| Capability | Supported method | Gate result |
|---|---|---|
| Read and inspect repository source, tests, workflows and evidence | GitHub connector, exact branch refs | PASS |
| Create isolated audit branch and draft PR | GitHub branch/PR operations | PASS |
| Modify source, tests, workflows and documentation | GitHub contents API | PASS |
| Execute Linux/Windows automated checks | GitHub Actions workflows | PASS |
| Obtain independent Codex review | PR review integration | PASS |
| Use the approved one-time Genesis policy for the first official release | Separate change register and fail-closed implementation | APPROVED; IMPLEMENTATION SEPARATE IN PR #9 |
| Perform physical user-machine L5 | Dmitry's real Windows machine and witnessed evidence | BLOCKED — external physical action pending final candidate |
| Publish installer or authorize release | Forbidden while any gate is blocked | BLOCKED BY SPEC |

Supported audit and correction work proceeds. External prerequisites cannot be simulated.

## Requirements Traceability Matrix

| ID | Requirement / risk domain | Required action | Verification | PASS criterion | Current status |
|---|---|---|---|---|---|
| AUD-001 | Product-scope compliance | Search UI/API/config for text-to-image, cm toggle, merged operations or legal claims | Static scan + targeted tests | No prohibited function or terminology; separate operations remain | PENDING |
| AUD-002 | Exact identity and deterministic build | Verify version/build/source/installer identity propagation and reproducibility | Manifest/code/workflow inspection + tests | No mutable or filename-only identity path; exact SHA propagated | OLD 1.4.9 IDENTITY INVALIDATED BY SOURCE FIXES; NEW IDENTITY REQUIRED AFTER FREEZE |
| AUD-003 | Archive/package admission | Check traversal, duplicate names, symlinks, CRC, decompression size, privacy denylist and atomic extraction | Adversarial tests | Every malformed or oversized archive fails before publication | PENDING |
| AUD-004 | Installer atomicity and recovery | Check staging, pre/post self-test, promotion, process shutdown, rollback and partial-install cleanup | Source inspection + Windows tests | Failure cannot leave mixed or falsely healthy installation | PENDING |
| AUD-005 | Local service exposure | Check bind address, port discovery, CORS, Host handling, browser launch and cross-origin write surface | Static + runtime tests | Loopback-only; untrusted origins/hosts cannot mutate state | PENDING |
| AUD-006 | Upload validation and resource exhaustion | Check extension/MIME/signature, bytes/pixels/frames, decompression bombs and malformed images | Adversarial upload tests | Invalid or oversized inputs fail before expensive processing | PENDING |
| AUD-007 | SVG/XML safety | Check DTD/entity, script/event/external references, CSS/URL, canonicalization and path injection | Adversarial SVG tests | Dangerous active/external content rejected; canonical bytes deterministic | PENDING |
| AUD-008 | Project-store integrity | Prevent stale AI snapshots from overwriting concurrent title, preset, active-asset and upload changes; preserve locks and atomic JSON | Concurrency regression plus complete suite | No traversal, lost update, partial JSON or asset/project mismatch | CODE FIXED in `e8a910f` and regression added in `a9649de`; CI PENDING |
| AUD-009 | Temporary/output file lifecycle | Check unique paths, cleanup on success/failure, collision resistance and permissions | Tests + static scan | No stale sensitive temp files or cross-request collisions | PENDING |
| AUD-010 | Command/process execution | Check shell use, quoting, inherited environment, executable resolution and timeout tree termination | Static scan + tests | No user-controlled command injection; child trees terminate | PENDING |
| AUD-011 | Output correctness | Verify PNG PPI/size/alpha, halftone, SVG and lineage/history selection | Existing and added tests | Binary outputs match declared operation and source lineage | PENDING |
| AUD-012 | Update/rollback project preservation | Establish invariant over multiple projects with raster/SVG, history, presets, titles and active selections | Windows before/update/rollback snapshots; compare every JSON, asset hash and runtime hash | Update preserves every state item; forced rollback restores complete baseline; missing field/hash is FAIL | PENDING — single-SVG diagnostic is insufficient |
| AUD-013 | Release authorization and physical L5 provenance | Require externally supplied, independently SHA-pinned record binding exact source/installer/version/build/install, physical environment, browser steps, output hashes, timestamp and Dmitry witness | Positive parser fixture; adversarial negatives; genuine physical run for actual PASS | Finalizer cannot create or retain authorized output without exact valid record and all gates | CODE/WORKFLOW/TESTS implemented in `15c605c`, `fb32159`, `57f9e9e`, `4f2cf23`; CI PENDING; ACTUAL PHYSICAL L5 NOT VERIFIED |
| AUD-014 | Dependency and action supply chain | Pin actions and tool versions; check packages and install scripts | Static contract tests | Release workflows use immutable action refs and bounded dependencies | `setup-node` and `attest` pinned in `57f9e9e`; complete repository scan PENDING |
| AUD-015 | Workflow trigger and permission matrix | Classify every workflow; test allowed event-permission combinations | Parse every root workflow | Automatic only for read-only validation; mutation/promotion/release/authorization manual-only | PENDING; PR #6 not yet integrated |
| AUD-016 | Privacy and evidence leakage | Search logs/artifacts/source bundles for user data, paths, tokens and unrestricted retention | Static/adversarial tests | No secrets or real user content; retention bounded | PENDING |
| AUD-017 | Error contracts and false success | Check API HTTP statuses, UI messages, evidence fields and exception handling | Tests | Failure is non-zero/4xx-5xx and cannot appear/finalize as PASS | PENDING |
| AUD-018 | Concurrency and denial of service | Check limits, simultaneous writes, audit locking, process count and queues | Stress/concurrency tests | Bounded resources and deterministic failure without corruption | PARTIAL: stale AI lost-update fixed; wider audit PENDING |
| AUD-019 | Browser/UI safety and critical flow | Check selectors, disabled states, upload/operation/history/export and identity display | Browser/source tests | Required user path executable and errors visible | PENDING |
| AUD-020 | Test/evidence trustworthiness | Find string-only tests, self-asserted PASS, stale evidence and unexecuted critical code | Red-team review + CI | Critical behavior has runtime/adversarial coverage; claims bounded | PENDING |

## Implemented corrective clusters

### Cluster A — physical-L5 authorization boundary

- `15c605c119384699ce16bfcd79f7f0939a111148`: finalizer schema 4, mandatory physical record and SHA, identity/freshness/scenario/output/witness validation, stale-output cleanup.
- `fb3215942b7b43a015e7278f04fc3565c5e5d592`: bounded credential-free HTTPS JSON fetcher with prepublication SHA validation and atomic write.
- `57f9e9ed59afdc520defee22937690172508a90b`: workflow inputs/download/finalizer wiring; normal baseline accepts prior normal or Genesis authorization; setup-node and attest immutable pins.
- `4f2cf23c49833597d355d1afa92d2808f03be4df`: synthetic parser fixture plus adversarial physical-L5 tests.
- Actual physical evidence does not exist and is not claimed.

### Cluster B — stale AI project overwrite

- `e8a910f99cfa645873cf9a54d7b2a2ef8073c703`: under-lock merge of AI dictionaries into live project state rather than whole-snapshot replacement.
- `a9649de6b47f1428e6073a2dd8f7c2f65e6e334e`: regression preserving concurrent rename, preset, upload, active selection and existing AI evidence.

## Confirmed remaining findings

1. **P1 — update/rollback generalization gap:** multi-project and raster/mixed-state evidence is still missing.
2. **P2 — workflow event/permission matrix:** safe read-only automation must remain allowed; automatic write/promotion/authorization must be eliminated.
3. **Identity boundary:** all application-source corrections require a new candidate identity and complete B0–B5/B8 rerun.
4. **Physical boundary:** parser tests cannot establish real physical provenance.

## Completion criteria

1. Every AUD row ends as PASS, FIXED/PASS, BLOCKED or FAIL with exact evidence.
2. Every correction has focused automated tests.
3. Complete source suite and production self-test run after corrections.
4. Windows-specific corrections receive Windows execution evidence.
5. Independent Codex review is performed on the actual remote commits.
6. No `main` merge, publication or release authorization occurs before all required evidence.
7. Final report separates hosted PASS, actual physical L5 and Genesis/normal authorization state.

Current state:

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
