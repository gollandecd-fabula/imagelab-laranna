# ImageLab Pilot Change Register v1.3.1 — APPROVED

- Exact baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- Product code changes require a reproduced defect.
- Evidence gaps may add tests/evidence only.
- Tool limitations may not change product architecture or test structure.
- Final claims bind to one candidate SHA.

| ID | Object | Milestone / gate | Confirmed reason | Allowed boundary | Next test | Rollback | Required evidence level | Factual status |
|---|---|---|---|---|---|---|---|---|
| CR-001 | Governance record | PG0–PG1 | Approved spec/RTM were not recorded correctly and the first guard self-matched its own prohibited-token declaration | Governance artifacts and scope guard only; no product code | Static governance, negative claim fixture and commit-order check | Reset pilot ref to exact pre-change SHA | L2 | VERIFIED L2 — corrected by `cf1f0f3f1d1192976aac0fc01b104c0736ba48da`; successful runs `30388836881` and `30389784679` |
| CR-002 | LIVE-E2E-01 | PG2–PG3 | Existing main browser matrix mocks API/storage/processing | Add real-server E2E without changing product architecture | Full live Alpha route | Remove only the test harness | L2 | PLANNED / NEXT ACTIVE CHANGE |
| CR-003 | Runtime training lock | PG2 | User runtime exposes train/rollback paths | Fail-close endpoints/UI; preserve offline evaluation code | Negative API/UI and no-write test | Re-enable only under separately approved offline scope | L2 | PLANNED |
| CR-004 | Visual reachability | PG4 | Manual artifact review indicates clipping/reachability risks | Minimal CSS/DOM fix after exact reproduction | Five-width interaction matrix | Revert the CSS/DOM patch | L2 | PLANNED |
| CR-005 | M2B-PILOT route | PG3 | Authorized pilot functions are not proven as one live route | Open only explicit background/extract/cleanup/size/QA/PNG/PNG-DTF slice | Real frozen-fixture route | Disable pilot controls; keep existing engines | L2 | PLANNED |
| CR-006 | Pilot QA/output validators | PG3 | No unified deterministic pilot contract | Add integrity/lineage/decode/px/PPI/alpha/boundary checks | Positive and negative fixtures | Revert validator layer only | L2 | PLANNED |
| CR-007 | Frozen Pilot Set | PG1 | No immutable eight-fixture set and predeclared thresholds | Add 5 representative + 3 adversarial fixtures and manifest | Hash/property validation plus artifact re-read | Remove generator, validator and manifest; reset to `cf1f0f3f1d1192976aac0fc01b104c0736ba48da` | L2 | VERIFIED L2 — commit `c26c83b12fdec68bb2aa89c3ca05d8588f3768d9`, run `30389784679`, artifact `8700428913` |
| CR-008 | Candidate/evidence binding | PG5 | No pilot candidate exists | Add one-SHA manifest and mismatch guard | Mismatched-SHA negative test | Revert workflow/docs only | L2 | PLANNED |
| CR-009 | Pilot Beta packaging | PG7 | No exact Beta installer | Only after Alpha PASS build one exact installer | Clean Windows route | Remain on Alpha; do not publish | L4 | DEFERRED |

## Active change boundary

```text
ACTIVE_GATE=PG2
ACTIVE_CHANGE=CR-002_LIVE_E2E_01
PRODUCT_PATCH_ALLOWED_ONLY_AFTER_REPRODUCED_DEFECT=true
ROLLBACK_SHA=c26c83b12fdec68bb2aa89c3ca05d8588f3768d9
NEXT_TEST=REAL_FASTAPI_PROJECT_UPLOAD_MASK_RESTART_REOPEN
RELEASE_BLOCKED=true
```
