# ImageLab Pilot Alpha — approved governance v1.3.1

## Status

```text
PILOT_SPEC_V1_3_1_APPROVED
PILOT_DELTA_RTM_V1_3_1_APPROVED
EXACT_BASELINE_RECHECK_PASS
PILOT_ALPHA_BATCH_1_AUTHORIZED
M2A_IN_PROGRESS
M2B_FULL_NOT_STARTED
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
```

This file is the governance-first repository record. It changes no product behavior.

## Authorization and baseline

- User-approved specification: `ImageLab_EXECUTION_SPEC_v1.3.1_CONTROLLED_VERTICAL_PILOT`.
- User-approved matrix: `PILOT_DELTA_RTM v1.3.1`.
- Repository: `gollandecd-fabula/imagelab-laranna`.
- Parent M2A PR: `#11`, draft/open/unmerged.
- Parent branch: `redteam/imagelab-complete-audit-20260725-v2`.
- Exact frozen planning baseline and rollback point: `410841404d3afc2788b8a01d2166699beb1cfc27`.
- Pilot branch: `pilot/controlled-vertical-alpha-v1-3-1`.
- Approved M1 baseline: `35dd66bca9b31f2e9c098063a5382cd4f1c09cd6`.
- Existing green CI on the parent SHA is baseline health only and is not Pilot Alpha evidence.

## Binding locks

1. Modify the existing repository and current ImageLab code only. Greenfield rewrite, parallel frontend/backend, new product repository, or separate SaaS fork are prohibited.
2. Pilot Alpha is a controlled vertical route. Full M2B remains `NOT STARTED`; only the explicit `M2B-PILOT` slice is authorized.
3. Main evidence must use a real FastAPI process, real ProjectStore/filesystem, real image files, real processing, and real exports. Mock browser tests remain component evidence only.
4. Runtime model training, model promotion, and user-triggered model-weight rollback are prohibited in Pilot Alpha.
5. No new external AI model is introduced in Alpha or Beta.
6. SaaS infrastructure is deferred until `PILOT_ALPHA_PASS`; only compatibility-preserving changes are allowed.
7. CI, traces, screenshots, output files, reports, and later installer evidence must bind to one exact candidate SHA. Any source change creates a new candidate and invalidates prior candidate evidence.
8. `PILOT_ALPHA_PASS` does not imply `M2A_COMPLETE`, `M2B_COMPLETE`, `PRODUCTION_READY`, `RELEASE_AUTHORIZED`, or Genesis authorization.
9. Merge, public installer publication, marketplace writes, and release remain blocked.
10. Connector or transport limits never authorize product/test architecture changes.

## Authorized Pilot Alpha Batch 1

- `CR-001`: this governance record and scope guard.
- `CR-007`: Frozen Pilot Set v1 manifest and immutable fixture hashes.
- `CR-002`: `LIVE-E2E-01` using a real backend and real files.
- `CR-003`: fail-close runtime training and rollback entry points.
- `CR-004`: confirmed visual reachability defects at 800/1024/1280/1440/1920.

`CR-005`, `CR-006`, and `CR-008` may start only after the Batch 1 foundations exist and their tests pass. `CR-009` remains deferred until `PILOT_ALPHA_PASS`.

## M2B-PILOT slice

Only these limited operations are authorized for the vertical pilot:

- background removal or print extraction using the current engine and manual mask;
- conservative cleanup without AI-restoration claims;
- existing size/PPI/canvas path;
- deterministic pilot QA for integrity, lineage, decoding, dimensions, PPI, alpha, and mask boundary;
- PNG and basic PNG DTF output without production-ready DTF claims.

Production Color, Palette, Halftone, Smart Vector, DTF Master, Masters, Logo, CardLab, Model Manager, new AI routing, SaaS infrastructure, Genesis, merge, and public release remain outside this scope.

## Pilot Delta RTM

| ID | Requirement | Current factual state | Class | Allowed action | Mandatory evidence | PASS criterion | Status |
|---|---|---|---|---|---|---|---|
| PIL-001 | Pilot scope authorization | v1.3.1 and this RTM were explicitly approved; repository record is this commit. | Governance | Keep scope and release locks in repository before product code. | Commit order and static scope check. | No conflicting source/scope statement in the pilot PR. | IN PROGRESS |
| PIL-002 | Exact baseline | Parent PR head was rechecked as `4108414…`. | Baseline verified | Recheck before every mutation; rebaseline on change. | PR/head metadata and ancestry. | One baseline and rollback SHA. | BASELINE PASS |
| PIL-003 | Project lifecycle/restart | Project code exists; live restart route is not proven. | Live evidence gap | Add live E2E; product fix only after reproduction. | Persisted project, active asset and hashes after restart. | Project/history survive; source unchanged. | PARTIAL |
| PIL-004 | Real upload/metadata | Upload code exists; no pilot live proof. | Evidence gap | Upload frozen real fixtures through live UI/API. | Stored hash, metadata, checks and preview. | Asset facts match binary file. | NOT PILOT-PROVEN |
| PIL-005 | Mask correction | Tools exist; main browser evidence is mocked. | Live evidence gap | Prove persistence and asset isolation live. | Mask state after switch/restart. | No cross-asset leakage. | NOT PILOT-PROVEN |
| PIL-006 | Background/extract | Legacy paths exist but M2A controls are blocked. | Authorized pilot slice | Open only the limited live path with preview/new version. | Source/result hashes, lineage and boundary checks. | Source unchanged; result limited to allowed region. | NOT STARTED |
| PIL-007 | Conservative cleanup | Operations exist; pilot contract absent. | Contract gap | Restrict to deterministic conservative operations. | Before/after metrics and hashes. | No hidden color/geometry mutation. | NOT STARTED |
| PIL-008 | Size/PPI/canvas | Implementation/tests exist; visual accessibility defects were found. | Confirmed visual defect + live gap | Reproduce and minimally fix layout/result evidence. | Requested/actual table, binary output and screenshots. | File facts match request; controls reachable. | OPEN |
| PIL-009 | Mandatory pilot QA | QA exists; pilot minimum contract is not fixed. | Contract gap | Add deterministic integrity/lineage/decode/px/PPI/alpha/boundary checks. | Positive and negative QA reports. | Every mandatory check passes; failing fixture blocks ready claim. | NOT STARTED |
| PIL-010 | PNG export | Export path exists; live download validation absent. | Evidence gap | Add live export/download and binary inspection. | PNG hash, dimensions, alpha, PPI and lineage. | Binary file matches claim. | NOT PILOT-PROVEN |
| PIL-011 | Basic PNG DTF | API format exists; basic pilot profile is not proven. | Profile gap | Fix a non-production pilot profile and validate it. | Output binary, manifest and QA. | Profile facts pass without production claim. | NOT STARTED |
| PIL-012 | Live E2E without mocks | Current visual matrix mocks API/storage/processing. | Confirmed evidence defect | Run real FastAPI and real filesystem through Playwright. | Server log, trace, persisted project and outputs. | Full route passes without mocked production surfaces. | ALPHA P0 |
| PIL-013 | Visual reachability | CI screenshots exist; manual review found clipping/reachability issues. | Confirmed product defect | Minimal layout/scroll/focus corrections only. | Five-width interactions, screenshots and manual review. | No hidden mandatory control or clipped tail. | ALPHA P0 |
| PIL-014 | No runtime training | Train/rollback user paths exist. | Confirmed policy violation | Fail-close runtime endpoints/UI; retain offline code outside pilot. | Negative API/UI tests and no promoted-model writes. | No user runtime path changes weights. | ALPHA P0 |
| PIL-015 | Frozen Pilot Set v1 | Immutable eight-fixture set is absent. | Test-asset gap | Create 5 representative + 3 adversarial fixtures and manifest before benchmark. | Fixture hashes, expected properties and thresholds. | Fixtures are fixed before processing evidence. | ALPHA P0 |
| PIL-016 | Single candidate | Pilot candidate does not yet exist. | Candidate pending | Bind all evidence after one verified patch to one SHA. | Candidate manifest/workflow metadata. | No mixed snapshot, blob or installer SHA. | NOT STARTED |
| PIL-017 | Exact Windows Beta | Pilot Beta candidate is absent. | Deferred | Do not modify installer before Alpha PASS. | Clean install/restart/uninstall evidence. | Exact installed route passes. | DEFERRED |
| PIL-018 | Physical pilot | Exact Beta L5 has not occurred. | Deferred | Run only after Beta clean-install PASS. | L5 report, hashes and defect register. | User route completes on exact candidate. | DEFERRED |

## Pilot Change Register

| ID | Object | Confirmed reason | Future boundary | Next test | Rollback | Status |
|---|---|---|---|---|---|---|
| CR-001 | Governance/scope guard | Approved scope was not recorded in the repository. | Documentation and static guard only. | Diff and scope check. | Revert governance commit. | THIS COMMIT |
| CR-002 | LIVE-E2E-01 | Current key browser tests mock production surfaces. | Add live test harness without product-architecture changes. | Full real Alpha route. | Remove harness; product unchanged. | PLANNED |
| CR-003 | Runtime training lock | Training/promotion/rollback are reachable in user runtime. | Fail-close routes and UI; keep offline evaluation code. | Negative API/UI/no-write tests. | Restore only under separately approved offline scope. | PLANNED |
| CR-004 | Visual reachability | Confirmed clipping/hidden-tail issues. | Minimal CSS/DOM fix. | Five-width reachability matrix. | Revert CSS/DOM patch. | PLANNED |
| CR-005 | M2B-PILOT route | Limited vertical processing route is not assembled. | Only approved pilot operations. | Real fixture route. | Disable pilot controls; existing engines stay. | PLANNED AFTER FOUNDATIONS |
| CR-006 | Pilot QA/validators | No unified deterministic pilot contract. | Validator layer only. | Positive/negative fixtures. | Revert validator layer. | PLANNED AFTER FOUNDATIONS |
| CR-007 | Frozen Pilot Set | No immutable manifest. | Test fixtures/manifest only. | Hash/property validation. | Remove test assets. | PLANNED |
| CR-008 | Candidate/evidence binding | Pilot candidate is absent. | Workflow/manifest guard only. | Mismatched-SHA negative test. | Revert workflow/docs. | PLANNED AFTER FOUNDATIONS |
| CR-009 | Beta packaging | Exact Beta installer is absent. | Packaging only after Alpha PASS. | Clean Windows route. | Return to Alpha; never publish. | DEFERRED |

## Gate order

`PG0 governance/baseline → PG1 frozen fixtures/no-training → PG2 live project/upload/mask → PG3 processing/QA/export → PG4 visual reachability → PG5 one-candidate full CI → PG6 Alpha verdict → PG7 Windows Beta → PG8 physical pilot`.

Any incomplete required gate yields:

```text
PILOT_BLOCKED
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
```
