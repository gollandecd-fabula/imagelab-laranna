from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def assert_gate(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate(evidence: Path, installer_sha: str) -> dict[str, Any]:
    ui = json.loads((evidence / "ui-gate.json").read_text("utf-8"))
    assert_gate(ui.get("status") == "PASS", "UI gate did not pass")
    assert_gate(ui.get("installer_sha256") == installer_sha, "installer SHA mismatch in UI evidence")
    files = evidence / "generated-files"

    with Image.open(files / "resized.png") as image:
        image.load()
        dpi = image.info.get("dpi")
        assert_gate(image.size == (400, 300), f"resized PNG is {image.size}, expected 400x300")
        assert_gate(isinstance(dpi, tuple) and abs(float(dpi[0]) - 200) <= 1.0 and abs(float(dpi[1]) - 200) <= 1.0, f"resized PNG embedded PPI invalid: {dpi}")

    with Image.open(files / "background.png") as image:
        alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8)
        border = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
        border_ratio = float(np.mean(border > 16))
        transparent_ratio = float(np.mean(alpha < 16))
        visible_ratio = float(np.mean(alpha > 16))
        assert_gate(border_ratio <= 0.02, f"background remains on border: {border_ratio:.4f}")
        assert_gate(transparent_ratio >= 0.20, f"background transparency insufficient: {transparent_ratio:.4f}")
        assert_gate(0.08 <= visible_ratio <= 0.75, f"subject coverage implausible: {visible_ratio:.4f}")

    with Image.open(files / "halftone.png") as image:
        alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8)
        coverage = float(np.mean(alpha > 16))
        components, _ = cv2.connectedComponents((alpha > 16).astype(np.uint8), 8)
        assert_gate(0.01 <= coverage <= 0.92, f"halftone coverage invalid: {coverage:.4f}")
        assert_gate(components >= 8, f"halftone lacks raster structure: {components}")

    svg_payload = (files / "vector.svg").read_text("utf-8")
    root = ET.fromstring(svg_payload)
    paths = [element for element in root.iter() if element.tag.endswith("path")]
    assert_gate(len(paths) >= 2, f"vector SVG has too few paths: {len(paths)}")
    lower = svg_payload.lower()
    assert_gate("<script" not in lower and "javascript:" not in lower, "unsafe SVG payload")
    diagnostics = ui["steps"]["vector"].get("diagnostics") or {}
    assert_gate(float(diagnostics.get("coverage_ratio", 0)) >= 0.84, f"vector coverage too low: {diagnostics}")
    assert_gate(float(diagnostics.get("quality_score", 0)) >= 0.64, f"vector quality too low: {diagnostics}")

    lineage = json.loads((evidence / "file-lineage.json").read_text("utf-8"))
    operations = {item.get("operation") for item in lineage.get("assets", [])}
    assert_gate({"enhance", "background", "halftone", "vectorize"}.issubset(operations), f"lineage missing operations: {operations}")

    return {
        "schema": 1,
        "status": "PASS",
        "installer_sha256": installer_sha,
        "resize": {"size_px": [400, 300], "ppi": 200},
        "background": {"border_visible_ratio": round(border_ratio, 6), "transparent_ratio": round(transparent_ratio, 6), "visible_ratio": round(visible_ratio, 6)},
        "halftone": {"coverage_ratio": round(coverage, 6), "components": int(components)},
        "vector": {"path_count": len(paths), "coverage_ratio": diagnostics.get("coverage_ratio"), "quality_score": diagnostics.get("quality_score")},
        "lineage_operations": sorted(str(item) for item in operations),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--installer-sha256", required=True)
    args = parser.parse_args()
    output = args.evidence_dir.resolve() / "output-validation.json"
    try:
        result = validate(args.evidence_dir.resolve(), args.installer_sha256)
    except Exception as exc:
        result = {"schema": 1, "status": "FAIL", "installer_sha256": args.installer_sha256, "error_type": type(exc).__name__, "error": str(exc)}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
