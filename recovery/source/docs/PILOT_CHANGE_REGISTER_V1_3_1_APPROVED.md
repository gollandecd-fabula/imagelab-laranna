# ImageLab Pilot Change Register v1.3.1 — APPROVED

- Exact baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- Product code changes require a reproduced defect.
- Evidence gaps may add tests/evidence only.
- Tool limitations may not change product architecture or test structure.
- Final claims bind to one candidate SHA.

| ID | Object | Confirmed reason | Allowed boundary | Next test | Rollback | Status |
|---|---|---|---|---|---|---|
| CR-001 | Governance record | Approved spec/RTM are not yet recorded correctly in the repository | One atomic first commit containing spec, RTM, register, baseline and scope guard | Static governance and commit-order check | Reset pilot ref to baseline | IN PROGRESS |
| CR-002 | LIVE-E2E-01 | Existing main browser matrix mocks API/storage/processing | Add real-server E2E without changing product architecture | Full live Alpha route | Remove only the test harness | PLANNED |
| CR-003 | Runtime training lock | User runtime exposes train/rollback paths | Fail-close endpoints/UI; preserve offline evaluation code | Negative API/UI and no-write test | Re-enable only under separately approved offline scope | PLANNED |
| CR-004 | Visual reachability | Manual artifact review indicates clipping/reachability risks | Minimal CSS/DOM fix after exact reproduction | Five-width interaction matrix | Revert the CSS/DOM patch | PLANNED |
| CR-005 | M2B-PILOT route | Authorized pilot functions are not proven as one live route | Open only explicit background/extract/cleanup/size/QA/PNG/PNG-DTF slice | Real frozen-fixture route | Disable pilot controls; keep existing engines | PLANNED |
| CR-006 | Pilot QA/output validators | No unified deterministic pilot contract | Add integrity/lineage/decode/px/PPI/alpha/boundary checks | Positive and negative fixtures | Revert validator layer only | PLANNED |
| CR-007 | Frozen Pilot Set | No immutable eight-fixture set and predeclared thresholds | Add 5 representative + 3 adversarial fixtures and manifest | Hash/property validation | Remove fixtures/manifest | PLANNED |
| CR-008 | Candidate/evidence binding | No pilot candidate exists | Add one-SHA manifest and mismatch guard | Mismatched-SHA negative test | Revert workflow/docs only | PLANNED |
| CR-009 | Pilot Beta packaging | No exact Beta installer | Only after Alpha PASS build one exact installer | Clean Windows route | Remain on Alpha; do not publish | DEFERRED |
