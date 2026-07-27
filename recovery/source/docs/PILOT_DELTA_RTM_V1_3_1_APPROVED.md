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

| ID | Requirement | Allowed action | Mandatory test | Evidence/artifact | PASS criterion | Status |
|---|---|---|---|---|---|---|
| PIL-001 | Pilot scope authorization | Approved v1.3.1/RTM recorded before product patch; executable scope guard | Static governance/commit-order check | Spec, RTM, register, baseline, guard | All five artifacts in the first atomic commit; no conflicting scope | APPROVED / REPOSITORY RECORD PENDING |
| PIL-002 | Exact baseline | Recheck PR #11/head and parallel mutation immediately before implementation | PR/head/ancestry/diff inventory | Baseline manifest and GitHub metadata | One baseline and rollback SHA; no parallel mutation | BASELINE VERIFIED FOR GOVERNANCE |
| PIL-003 | Project lifecycle | Do not change product code until live route reproduces a defect | Real FastAPI create→upload→process→restart→reopen | Trace, project JSON and hashes | Project/history/active version persist; source unchanged | PARTIAL / LIVE EVIDENCE GAP |
| PIL-004 | Real upload | Add real fixture/live upload evidence; fix only reproduced defect | UI/API upload of real raster | Stored hash, metadata, checks, preview | Asset metadata factual and file intact | EVIDENCE GAP |
| PIL-005 | Mask | Prove live persistence and asset isolation | Draw/add/subtract/clear/switch/restart | Mask data and browser trace | Mask bound to correct asset and restored | EVIDENCE GAP |
| PIL-006 | Background/Extract | Open only explicit M2B-PILOT path | Live masked operation on frozen fixtures | Source/result hashes, lineage, boundary metrics | New version; unchanged source; no forbidden outside-mask change | NOT STARTED |
| PIL-007 | Cleanup | Use conservative deterministic operations only | Live cleanup, region/color checks | Before/after metrics and parameters | No hidden color/geometry change; valid lineage | NOT STARTED |
| PIL-008 | Size/PPI/Canvas | Reproduce specific live/visual defect before minimal fix | Linked/unlinked, resample, margins, invalid input, binary check | Requested/actual table, screenshots, output | Binary file matches requested values; controls reachable | BLOCKED BY LIVE/VISUAL EVIDENCE |
| PIL-009 | Pilot QA | Implement only deterministic mandatory checks | Positive and negative QA fixtures | QA report linked to asset/candidate | All required checks PASS; failure blocks readiness | NOT STARTED |
| PIL-010 | PNG export | Add live export/download and binary validation | UI/API export and decode | PNG, hash, dimensions, alpha, PPI, lineage | File exactly matches claimed parameters | EVIDENCE GAP |
| PIL-011 | Basic PNG DTF | Fix one basic pilot profile without production claim | Live export/decode/metadata | PNG DTF, manifest and QA | Valid basic profile; no production-ready claim | NOT STARTED |
| PIL-012 | LIVE-E2E-01 | Use real FastAPI/ProjectStore/filesystem/processing/export; no route mocks | Full Alpha route | Server log, Playwright trace, downloads, persisted project | Full route passes without mocked production surfaces | NOT STARTED / P0 |
| PIL-013 | Visual reachability | Fix only reproduced layout/scroll/focus defects | Reachability at 800/1024/1280/1440/1920 | Screenshots, assertions, manual review | No clipped or unreachable mandatory controls | OPEN / P0 |
| PIL-014 | No runtime training | Fail-close train/rollback in user runtime; keep offline evaluation code | Negative API/UI and no-write tests | 403/404/disabled behavior and no promoted-model writes | No user runtime path changes model weights | OPEN / P0 |
| PIL-015 | Frozen Pilot Set v1 | Create 5 representative + 3 adversarial immutable fixtures before benchmark | Fixture hash/property validation | Fixture files and manifest | Eight fixtures and thresholds frozen before processing | NOT STARTED / P0 |
| PIL-016 | Single candidate | Bind CI, traces, screenshots, outputs and reports to one SHA | Mismatched-SHA negative guard | Candidate manifest and workflow metadata | No mixed snapshots, orphan blobs or different installer SHA | NOT STARTED |
| PIL-017 | Exact Windows Beta | Do not touch installer before Alpha PASS | Clean install, route, restart, uninstall, preservation | Installer SHA and Windows evidence | Same route passes on exact installed build | DEFERRED |
| PIL-018 | Physical pilot | Run only after exact Beta clean-install PASS | User executes full route | L5 report, output hashes, defect register | Physical route complete; blockers classified | DEFERRED |

## Gate order

1. `PG0`: approved spec + approved RTM + exact baseline.
2. `PG1`: governance-first commit, scope guard and Frozen Pilot Set.
3. `PG2`: live project/upload/mask route.
4. `PG3`: processing/size/QA/export and binary validation.
5. `PG4`: five-width interaction matrix and manual screenshot review.
6. `PG5`: full exact-head CI and single-candidate evidence.
7. `PG6`: close PIL-001–PIL-016 or remain blocked.
8. `PG7–PG8`: exact Windows Beta and physical pilot, only after Alpha PASS.

Current protocol status:

```text
PILOT_ALPHA_AUTHORIZED
GOVERNANCE_FIRST_COMMIT_PENDING
PRODUCT_IMPLEMENTATION_NOT_STARTED
M2A_IN_PROGRESS
M2B_FULL_NOT_STARTED
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
```
