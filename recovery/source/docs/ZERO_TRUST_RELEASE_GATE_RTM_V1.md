# ImageLab Zero-Trust Release Gate — RTM v1

Date: 2026-07-25  
Owner: ImageLab by LarannA  
Mode: PROTOCOL LOCK / FAIL-CLOSED

## Scope lock

The exact installer binary delivered to the user must be the same binary, by SHA-256, that passes the clean-Windows release gate. Source tests, API-only tests, portable tests, package inspection, a differently built installer, a matching filename, or an operator-entered authorization flag do not authorize release.

No historical installer may be retroactively renamed, relabelled or declared `RELEASE_AUTHORIZED`.

## Evidence levels

- L0: static code/configuration evidence.
- L1: unit and component tests.
- L2: source runtime.
- L3: packaged portable runtime.
- L4: exact installer installed and executed on clean Windows.
- L5: real browser-driven user path on the installed build, with output-file validation.
- Physical user-machine L5 is an additional release prerequisite and cannot be replaced by a hosted runner.

## First-release bootstrap rule

`GENESIS-FIRST-RELEASE-V1` is a one-time bootstrap rule for the first official ImageLab release only.

It does not mark G6 or G7 as `PASS`. Instead, the dedicated Genesis Release Gate may record:

- `G6 = NOT_APPLICABLE_FIRST_RELEASE`;
- `G7 = NOT_APPLICABLE_FIRST_RELEASE`.

This is permitted only when all of the following are independently verified:

1. A completed exact-SHA qualification run proves G0–G5 and G8 `PASS` for the candidate.
2. Complete paginated GitHub Releases and Actions-history queries find zero authorized installer assets, zero `ImageLab-RELEASE-AUTHORIZATION.json` assets, zero prior successful genesis runs and zero prior authorized genesis artifacts.
3. A strictly validated request changes exactly `recovery/genesis-request/GENESIS-REQUEST.json` in a reviewed push to `bootstrap/zero-trust-gate`; no other file is changed.
4. An externally produced and independently SHA-pinned physical user-machine L5 manifest and evidence bundle match the exact installer SHA, version and build.
5. Every other genesis finalizer requirement passes.
6. The dedicated genesis finalizer creates the first genuine `ImageLab-RELEASE-AUTHORIZATION.json`.

After that first authorization record exists, the genesis path must fail closed permanently. Every later release must use the normal G6/G7 update and rollback path against a genuine prior authorized release.

## Current exact candidate

- Version: `1.4.9-recovery-candidate`.
- Build ID: `REC-RT8-M6-20260724-06`.
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
| ZTR-008 | Test update over a real previous authorized version | ZTR-M5 | Normal mode requires exact prior installer plus independently SHA-pinned prior finalizer record; genesis mode permits only `NOT_APPLICABLE_FIRST_RELEASE` after verified absence | Windows behavior-level update test or genesis absence adversarial test | `baseline-verification.json` or `genesis-baseline-verification.json` | Normal: prior authorized baseline is valid and update passes. Genesis: zero prior authorized assets are proven and no G6 PASS is claimed | MECHANISM PASS ON 1.4.8→1.4.9 DIAGNOSTIC; NORMAL G6 BLOCKED; GENESIS IMPLEMENTATION PENDING CI |
| ZTR-009 | Test rollback on forced failure | ZTR-M5 | Normal mode injects failure and restores prior authorized install; genesis mode records only `NOT_APPLICABLE_FIRST_RELEASE` | Windows rollback test or genesis finalizer adversarial test | `rollback-test.json`, genesis final verdict | Normal: exact prior install/project restored. Genesis: G7 is not represented as PASS | MECHANISM PASS, NON-AUTHORIZING; NORMAL G7 BLOCKED; GENESIS IMPLEMENTATION PENDING CI |
| ZTR-010 | Independent second verification | ZTR-M6 | Separate Windows job downloads the same exact candidate and repeats installed user path | Independent Windows/Chromium run | `independent-verification.json`, self-tests, trace and outputs | Same SHA and critical scenarios PASS independently | HOSTED L4/L5 PASS |
| ZTR-011 | Preserve complete evidence | ZTR-M6 | Always aggregate pass or fail evidence | Final archive and artifact checks | `release-evidence.zip`, release verdict artifact | Logs, traces, outputs, hashes, physical L5 bundle and verdict are preserved | HOSTED EVIDENCE PRESERVED; AUTHORIZED RELEASE ARCHIVE BLOCKED |
| ZTR-012 | Attest released outputs when supported | ZTR-M6 | Optional GitHub artifact attestation only after authorization | Attestation workflow step | GitHub attestation | Attestation subject digest matches authorized outputs | CONFIGURED / NOT EXECUTED |
| ZTR-013 | Never publish on partial evidence | ZTR-M6 | Authorized upload is conditional on finalizer success | Workflow graph, positive and negative tests | workflow, final verdict, authorization record | Any skip, missing evidence, mismatch or failure blocks authorized artifact | IMPLEMENTED / L1 VERIFIED |
| ZTR-014 | Bootstrap the first release without inventing a historical baseline | ZTR-M5/M6 | Dedicated genesis workflow consumes a strictly validated request, exact qualification run, Release/Actions history and a separate genesis finalizer | `tests/test_genesis_release_gate.py` | Genesis works only once; normal gate is unchanged; prior assets/runs/artifacts, mixed-file pushes or malformed evidence block | IMPLEMENTED / FINAL-HEAD CI VERIFICATION PENDING |
| ZTR-014A | Execute genesis without modifying default `main` | ZTR-M5/M6 | Dedicated root request workflow `.github/workflows/zero-trust-genesis-request.yml` listens only for a reviewed request-only push to `bootstrap/zero-trust-gate`; source template retains manual dispatch | Workflow static contract and request resolver tests | Push changes exactly the fixed JSON request path and every field matches the finalizer arguments | IMPLEMENTED / FINAL-HEAD CI VERIFICATION PENDING |
| ZTR-014B | Prevent repeated genesis before Release publication | ZTR-M5/M6 | Scan prior workflow runs and authorized genesis artifacts in addition to Releases | History verifier adversarial tests | Any prior successful genesis run or authorized artifact blocks | IMPLEMENTED / FINAL-HEAD CI VERIFICATION PENDING |
| ZTR-015 | Require physical user-machine L5 for genesis authorization | ZTR-M6 | Download independently pinned manifest and evidence ZIP; inspect exact SHA, identity, self-tests, browser trace and output files | Positive and tamper tests | Exact physical L5 manifest and bundle pass; missing or mismatched evidence blocks | VALIDATOR IMPLEMENTED / REAL PHYSICAL L5 NOT YET SUPPLIED |

## Release gates

| Gate | Description | Minimum evidence | Current state |
|---|---|---|---|
| G0 | Static, identity, JavaScript and backend self-test | L0–L2 | PASS for exact 1.4.9 |
| G1 | Every required test file in an isolated matrix process | L1 | 26/26 PASS for exact 1.4.9; evidence-hardening suite 152/152 PASS |
| G2 | Deterministic exact candidate and package verification | L3 | PASS; two byte-identical installers |
| G3 | Exact EXE clean Windows installation and mandatory embedded self-tests | L4 | PASS on hosted clean Windows |
| G4 | Installed UI Playwright flow in Edge | L5 | PASS on hosted Windows; physical user-machine L5 not verified |
| G5 | Output-file validation | L5 | PASS on hosted Windows |
| G6 | Update from externally pinned prior authorized release | L4/L5 | NORMAL: BLOCKED because no genuine historical baseline exists. GENESIS: may be `NOT_APPLICABLE_FIRST_RELEASE`, never PASS, only after verified absence |
| G7 | Forced-failure rollback to prior authorized release | L4/L5 | NORMAL: BLOCKED by G6. GENESIS: may be `NOT_APPLICABLE_FIRST_RELEASE`, never PASS |
| G8 | Independent exact-SHA rerun using another browser | L4/L5 | PASS on independent hosted Windows runner |

A normal release is authorized only when G0–G8 are all `PASS`, the prior authorization record is valid, physical user-machine L5 is verified and the final verdict is `RELEASE_AUTHORIZED`.

The one-time genesis release is authorized only when G0–G5 and G8 are `PASS`, G6/G7 are exactly `NOT_APPLICABLE_FIRST_RELEASE`, the request verifier and Release/Actions-history absence verifier are `PASS`, physical user-machine L5 is verified for the exact candidate, and the genesis final verdict is `RELEASE_AUTHORIZED`.

Current final state:

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
