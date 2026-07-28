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
| PIL-001 | Pilot scope authorization | PG0–PG1 | Approved v1.3.1/RTM recorded before product patch; executable scope guard | Static governance/commit-order check | Spec, RTM, register, baseline, guard | L2 | All five artifacts in the first atomic commit; no conflicting scope | VERIFIED L2 — governance guard remains successful through run `30392510531` on head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea` |
| PIL-002 | Exact baseline | PG0 and before each batch | Recheck PR #11/head and parallel mutation immediately before implementation | PR/head/ancestry/diff inventory | Baseline manifest and GitHub metadata | L2 | One baseline and rollback SHA; no parallel mutation | VERIFIED L2 FOR CR-004 BATCH — exact head was rechecked before every test-only mutation; ancestry and scope passed on run `30392510531`; CR-005 requires a fresh exact-head check before its first mutation |
| PIL-003 | Project lifecycle | PG2 | Do not change product code until live route reproduces a defect | Real FastAPI create→upload→process→restart→reopen | Trace, project JSON and hashes | L2 | Project/history/active version persist; source unchanged | VERIFIED L2 FOUNDATION — real-server regression run `30392510526` passed on exact head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`; full Alpha processing slice remains open |
| PIL-004 | Real upload | PG2 | Add real fixture/live upload evidence; fix only reproduced defect | UI/API upload of real raster | Stored hash, metadata, checks, preview | L2 | Asset metadata factual and file intact | VERIFIED L2 — real HTTP upload/preview/download; source SHA `1fed41525f428888d2f6e7194077f2a7eef2277ee4aabf549a96f40a8080cbc8` unchanged after processing and restart |
| PIL-005 | Mask | PG2 | Prove live persistence and asset isolation | Draw/add/subtract/clear/switch/restart | Mask data and browser trace | L2 | Mask bound to correct asset and restored | PARTIAL L2 — add/subtract stroke state bound to source asset survived restart; clear/switch and browser mask-operation path remain unverified |
| PIL-006 | Background/Extract | PG3 | Open only explicit M2B-PILOT path | Live masked operation on frozen fixtures | Source/result hashes, lineage, boundary metrics | L2 | New version; unchanged source; no forbidden outside-mask change | NOT STARTED — CR-005 active evidence-first |
| PIL-007 | Cleanup | PG3 | Use conservative deterministic operations only | Live cleanup, region/color checks | Before/after metrics and parameters | L2 | No hidden color/geometry change; valid lineage | NOT STARTED — CR-005 active evidence-first |
| PIL-008 | Size/PPI/Canvas | PG3–PG4 | Reproduce specific live/visual defect before minimal fix | Linked/unlinked, resample, margins, invalid input, binary check | Requested/actual table, screenshots, output | L2 | Binary file matches requested values; controls reachable | PARTIAL L2 — one linked 200×200 px / 200 PPI result and five-width control reachability are verified; linked/unlinked/resample/canvas/invalid-input binary matrix remains open |
| PIL-009 | Pilot QA | PG3 | Implement only deterministic mandatory checks | Positive and negative QA fixtures | QA report linked to asset/candidate | L2 | All required checks PASS; failure blocks readiness | PARTIAL L2 — positive QA returned 20 checks; mandatory negative fixtures and mask-boundary blocking remain unverified |
| PIL-010 | PNG export | PG3 | Add live export/download and binary validation | UI/API export and decode | PNG, hash, dimensions, alpha, PPI, lineage | L2 | File exactly matches claimed parameters | VERIFIED L2 FOUNDATION — downloaded RGBA PNG 200×200, embedded 199.9996 PPI, SHA `3ddce19ab3bc49de1fb3b0b4de7568a0e12abb6ab40d2707f4ed0630133d1906`; explicit M2B-PILOT export manifest and broader matrix remain open |
| PIL-011 | Basic PNG DTF | PG3 | Fix one basic pilot profile without production claim | Live export/decode/metadata | PNG DTF, manifest and QA | L2 | Valid basic profile; no production-ready claim | NOT STARTED — CR-005 active evidence-first |
| PIL-012 | LIVE-E2E-01 | PG2–PG3 | Use real FastAPI/ProjectStore/filesystem/processing/export; no route mocks | Full Alpha route | Server log, Playwright trace, downloads, persisted project | L2 | Full route passes without mocked production surfaces | PARTIAL L2 FOUNDATION — real uvicorn/FastAPI route and restart passed on `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`; full M2B-PILOT processing route remains open |
| PIL-013 | Visual reachability | PG4 | Fix only reproduced layout/scroll/focus defects | Reachability at 800/1024/1280/1440/1920 | Screenshots, assertions, manual review | L2 | No clipped or unreachable mandatory controls | VERIFIED L2 — final test-only head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`, run `30392510709`, artifact `8701517142`, digest `sha256:739ddd6afd41d368fc49e3a7a7c9a05d07b758146d2b916b953f2a7bbc1fe4e8`; five screenshots re-read and manually reviewed; all 20 modules checked at every width; failure count and horizontal overflow are zero; no CSS/DOM patch required |
| PIL-014 | No runtime training | PG2 | Fail-close train/rollback in user runtime; keep offline evaluation code | Negative API/UI and no-write tests | 403/404 behavior, served UI, promoted-model snapshots and hosted artifact | L2 | No user runtime path changes model weights | VERIFIED L2 — defect reproduced on `69461c67f45efc3eae021499443ad1b22e80f3f9`; minimal entry-only fix `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; regression run `30392510506` passed on exact head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea` |
| PIL-015 | Frozen Pilot Set v1 | PG1 | Create 5 representative + 3 adversarial immutable fixtures before benchmark | Fixture hash/property validation | Fixture generator, manifest, hosted artifact `8700428913` | L2 | Eight fixtures and thresholds frozen before processing | VERIFIED L2 — run `30389784679`; artifact digest `sha256:e1d36524fbf08abc23d3e867dd1b9514ffcb92e90b54a24cfa6b5424c5ae9779`; processing benchmark remains `NOT_STARTED` |
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
- Regression run `30392510526` passed the same foundation route on exact head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`.

## CR-003 runtime-training evidence

- Failing real-runtime probe commit: `69461c67f45efc3eae021499443ad1b22e80f3f9`.
- Reproduction run `30390762914`: train and rollback returned HTTP 422; served UI contained both routes; promoted-model snapshot did not change.
- Reproduction artifact: `8700807612`, digest `sha256:70450547a5443179ac7d53c674b98d729064eab56365278a67af90331cc2d9d8`.
- Minimal product patch: `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; only `recovery/source/app/entry.py` changed.
- Successful real-runtime run `30391223409`: train 404, rollback 404, UI route exposure false, before/after promoted-model snapshots equal.
- Successful artifact: `8700986776`, digest `sha256:99b172b3d4aef39c2eb2d06dbb47f4d3e3e2f7b9ed17e9a3773a9cfa1200c75f`, exact head `11b9b3be4a8c32bbceee394994077d03eb76f5f6`.
- Regression run `30392510506` succeeded on exact head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`.

## CR-004 visual-reachability evidence

- Evidence-only harness commit: `92f645b0be20e48cd8d387dec9bd29558f3c0144`; no product CSS/DOM changes.
- Run `30391651677` exposed a harness setup defect: duplicate creation of the runtime-provided `TS-001`; no visual claim was made.
- Test-only correction `203aa0734dd7565584bdcafda419ba74b6f0abbf`; run `30391900948` exposed incompatible positional `wait_for_function` usage; no visual claim was made.
- Test-only correction `414e1fbfd6302e5de1d493aaf81e48a03ae15f25`; run `30392106416` completed all visual checks and created five screenshots. The only reported failure was the browser's `/favicon.ico` request; server evidence confirmed no application-resource failure.
- Final test-only classification commit: `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`; visual/control/overflow criteria were unchanged and favicon remained recorded as an ignored non-contract browser probe.
- Final run `30392510709`: successful real uvicorn/FastAPI/Chromium route with no route mocks.
- Hosted artifact: `8701517142`, digest `sha256:739ddd6afd41d368fc49e3a7a7c9a05d07b758146d2b916b953f2a7bbc1fe4e8`, exact head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`.
- Downloaded archive was re-read successfully: ZIP integrity valid; report status `VERIFIED_L2_NO_REACHABILITY_DEFECTS`; `failure_count=0`; screenshots for 800/1024/1280/1440/1920 present; each width covered 20 modules with zero horizontal overflow and no clipped, obscured or unfocusable mandatory control.
- All five screenshots were manually reviewed. 800 px uses a scrollable stacked route; 1024 px retains drawer/mandatory controls; 1280 px has no clipped fields; 1440 px has no three-column overlap; 1920 px retains focus and usable allocation without lost controls.
- Governance `30392510531`, runtime-training `30392510506` and LIVE-E2E `30392510526` also succeeded on the same head.

Current protocol status:

```text
PILOT_ALPHA_AUTHORIZED
PG1_VERIFIED_L2
PG2_PARTIAL_L2
PG4_VISUAL_REACHABILITY_VERIFIED_L2
CR_003_VERIFIED_L2
CR_004_VERIFIED_L2_NO_PRODUCT_PATCH_REQUIRED
CR_005_M2B_PILOT_EVIDENCE_NEXT
PRODUCT_IMPLEMENTATION_STARTED
M2A_IN_PROGRESS
M2B_FULL_NOT_STARTED
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
```
