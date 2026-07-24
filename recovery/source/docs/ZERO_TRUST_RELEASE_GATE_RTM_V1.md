# ImageLab Zero-Trust Release Gate — RTM v1

Date: 2026-07-24  
Status snapshot updated: 2026-07-25  
Owner: ImageLab by LarannA  
Mode: PROTOCOL LOCK / FAIL-CLOSED

## Scope lock

The exact installer binary delivered to the user must be the same binary, by SHA-256, that passes the clean-Windows release gate. Source tests, API-only tests, portable tests, package inspection, or a different installer binary do not authorize release.

This status update does not change any requirement, test method, PASS criterion, or release boundary. It only reconciles the RTM status fields with current evidence.

## Current exact candidate

- Version: `1.4.9-recovery-candidate`.
- Build ID: `REC-RT8-M6-20260724-06`.
- Source SHA-256: `83bcfcc9e9d6dfaa29ef2827f3a967d9719cbff2650672b7d5d9d3eac1af4885`.
- Exact Windows installer: `ImageLab_by_LarannA_RC13_WINDOWS_Setup_x64.exe`.
- Exact installer SHA-256: `12817550c2fac6a6453945c38eefe86368cd4cfa1991c1565e49b092bd818d56`.
- Hosted Windows evidence run: `30111216367`.

## Evidence levels

- L0: static code/configuration evidence.
- L1: unit and component tests.
- L2: source runtime.
- L3: packaged portable runtime.
- L4: exact installer installed and executed on clean Windows.
- L5: real browser-driven user path on the installed build, with output-file validation.

Hosted L5 evidence and physical user-machine L5 evidence are tracked separately. Hosted browser execution does not replace the still-unverified physical target-machine run required by the project release plan.

## Requirements traceability matrix

| ID | Requirement | Milestone | Action | Test | Evidence artifact | PASS criterion | Current status |
|---|---|---|---|---|---|---|---|
| ZTR-001 | Create a single fail-closed release orchestrator | ZTR-M0 | Gate manifests, isolated unit verdict and final verdict generator | Local unit tests | `unit-matrix-verdict.json`, `final-verdict.json` | Missing, malformed, skipped or failed evidence produces non-zero exit and `RELEASE_BLOCKED` | IMPLEMENTED / L1 VERIFIED |
| ZTR-002 | Test the exact installer later distributed | ZTR-M1 | Build once, record SHA-256 and propagate immutable artifact | Two deterministic builds; workflow SHA checks | `candidate-manifest.json`, `reproducibility.json` | Every downstream stage records the same installer SHA-256 | HOSTED L3 PASS / EXACT SHA PINNED |
| ZTR-003 | Run backend production self-test before installation commit | ZTR-M1 | Installer runs the same production-service self-test in staging and after promotion | Source and installed self-tests | `preinstall-selftest.json`, `postinstall-selftest.json` | Resize/PPI, history lineage, background, halftone, vector and export all PASS | SOURCE L2 PASS / HOSTED WINDOWS PASS |
| ZTR-004 | Validate portable/package runtime | ZTR-M2 | Build deterministic payload and validate required runtime files | Two package builds and CRC/PE checks | `candidate-manifest.json` | Exact packaged code passes structural and reproducibility checks | HOSTED L3 PASS |
| ZTR-005 | Install exact EXE in clean Windows | ZTR-M3 | Fresh GitHub-hosted Windows runner installs candidate | PowerShell clean installation test | `clean-install.json`, installation logs, environment | Installer exit 0; exact version/build/install ID responds | HOSTED L4 PASS |
| ZTR-006 | Control installed UI through a real browser | ZTR-M4 | Playwright drives installed UI in Microsoft Edge; independent job uses bundled Chromium | Browser-driven scenario | trace, video, screenshots, UI evidence | Forms, buttons, history switching and operations execute from UI | HOSTED L5 PASS / PHYSICAL USER-MACHINE L5 UNVERIFIED |
| ZTR-007 | Validate generated files, not UI messages | ZTR-M4 | Binary PNG/SVG validators inspect generated files | Output validation after UI flow | output validation evidence and generated files | Actual px/PPI, alpha, halftone structure, SVG fidelity and lineage pass | HOSTED L5 PASS / PHYSICAL USER-MACHINE L5 UNVERIFIED |
| ZTR-008 | Test update over a real previous authorized version | ZTR-M5 | Download externally SHA-pinned prior release, install and keep it running, then install candidate | Windows update test | `baseline-verification.json`, `update-test.json` | Baseline differs from candidate; old process stops; project data survives; new exact identity starts | BLOCKED — AUTHORIZED BASELINE NOT AVAILABLE |
| ZTR-009 | Test rollback on forced failure | ZTR-M5 | Inject failure after atomic promotion | Windows rollback test | `rollback-test.json` | Previous candidate install, hashes and project data are restored and runnable | MECHANISM DIAGNOSTIC PASS / AUTHORIZING EXECUTION BLOCKED BY ZTR-008 |
| ZTR-010 | Independent second verification | ZTR-M6 | Separate Windows job downloads the same exact candidate and repeats user path | Independent Windows/Chromium run | `independent-verification.json` plus trace and outputs | Same SHA and critical scenarios PASS independently | HOSTED L4/L5 PASS |
| ZTR-011 | Preserve complete evidence | ZTR-M6 | Always aggregate pass or fail evidence | Final archive test | `release-evidence.zip`, `ImageLab-RELEASE-VERDICT` | Logs, traces, videos, screenshots, outputs, hashes and verdict are preserved | HOSTED EVIDENCE PRESERVED / FINAL AUTHORIZED ARCHIVE BLOCKED |
| ZTR-012 | Attest released binary provenance when supported | ZTR-M6 | Optional GitHub artifact attestation only after authorization | Attestation workflow step | GitHub attestation | Attestation subject digest matches authorized installer | CONFIGURED / NOT EXECUTED — RELEASE BLOCKED |
| ZTR-013 | Never publish on partial evidence | ZTR-M6 | Authorized artifact upload is conditional on finalizer success | Workflow graph and unit tests | workflow, `final-verdict.json` | Any skip, missing evidence, mismatch or failure blocks authorized artifact | IMPLEMENTED / L1 VERIFIED / CURRENT VERDICT BLOCKED |

## Release gates

| Gate | Description | Minimum evidence | Current state |
|---|---|---|---|
| G0 | Static, identity, JavaScript and backend self-test | L0–L2 | PASS — source regression and self-test evidence |
| G1 | Every required test file in an isolated matrix process | L1 | PASS — 26/26 required isolated test files |
| G2 | Deterministic exact candidate and package verification | L3 | PASS — two byte-identical exact Windows installers |
| G3 | Exact EXE clean Windows installation | L4 | PASS on hosted clean Windows |
| G4 | Installed UI Playwright flow in Edge | L5 | PASS hosted / physical user-machine L5 unverified |
| G5 | Output-file validation | L5 | PASS hosted / physical user-machine L5 unverified |
| G6 | Update from externally pinned prior authorized release | L4/L5 | BLOCKED — no prior `RELEASE_AUTHORIZED` baseline exists |
| G7 | Forced-failure rollback | L4 | Technical mechanism diagnostic PASS; authorizing gate BLOCKED by invalid G6 baseline |
| G8 | Independent exact-SHA rerun using another browser | L4/L5 | PASS on independent hosted Windows runner |

## Evidence references

- Hosted Windows summary: `recovery/evidence/windows-gate/rc13-windows-evidence-summary.json`.
- Update/rollback mechanism diagnostic: `recovery/evidence/update-rollback/diagnostic-update-rollback-148-149-summary.json`.
- G6 blocker: `recovery/evidence/update-rollback/g6-authorized-baseline-blocker.json`.

Release is authorized only when every applicable mandatory gate is genuinely `PASS`, all expected evidence files exist, the exact binary SHA is consistent, the physical user-machine requirement is complete, and the final verdict is `RELEASE_AUTHORIZED`.

Current final state:

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
