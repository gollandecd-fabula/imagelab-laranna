# ImageLab Zero-Trust Release Gate — RTM v1

Date: 2026-07-24  
Owner: ImageLab by LarannA  
Mode: PROTOCOL LOCK / FAIL-CLOSED

## Scope lock

The exact installer binary delivered to the user must be the same binary, by SHA-256, that passes the clean-Windows release gate. Source tests, API-only tests, portable tests, package inspection, or a different installer binary do not authorize release.

## Evidence levels

- L0: static code/configuration evidence.
- L1: unit and component tests.
- L2: source runtime.
- L3: packaged portable runtime.
- L4: exact installer installed and executed on clean Windows.
- L5: real browser-driven user path on the installed build, with output-file validation.

## Requirements traceability matrix

| ID | Requirement | Milestone | Action | Test | Evidence artifact | PASS criterion | Current status |
|---|---|---|---|---|---|---|---|
| ZTR-001 | Create a single fail-closed release orchestrator | ZTR-M0 | Gate manifests, isolated unit verdict and final verdict generator | Local unit tests | `unit-matrix-verdict.json`, `final-verdict.json` | Missing, malformed, skipped or failed evidence produces non-zero exit and `RELEASE_BLOCKED` | IMPLEMENTED / L1 VERIFIED |
| ZTR-002 | Test the exact installer later distributed | ZTR-M1 | Build once, record SHA-256 and propagate immutable artifact | Two local deterministic builds; workflow SHA checks | `candidate-manifest.json`, `reproducibility.json` | Every downstream stage records the same installer SHA-256 | IMPLEMENTED / L3 LOCAL VERIFIED |
| ZTR-003 | Run backend production self-test before installation commit | ZTR-M1 | Installer runs the same production-service self-test in staging and after promotion | Source self-test executed; installer calls statically tested | `preinstall-selftest.json`, `postinstall-selftest.json` | Resize/PPI, history lineage, background, halftone, vector and export all PASS | SOURCE L2 PASS; WINDOWS EXECUTION PENDING |
| ZTR-004 | Validate portable/package runtime | ZTR-M2 | Build deterministic payload and validate required runtime files | Two package builds and CRC/PE checks | `candidate-manifest.json` | Exact packaged code passes structural and reproducibility checks | L3 LOCAL VERIFIED |
| ZTR-005 | Install exact EXE in clean Windows | ZTR-M3 | Fresh GitHub-hosted Windows runner installs candidate | PowerShell clean installation test | `clean-install.json`, installation logs, environment | Installer exit 0; exact version/build/install ID responds | IMPLEMENTED / NOT EXECUTED |
| ZTR-006 | Control installed UI through a real browser | ZTR-M4 | Playwright drives installed UI in Microsoft Edge; independent job uses bundled Chromium | Browser-driven scenario | trace, video, screenshots, `ui-gate.json` | Forms, buttons, history switching and operations execute from UI | IMPLEMENTED / NOT EXECUTED |
| ZTR-007 | Validate generated files, not UI messages | ZTR-M4 | Binary PNG/SVG validators inspect generated files | Output validation after UI flow | `output-validation.json`, generated files | Actual px/PPI, alpha, halftone structure, SVG fidelity and lineage pass | IMPLEMENTED / NOT EXECUTED |
| ZTR-008 | Test update over a real previous authorized version | ZTR-M5 | Download externally SHA-pinned prior release, install and keep it running, then install candidate | Windows update test | `baseline-verification.json`, `update-test.json` | Baseline differs from candidate; old process stops; project data survives; new exact identity starts | IMPLEMENTED / NOT EXECUTED |
| ZTR-009 | Test rollback on forced failure | ZTR-M5 | Inject failure after atomic promotion | Windows rollback test | `rollback-test.json` | Previous candidate install, hashes and project data are restored and runnable | IMPLEMENTED / NOT EXECUTED |
| ZTR-010 | Independent second verification | ZTR-M6 | Separate Windows job downloads the same exact candidate and repeats user path | Independent Windows/Chromium run | `independent-verification.json` plus trace and outputs | Same SHA and critical scenarios PASS independently | IMPLEMENTED / NOT EXECUTED |
| ZTR-011 | Preserve complete evidence | ZTR-M6 | Always aggregate pass or fail evidence | Final archive test | `release-evidence.zip`, `ImageLab-RELEASE-VERDICT` | Logs, traces, videos, screenshots, outputs, hashes and verdict are preserved | IMPLEMENTED; FULL ARCHIVE PENDING CI |
| ZTR-012 | Attest released binary provenance when supported | ZTR-M6 | Optional GitHub artifact attestation only after authorization | Attestation workflow step | GitHub attestation | Attestation subject digest matches authorized installer | CONFIGURED / NOT EXECUTED |
| ZTR-013 | Never publish on partial evidence | ZTR-M6 | Authorized artifact upload is conditional on finalizer success | Workflow graph and unit tests | workflow, `final-verdict.json` | Any skip, missing evidence, mismatch or failure blocks authorized artifact | IMPLEMENTED / L1 VERIFIED |

## Release gates

| Gate | Description | Minimum evidence | Local state |
|---|---|---|---|
| G0 | Static, identity, JavaScript and backend self-test | L0–L2 | PASS locally |
| G1 | Every test file in an isolated matrix process | L1 | 18/18 files PASS locally |
| G2 | Deterministic exact candidate and package verification | L3 | PASS locally; two byte-identical EXEs |
| G3 | Exact EXE clean Windows installation | L4 | NOT EXECUTED |
| G4 | Installed UI Playwright flow in Edge | L5 | NOT EXECUTED |
| G5 | Output-file validation | L5 | NOT EXECUTED |
| G6 | Update from externally pinned prior authorized release | L4/L5 | NOT EXECUTED |
| G7 | Forced-failure rollback | L4 | NOT EXECUTED |
| G8 | Independent exact-SHA rerun using another browser | L4/L5 | NOT EXECUTED |

Release is authorized only when G0–G8 are all `PASS`, all expected evidence files exist, the exact binary SHA is consistent, and the final verdict is `RELEASE_AUTHORIZED`.
