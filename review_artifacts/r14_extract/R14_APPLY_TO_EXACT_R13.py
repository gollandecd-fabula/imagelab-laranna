from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

EXPECTED_R13_SHA256 = "60763e3b70142b334445d68c5ec82d83a14cf717e13b1e35c842faa559e9b991"


MANUAL_REPLACEMENT = r'''def _validate_explicit_perspective(points: Any) -> list[list[float]]:
    """Validate explicit user geometry before delegating the transform.

    R14 must never infer a perspective quadrilateral.  Only four finite,
    distinct, convex points in TL/TR/BR/BL order are accepted.
    """
    if not isinstance(points, list) or len(points) != 4:
        raise legacy.ProcessingError("Для перспективы требуются четыре точки")
    parsed: list[list[float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise legacy.ProcessingError("Каждая точка перспективы должна содержать X и Y")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError) as exc:
            raise legacy.ProcessingError("Координаты перспективы должны быть числами") from exc
        if not bool(np.isfinite([x, y]).all()) or not 0.0 <= x <= 100.0 or not 0.0 <= y <= 100.0:
            raise legacy.ProcessingError("Координаты перспективы задаются от 0 до 100 %")
        parsed.append([x, y])
    polygon = np.asarray(parsed, dtype=np.float32)
    if len(np.unique(polygon, axis=0)) != 4:
        raise legacy.ProcessingError("Точки перспективы должны быть различными")
    contour = polygon.reshape((-1, 1, 2))
    area = abs(float(cv2.contourArea(contour)))
    if area < 4.0 or not cv2.isContourConvex(contour):
        raise legacy.ProcessingError("Четырёхугольник перспективы вырожден или точки указаны в неверном порядке")
    return parsed


def _manual_roi_working_fragment(
    image: Image.Image,
    params: dict[str, Any],
) -> tuple[Image.Image, dict[str, Any]]:
    """Return the exact manual ROI as a non-destructive working fragment.

    No segmentation, fabric model, texture filtering, feather-generated alpha,
    alpha crop or automatic extraction fallback is permitted in this path.
    Explicit four-point perspective is the only geometric correction applied.
    """
    if str(params.get("mode", "auto")).strip().lower() != "region":
        raise legacy.ProcessingError("Рабочий фрагмент ROI доступен только в режиме region")

    region, region_box = legacy._extract_region(image, params)
    perspective = params.get("perspective")
    transform_requested = perspective is not None
    transform_applied = False
    if transform_requested:
        validated = _validate_explicit_perspective(perspective)
        region = legacy._perspective(region, validated)
        transform_applied = True

    straighten_requested = legacy._bool(params, "straighten", False)
    ignored = [
        key
        for key in (
            "sensitivity",
            "texture_reduction",
            "reduce_fabric_texture",
            "feather",
            "crop_output",
            "padding",
            "padding_mm",
        )
        if key in params
    ]
    diagnostics: dict[str, Any] = {
        "strategy": "manual_roi_working_fragment_v1",
        "semantics": "working_fragment",
        "region_box_px": list(region_box),
        "strict_roi": True,
        "segmentation_applied": False,
        "background_removed": False,
        "texture_reduction_applied": False,
        "feather_alpha_applied": False,
        "alpha_crop_applied": False,
        "alpha_silhouette_dewarp_applied": False,
        "transform_requested": transform_requested,
        "transform_applied": transform_applied,
        "transform_kind": "explicit_4_point_perspective" if transform_applied else "none",
        "deskew_requested": straighten_requested,
        "deskew_applied": False,
        "deskew_reason": "no_safe_planar_evidence_fail_closed" if straighten_requested else "not_requested",
        "ignored_segmentation_controls": ignored,
        "fallback": False,
    }
    return region, diagnostics

'''


PROCESS_REPLACEMENT = r'''    mode = str(recorded.get("mode", "auto")).strip().lower()
    if mode == "region":
        # R14 hard branch: a manual ROI can never fall through to automatic
        # segmentation. Invalid ROI/perspective raises a clear ProcessingError.
        result, diagnostics = _manual_roi_working_fragment(image, recorded)
        ai = engine.analyze(result, module="extract")
        details = ai.setdefault("details", {})
        details["manual_roi_working_fragment"] = diagnostics
        details["extract_fidelity"] = {
            "strategy": "manual_roi_working_fragment",
            "semantics": "working_fragment",
            "region_box_px": diagnostics["region_box_px"],
            "strict_roi": True,
            "segmentation_applied": False,
            "background_removed": False,
            "fallback": False,
        }
    else:
        solved = _fidelity_extract(image, recorded)
        if solved is None:
            # R14 does not redefine automatic extraction semantics.
            result, ai = legacy._ai_extract_print(image, recorded)
            ai.setdefault("details", {})["extract_fidelity"] = {
                "strategy": "existing_ai_legacy_fallback",
                "fallback": True,
            }
        else:
            result, diagnostics = solved
            ai = engine.analyze(result, module="extract")
            preflight = engine.preflight(result, "extract_print", module="extract")
            ai["preflight"] = preflight
            ai.setdefault("details", {})["extract_fidelity"] = diagnostics
            if not preflight["details"]["passed"]:
                raise legacy.ProcessingError("AI-проверка заблокировала непригодный результат извлечения принта")

'''


DEWARP_REPLACEMENT = r'''    # R14: alpha/artwork silhouette is not geometry evidence.  Keep the old
    # helper unreachable from process_extract.  If a caller asks to straighten,
    # fail closed to unchanged geometry and report the no-op truthfully.
    if legacy._bool(params, "straighten", False):
        ai.setdefault("details", {})["local_dewarp"] = {
            "strategy": "r14_alpha_silhouette_dewarp_disabled",
            "requested": True,
            "applied": False,
            "reason": "alpha_silhouette_is_not_safe_geometry_evidence",
        }

'''


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def patch_exact_r13(source: str, *, verify_hash: bool = True) -> str:
    if verify_hash:
        actual = sha256_text(source)
        if actual != EXPECTED_R13_SHA256:
            raise SystemExit(
                f"BLOCKED_EXACT_R13_SHA_MISMATCH expected={EXPECTED_R13_SHA256} actual={actual}"
            )

    manual_start_marker = "def _manual_roi_loss_averse_extract("
    local_dewarp_marker = "def _local_dewarp("
    if source.count(manual_start_marker) != 1 or source.count(local_dewarp_marker) != 1:
        raise SystemExit("BLOCKED_R13_MANUAL_FUNCTION_ANCHOR_MISMATCH")
    start = source.index(manual_start_marker)
    end = source.index(local_dewarp_marker, start)
    patched = source[:start] + MANUAL_REPLACEMENT + source[end:]

    process_start_marker = "    manual = _manual_roi_loss_averse_extract(image, recorded)\n"
    dewarp_comment_marker = "    # Local alpha-silhouette dewarp is not safe as an implicit operation:"
    if patched.count(process_start_marker) != 1 or patched.count(dewarp_comment_marker) != 1:
        raise SystemExit("BLOCKED_R13_PROCESS_BRANCH_ANCHOR_MISMATCH")
    start = patched.index(process_start_marker)
    end = patched.index(dewarp_comment_marker, start)
    patched = patched[:start] + PROCESS_REPLACEMENT + patched[end:]

    dewarp_start = patched.index(dewarp_comment_marker)
    diagnostics_marker = '    recorded["diagnostics"] = ai.get("details", {})\n'
    if patched.count(diagnostics_marker) != 1:
        raise SystemExit("BLOCKED_R13_DIAGNOSTICS_ANCHOR_MISMATCH")
    dewarp_end = patched.index(diagnostics_marker, dewarp_start)
    patched = patched[:dewarp_start] + DEWARP_REPLACEMENT + patched[dewarp_end:]

    forbidden_manual = (
        "_manual_roi_loss_averse_extract",
        'engine.segment_print(region',
        '"manual_roi_ai_plus_border_fabric_v1"',
    )
    # The old segment_print/fabric strings may legitimately remain in the auto
    # path. Only the old manual function name is globally forbidden here.
    if forbidden_manual[0] in patched:
        raise SystemExit("BLOCKED_OLD_MANUAL_BRANCH_REMAINS")
    if patched.count("_manual_roi_working_fragment(") != 2:
        raise SystemExit("BLOCKED_NEW_MANUAL_BRANCH_WIRING_MISMATCH")
    if patched.count("manual_roi_working_fragment_v1") != 1:
        raise SystemExit("BLOCKED_NEW_DIAGNOSTIC_STRATEGY_MISMATCH")
    return patched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.input.read_text(encoding="utf-8")
    candidate = patch_exact_r13(source, verify_hash=True)
    args.output.write_text(candidate, encoding="utf-8", newline="\n")
    print(f"R13_SHA256={sha256_text(source)}")
    print(f"R14_CANDIDATE_SHA256={sha256_text(candidate)}")
    print(f"OUTPUT={args.output}")


if __name__ == "__main__":
    main()
