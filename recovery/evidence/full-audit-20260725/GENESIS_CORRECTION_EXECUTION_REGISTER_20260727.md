# ImageLab by LarannA — Genesis correction execution register

Date: 2026-07-27  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Branch: `redteam/imagelab-complete-audit-20260725-v2`  
Starting exact head: `65f6c0110f92102a78916170c8876464c950ad81`

## Active milestone and change boundary

- Active milestone: **M5 — Genesis and release-gate conformance**.
- Authorized change boundary: correct confirmed Genesis P1/P2 defects, history-evidence incompatibility, tests, active workflow copies and truthful RTM/runbook records.
- Prohibited in this change: assign a release identity, publish an installer, fabricate G7 or physical L5 evidence, merge to protected branches, mark the program or release complete.
- Next tests: focused Genesis tests; complete source suite; workflow-governance, dependency, bootstrap, source-snapshot and evidence-hardening CI; independent review of the exact remote head.
- Rollback condition: if the focused tests or mandatory CI fail because of the patch, revert the correction commit or apply the smallest follow-up patch without weakening any requirement.
- Maximum evidence available in this execution: L1/L2 implementation and CI. Exact packaged runtime G7 requires L3; physical user path requires L5.

## Requirements traceability and execution plan

| Requirement | Milestone | Action | Test | Required evidence | Artifact | PASS criterion | Pre-change status |
|---|---|---|---|---|---|---|---|
| GEN-G7 | M5 | Require independently pinned schema-3 update/rollback evidence for the exact candidate; permit bypass only of the prior-authorized-baseline part of G6 | Positive exact evidence; missing, malformed, failed, N/A, SHA mismatch, candidate mismatch, self-baseline and inventory mismatch negatives | L1 implementation; L3 actual candidate evidence | Genesis finalizer, G7 evidence ZIP, workflow inputs, tests | Genesis blocks unless exact non-authorizing diagnostic G7 rollback evidence is valid | FAILED |
| GEN-OUTPUT | M5 | Emit only `GENESIS_RELEASE_AUTHORIZED`, a Genesis-specific installer name and `ImageLab-GENESIS-RELEASE-AUTHORIZATION.json`; remove stale ordinary and Genesis outputs | Positive Genesis-only output test; negative test forbidding ordinary authorization artifacts | L1 then L3 | Genesis finalizer, workflow artifact paths, tests | No ordinary `RELEASE_AUTHORIZED` status/file exists in Genesis mode | FAILED |
| GEN-HISTORY | M5 | Align active workflows and finalizer with schema-2 `verify_no_prior_release.py`, including releases, workflow runs, artifacts and current run ID | Contract tests for schema, current run, prior successful run and prior authorized artifact | L1/L2 | Root/source workflows, finalizer, tests | Workflow can produce valid schema-2 history evidence and blocks on any prior Genesis/normal authorization | FAILED |
| AUD-013 | M5 | Remove overstated RTM claim; after implementation tests, record implementation corrected while actual L5 remains unverified | Static RTM contract and independent review | L0/L1 | Full audit RTM | Claim never exceeds evidence; physical L5 remains separate | FAILED |
| AUD-002 | M2 | Freeze source and assign new exact version, Build ID, source SHA and installer SHA | Two reproducible builds and exact manifest/runtime identity | L3 | Candidate manifest and installer | Exact identity propagated and reproducible | BLOCKED — outside active milestone |
| AUD-004 | M2/M4 | Execute install/update/failure/rollback lifecycle without mixed state | Windows lifecycle and fault injection | L3 | Installer/update/rollback evidence | Success leaves only new version; failure restores prior version | PARTIAL — outside active milestone |
| AUD-012 | M2 | Prove multi-project raster/SVG preservation through update and rollback | Schema-3 inventories before/update/rollback | L3 | Update/rollback evidence ZIP | All projects/assets/presets/history preserved exactly | UNVERIFIED — actual evidence not available |
| AUD-011 | M2 | Re-run all processing, lineage, output and export gates on frozen exact candidate | Installed output validators and package tests | L3 | Output files and manifests | Outputs match declared operation and lineage | UNVERIFIED FOR FINAL CANDIDATE |
| AUD-009 | M2/M4 | Verify cleanup on all failure/cancel/crash paths | Failure injection and filesystem inventory | L2/L3 | Cleanup evidence | No orphan, partial active or stale authorization files | PARTIAL |
| AUD-016 | M5 | Scan final installer, archives, logs and artifacts for secrets/user content | Privacy denylist and secret scan | L3 | Privacy report, SBOM | No prohibited content in package/evidence | UNVERIFIED — final package absent |
| AUD-018 | M2/M6 | Execute concurrency, large-file, cancellation and resource-exhaustion stress gates | Stress/concurrency suite | L2/L3 | Stress report | Bounded failure without corruption or false success | PARTIAL |
| AUD-020 | M6 | Obtain independent review after exact correction head and rerun all mandatory CI | Independent Codex/red-team review | L2/L3 | Review and CI run IDs | No unresolved P0/P1 | FAILED PRE-CHANGE |
| PHYSICAL-L5 | M7 | Run exact final installer on Dmitry's physical Windows machine through browser UI | Launch → upload → operation/history → export → restart → project validation | L5 | Physical manifest and evidence ZIP | Direct witnessed user path and validated outputs pass | NOT_STARTED / BLOCKED |
| GENESIS-AUTH | M7 | Execute Genesis only after implementation, exact G7 evidence, closed audit and physical L5 | Full Genesis G0–G8 finalization | L5 | Genesis authorization record and installer | One-time Genesis authorization succeeds without bypass | BLOCKED |
| MERGE/PUBLISH | M7 | Merge and publish only after every mandatory row is closed | Exact-head release checklist | L5 | Merge/release/checksums/SBOM | No FAILED, PARTIAL, BLOCKED or UNVERIFIED mandatory row | BLOCKED |

## Status rule

No requirement in this register may be marked PASS solely because a schema, validator, mock, synthetic fixture or CI infrastructure exists. Synthetic tests may close implementation contracts at L1/L2 only. G7 exact-candidate runtime remains L3 and the user-critical physical path remains L5.

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
