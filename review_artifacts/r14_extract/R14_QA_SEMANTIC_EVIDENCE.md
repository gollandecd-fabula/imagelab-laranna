# ImageLab R14-14 — QA semantic routing evidence

## Protocol state

Review-only. Authoritative product source, accepted R12 modules, packaging, installer, merge and release metadata were not modified by this cycle.

Evidence ceiling: **L1 / compatibility source-runtime scaffold**. The exact R13 `extract_fidelity.py` is known and hash-bound, but no artifact was found that proves `qa_service.py` or `repair_service.py` bytes for packaged R13. Therefore these QA/repair changes are **not** claimed as exact-R13 L2/L3 evidence.

## Binding requirement

Manual `extract_print` with `semantics=working_fragment` intentionally preserves the selected ROI's fabric/background for the separate downstream chain `Extract -> Improve -> Remove Background`. QA must not reject that correct result for being opaque or for lacking a cutout mask, and automatic repair must not convert manual ROI back into segmentation tuning. Auto/cutout extraction keeps the established cutout QA semantics.

## Baseline and candidate identity

Compatibility scaffold: `ImageLab_by_LarannA_A28_RC4_PREBUILD6_R1_SOURCE.zip` (recovery/reference only, not exact R13).

```text
qa_service baseline SHA-256   eba31662dfb3e0fcded0673fdb4e949f2e419d8cddbbadff548d660254aee062
qa_service candidate SHA-256  c1d12ae55467c664e0a26459cba05535b5c866b01ac15e90886e9f51755dd10a
repair baseline SHA-256       084f682b3bf279bf13d27c85c33ba6d8c3a92854a7479d153a6e9e3a1689b97f
repair candidate SHA-256      a28023a8625f45a0f7cf014194255d12c5c3141d9b783977bcf23f70007f9533
combined patch SHA-256        f455d683f54fe7e326d492af5c5154092b8e600969a1eceefb6deea6c86426f5
R14 regression SHA-256        5a34b02443e8348fb3b63c76ca077a5f10975f620cd7c6af9d07d109863d188e
```

## Candidate semantics

`qa_service.py`:
- recognizes working-fragment semantics only from explicit recorded diagnostics, never by guessing from opacity/ROI alone;
- checks explicit semantics, strict ROI and ROI bounds, output dimensions matching ROI, non-destructive flags, no fallback, and explicit source-alpha coverage semantics;
- does not emit legacy `print_coverage`, `print_transparency`, `print_garment_gate`, or `print_border_purity` checks for working fragments;
- routes the generic AI output preflight to `geometry` for a working fragment because `extract_print` preflight is specifically a cutout-mask gate;
- retains legacy cutout QA for auto/non-working-fragment extraction;
- makes all working-fragment contract checks critical/fail-closed.

`repair_service.py`:
- returns no automatic repair plan for `extract_print` when `mode=region`;
- preserves the existing automatic extraction repair behavior for `mode=auto`.

## Executed tests

### R14 working-fragment/API suite

```text
python -m py_compile app/services/qa_service.py app/services/repair_service.py tests/test_r14_working_fragment_qa_candidate.py
pytest -q tests/test_r14_working_fragment_qa_candidate.py
..... [100%]
```

**5/5 passed**. Coverage:
1. correct working fragment passes without legacy cutout checks;
2. segmentation/fallback/wrong coverage semantics/strict-ROI or ROI-dimension violations fail closed;
3. auto extraction retains legacy cutout QA;
4. manual-region repair never tunes cutout controls while auto still can;
5. real FastAPI `/api/projects/{id}/qa` + `qa_contract` technical/visual layer path accepts the correct working-fragment contract.

### Focused existing ImageLab regressions

```text
pytest -q \
  tests/test_print_extraction.py \
  tests/test_product_workflows.py \
  tests/test_ai_contours.py \
  tests/test_redteam_adversarial.py \
  tests/test_full_audit_v2.py \
  tests/test_project_process_hardening_rc4_prebuild6_recovered_20260906.py
```

Result: **58/58 passed**.

### Broad QA / repair / extract regression selection

Selected all existing test files that reference QA, repair, extraction or `/qa`, excluding only `test_a28_short_export_formats.py` because its PSD/PSB writer dependency is unavailable in this Linux scaffold.

Result: **95/95 passed**.

### Known scaffold blocker reproduced separately

```text
pytest -q tests/test_a28_short_export_formats.py
```

Observed exactly three failures:
- PSD roundtrip;
- PSB roundtrip;
- exported PSB reopen/process.

All three terminate at `ModuleNotFoundError: No module named 'psd_tools'` / `ExportError: PSD/PSB writer недоступен: psd-tools не установлен` before reaching R14 behavior. Project metadata pins `psd-tools==1.19.0`; the scaffold's local vendor wheel is Windows CPython 3.13 and is not usable by this Linux runtime. This dependency is outside R14 F03/F04 scope and was not modified.

Therefore **full-suite PASS is not claimed**.

## Protocol deviation and rollback

During preparation of these review artifacts, one incorrect connector action created GitHub issue #23 instead of the intended review file. The issue contained no product change and was immediately renamed to a rollback record and closed as `not_planned`. A subsequent PR read confirmed PR #21 head remained exactly `194d7f85110a34c1c2b8e02d7ae219aeb29a0b38`. This deviation is not treated as evidence and does not expand the allowed R14 scope.

## Provenance search

- `/GLAZ/ImageLab` contains no newer full ImageLab source/package artifact after PREBUILD6_R1 on 2026-09-06.
- Exact R13 extraction source is preserved in the review packet and reconstructs to SHA-256 `60763e3b70142b334445d68c5ec82d83a14cf717e13b1e35c842faa559e9b991`.
- `R14_BUILDER_BRIEF.md` explicitly states that exact extraction source came byte-for-byte from packaged payload `imagelab_payload_R13_XTRCT.zip`.
- No available manifest establishes the exact packaged-R13 hashes for `qa_service.py` or `repair_service.py`.

Hence exact-R13 QA/repair integration remains **UNVERIFIED**.

## RTM impact

| Requirement | Evidence | Status |
|---|---:|---|
| R14-7 Extract -> Improve -> explicit Remove Background remains separate | compatibility API/source | PARTIAL |
| R14-8 truthful diagnostics/QA semantics | L1 + compatibility API | PARTIAL |
| R14-10 regression coverage | L1 + compatibility runtime | PARTIAL; full suite blocked by unrelated scaffold dependency |
| R14-14 QA semantic routing | L1 + compatibility API | PARTIAL; exact R13 provenance not established |
| R14-11 packaged runtime | none | NOT_STARTED |
| R14-12 installed runtime | none | NOT_STARTED |
| R14-13 physical user path | none | NOT_STARTED |

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
