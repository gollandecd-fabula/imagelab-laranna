# ImageLab R7-SMOOTH — Codex review-only packet

Scope: review the local R6 -> R7 delta only. Do not merge this PR; it contains review artifacts, not the authoritative product source.

## Locked requirements
- Manual Improve: add `Сглаживание` slider 0..100, default 0.
- Manual smoothing=0 must be a strict no-op relative to R6 output.
- Quick/automatic Improve: smoothing applies automatically without exposing the manual slider.
- Smoothing is post-resize, to address pixelation introduced by large physical-size upscales.
- Saturation must remain absent from Improve.
- Centering must not change.
- Existing divider drag behavior must remain; the patch also recenters its transparent hit-area so the visible line aligns with the actual split boundary.

## Local evidence before Codex
- Manual smoothing=0: byte-identical PNG vs R6 for the same processing parameters.
- Denoise benchmark: byte-identical metrics vs R6.
- 8x source-runtime API: manual 0/50/100 recorded correctly; auto detail+denoise100 selected smoothing 72.
- Synthetic 8x/12x: alpha unchanged; max mean RGB drift <0.24; at smoothing100 strong-edge proxy retains ~90–93%.
- UI: smoothing appears only inside Manual controls; saturation absent; quick hides the slider; divider drag works; visible divider/split mismatch ~0.0005 px after regression fix.

## Review questions
1. Is `_post_resize_smoothing` safe for RGBA, large images, and edge preservation? Any overflow/shape/alpha pitfalls?
2. Is `_automatic_smoothing_strength` appropriately bounded and deterministic for 1x..12x upscales?
3. Does manual `smoothing=0` remain a strict no-op through the full enhance path?
4. Are there parameter-validation or persistence issues in `m2a_processing.py`?
5. Could the extra Gaussian/Sobel allocations cause unacceptable peak memory on the existing 150 Mpx maximum?
6. Does the UI correctly send manual vs automatic parameters without reintroducing Saturation?
7. Does the one-line divider hit-area transform preserve drag while aligning the visible line?

Please prioritize correctness, performance/memory risks, and regressions. No release-readiness claims; physical L5 remains external.
