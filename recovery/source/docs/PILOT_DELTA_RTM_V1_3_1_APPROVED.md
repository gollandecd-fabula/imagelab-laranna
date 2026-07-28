# ImageLab PILOT_DELTA_RTM v1.3.1 — APPROVED

Approved by the user on 2026-07-27:

> Утверждаю PILOT_DELTA_RTM v1.3.1 и разрешаю начать Pilot Alpha с повторной проверкой exact head.

- Repository: `gollandecd-fabula/imagelab-laranna`
- Parent branch: `redteam/imagelab-complete-audit-20260725-v2`
- Exact planning baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- Release: `BLOCKED`
- Rule: a green baseline CI is not Pilot Alpha evidence.
- Rule: an evidence gap does not authorize a product-code change.
- Rule: PASS requires implementation, relevant test and artifact on one exact candidate SHA.

| ID | Requirement | Milestone / gate | Allowed action | Mandatory test | Evidence / artifact | Required evidence level | PASS criterion | Factual status |
|---|---|---|---|---|---|---|---|---|
| PIL-001 | Pilot scope authorization | PG0–PG1 | Approved v1.3.1/RTM recorded before product patch; executable scope guard | Static governance/commit-order check | Spec, RTM, register, baseline, guard | L2 | All five artifacts in the first atomic commit; no conflicting scope | VERIFIED L2 — governance guard remains successful through run `30391223269` on head `11b9b3be4a8c32bbceee394994077d03eb76f5f6` |
| PIL-002 | Exact baseline | PG0 and before each batch | Recheck PR #11/head and parallel mutation immediately before implementation | PR/head/ancestry/diff inventory | Baseline manifest and GitHub metadata | L2 | One baseline and rollback SHA; no parallel mutation | VERIFIED L2 FOR CR-003 BATCH — exact head `69461c67f45efc3eae021499443ad1b22e80f3f9` rechecked before patch; ancestry and scope passed on `30391223269`; next batch requires a fresh head check |
| PIL-003 | Project lifecycle | PG2 | Do not change product code until live route reproduces a defect | Real FastAPI create→upload→process→restart→reopen | Trace, project JSON and hashes | L2 | Project/history/active version persist; source unchanged | VERIFIED L2 FOUNDATION — regression run `30391223340` passed on product head `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; full Alpha processing slice remains open |
| PIL-004 | Real upload | PG2 | Add real fixture/live upload evidence; fix only reproduced defect | UI/API upload of real raster | Stored hash, metadata, checks, preview | L2 | Asset metadata factual and file intact | VERIFIED L2 — real HTTP upload/preview/download; source SHA `1fed41525f428888d2f6e7194077f2a7eef2277ee4aabf549a96f40a8080cbc8` unchanged after processing and restart |
| PIL-005 | Mask | PG2 | Prove live persistence and asset isolation | Draw/add/subtract/clear/switch/restart | Mask data and browser trace | L2 | Mask bound to correct asset and restored | PARTIAL L2 — add/subtract stroke state bound to source asset survived restart; clear/switch and browser trace remain unverified |
| PIL-006 | Background/Extract | PG3 | Open only explicit M2B-PILOT path | Live masked operation on frozen fixtures | Source/result hashes, lineage, boundary metrics | L2 | New version; unchanged source; no forbidden outside-mask change | NOT STARTED |
| PIL-007 | Cleanup | PG3 | Use conservative deterministic operations only | Live cleanup, region/color checks | Before/after metrics and parameters | L2 | No hidden color/geometry change; valid lineage | NOT STARTED |
| PIL-008 | Size/PPI/Canvas | PG3–PG4 | Reproduce specific live/visual defect before minimal fix | Linked/unlinked, resample, margins, invalid input, binary check | Requested/actual table, screenshots, output | L2 | Binary file matches requested values; controls reachable | PARTIAL L2 — one linked 200×200 px / 200 PPI result verified; remaining matrix and visual reachability are open |
| PIL-009 | Pilot QA | PG3 | Implement only deterministic mandatory checks | Positive and negative QA fixtures | QA report linked to asset/candidate | L2 | All required checks PASS; failure blocks readiness | PARTIAL L2 — positive QA returned 20 checks; mandatory negative fixtures remain unverified |
| PIL-010 | PNG export | PG3 | Add live export/download and binary validation | UI/API export and decode | PNG, hash, dimensions, alpha, PPI, lineage | L2 | File exactly matches claimed parameters | VERIFIED L2 FOUNDATION — downloaded RGBA PNG 200×200, embedded 199.9996 PPI, SHA `3ddce19ab3bc49de1fb3b0b4de7568a0e12abb6ab40d2707f4ed0630133d1906`; broader export matrix remains open |
| PIL-011 | Basic PNG DTF | PG3 | Fix one basic pilot profile without production claim | Live export/decode/metadata | PNG DTF, manifest and QA | L2 | Valid basic profile; no production-ready claim | NOT STARTED |
| PIL-012 | LIVE-E2E-01 | PG2–PG3 | Use real FastAPI/ProjectStore/filesystem/processing/export; no route mocks | Full Alpha route | Server log, Playwright trace, downloads, persisted project | L2 | Full route passes without mocked production surfaces | PARTIAL L2 FOUNDATION — real uvicorn/FastAPI route and restart passed on `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; full M2B-PILOT route and Playwright trace remain open |
| PIL-013 | Visual reachability | PG4 | Fix only reproduced layout/scroll/focus defects | Reachability at 800/1024/1280/1440/1920 | Screenshots, assertions, manual review | L2 | No clipped or unreachable mandatory controls | OPEN / P0 — next active reproduction; no CSS/DOM patch authorized before evidence |
| PIL-014 | No runtime training | PG2 | Fail-close train/rollback in user runtime; keep offline evaluation code | Negative API/UI and no-write tests | 403/404 behavior, served UI, promoted-model snapshots and hosted artifact | L2 | No user runtime path changes model weights | VERIFIED L2 — defect reproduced on `69461c67f45efc3eae021499443ad1b22e80f3f9` with HTTP 422 and UI exposure; minimal entry-only fix `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; run `30391223409` returned 404/404, UI routes absent, model snapshots unchanged; artifact `8700986776` digest `sha256:99b172b3d4aef39c2eb2d06dbb47f4d3e3e2f7b9ed17e9a3773a9cfa1200c75f` re-read successfully |
| PIL-015 | Frozen Pilot Set v1 | PG1 | Create 5 representative + 3 adversarial immutable fixtures before benchmark | Fixture hash/property validation | Fixture generator, manifest, hosted artifact `8700428913` | L2 | Eight fixtures and thresholds frozen before processing | VERIFIED L2 — run `30389784679`; artifact digest `sha256:e1d36524fbf08abc23d3e867dd1b9514ffcb92e90b54a24cfa6b5424c5ae9779`; benchmark remains `NOT_STARTED` |
| PIL-016 | Single candidate | PG5 | Bind CI, traces, screenshots, outputs and reports to one SHA | Mismatched-SHA negative guard | Candidate manifest and workflow metadata | L2 | No mixed snapshots, orphan blobs or different installer SHA | NOT STARTED |
| PIL-017 | Exact Windows Beta | PG7 | Do not touch installer before Alpha PASS | Clean install, route, restart, uninstall, preservation | Installer SHA and Windows evidence | L4 | Same route passes on exact installed build | DEFERRED |
| PIL-018 | Physical pilot | PG8 | Run only after exact Beta clean-install PASS | User executes full route | L5 report, output hashes, defect register | L5 | Physical route complete; blockers classified | DEFERRED |

## Gate order

1. `PG0`: approved spec + approved RTM + exact baseline.
2. `PG1`: governance-first commit, scope guard and Frozen Pilot Set.
3. `PG2`: live project/upload/mask route.
4. `PG3`: processing/size/QA/export and binary validation.
5. `PG4`: five-width interaction matrix and manual screenshot review.
6. `PG5`: full exact-head CI and single-candidate evidence.
7. `PG6`: close PIL-001–PIL-016 or remain blocked.
8. `PG7–PG8`: exact Windows Beta and physical pilot, only after Alpha PASS.

## PG1 execution evidence

- Governance self-match defect reproduced on run `30287592705`; failed step: `Block prohibited completion claims`.
- Minimal guard-only correction: commit `cf1f0f3f1d1192976aac0fc01b104c0736ba48da`.
- Corrected governance run `30388836881`: all governance steps successful.
- Frozen Pilot Set commit: `c26c83b12fdec68bb2aa89c3ca05d8588f3768d9`.
- Frozen-set run `30389784679`: generation, validation, artifact upload, ancestry, scope, claim and manifest checks successful.
- Hosted artifact: `8700428913`, head SHA `c26c83b12fdec68bb2aa89c3ca05d8588f3768d9`, digest `sha256:e1d36524fbf08abc23d3e867dd1b9514ffcb92e90b54a24cfa6b5424c5ae9779`.
- Downloaded archive was re-read successfully; ZIP integrity and all eight file hashes matched the frozen manifest.

## PG2 foundation execution evidence

- Test-only commit: `1a797196c63066eb78b2c13466590fc34a1457cd`; product code unchanged.
- Real-server run `30390448536`: successful create, upload, preview/download, mask persistence, process, QA, PNG export/download, bundle, stop, restart and reopen.
- Hosted artifact: `8700686010`, digest `sha256:4fcd60642cb3cd96dbe9b647b000f53ca66c667defc65bc0472fdad5469cbfda`, exact head `1a797196c63066eb78b2c13466590fc34a1457cd`.
- Downloaded archive was re-read successfully; ZIP integrity, trace candidate SHA, project JSON, server log, PNG, bundle and runtime files were verified.
- Regression run `30391223340` passed the same foundation route after the CR-003 product patch.

## CR-003 runtime-training evidence

- Failing real-runtime probe commit: `69461c67f45efc3eae021499443ad1b22e80f3f9`.
- Reproduction run `30390762914`: train and rollback returned HTTP 422; served UI contained both routes; promoted-model snapshot did not change.
- Reproduction artifact: `8700807612`, digest `sha256:70450547a5443179ac7d53c674b98d729064eab56365278a67af90331cc2d9d8`.
- Minimal product patch: `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; only `recovery/source/app/entry.py` changed.
- Successful real-runtime run `30391223409`: train 404, rollback 404, UI route exposure false, before/after promoted-model snapshots equal.
- Successful artifact: `8700986776`, digest `sha256:99b172b3d4aef39c2eb2d06dbb47f4d3e3e2f7b9ed17e9a3773a9cfa1200c75f`, exact head `11b9b3be4a8c32bbceee394994077d03eb76f5f6`.
- Downloaded archive was re-read successfully; ZIP integrity and report fields matched the workflow metadata.
- Governance run `30391223269` and LIVE-E2E regression run `30391223340` both succeeded on the same head.

Current protocol status:

```text
PILOT_ALPHA_AUTHORIZED
PG1_VERIFIED_L2
PG2_IN_PROGRESS
CR_003_VERIFIED_L2
CR_004_VISUAL_REACHABILITY_REPRODUCTION_NEXT
PRODUCT_IMPLEMENTATION_STARTED
M2A_IN_PROGRESS
M2B_FULL_NOT_STARTED
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
```
