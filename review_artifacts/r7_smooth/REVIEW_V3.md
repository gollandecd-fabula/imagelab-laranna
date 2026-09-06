# ImageLab R7-SMOOTH — Codex re-review V3

Review the exact latest review-artifact head only. This PR is review-only: do not merge, do not modify product source, and do not infer installed Windows L4, physical user L5, milestone completion, or release readiness.

## Why V3 exists
The previous independent review on head `f6b3b6b76bc5ade8d1727303d81ba148afe77f50` found two new P1 reproducibility defects:
1. `R7_POST_CODEX_FIX.patch` was not a valid applicable unified diff.
2. `R7_REGRESSION_TESTS.py` / `R7_BROWSER_REGRESSION.py` depended on absent `/mnt/data` trees and fixtures.

One Builder invocation was used for this correction cycle. It correctly returned `BLOCKED_MISSING_EXACT_RECONSTRUCTION_INPUT` rather than inventing bytes. No Builder retry was made. Local inspection then recovered two exact payload ZIP snapshots (99 files each, CRC PASS) whose only differences are exactly the three post-review correction endpoints. V3 is built from those exact bytes; no product or installer byte was changed.

## One clean-checkout command

```bash
python review_artifacts/r7_smooth/R7_REPRO_RUNNER.py
```

The runner performs the complete reproducibility gate:
1. verifies SHA-256 and size of every committed support input;
2. concatenates the committed `R7_REPRO_SNAPSHOT.part*.b64` files in manifest order, decodes the exact `tar.xz`, and verifies archive SHA/size;
3. extracts an exact three-file pre-correction endpoint snapshot and verifies all 3 files by SHA/size;
4. runs `git apply --check R7_POST_CODEX_FIX.patch`, applies it, then verifies all 3 corrected endpoint files by exact SHA/size;
5. verifies an exact 33-file final static dependency snapshot used by the browser regression;
6. proves the patched final `app/static/app.js` and `13-m2a-closure-fixes.js.part` are byte-identical to the copies exercised by Playwright;
7. imports the exact reconstructed `image_processing.py` with inert stubs only for unrelated application imports, then runs the four smoothing regressions;
8. runs Playwright against the exact final static dependency snapshot; the browser script generates deterministic synthetic PNG bytes in-process, so no external fixture file is required.

No executable regression path references `/mnt/data`, `imagelab_r7work`, or `imagelab_r7packaged`.

## Exact identities
- pre-correction payload ZIP SHA-256: `acac42f36aabbaae78ff91cf7ebbc8782456fd3a325c9765dfe081a8ecd623fc`
- final payload ZIP SHA-256: `4d55ea0302c042feadfdcd583e97c6f370b1bc20dfc73424c0e38a3fc11ef4c6`
- snapshot archive SHA-256: `3f8e770875521ad73ef224fbdd161f9fd996e789f6635380f069b69d4b950d01`
- correction patch SHA-256: `09dafafce30ee75c8dd00a2759fe4b3896a47e09ac69106b716717468820b56f`
- changed paths, exactly three:
  - `app/services/image_processing.py`
  - `app/static/app.js`
  - `app/static/m2a-ui-parts/13-m2a-closure-fixes.js.part`

The manifest contains the exact pre/final SHA and size for all three endpoints plus SHA/size for all 33 browser static files.

## Local clean-checkout V12 result
- snapshot transport/integrity: PASS
- pre endpoint verification: 3/3 PASS
- `git apply --check`: PASS
- final endpoint verification: 3/3 PASS
- final browser static snapshot: 33/33 PASS
- patched JS ↔ browser-tested JS byte identity: PASS
- Python regression: 4/4 PASS
- browser regression: PASS
- manual path: `smoothing=73`, no `smoothing_auto`
- quick path: `smoothing_auto=true`, no manual `smoothing`
- Saturation control count in Improve: 0
- bottom split slider count: 0
- direct divider drag: PASS
- divider/clip delta: `0.00044799999977840343 px`
- browser page errors: 0

## Fixture identity
The browser regression generates a deterministic synthetic RGBA source (`192×144`) and a deterministic nearest-neighbour `2304×1728` result in-process. These images exist only to exercise UI routing and divider geometry; they are **not** represented as historical user fixtures or image-quality evidence. No external fixture file is required.

## Product / ГЛАЗ invariant
Review-artifact changes do not alter the packaged product. Rechecked installer:
- bytes: `31847936`
- SHA-256: `daf2bb55bf09dc614f8b17e7a064e6b2b436acd5e2d77eefc450f38530497fb6`

Packaged/ГЛАЗ evidence was visually re-opened after the reproducibility correction: manual `Сглаживание` remains present; Saturation remains absent from Improve; the divider remains one directly draggable vertical line with no bottom slider; and the `0 → 50 → 76 → 100` sheet shows monotonic visible smoothing. That is existing L3 packaged evidence. V3 itself establishes reproducible review-artifact L2 only.

## Review request
Re-check:
- the two V3 reproducibility P1 findings;
- alpha-aware smoothing / hidden-RGB safety;
- bounded-memory design;
- strict smoothing=0 no-op;
- automatic smoothing strength bounds;
- Quick/Manual routing;
- regression coverage;
- divider direct-drag geometry;
- absence of Saturation in Improve.

If no concrete P0/P1/P2 remain in R7 scope, state exactly `NO_R7_P0_P1_P2_FOUND`.
