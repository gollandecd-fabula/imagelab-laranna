# ImageLab Zero-Trust Release Gate — RTM v1

Date: 2026-07-25  
Owner: ImageLab by LarannA  
Mode: PROTOCOL LOCK / FAIL-CLOSED

## Scope lock

The installer delivered to the user must be byte-for-byte identical, by SHA-256, to the installer that passes the release gate. Source tests, API-only tests, portable tests, package inspection, a differently built installer, a matching filename, synthetic evidence or an operator-entered authorization flag do not authorize release.

## Evidence levels

- L0: static code/configuration evidence.
- L1: unit and component tests.
- L2: source runtime.
- L3: packaged portable runtime.
- L4: exact installer installed and executed on clean Windows.
- L5: real browser-driven user path on the installed build, with output-file validation.
- Physical user-machine L5 is an additional release prerequisite and cannot be replaced by a hosted runner.

## Candidate identity state

The former exact `1.4.9-recovery-candidate / REC-RT8-M6-20260724-06` and installer SHA `12817550c2fac6a6453945c38eefe86368cd4cfa1991c1565e49b092bd818d56` remain historical evidence only. Application-source corrections in the full-audit branch invalidate that candidate identity for release. A new version, Build ID, source SHA and installer SHA must be assigned after code freeze and must pass a complete new B0–B5/B8 run.

Physical user-machine L5 for the corrected candidate: `NOT VERIFIED`.

## Requirements traceability matrix

| ID | Requirement | Milestone | Action | Test | Evidence artifact | PASS criterion | Current status |
|---|---|---|---|---|---|---|---|
| ZTR-001 | Create a single fail-closed release orchestrator | ZTR-M0 | Gate manifests, isolated unit verdict and final-verdict generator | Positive and adversarial finalizer tests | `unit-matrix-verdict.json`, `final-verdict.json` | Missing, malformed, skipped, stale, mismatched or failed evidence produces non-zero exit and `RELEASE_BLOCKED` | IMPLEMENTED; REVALIDATION PENDING |
| ZTR-002 | Test the exact installer later distributed | ZTR-M1 | Build once, record SHA-256 and propagate immutable artifact | Two deterministic builds; downstream SHA checks | `candidate-manifest.json`, `reproducibility.json` | Every downstream stage records the same installer SHA-256 | NEW CANDIDATE NOT YET FROZEN |
| ZTR-003 | Run production self-test before installation commit and after promotion | ZTR-M1 | Installer runs production self-test in staging and after promotion; finalizer requires clean and independent pre/post evidence | Source self-test, clean Windows install and independent rerun | `preinstall-selftest.json`, `postinstall-selftest.json` | Critical operations PASS with exact app/version/build/install identity | IMPLEMENTED; NEW-CANDIDATE WINDOWS RERUN REQUIRED |
| ZTR-004 | Validate portable/package runtime | ZTR-M2 | Build deterministic payload and validate required runtime files | Two package builds and CRC/PE checks | `candidate-manifest.json` | Exact packaged code passes structural and reproducibility checks | NEW-CANDIDATE RERUN REQUIRED |
| ZTR-005 | Install exact EXE in clean Windows | ZTR-M3 | Fresh hosted Windows runner installs candidate | PowerShell clean-install test | `clean-install.json`, logs | Installer exit 0; exact version/build/install ID responds | HISTORICAL 1.4.9 PASS; NEW CANDIDATE PENDING |
| ZTR-006 | Control installed UI through browsers and require physical user-machine L5 | ZTR-M4 | Hosted Edge and bundled Chromium runs plus external SHA-pinned physical record | Browser scenarios; adversarial physical-record tests; actual witnessed run | UI evidence plus `physical-l5.json` | Hosted paths PASS; physical record binds exact source/installer/version/build/install, required steps, output hashes, timestamp and Dmitry witness | VALIDATOR/WORKFLOW IMPLEMENTED; CI PENDING; ACTUAL PHYSICAL L5 NOT VERIFIED |
| ZTR-007 | Validate generated files, not UI messages | ZTR-M4 | Binary PNG/SVG validators inspect generated files | Output validation after UI flow | `output-validation.json`, generated files | Actual px/PPI, alpha, halftone, SVG fidelity and lineage pass | HISTORICAL PASS; NEW CANDIDATE PENDING |
| ZTR-008 | Test update over a real previous authorized version | ZTR-M5 | Require exact prior normal or Genesis installer plus independently SHA-pinned finalizer record; keep baseline running; install candidate; verify complete project preservation | Windows behavior update test | `baseline-verification.json`, `update-test.json`, snapshots | Prior record is `RELEASE_AUTHORIZED` or `GENESIS_RELEASE_AUTHORIZED`, binds exact different installer, old process stops, all projects survive, new identity starts | NORMAL PATH IMPLEMENTED; MULTI-PROJECT EVIDENCE EXPANSION PENDING |
| ZTR-009 | Test rollback on forced failure | ZTR-M5 | Inject failure after atomic promotion and verify full installation/project restoration | Windows behavior rollback test | `rollback-test.json`, snapshots | Critical hashes, identity, every project JSON and asset byte are restored and runnable | SINGLE-PROJECT DIAGNOSTIC HISTORICAL; MULTI-PROJECT RERUN PENDING |
| ZTR-010 | Independent second verification | ZTR-M6 | Separate Windows job repeats exact candidate path | Independent Windows/Chromium run | independent evidence | Same SHA and critical scenarios PASS independently | NEW CANDIDATE PENDING |
| ZTR-011 | Preserve complete evidence | ZTR-M6 | Always aggregate pass or fail evidence, including pinned physical record | Final archive and artifact checks | `release-evidence.zip`, verdict artifact | Logs, traces, outputs, hashes, physical record and verdict are preserved | IMPLEMENTED; REVALIDATION PENDING |
| ZTR-012 | Attest released outputs when supported | ZTR-M6 | Optional attestation only after authorization using immutable action commit | Workflow contract | GitHub attestation | Subject digest matches authorized outputs | ACTION PINNED; NOT EXECUTED |
| ZTR-013 | Never publish on partial evidence | ZTR-M6 | Clear stale normal/Genesis outputs before evaluation and on failure; upload authorized artifact only after finalizer success | Positive and adversarial tests | workflow, verdict, authorization record | Any missing gate, invalid baseline, physical-L5 failure, identity mismatch or stale output blocks authorization | CODE IMPLEMENTED; CI AND INDEPENDENT REVIEW PENDING |

## Release gates

| Gate | Description | Minimum evidence | Current state |
|---|---|---|---|
| G0 | Static, identity, JavaScript and backend self-test | L0–L2 | NEW CANDIDATE PENDING |
| G1 | Every required test file in an isolated process | L1 | UPDATED SUITE PENDING CI |
| G2 | Deterministic exact candidate and package verification | L3 | NEW CANDIDATE PENDING |
| G3 | Exact EXE clean Windows installation and embedded self-tests | L4 | NEW CANDIDATE PENDING |
| G4 | Installed UI flow in Edge | Hosted L5 | NEW CANDIDATE PENDING |
| G5 | Output-file validation | Hosted L5 | NEW CANDIDATE PENDING |
| G6 | Update from externally pinned prior normal/Genesis authorized release | L4/L5 | NORMAL PATH AVAILABLE AFTER GENESIS; MULTI-PROJECT TEST PENDING |
| G7 | Forced-failure rollback with complete project restoration | L4/L5 | MULTI-PROJECT TEST PENDING |
| G8 | Independent exact-SHA rerun using another browser | L4/L5 | NEW CANDIDATE PENDING |
| Physical L5 | Real user-machine browser path and validated outputs, SHA-pinned and Dmitry-witnessed | Physical L5 | NOT VERIFIED |

Release is authorized only when every applicable gate is PASS, all evidence exists, exact binary/source identities are consistent, the prior authorization chain or approved one-time Genesis path is valid, physical user-machine L5 is verified, and the final verdict is an allowed authorization status.

Current final state:

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
