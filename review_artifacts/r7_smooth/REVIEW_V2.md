# ImageLab R7-SMOOTH — Codex re-review V2

Review the latest packet only. This is review-only: do not merge and do not infer physical L5 or release readiness.

## Prior Codex findings addressed
1. P1 alpha awareness: smoothing now uses premultiplied RGB for gradient/Gaussian work, blurs alpha, unpremultiplies the blurred color, and restores the exact original alpha. The regression suite requires visible output to be identical when only hidden RGB under alpha=0 differs.
2. P2 full-frame memory: images above 32 Mpx use a disk-backed immutable raw RGBA source while the destination canvas is updated in-place; tile temporaries stay bounded. 150 Mpx completed at about 0.90 GiB peak RSS, down from about 1.39 GiB.
3. P2 Quick/Manual routing: the active segmented mode is now the source of truth; changing the preset synchronizes the segmented control and manual panel. Browser regression captures the exact parameter objects for manual and quick paths.
4. P1 regression coverage: executable Python and Playwright regressions are included in this packet.

## Fresh evidence
- Python regression suite: 4/4 PASS.
- Browser regression: PASS; manual sends `smoothing=73`; quick sends `smoothing_auto=true`; Saturation count 0.
- Divider: no bottom split slider; direct drag works; visible divider/clip mismatch about 0.00045 px.
- R6 vs current R7 manual smoothing=0 full enhance/resize PNG: byte-identical SHA-256 `2d3c525be90a3f6cc03cbcc203e2005378afe3a9e2c030f13441ae46303782a3`.
- Source API: manual 0/50/100 persist exactly; auto Detail at 8x selects 72.
- Memory: 29.76 Mpx ~0.50 GiB, 64 Mpx ~0.56 GiB, 150 Mpx ~0.90 GiB; no OOM.

## Files
- `R7_SMOOTH.patch`: original R6→R7 packet reviewed previously.
- `R7_POST_CODEX_FIX.patch`: exact post-review correction delta from the previously packaged R7 to current source.
- `R7_REGRESSION_TESTS.py`: executable alpha/tile/no-op/auto-strength tests.
- `R7_BROWSER_REGRESSION.py`: executable mode-routing/divider/Saturation browser test.
- `EVIDENCE_V2.json`: measured current evidence.

Re-check whether the four prior findings are closed and report any new concrete P0/P1/P2 in this R7 scope. If none remain, state `NO_R7_P0_P1_P2_FOUND`.
