# ImageLab R14 — PRINT EXTRACT WORKING PATCH — Builder Brief

## Hard boundary
Review-only. Do not modify authoritative product source, do not merge, do not publish an installer, do not claim release/L5.
All Builder writes, if any, must stay under `review_artifacts/r14_extract/**`.

## Exact local baseline
The attached review artifact `R13_extract_fidelity.py` is byte-for-byte from local packaged payload `imagelab_payload_R13_XTRCT.zip`.
UI extraction call is captured in `R13_app_extract_snippet.txt`.

## Product-owner target behavior (binding)
The user selects/identifies the print on a T-shirt or another garment/product. `Extract Print` must produce a **rectangular working image fragment WITH its current background/fabric**, not a transparent cutout by default. The fragment must preserve the entire print, be maximally straightened/aligned without inventing geometry or damaging details, and be suitable for the next explicit steps: `Improve` and later `Remove Background`, then print use.

### Required semantics
1. Manual ROI is the hard spatial boundary. No pixels outside ROI.
2. Default manual-ROI result keeps RGB/background inside ROI and remains opaque (subject to original source alpha); it must NOT run print segmentation/background removal.
3. No hidden alpha-mask extraction in the default working-fragment path.
4. No alpha-silhouette auto-dewarp. Arbitrary artwork silhouette is not evidence of garment curvature.
5. Explicit 4-point perspective remains allowed and should be applied before final crop/result.
6. Automatic alignment/deskew may be used ONLY behind a strict confidence gate and only for reversible planar rotation/perspective corrections. If confidence is insufficient, fail closed to the unchanged ROI crop; never guess.
7. Preserve all print detail and existing background so downstream `Improve` can operate on a complete raster, followed by explicit `Remove Background`.
8. Existing ImageLab real-view, improve/smoothing, resize, export, shutter/divider, centering are out of scope and must not be changed.
9. Auto extraction mode must not be silently redefined unless the smallest safe correction requires it; prefer the manual ROI working-fragment path for this milestone.

## Requested Builder output
Produce a minimal proposed patch/design under `review_artifacts/r14_extract/BUILDER_PROPOSAL.md` (and optional patch artifact there only) covering:
- exact functions/branches to change;
- proposed parameter/diagnostic contract;
- safe deskew confidence strategy;
- regression tests needed for: background preserved, no segmentation, exact ROI, detail preservation, perspective 4-point, fail-closed deskew, extract→improve→remove-background compatibility;
- risks/P0-P2 findings in the current R13 logic relative to this target.

Do not modify product files. Do not merge. Do not claim PASS/L5.
