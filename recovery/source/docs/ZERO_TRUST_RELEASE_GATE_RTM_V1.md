# ImageLab Zero-Trust Release Gate — RTM v1

Date: 2026-07-25  
Owner: ImageLab by LarannA  
Mode: PROTOCOL LOCK / FAIL-CLOSED

## Scope lock

The exact installer binary delivered to the user must be the same binary, by SHA-256, that passes the clean-Windows release gate. Source tests, API-only tests, portable tests, package inspection, a differently built installer, a matching filename, or an operator-entered authorization flag do not authorize release.

## Evidence levels

- L0: static code/configuration evidence.
- L1: unit and component tests.
- L2: source runtime.
- L3: packaged portable runtime.
- L4: exact installer installed and executed on clean Windows.
- L5: real browser-driven user path on the installed build, with output-file validation.
- Physical user-machine L5 is an additional release prerequisite and cannot be replaced by a hosted runner.

## Current exact candidate

- Version: `1.4.9-recovery-candidate`.
- Build ID: `REC-RT8-M6-20260724-06`.
- Source bundle SHA-256: `83bcfcc9e9d6dfaa29ef2827f3a967d9719cbff2650672b7d5d9d3eac1af4885`.
- Canonical source provenance: `recovery/dist/ImageLab_by_LarannA_RECOVERY_1.4.9_SOURCE.zip`, promoted to `bootstrap/imagelab-source.zip` by commit `87dfdb2f1c37359028320a2df3b055baf9a03b1f`.
- Canonical-source pin: `recovery/evidence/windows-gate/bootstrap-canonical-source-pin.json`.
- Installer SHA-256: `12817550c2fac6a6453945c38eefe86368cd4cfa1991c1565e49b092bd818d56`.
- Hosted Windows evidence run: `30111216367`.
- Real-project update/rollback diagnostic: PASS, explicitly non-authorizing.
- Genuine previous `RELEASE_AUTHORIZED` baseline: unavailable.
- Physical user-machine L5: not verified.

## Requirements traceability matrix

| ID | Requirement | Milestone | Action | Test | Evidence artifact | PASS criterion | Current status |
|---|---|---|---|---|---|---|---|
| ZTR-001 | Create a single fail-closed release orchestrator | ZTR-M0 | Gate manifests, isolated unit verdict and final verdict generator | Positive and adversarial finalizer tests | `unit-matrix-verdict.json`, `final-verdict.json` | Missing, malformed, skipped, stale, mismatched or failed evidence produces non-zero exit and `RELEASE_BLOCKED` | IMPLEMENTED / L1 VERIFIED |
| ZTR-002 | Test the exact installer later distributed | ZTR-M1 | Build once, record SHA-256 and propagate immutable artifact | Two deterministic builds; downstream SHA checks | `candidate-manifest.json`, `reproducibility.json` | Every downstream stage records the same installer SHA-256 | HOSTED L3 PASS FOR EXACT 1.4.9 |
| ZTR-003 | Run backend production self-test before installation commit and after promotion | ZTR-M1 | Installer runs the same production-service self-test in staging and after promotion; finalizer requires clean and independent pre/post evidence | Source self-test, clean Windows install and independent Windows rerun | `preinstall-selftest.json`, `postinstall-selftest.json` | Resize/PPI, history lineage, background, halftone, vector and export all PASS with exact app/version/build/install identity | HOSTED WINDOWS PASS; FINALIZER ENFORCEMENT VERIFIED |
| ZTR-004 | Validate portable/package runtime | ZTR-M2 | Build deterministic payload and validate required runtime files | Two package builds and CRC/PE checks | `candidate-manifest.json` | Exact packaged code passes structural and reproducibility checks | HOSTED L3 PASS |
| ZTR-005 | Install exact EXE in clean Windows | ZTR-M3 | Fresh GitHub-hosted Windows runner installs candidate | PowerShell clean installation test | `clean-install.json`, installation logs, environment | Installer exit 0; exact version/build/install ID responds | HOSTED L4 PASS |
| ZTR-006 | Control installed UI through a real browser | ZTR-M4 | Playwright drives installed UI in Microsoft Edge; independent job uses bundled Chromium | Browser-driven scenario | trace, video, screenshots, `ui-gate.json` | Forms, buttons, history switching and operations execute from UI | HOSTED L5 PASS; PHYSICAL USER-MACHINE L5 NOT VERIFIED |
| ZTR-007 | Validate generated files, not UI messages | ZTR-M4 | Binary PNG/SVG validators inspect generated files | Output validation after UI flow | `output-validation.json`, generated files | Actual px/PPI, alpha, halftone structure, SVG fidelity and lineage pass | HOSTED L5 PASS; OUTPUTS BYTE-IDENTICAL ACROSS RUNNERS |
| ZTR-008 | Test update over a real previous authorized version | ZTR-M5 | Require exact prior installer plus independently SHA-pinned prior finalizer authorization record; keep baseline running; install candidate; verify real project and asset preservation | Windows behavior-level update test | `baseline-verification.json`, `update-test.json`, project snapshots | Prior record says `RELEASE_AUTHORIZED` and binds exact installer; baseline differs from candidate; old process stops; real project survives; new exact identity starts | MECHANISM PASS ON 1.4.8→1.4.9 DIAGNOSTIC; AUTHORIZING G6 BLOCKED — NO PRIOR AUTHORIZED BASELINE |
| ZTR-009 | Test rollback on forced failure | ZTR-M5 | Inject failure after atomic promotion and reopen the real project after restoration | Windows behavior-level rollback test | `rollback-test.json`, project snapshots | Previous candidate install, critical hashes, identity, project JSON and asset bytes are restored and runnable | MECHANISM PASS, NON-AUTHORIZING; G7 BLOCKED BY G6 BASELINE |
| ZTR-010 | Independent second verification | ZTR-M6 | Separate Windows job downloads the same exact candidate and repeats installed user path | Independent Windows/Chromium run | `independent-verification.json`, self-tests, trace and outputs | Same SHA and critical scenarios PASS independently | HOSTED L4/L5 PASS |
| ZTR-011 | Preserve complete evidence | ZTR-M6 | Always aggregate pass or fail evidence | Final archive and artifact checks | `release-evidence.zip`, `ImageLab-RELEASE-VERDICT` | Logs, traces, videos, screenshots, outputs, hashes and verdict are preserved | HOSTED EVIDENCE PRESERVED; AUTHORIZED RELEASE ARCHIVE BLOCKED |
| ZTR-012 | Attest released outputs when supported | ZTR-M6 | Optional GitHub artifact attestation only after authorization | Attestation workflow step | GitHub attestation | Attestation subject digest matches authorized outputs | CONFIGURED / NOT EXECUTED |
| ZTR-013 | Never publish on partial evidence | ZTR-M6 | Authorized artifact upload is conditional on finalizer success; finalizer creates a prior-release authorization record only after complete PASS | Workflow graph, positive and negative tests | workflow, `final-verdict.json`, `ImageLab-RELEASE-AUTHORIZATION.json` | Any skip, missing evidence, mismatch, filename-only baseline, non-authorized record or failure blocks authorized artifact | IMPLEMENTED / L1 VERIFIED |

## Release gates

| Gate | Description | Minimum evidence | Current state |
|---|---|---|---|
| G0 | Static, identity, JavaScript and backend self-test | L0–L2 | PASS for exact 1.4.9 |
| G1 | Every required test file in an isolated matrix process | L1 | 26/26 PASS for exact 1.4.9; evidence-hardening suite 152/152 PASS |
| G2 | Deterministic exact candidate and package verification | L3 | PASS; two byte-identical installers |
| G3 | Exact EXE clean Windows installation and mandatory embedded self-tests | L4 | PASS on hosted clean Windows |
| G4 | Installed UI Playwright flow in Edge | L5 | PASS on hosted Windows; physical user-machine L5 not verified |
| G5 | Output-file validation | L5 | PASS on hosted Windows |
| G6 | Update from externally pinned prior authorized release with independently pinned prior finalizer record | L4/L5 | BLOCKED: no genuine historical `RELEASE_AUTHORIZED` installer and record exist; non-authorizing mechanism diagnostic PASS |
| G7 | Forced-failure rollback with real-project restoration | L4/L5 | BLOCKED in authorizing form by G6; non-authorizing mechanism diagnostic PASS |
| G8 | Independent exact-SHA rerun using another browser | L4/L5 | PASS on independent hosted Windows runner |

Release is authorized only when G0–G8 are all `PASS`, all expected evidence files exist, the exact binary SHA is consistent, the baseline authorization record is independently pinned and valid, physical user-machine L5 is verified, and the final verdict is `RELEASE_AUTHORIZED`.

Current final state:

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
