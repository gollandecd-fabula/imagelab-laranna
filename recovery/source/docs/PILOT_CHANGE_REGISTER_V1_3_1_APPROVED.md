# ImageLab Pilot Change Register v1.3.1 — APPROVED

- Exact baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- Product code changes require a reproduced defect.
- Evidence gaps may add tests/evidence only.
- Tool limitations may not change product architecture or test structure.
- Final claims bind to one candidate SHA.

| ID | Object | Milestone / gate | Confirmed reason | Allowed boundary | Next test | Rollback | Required evidence level | Factual status |
|---|---|---|---|---|---|---|---|---|
| CR-001 | Governance record | PG0–PG1 | Approved spec/RTM were not recorded correctly and the first guard self-matched its own prohibited-token declaration | Governance artifacts and scope guard only; no product code | Static governance, negative claim fixture and commit-order check | Reset pilot ref to exact pre-change SHA | L2 | VERIFIED L2 — corrected by `cf1f0f3f1d1192976aac0fc01b104c0736ba48da`; governance remains successful through `30391223269` |
| CR-002 | LIVE-E2E-01 | PG2–PG3 | Existing main browser matrix mocks API/storage/processing | Add real-server E2E without changing product architecture | Full live Alpha route | Remove only the test harness | L2 | PARTIAL VERIFIED L2 — foundation route commit `1a797196c63066eb78b2c13466590fc34a1457cd`, run `30390448536`, artifact `8700686010`; regression run `30391223340` passed after CR-003; full M2B-PILOT/Playwright route remains open |
| CR-003 | Runtime training lock | PG2 | Real HTTP reproduction proved train/rollback returned 422 and served UI exposed both routes | Fail-close only at the audited user-runtime entry; remove served UI controls; preserve feedback and offline evaluation/training code | Real HTTP 404/404, served UI no-route check, promoted-model before/after snapshot, LIVE-E2E regression | Revert only `11b9b3be4a8c32bbceee394994077d03eb76f5f6` to `69461c67f45efc3eae021499443ad1b22e80f3f9` | L2 | VERIFIED L2 — fix `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; run `30391223409`; artifact `8700986776`; governance `30391223269`; LIVE-E2E regression `30391223340` |
| CR-004 | Visual reachability | PG4 | Manual artifact review indicates clipping/reachability risks, but exact five-width defect is not yet reproduced | Evidence-only Playwright five-width run first; CSS/DOM patch only after exact reproduction | 800/1024/1280/1440/1920 screenshots, control bounding boxes, scroll/focus assertions and manual review | Remove only the visual evidence harness until a defect-specific patch is authorized | L2 | ACTIVE — REPRODUCTION TEST NEXT; CSS/DOM PATCH NOT YET AUTHORIZED |
| CR-005 | M2B-PILOT route | PG3 | Authorized pilot functions are not proven as one live route | Open only explicit background/extract/cleanup/size/QA/PNG/PNG-DTF slice | Real frozen-fixture route | Disable pilot controls; keep existing engines | L2 | PLANNED |
| CR-006 | Pilot QA/output validators | PG3 | No unified deterministic pilot contract | Add integrity/lineage/decode/px/PPI/alpha/boundary checks | Positive and negative fixtures | Revert validator layer only | L2 | PLANNED |
| CR-007 | Frozen Pilot Set | PG1 | No immutable eight-fixture set and predeclared thresholds | Add 5 representative + 3 adversarial fixtures and manifest | Hash/property validation plus artifact re-read | Remove generator, validator and manifest; reset to `cf1f0f3f1d1192976aac0fc01b104c0736ba48da` | L2 | VERIFIED L2 — commit `c26c83b12fdec68bb2aa89c3ca05d8588f3768d9`, run `30389784679`, artifact `8700428913` |
| CR-008 | Candidate/evidence binding | PG5 | No pilot candidate exists | Add one-SHA manifest and mismatch guard | Mismatched-SHA negative test | Revert workflow/docs only | L2 | PLANNED |
| CR-009 | Pilot Beta packaging | PG7 | No exact Beta installer | Only after Alpha PASS build one exact installer | Clean Windows route | Remain on Alpha; do not publish | L4 | DEFERRED |

## Active change boundary

```text
ACTIVE_CHANGE=CR-004_VISUAL_REACHABILITY_REPRODUCTION
ACTIVE_SCOPE=PLAYWRIGHT_EVIDENCE_AND_SCREENSHOTS_ONLY
CSS_DOM_PRODUCT_PATCH_ALLOWED=false
ROLLBACK_SHA=11b9b3be4a8c32bbceee394994077d03eb76f5f6
NEXT_TEST=FIVE_WIDTH_REACHABILITY_800_1024_1280_1440_1920
REQUIRED_EVIDENCE_LEVEL=L2
RELEASE_BLOCKED=true
```
