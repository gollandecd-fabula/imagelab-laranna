# ImageLab Pilot Change Register v1.3.1 — APPROVED

- Exact baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- Product code changes require a reproduced defect.
- Evidence gaps may add tests/evidence only.
- Tool limitations may not change product architecture or test structure.
- Final claims bind to one candidate SHA.

| ID | Object | Milestone / gate | Confirmed reason | Allowed boundary | Next test | Rollback | Required evidence level | Factual status |
|---|---|---|---|---|---|---|---|---|
| CR-001 | Governance record | PG0–PG1 | Approved spec/RTM were not recorded correctly and the first guard self-matched its own prohibited-token declaration | Governance artifacts and scope guard only; no product code | Static governance, negative claim fixture and commit-order check | Reset pilot ref to exact pre-change SHA | L2 | VERIFIED L2 — corrected by `cf1f0f3f1d1192976aac0fc01b104c0736ba48da`; governance remains successful through `30392510531` |
| CR-002 | LIVE-E2E-01 | PG2–PG3 | Existing main browser matrix mocks API/storage/processing | Add real-server E2E without changing product architecture | Full live Alpha route | Remove only the test harness | L2 | PARTIAL VERIFIED L2 — foundation route commit `1a797196c63066eb78b2c13466590fc34a1457cd`, artifact `8700686010`; regression run `30392510526` passed on `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`; full M2B-PILOT route remains open |
| CR-003 | Runtime training lock | PG2 | Real HTTP reproduction proved train/rollback returned 422 and served UI exposed both routes | Fail-close only at the audited user-runtime entry; remove served UI controls; preserve feedback and offline evaluation/training code | Real HTTP 404/404, served UI no-route check, promoted-model before/after snapshot, LIVE-E2E regression | Revert only `11b9b3be4a8c32bbceee394994077d03eb76f5f6` to `69461c67f45efc3eae021499443ad1b22e80f3f9` | L2 | VERIFIED L2 — fix `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; artifact `8700986776`; regression run `30392510506` passed on `ec02228354583b422b8e44b11a1fa49dbe4ec5ea` |
| CR-004 | Visual reachability | PG4 | Exact five-width evidence was absent; two early runs exposed only harness defects, not product defects | Evidence-only real Playwright run; CSS/DOM patch allowed only after a reproduced product defect | 800/1024/1280/1440/1920 screenshots, all-module control bounds, scroll/focus/occlusion/overflow assertions and manual review | Remove only visual evidence harness commits; product rollback not applicable because product UI was not changed | L2 | VERIFIED L2 — final head `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`, run `30392510709`, artifact `8701517142`, digest `sha256:739ddd6afd41d368fc49e3a7a7c9a05d07b758146d2b916b953f2a7bbc1fe4e8`; five screenshots manually reviewed; 20 modules per width; zero failures/overflow; NO PRODUCT PATCH REQUIRED |
| CR-005 | M2B-PILOT route | PG3 | Authorized background/extract/cleanup/size/QA/PNG/PNG-DTF functions are not proven as one live route | First add a real-server evidence harness using existing APIs/engines and Frozen Pilot Set; product patch only after a specific reproduced defect; do not open prohibited M2B functions | Real source-runtime route with source-hash immutability, lineage, masked outside-region comparison, requested/actual size/PPI/canvas, QA blocking, PNG/PNG-DTF decode and manifests, restart/reopen | Remove CR-005 evidence harness and reset to exact pre-change SHA `ec02228354583b422b8e44b11a1fa49dbe4ec5ea`; any later defect-specific product patch has its own rollback | L2 | ACTIVE — EVIDENCE HARNESS NEXT; PRODUCT PATCH NOT YET AUTHORIZED |
| CR-006 | Pilot QA/output validators | PG3 | No unified deterministic pilot contract | Add integrity/lineage/decode/px/PPI/alpha/boundary checks | Positive and negative fixtures | Revert validator layer only | L2 | PLANNED — may be reproduced by CR-005 but remains a separate mandatory row |
| CR-007 | Frozen Pilot Set | PG1 | No immutable eight-fixture set and predeclared thresholds | Add 5 representative + 3 adversarial fixtures and manifest | Hash/property validation plus artifact re-read | Remove generator, validator and manifest; reset to `cf1f0f3f1d1192976aac0fc01b104c0736ba48da` | L2 | VERIFIED L2 — commit `c26c83b12fdec68bb2aa89c3ca05d8588f3768d9`, run `30389784679`, artifact `8700428913` |
| CR-008 | Candidate/evidence binding | PG5 | No pilot candidate exists | Add one-SHA manifest and mismatch guard | Mismatched-SHA negative test | Revert workflow/docs only | L2 | PLANNED |
| CR-009 | Pilot Beta packaging | PG7 | No exact Beta installer | Only after Alpha PASS build one exact installer | Clean Windows route | Remain on Alpha; do not publish | L4 | DEFERRED |

## Active change boundary

```text
ACTIVE_GATE=PG3
ACTIVE_CHANGE=CR-005_M2B_PILOT_ROUTE_EVIDENCE
ACTIVE_SCOPE=REAL_SERVER_TEST_HARNESS_AND_ARTIFACTS_ONLY
PRODUCT_PATCH_ALLOWED=false
PROHIBITED=M2B_FULL_COLOR_PALETTE_PRODUCTION_HALFTONE_SMART_VECTOR_DTF_MASTER_MASTERS_LOGO_CARDLAB
ROLLBACK_SHA=ec02228354583b422b8e44b11a1fa49dbe4ec5ea
NEXT_TEST=REAL_M2B_PILOT_BACKGROUND_OR_EXTRACT_CLEANUP_SIZE_QA_PNG_PNG_DTF_RESTART_REOPEN
REQUIRED_EVIDENCE_LEVEL=L2
RELEASE_BLOCKED=true
```
