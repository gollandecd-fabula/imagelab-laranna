# ImageLab by LarannA — Full Program Audit RTM

Date: 2026-07-25  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Branch: `redteam/imagelab-full-audit-clean-20260725`  
Base: `bootstrap/zero-trust-gate` at `12208d708f3870fc2323ad351b3a2abe14fa672a`

## Scope lock

This audit must assess and, where supported, correct the complete current program and its delivery chain without changing the selected product specification:

- uploaded-image processing only; no text-to-image mode;
- physical dimensions in millimetres; edge softness in pixels; no mm/cm toggle;
- background removal and print extraction remain separate operations;
- exact candidate identity and evidence are not relabelled or weakened;
- no installer publication, no `main` modification, no PR #2 merge;
- no fabricated historical `RELEASE_AUTHORIZED` baseline;
- hosted runners cannot replace physical user-machine L5.

## Capability Gate

| Capability | Supported method | Gate result |
|---|---|---|
| Read and inspect repository source, tests, workflows and evidence | GitHub connector, exact branch refs | PASS |
| Create isolated audit branch and draft PR | GitHub branch/PR operations | PASS |
| Modify source, tests, workflows and documentation | GitHub contents API | PASS |
| Execute Linux/Windows automated checks | GitHub Actions workflows | PASS |
| Obtain independent Codex review | PR review integration | PASS |
| Verify a genuine prior authorized release | Requires external historical installer plus prior finalizer record | BLOCKED — input absent |
| Perform physical user-machine L5 | Requires Dmitry's real Windows machine and witnessed evidence | BLOCKED — external physical action |
| Publish installer or authorize release | Forbidden while any gate is blocked | BLOCKED BY SPEC |

Supported audit and correction work proceeds. Blocked external prerequisites remain explicitly blocked and cannot be simulated.

## Requirements Traceability Matrix

| ID | Requirement / risk domain | Required action | Verification | PASS criterion | Initial status |
|---|---|---|---|---|---|
| AUD-001 | Product-scope compliance | Search UI/API/config for text-to-image, cm toggle, merged operations or legal claims | Static scan + targeted tests | No prohibited function or terminology; required separate operations remain | PENDING |
| AUD-002 | Exact identity and deterministic build | Verify version/build/source/installer identity propagation and reproducibility controls | Manifest/code/workflow inspection + tests | No mutable or filename-only identity path; exact SHA propagated | PENDING |
| AUD-003 | Archive/package admission | Check traversal, duplicate names, symlinks, CRC, decompression size, privacy denylist and atomic extraction | Adversarial tests | Every malformed or oversized archive fails before publication | PENDING |
| AUD-004 | Installer atomicity and recovery | Check staging, pre/post self-test, promotion, process shutdown, rollback and partial-install cleanup | Source inspection + Windows tests | Failure cannot leave mixed or falsely healthy installation | PENDING |
| AUD-005 | Local service exposure | Check bind address, port discovery, CORS, Host handling, browser launch and cross-origin write surface | Static + runtime tests | Service is loopback-only; untrusted origins/hosts cannot mutate state | PENDING |
| AUD-006 | Upload validation and resource exhaustion | Check extension/MIME/signature, max bytes/pixels/frames, decompression bombs and malformed images | Adversarial upload tests | Invalid, mismatched or oversized inputs fail safely before expensive processing | PENDING |
| AUD-007 | SVG/XML safety | Check DTD/entity handling, script/event/external references, data URLs, canonicalization and path injection | Adversarial SVG tests | Dangerous active/external content rejected or removed; canonical bytes are deterministic | PENDING |
| AUD-008 | Project-store integrity | Check identifier/path validation, atomic writes, locks, active asset consistency and recovery from corruption | Concurrency/adversarial tests | No traversal, lost update, partial JSON or asset/project mismatch | PENDING |
| AUD-009 | Temporary/output file lifecycle | Check unique paths, cleanup on success/failure, collision resistance and safe permissions | Tests + static scan | No stale sensitive temp files or cross-request collisions | PENDING |
| AUD-010 | Command/process execution | Check `shell=True`, unquoted PowerShell, inherited environment, executable resolution and timeout/kill behavior | Static scan + tests | No user-controlled command injection; child trees terminate on timeout/failure | PENDING |
| AUD-011 | Output correctness | Verify PNG PPI/size/alpha, halftone structure, SVG output and lineage/history selection | Existing and added tests | Binary outputs match declared operation and active source lineage | PENDING |
| AUD-012 | Update/rollback project preservation | Establish the preservation invariant over representative multiple projects containing raster and sanitized SVG assets, mixed lineage/history state, presets, titles and active selections | Windows before/update/rollback snapshots; compare every project JSON, every stored asset byte hash, metadata, active state, install identity and critical runtime hashes | Candidate update preserves every pre-existing project and asset exactly except explicitly allowed installation identity changes; forced rollback restores the complete baseline installation and all project/asset state; any missing snapshot, asset, field or hash is FAIL; no authorizing PASS without a genuine authorized baseline | PENDING |
| AUD-013 | Release authorization completeness and physical L5 provenance | Make physical user-machine L5 a mandatory externally supplied and independently SHA-pinned authorization record binding the exact source SHA, installer name/SHA, version, Build ID, install ID, physical environment descriptor, browser-driven scenario, validated output hashes, execution timestamp and Dmitry's direct witness | Finalizer positive/negative tests for missing, malformed, stale, reused, hosted-runner, witness-missing and identity-mismatched records; genuine witnessed physical run required for actual PASS | Finalizer cannot create or retain authorized output unless every gate passes and the pinned physical-L5 record matches the exact candidate and proves the required user path; until genuine physical evidence exists status remains BLOCKED / NOT VERIFIED | PENDING |
| AUD-014 | Dependency and action supply chain | Check pinned GitHub Actions, Python/Go/Node versions, package pinning/hashes and untrusted install scripts | Static contract tests | Release workflows use immutable action refs and bounded dependency versions; gaps reported | PENDING |
| AUD-015 | Workflow trigger and permission matrix | Classify every workflow as validation-only, mutating, promotion, release or authorization; inspect triggers, branch refs and `contents`/`id-token`/attestation permissions | Parse every root workflow and test allowed event-permission combinations | Automatic execution is permitted only for read-only validation with no push, publish, attestation or authorization path; every repository-writing, promotion, release or authorization workflow is manual-only and least-privileged; retired workflows cannot auto-run or write | PENDING |
| AUD-016 | Privacy and evidence leakage | Search logs/artifacts/source bundles for user data, absolute paths, tokens, project assets and unrestricted retention | Static/adversarial tests | No secrets or real user content in source/evidence; retention is bounded | PENDING |
| AUD-017 | Error contracts and false success | Check API HTTP statuses, UI success messages, evidence status fields and exception handling | Tests | Failure is non-zero/4xx-5xx and cannot be displayed or finalized as PASS | PENDING |
| AUD-018 | Concurrency and denial of service | Check processing limits, simultaneous writes, audit log locking, process count and queue behavior | Stress/concurrency tests | Bounded resources; deterministic failure without corruption | PENDING |
| AUD-019 | Browser/UI safety and accessibility-critical flow | Check deterministic selectors, disabled states, upload/operation/history/export sequence and build identity display | Browser/source tests | Required user path remains executable and errors are visible | PENDING |
| AUD-020 | Test/evidence trustworthiness | Search for string-only tests, self-asserted PASS fields, stale evidence and unexecuted critical code | Red-team review + CI | Critical behavior has runtime/adversarial coverage; claims stay bounded | PENDING |

## Confirmed findings before implementation

1. **P1 — physical L5 authorization gap.** The RTM says physical user-machine L5 is mandatory, but the current finalizer/workflow does not consume an independently pinned physical-L5 evidence record as a mandatory authorization input.
2. **P1 — stale project overwrite in AI analysis.** The endpoint mutates an asset from a previously read project snapshot and saves the entire snapshot, which can erase concurrent uploads, processing results, title/preset changes or active-asset revisions.
3. **Identity boundary.** Any application-source correction creates a new candidate. Existing `1.4.9 / Build ID 06` hosted evidence cannot authorize the corrected source.
4. **P1 — update/rollback evidence generalization gap.** The current non-authorizing diagnostic proves one generated SVG project path only; it does not establish preservation for multiple projects, raster assets or mixed project state.
5. **P2 — workflow-policy overreach.** Requiring all active workflows to be manual-only would incorrectly disable safe read-only continuous validation. The enforceable boundary is an event-permission matrix: automatic read-only validation may run, while mutation, promotion, release and authorization remain manual-only.

## Completion criteria

1. Every AUD row has a final status: PASS, FIXED/PASS, BLOCKED, or FAIL with exact evidence.
2. Every code or workflow correction has focused automated tests.
3. Complete source suite and production release self-test run after corrections.
4. Windows-specific corrections receive Windows execution evidence when applicable.
5. Independent Codex review is requested after implementation; valid findings are corrected and retested.
6. No merge into `main`, installer publication or release authorization occurs.
7. Final report distinguishes hosted technical PASS from physical L5 and historical-baseline blockers.
