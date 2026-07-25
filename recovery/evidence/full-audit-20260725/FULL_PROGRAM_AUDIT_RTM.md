# ImageLab by LarannA — Full Program Audit RTM

Date: 2026-07-25  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Branch: `redteam/imagelab-full-audit-20260725`  
Base: PR #6 head `279116a3b0828bbbf275e66f8e4be4d8348af584`

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
| AUD-012 | Update/rollback project preservation | Recheck real project snapshots, canonical asset SHA, install identity and critical hashes | Windows behavior diagnostic | Mechanism PASS; authorizing claim remains blocked without valid baseline | PENDING |
| AUD-013 | Release authorization completeness | Audit finalizer for missing/skipped/stale evidence, physical L5, exact candidate and prior authorization chain | Positive/negative finalizer tests | No authorized output unless every mandatory gate including physical L5 is verified | PENDING |
| AUD-014 | Dependency and action supply chain | Check pinned GitHub Actions, Python/Go/Node versions, package pinning/hashes and untrusted install scripts | Static contract tests | Release workflows use immutable action refs and bounded dependency versions; gaps reported | PENDING |
| AUD-015 | Workflow triggers and permissions | Check active/retired workflows, automatic triggers, write/id-token/attestation permissions and branch refs | YAML contract tests | Least privilege; retired workflows cannot auto-run/write; active gates are manual-only | PENDING |
| AUD-016 | Privacy and evidence leakage | Search logs/artifacts/source bundles for user data, absolute paths, tokens, project assets and unrestricted retention | Static/adversarial tests | No secrets or real user content in source/evidence; retention is bounded | PENDING |
| AUD-017 | Error contracts and false success | Check API HTTP statuses, UI success messages, evidence status fields and exception handling | Tests | Failure is non-zero/4xx-5xx and cannot be displayed or finalized as PASS | PENDING |
| AUD-018 | Concurrency and denial of service | Check processing limits, simultaneous writes, audit log locking, process count and queue behavior | Stress/concurrency tests | Bounded resources; deterministic failure without corruption | PENDING |
| AUD-019 | Browser/UI safety and accessibility-critical flow | Check deterministic selectors, disabled states, upload/operation/history/export sequence and build identity display | Browser/source tests | Required user path remains executable and errors are visible | PENDING |
| AUD-020 | Test/evidence trustworthiness | Search for string-only tests, self-asserted PASS fields, stale evidence and unexecuted critical code | Red-team review + CI | Critical behavior has runtime/adversarial coverage; claims stay bounded | PENDING |

## Completion criteria

1. Every AUD row has a final status: PASS, FIXED/PASS, BLOCKED, or FAIL with exact evidence.
2. Every code or workflow correction has focused automated tests.
3. Complete source suite and production release self-test run after corrections.
4. Windows-specific corrections receive Windows execution evidence when applicable.
5. Independent Codex review is requested after implementation; valid findings are corrected and retested.
6. No merge into `main`, installer publication or release authorization occurs.
7. Final report distinguishes hosted technical PASS from physical L5 and historical-baseline blockers.
