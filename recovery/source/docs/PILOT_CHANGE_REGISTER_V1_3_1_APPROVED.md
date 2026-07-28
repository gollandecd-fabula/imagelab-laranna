# ImageLab Pilot Change Register v1.3.1 — APPROVED

- Exact baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- Product code changes require a reproduced defect.
- Evidence gaps may add tests/evidence only.
- Tool limitations may not change product architecture or test structure.
- Final claims bind to one candidate SHA.

| ID | Object | Milestone / gate | Confirmed reason | Allowed boundary | Next test | Rollback | Required evidence level | Factual status |
|---|---|---|---|---|---|---|---|---|
| CR-001 | Governance record | PG0–PG1 | Approved spec/RTM were not recorded correctly and the first guard self-matched its own prohibited-token declaration | Governance artifacts and scope guard only; no product code | Static governance, negative claim fixture and commit-order check | Reset pilot ref to exact pre-change SHA | L2 | VERIFIED L2 — corrected by `cf1f0f3f1d1192976aac0fc01b104c0736ba48da`; successful runs `30388836881` and `30389784679` |
| CR-002 | LIVE-E2E-01 | PG2–PG3 | Existing main browser matrix mocks API/storage/processing | Add real-server E2E without changing product architecture | Full live Alpha route | Remove only the test harness | L2 | PARTIAL VERIFIED L2 — foundation route commit `1a797196c63066eb78b2c13466590fc34a1457cd`, run `30390448536`, artifact `8700686010`; full M2B-PILOT/Playwright route remains open |
| CR-003 | Runtime training lock | PG2 | User runtime exposes train/rollback paths | First reproduce by real HTTP; then fail-close endpoints/UI only, preserving offline evaluation code | Negative API/UI and no-write test | Revert CR-003-only patch to exact pre-change SHA | L2 | ACTIVE — REPRODUCTION TEST NEXT; PRODUCT PATCH NOT YET AUTHORIZED |
| CR-004 | Visual reachability | PG4 | Manual artifact review indicates clipping/reachability risks | Minimal CSS/DOM fix after exact reproduction | Five-width interaction matrix | Revert the CSS/DOM patch | L2 | PLANNED |
| CR-005 | M2B-PILOT route | PG3 | Authorized pilot functions are not proven as one live route | Open only explicit background/extract/cleanup/size/QA/PNG/PNG-DTF slice | Real frozen-fixture route | Disable pilot controls; keep existing engines | L2 | PLANNED |
| CR-006 | Pilot QA/output validators | PG3 | No unified deterministic pilot contract | Add integrity/lineage/decode/px/PPI/alpha/boundary checks | Positive and negative fixtures | Revert validator layer only | L2 | PLANNED |
| CR-007 | Frozen Pilot Set | PG1 | No immutable eight-fixture set and predeclared thresholds | Add 5 representative + 3 adversarial fixtures and manifest | Hash/property validation plus artifact re-read | Remove generator, validator and manifest; reset to `cf1f0f3f1d1192976aac0fc01b104c0736ba48da` | L2 | VERIFIED L2 — commit `c26c83b12fdec68bb2aa89c3ca05d8588f3768d9`, run `30389784679`, artifact `8700428913` |
| CR-008 | Candidate/evidence binding | PG5 | No pilot candidate exists | Add one-SHA manifest and mismatch guard | Mismatched-SHA negative test | Revert workflow/docs only | L2 | PLANNED |
| CR-009 | Pilot Beta packaging | PG7 | No exact Beta installer | Only after Alpha PASS build one exact installer | Clean Windows route | Remain on Alpha; do not publish | L4 | DEFERRED |

## Active change boundary

```text
ACTIVE_GATE=PG2
ACTIVE_CHANGE=CR-003_RUNTIME_TRAINING_LOCK_REPRODUCTION
ALLOWED_CHANGE=REAL_HTTP_NEGATIVE_TEST_AND_EVIDENCE_ONLY
PRODUCT_PATCH_ALLOWED=false
ROLLBACK_SHA=1a797196c63066eb78b2c13466590fc34a1457cd
NEXT_TEST=TRAIN_ROLLBACK_MUST_RETURN_403_OR_404_AND_CREATE_NO_MODEL_FILES
RELEASE_BLOCKED=true
```
