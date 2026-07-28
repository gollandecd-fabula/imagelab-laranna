# ImageLab Pilot Change Register v1.3.1 — APPROVED

- Exact baseline: `410841404d3afc2788b8a01d2166699beb1cfc27`
- Product code changes require a reproduced defect.
- Evidence gaps may add tests/evidence only.
- Tool limitations may not change product architecture or test structure.
- Final claims bind to one candidate SHA.

| ID | Object | Milestone / gate | Confirmed reason | Allowed boundary | Next test | Rollback | Required evidence level | Factual status |
|---|---|---|---|---|---|---|---|---|
| CR-001 | Governance record | PG0–PG1 | Approved spec/RTM were not recorded correctly and the first guard self-matched its own prohibited-token declaration | Governance artifacts and scope guard only; no product code | Static governance, negative claim fixture and commit-order check | Reset pilot ref to exact pre-change SHA | L2 | VERIFIED L2 — corrected by `cf1f0f3f1d1192976aac0fc01b104c0736ba48da`; governance successful on `0667e43a6b9322d0a40efea3fc2bd48210b40517`, run `30393464356` |
| CR-002 | LIVE-E2E-01 | PG2–PG3 | Existing main browser matrix mocks API/storage/processing | Add real-server E2E without changing product architecture | Full live Alpha route | Remove only the test harness | L2 | PARTIAL VERIFIED L2 — foundation artifact `8700686010`; regression run `30393464372` passed on `0667e43a6b9322d0a40efea3fc2bd48210b40517`; CR-005 route remains incomplete |
| CR-003 | Runtime training lock | PG2 | Real HTTP reproduction proved train/rollback returned 422 and served UI exposed both routes | Fail-close only at the audited user-runtime entry; remove served UI controls; preserve feedback and offline evaluation/training code | Real HTTP 404/404, served UI no-route check, promoted-model before/after snapshot, LIVE-E2E regression | Revert only `11b9b3be4a8c32bbceee394994077d03eb76f5f6` to `69461c67f45efc3eae021499443ad1b22e80f3f9` | L2 | VERIFIED L2 — fix `11b9b3be4a8c32bbceee394994077d03eb76f5f6`; artifact `8700986776`; regression run `30393464680` passed on `0667e43a6b9322d0a40efea3fc2bd48210b40517` |
| CR-004 | Visual reachability | PG4 | Exact five-width evidence was absent; early failures were harness defects, not product defects | Evidence-only real Playwright run; CSS/DOM patch allowed only after a reproduced product defect | 800/1024/1280/1440/1920 screenshots, all-module control bounds, scroll/focus/occlusion/overflow assertions and manual review | Remove only visual evidence harness commits; product rollback not applicable because product UI was not changed | L2 | VERIFIED L2 — artifact `8701517142`; regression run `30393464351` passed on `0667e43a6b9322d0a40efea3fc2bd48210b40517`; NO PRODUCT PATCH REQUIRED |
| CR-005 | M2B-PILOT route | PG3 | The authorized route lacked real end-to-end evidence | Keep the real-server harness and frozen output manifest; do not open prohibited M2B functions | Real source-runtime route with hashes, lineage, mask boundary, size/PPI/canvas, QA, PNG/PNG-DTF, restart/reopen | Remove CR-005 harness and reset to `a6543fce0579f5ab0c05ca269536d6c555af51ac` | L2 | PARTIAL L2 — commit `0667e43a6b9322d0a40efea3fc2bd48210b40517`, run `30393464347`, artifact `8701852326`, digest `sha256:7dda8b4f7c79c182f0787e17819a898b5a0fd829b50310b1d143bdb383eeabb8`; 47/49 checks passed; two product defects reproduced |
| CR-005A | Size/PPI/Canvas runtime contract | PG3 / PIL-008 / PIL-SZ-001 | Served `applyGeometry` transmits size, PPI, crop and rotation but no canvas or margin parameters; exact check `geometry_canvas_margin_runtime_contract` failed | Minimal existing UI/request/model/geometry-processing patch for explicit canvas width/height and four margins only; no layout redesign, no unrelated geometry refactor | Real route requests canvas and margins; decoded PNG dimensions/placement/PPI equal request; source unchanged; invalid canvas/margins blocked; existing linked/unlinked tests and all regressions | Restore the four CR-005A product files exactly from `4ee202cbc38afa7b9736eb097f6a4d582ebfad0b` while keeping temporary patch/workflow files absent | L2 | PATCH APPLIED / UNVERIFIED — atomic product commit `f0dcde78fb8f0c0f1a6f87ddad9124614dc7a0ed`; local syntax/static/dynamic geometry checks passed; GitHub downstream workflows were not executed because a `GITHUB_TOKEN` push is recursion-suppressed; connector-triggered exact-head tests are mandatory before verification |
| CR-006 | Pilot QA/output validators | PG3 / PIL-009 / PIL-QA-001 | Real QA returned `overall_passed=true` for frozen adversarial 32×32 raster; exact check `qa_negative_low_resolution` failed | After CR-005A, add one deterministic minimum-dimension/pixel-count gate to existing QA service and expose the same factual result; do not alter unrelated checks or thresholds | Positive pilot output remains accepted; 32×32 fixture fails required QA and blocks ready claim; report/route/regression tests | Revert only the CR-006 QA commit to the exact post-CR-005A SHA | L2 | BLOCKED BY UNVERIFIED CR-005A — DEFECT REPRODUCED; PRODUCT PATCH NOT YET AUTHORIZED |
| CR-007 | Frozen Pilot Set | PG1 | No immutable eight-fixture set and predeclared thresholds | Add 5 representative + 3 adversarial fixtures and manifest | Hash/property validation plus artifact re-read | Remove generator, validator and manifest; reset to `cf1f0f3f1d1192976aac0fc01b104c0736ba48da` | L2 | VERIFIED L2 — commit `c26c83b12fdec68bb2aa89c3ca05d8588f3768d9`, run `30389784679`, artifact `8700428913` |
| CR-008 | Candidate/evidence binding | PG5 | No pilot candidate exists | Add one-SHA manifest and mismatch guard | Mismatched-SHA negative test | Revert workflow/docs only | L2 | PLANNED |
| CR-009 | Pilot Beta packaging | PG7 | No exact Beta installer | Only after Alpha PASS build one exact installer | Clean Windows route | Remain on Alpha; do not publish | L4 | DEFERRED |

## CR-005 reproduction evidence

- Exact test-only head: `0667e43a6b9322d0a40efea3fc2bd48210b40517`.
- Real-source run: `30393464347`; route status `DEFECTS_REPRODUCED`.
- Hosted artifact: `8701852326`, digest `sha256:7dda8b4f7c79c182f0787e17819a898b5a0fd829b50310b1d143bdb383eeabb8`.
- Downloaded ZIP integrity passed and its SHA-256 matched the GitHub digest.
- Report SHA-256: `cd4f9760001d6301851ee343695b89092d1877d00546f76eae08f747d6fa72fa`.
- Output manifest SHA-256: `3e69683426e2ae04d4e8ac69d70ba970a43e9a76959fef4559c87002aa6416d0`.
- Passed: background, extract, manual selection, conservative cleanup, outside-mask preservation, linked/unlinked size and PPI, invalid-input blocking, positive QA, PNG, basic PNG DTF, source immutability, lineage, restart/reopen and project bundle.
- Failed only: `geometry_canvas_margin_runtime_contract`; `qa_negative_low_resolution`.

## CR-005A patch application evidence

- Exact source snapshot head: `4ee202cbc38afa7b9736eb097f6a4d582ebfad0b`; exact source artifact `8702105986`, digest `sha256:8162c3f045cb4d2114ed7e992990e5b9366f2598ce443e29377c82f9c283d53d`.
- Local verified patch SHA-256: `c0ac7c29188de798927434e841a878334226919ce81226c6e2ce32a990e7800d`.
- One-time fail-closed staging commit: `826606988d74b855b6c72554c1d67fdc8a3fe93c`; only the patch and self-removing workflow were added.
- Atomic product commit: `f0dcde78fb8f0c0f1a6f87ddad9124614dc7a0ed`; one commit ahead of staging; temporary patch/workflow removed in the same commit.
- Exact product diff: four allowed files only — `app/static/index.html`, `app/static/app.js`, `app/services/image_processing.py`, `tests/m2b_pilot_route_probe.py`; no dependency/configuration/installer/release changes.
- Pre-commit checks in the one-time workflow: exact patch hash, `git apply --check`, Python compile, JavaScript syntax, dynamic 720×360 / 300 PPI / 60-30-60-30 px geometry check, invalid canvas rejection, negative-margin rejection, zero-margin no-op, `git diff --check`, exact changed-file allowlist.
- The bot push could not trigger downstream workflows by GitHub recursion design. Therefore the product commit remains `UNVERIFIED` until connector-triggered runs complete on the later exact head containing the same product tree.

## Active change boundary

```text
ACTIVE_GATE=PG3
ACTIVE_CHANGE=CR-005A_SIZE_PPI_CANVAS_RUNTIME_CONTRACT_VERIFICATION
ACTIVE_REQUIREMENT=PIL-008_PIL-SZ-001
PRODUCT_PATCH_ALLOWED=false
PRODUCT_PATCH_SHA=f0dcde78fb8f0c0f1a6f87ddad9124614dc7a0ed
ROLLBACK=RESTORE_EXACT_FOUR_PRODUCT_FILES_FROM_4ee202cbc38afa7b9736eb097f6a4d582ebfad0b_KEEP_TEMP_FILES_ABSENT
NEXT_TEST=REAL_CANVAS_MARGIN_BINARY_PLACEMENT_PPI_INVALID_INPUT_SOURCE_IMMUTABILITY_AND_ALL_REGRESSIONS
REQUIRED_EVIDENCE_LEVEL=L2
RELEASE_BLOCKED=true
```
