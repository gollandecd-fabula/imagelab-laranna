# ImageLab R14 — independent L1 evidence

Status is intentionally fail-closed. This artifact does **not** authorize product-source changes, packaging, installer publication, merge, L3/L4/L5, milestone completion, or release.

## Binding target

Manual `mode=region` Extract Print must return a rectangular working fragment with the current fabric/background preserved. It must keep every source detail for the later explicit `Improve -> Remove Background` chain. No default segmentation, background removal, texture reduction, feather-generated alpha, alpha crop, or alpha-silhouette dewarp is permitted. Manual ROI is a hard boundary; explicit validated four-point perspective remains allowed; unproved deskew fails closed to unchanged geometry.

## Exact-R13 identity

The prior Codex reconstruction reported packaged R13 SHA-256:

`60763e3b70142b334445d68c5ec82d83a14cf717e13b1e35c842faa559e9b991`

The newest complete source snapshot found in `/GLAZ/ImageLab` is `ImageLab_by_LarannA_A28_RC4_PREBUILD6_R1_SOURCE.zip`, but its `app/services/extract_fidelity.py` SHA-256 is:

`5051f1ee2dde767cc5ab1b2f884fba4e5fa0bf8c9d11d5e10a1eb836b260a44f`

Therefore PREBUILD6_R1 is **not** accepted as the exact R13 baseline and must not be substituted for it. It remains recovery/reference only.

## Independent safety harness

A local isolated L1 harness exercised the proposed manual working-fragment semantics without claiming integration into exact R13.

Command/result:

```text
python -m py_compile r14_manual_fragment_candidate.py test_r14_manual_fragment_candidate.py
pytest -q test_r14_manual_fragment_candidate.py
........... [100%]
11 passed in 0.29s
```

Harness SHA-256:

```text
75da2092dd117c9ade80636c932bd7003ba14badcff009b6cff03e6c68d014e2  r14_manual_fragment_candidate.py
fd1fcb23f150ccc5bd5524e3e0d68b4e8d3fd2106bd0a9e05cb2540f0bd752e7  test_r14_manual_fragment_candidate.py
```

### What the 11 L1 tests cover

1. exact RGBA ROI equality without geometric transform;
2. hidden RGB and source alpha preservation;
3. opaque input remains opaque and pixel-equal;
4. segmentation/background-removal/texture controls are not applied;
5. no manual-to-auto fallback surface in the candidate helper;
6. requested unsafe straighten is a truthful no-op;
7. auto/non-region input is not consumed by the manual helper;
8. malformed/missing/duplicate/self-intersecting/out-of-range perspective fails closed;
9. explicit identity four-point perspective routes as an explicit transform;
10. explicit non-identity four-point perspective remains supported;
11. ROI result dimensions remain bounded to the selected rectangle.

## Exact-R13 patch artifact

`R14_APPLY_TO_EXACT_R13.py` is a deterministic review-only patcher. It refuses to run unless the input UTF-8 source SHA-256 equals the exact R13 digest above. It replaces only the manual-region extraction branch/wiring and disables alpha-silhouette dewarp from `process_extract`, while leaving auto extraction logic in place. The patcher itself is currently an L0 artifact until executed against the exact reconstructed R13 bytes.

## RTM status after this evidence

| Requirement | Evidence now | Actual status |
|---|---:|---|
| hard ROI crop | L1 isolated | PARTIAL — exact R13 runtime not yet verified |
| preserve fabric/background and source alpha | L1 isolated | PARTIAL |
| no manual segmentation/removal/texture/alpha crop | L1 isolated | PARTIAL |
| no manual-to-auto fallback | L1 isolated | PARTIAL |
| explicit 4-point perspective | L1 isolated | PARTIAL |
| malformed perspective fail-closed | L1 isolated | PARTIAL |
| no alpha-silhouette dewarp | L1 isolated | PARTIAL |
| truthful diagnostics | L0/L1 structure | PARTIAL |
| exact R13 integration | none | NOT_STARTED / awaiting exact apply-runtime evidence |
| Extract -> Improve -> Remove Background source runtime | none | NOT_STARTED |
| packaged runtime | none | NOT_STARTED |
| installed runtime | none | NOT_STARTED |
| physical user path | none | NOT_STARTED |

## Required next evidence

1. Reconstruct exact R13 from the three committed review fragments and re-check SHA-256.
2. Run `R14_APPLY_TO_EXACT_R13.py` against that exact file.
3. `py_compile` the generated candidate.
4. Run deterministic regressions with spies that prove no `segment_print`, no texture/filter/crop-alpha, and no legacy auto fallback for `mode=region`.
5. Run source-runtime integration against the exact ImageLab runtime if the required surrounding packaged source is available.
6. Only after verified integration may a scoped delta be transferred to an authoritative working copy; do not touch accepted R12 modules.
7. L3 -> L4 -> one physical L5 question remain mandatory.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
