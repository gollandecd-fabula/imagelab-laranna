# ImageLab R7-SMOOTH — Codex re-review V4

Review the exact latest review-artifact head only. This PR is review-only: do not merge, do not modify product source, and do not infer installed Windows L4, physical user L5, milestone completion, or release readiness.

## Why V4 exists
The V3 Reviewer found one concrete P1 regression-coverage gap: V3 exercised smoothing helpers and client routing, but did not execute the real Improve backend dispatcher that selects manual/automatic smoothing and calls `_post_resize_smoothing`.

V4 changes **review artifacts only**. No product or installer byte changed. The exact backend dispatcher from the frozen R7 payload is now committed separately as `R7_BACKEND_ROUTE.py` and copied into the reconstructed candidate before tests. It is byte-identical in the pre/final payloads:
- product path: `app/services/m2a_processing.py`
- SHA-256: `00d3141f75adbd385c4a6a0b13eb329ababfa5d9019a97ee8b4b98df21c736e0`
- bytes: `13538`

## One clean-checkout command

```bash
python review_artifacts/r7_smooth/R7_REPRO_RUNNER.py
```

The runner now:
1. verifies all non-snapshot control/support files by SHA-256 and size;
2. decodes the existing committed V3 snapshot and verifies the exact extracted three pre-correction endpoints plus all 33 browser static dependencies by their content SHA/size;
3. inserts `R7_BACKEND_ROUTE.py` at its exact product path and verifies the resulting four-file pre-correction candidate;
4. runs `git apply --check`, applies the same three-file correction patch, and verifies the exact four-file final candidate;
5. proves the backend route is unchanged and exact;
6. runs the unchanged four helper regressions;
7. runs three new real-backend integration regressions through `m2a_processing.process_image(..., "enhance", ...)`;
8. runs the exact final browser routing/divider regression.

Snapshot tar container bytes are not used as an evidence identity in V4. The runner instead verifies every extracted code file actually used by the tests against the manifest. Therefore a different but equivalent tar container cannot alter the tested code without failing file-level SHA verification.

## Real Improve backend regressions
The new `R7_BACKEND_REGRESSION_TESTS.py` imports the exact reconstructed `image_processing.py` and `m2a_processing.py`. Only external input/persistence plumbing is intercepted (`_load_rgba` provides deterministic in-memory RGBA; `_save_result` captures the result). Real `_enhance`, `geometry_m2a`, automatic-strength selection, and `_post_resize_smoothing` execute.

Latest clean-checkout results:
- manual `preset=custom`, `smoothing=73`: smoothing called exactly once with `73`; recorded mode/effective = `manual/73`;
- manual `smoothing=0`: smoothing call count = `0`; recorded mode/effective = `manual/0`;
- automatic `preset=detail`, `denoise=100`, `smoothing_auto=true`, 4× physical resize: `64×48 → 256×192`; auto strength = `60`; smoothing called once with strength `60`, upscale factor `4.0`; recorded mode/effective = `automatic/60`.

## Full latest local gate
- pre candidate: 4/4 exact
- `git apply --check`: PASS
- final candidate: 4/4 exact
- exact backend dispatcher: PASS
- final browser static: 33/33 exact
- helper regressions: **4/4 PASS**
- real Improve backend integrations: **3/3 PASS**
- browser regression: PASS
- manual client smoothing: 73
- quick client `smoothing_auto`: true
- Saturation count: 0
- bottom split slider count: 0
- divider/clip delta: `0.00044799999977840343 px`
- browser errors: 0
- executable references to `/mnt/data`, old local trees, or external fixture files: 0

## Product / ГЛАЗ invariant
Frozen installer remains:
- bytes: `31847936`
- SHA-256: `daf2bb55bf09dc614f8b17e7a064e6b2b436acd5e2d77eefc450f38530497fb6`

ГЛАЗ was re-opened after the backend-coverage correction. Manual `Сглаживание` remains visible, Saturation remains absent from Improve, the divider remains one direct-drag vertical line with no bottom slider, centering remains intact, and the `0 → 50 → 76 → 100` comparison remains visually monotonic. This is existing packaged L3 evidence; V4 review reproducibility remains L2.

## Review request
Re-check the latest P1: the clean-checkout suite must now execute the actual Improve backend routing that selects manual/automatic smoothing and actually calls `_post_resize_smoothing`. Also check for any other concrete R7 P0/P1/P2.

If no concrete P0/P1/P2 remain, state exactly `NO_R7_P0_P1_P2_FOUND`.
