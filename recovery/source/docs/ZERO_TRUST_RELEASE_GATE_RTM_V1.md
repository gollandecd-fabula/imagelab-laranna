# ImageLab Zero-Trust Release Gate — RTM v1

Date: 2026-07-27  
Owner: ImageLab by LarannA  
Mode: PROTOCOL LOCK / FAIL-CLOSED

## Scope lock

The installer delivered to the user must be byte-for-byte identical, by SHA-256, to the installer that passes the release gate. Source tests, API-only tests, portable tests, package inspection, a differently built installer, a matching filename, synthetic evidence or an operator-entered authorization flag do not authorize release.

Genesis is a one-time first-release exception only for the impossible requirement to update from an earlier authorized release. Genesis does not waive G7 or any other gate. It requires independently pinned, schema-3 update/rollback evidence produced with a distinct non-authorizing diagnostic baseline for the exact candidate.

Normal and Genesis modes use the same mandatory `validate_physical_l5` implementation and the same independently SHA-pinned physical-L5 JSON schema. A separate or weaker Genesis physical schema is forbidden.

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
| ZTR-001 | Create a single fail-closed release orchestrator | ZTR-M0 | Gate manifests, isolated unit verdict and final-verdict generator | Positive and adversarial finalizer tests | `unit-matrix-verdict.json`, `final-verdict.json` | Missing, malformed, skipped, stale, mismatched or failed evidence produces non-zero exit and `RELEASE_BLOCKED` | IMPLEMENTED; CURRENT-HEAD CI REVALIDATION REQUIRED |
| ZTR-002 | Test the exact installer later distributed | ZTR-M1 | Build once, record SHA-256 and propagate immutable artifact | Two deterministic builds; downstream SHA checks | `candidate-manifest.json`, `reproducibility.json` | Every downstream stage records the same installer SHA-256 | NEW CANDIDATE NOT YET FROZEN |
| ZTR-003 | Run production self-test before installation commit and after promotion | ZTR-M1 | Installer runs production self-test in staging and after promotion; finalizer requires clean and independent pre/post evidence | Source self-test, clean Windows install and independent rerun | `preinstall-selftest.json`, `postinstall-selftest.json` | Critical operations PASS with exact app/version/build/install identity | IMPLEMENTED; NEW-CANDIDATE WINDOWS RERUN REQUIRED |
| ZTR-004 | Validate portable/package runtime | ZTR-M2 | Build deterministic payload and validate required runtime files | Two package builds and CRC/PE checks | `candidate-manifest.json` | Exact packaged code passes structural and reproducibility checks | NEW-CANDIDATE RERUN REQUIRED |
| ZTR-005 | Install exact EXE in clean Windows | ZTR-M3 | Fresh hosted Windows runner installs candidate | PowerShell clean-install test | `clean-install.json`, logs | Installer exit 0; exact version/build/install ID responds | HISTORICAL 1.4.9 PASS; NEW CANDIDATE PENDING |
| ZTR-006 | Control installed UI through browsers and require physical user-machine L5 | ZTR-M4 | Hosted Edge and bundled Chromium runs plus one external SHA-pinned physical JSON record accepted by the shared validator | Browser scenarios; adversarial shared-validator tests; actual witnessed run | UI evidence plus `physical-l5.json` | Hosted paths PASS; record binds exact source/installer/version/build/install, required steps, output hashes, timestamp and Dmitry witness | SHARED VALIDATOR WIRED INTO BOTH MODES; ACTUAL PHYSICAL L5 NOT VERIFIED |
| ZTR-007 | Validate generated files, not UI messages | ZTR-M4 | Binary PNG/SVG validators inspect generated files | Output validation after UI flow | `output-validation.json`, generated files | Actual px/PPI, alpha, halftone, SVG fidelity and lineage pass | HISTORICAL PASS; NEW CANDIDATE PENDING |
| ZTR-008 | Test normal update over a real previous authorized version | ZTR-M5 | Require exact prior normal or Genesis installer plus independently SHA-pinned finalizer record; verify complete project preservation | Windows behavior update test | `baseline-verification.json`, `update-test.json`, snapshots | Prior record binds an exact different authorized installer; old process stops; all projects survive; new identity starts | NORMAL PATH IMPLEMENTED; NEW EXACT-CANDIDATE EVIDENCE PENDING |
| ZTR-008G | Bind one-time Genesis G6 exception | ZTR-M5 | Permit bypass only of the missing prior-authorized update baseline; forbid current-candidate self-baseline | Positive and adversarial Genesis contracts | history evidence, request evidence, `g7-evidence.json` | No prior normal/Genesis authorization exists; current candidate is not its own diagnostic baseline | CORRECTION PUSHED; CI/INDEPENDENT REVIEW PENDING |
| ZTR-009 | Require rollback on forced failure in normal and Genesis modes | ZTR-M5 | Inject failure after atomic promotion and verify full installation/project restoration; Genesis consumes independently pinned `ImageLab-GENESIS-G7-EVIDENCE.zip` | Schema-3 update/rollback validation; missing/failed/N/A/self-baseline negatives | `g7-evidence.json`, `update-test.json`, `rollback-test.json`, snapshots | G7 is PASS for exact candidate; critical hashes, identity, every project JSON and asset byte are restored and runnable | IMPLEMENTATION CORRECTED; ACTUAL L3/L4 G7 EVIDENCE NOT VERIFIED |
| ZTR-010 | Independent second verification | ZTR-M6 | Separate Windows job repeats exact candidate path | Independent Windows/Chromium run | independent evidence | Same SHA and critical scenarios PASS independently | NEW CANDIDATE PENDING |
| ZTR-011 | Preserve complete evidence | ZTR-M6 | Always aggregate pass or fail evidence, including pinned G7 and shared physical record | Final archive and artifact checks | `release-evidence.zip`, verdict artifact | Logs, traces, outputs, hashes, G7, physical record and verdict are preserved | IMPLEMENTED; CURRENT-HEAD REVALIDATION REQUIRED |
| ZTR-012 | Attest released outputs when supported | ZTR-M6 | Optional attestation only after authorization using immutable action commit | Workflow contract | GitHub attestation | Subject digest matches authorized outputs | ACTION PINNED; NOT EXECUTED |
| ZTR-013 | Never publish on partial evidence | ZTR-M6 | Clear stale normal/Genesis outputs before evaluation and on failure; Genesis emits only Genesis-specific status/name/record; direct and request-only workflows use the same finalizer | Positive and adversarial tests | workflows, verdict, authorization record | Any missing gate, invalid request/history/G7/L5, identity mismatch or stale/ordinary Genesis output blocks authorization | CORRECTION PUSHED; CI AND INDEPENDENT REVIEW PENDING |

## Release gates

| Gate | Description | Minimum evidence | Current state |
|---|---|---|---|
| G0 | Static, identity, JavaScript and backend self-test | L0–L2 | NEW CANDIDATE PENDING |
| G1 | Every required test file in an isolated process | L1 | UPDATED SUITE CURRENT-HEAD CI PENDING |
| G2 | Deterministic exact candidate and package verification | L3 | NEW CANDIDATE PENDING |
| G3 | Exact EXE clean Windows installation and embedded self-tests | L4 | NEW CANDIDATE PENDING |
| G4 | Installed UI flow in Edge | Hosted L5 | NEW CANDIDATE PENDING |
| G5 | Output-file validation | Hosted L5 | NEW CANDIDATE PENDING |
| G6 normal | Update from externally pinned prior normal/Genesis authorized release | L4/L5 | AVAILABLE ONLY AFTER GENESIS; NEW EVIDENCE PENDING |
| G6 Genesis | One-time bypass of only the absent prior-authorized update baseline | L1 contract plus exact history | IMPLEMENTATION CORRECTED; NOT EXECUTED |
| G7 | Forced-failure rollback with complete project restoration; never N/A in Genesis | L3/L4/L5 | IMPLEMENTATION CORRECTED; ACTUAL EXACT-CANDIDATE EVIDENCE PENDING |
| G8 | Independent exact-SHA rerun using another browser | L4/L5 | NEW CANDIDATE PENDING |
| Physical L5 | One shared real user-machine browser path and validated outputs, SHA-pinned and Dmitry-witnessed | Physical L5 | NOT VERIFIED |

Genesis success may create only:

- status `GENESIS_RELEASE_AUTHORIZED`;
- an installer whose filename contains `GENESIS_RELEASE_AUTHORIZED`;
- `ImageLab-GENESIS-RELEASE-AUTHORIZATION.json`;
- the corresponding checksum and evidence archive.

An ordinary `RELEASE_AUTHORIZED` status, installer name or authorization JSON in Genesis mode is a blocking defect.

Release is authorized only when every applicable gate is PASS, all evidence exists, exact binary/source identities are consistent, the prior authorization chain or approved one-time Genesis path is valid, physical user-machine L5 is verified, and the final verdict is an allowed authorization status.

Current final state:

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
