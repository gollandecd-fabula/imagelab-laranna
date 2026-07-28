from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = SOURCE_ROOT / "tests" / "fixtures" / "pilot_v1"
GENERATED_ROOT = FIXTURE_ROOT / "generated"
MANIFEST = FIXTURE_ROOT / "manifest.json"
GENERATOR = SOURCE_ROOT / "tools" / "generate_pilot_frozen_set.py"


class FrozenSetError(AssertionError):
    pass


def _fail(message: str) -> None:
    raise FrozenSetError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_png(data: bytes, *, decode_pixels: bool) -> dict[str, Any]:
    if not data.startswith(PNG_SIGNATURE):
        _fail("signature")
    position = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    seen_iend = False

    while position < len(data):
        if position + 8 > len(data):
            _fail("truncated chunk header")
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        position += 8
        end = position + length
        if end + 4 > len(data):
            _fail("truncated chunk payload")
        payload = data[position:end]
        expected_crc = struct.unpack(">I", data[end : end + 4])[0]
        actual_crc = binascii.crc32(kind + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            _fail(f"crc mismatch in {kind.decode('ascii', 'replace')}")
        chunks.append((kind, payload))
        position = end + 4
        if kind == b"IEND":
            seen_iend = True
            break

    if not seen_iend:
        _fail("truncated png: missing IEND")
    if position != len(data):
        _fail("trailing bytes after IEND")
    if not chunks or chunks[0][0] != b"IHDR":
        _fail("IHDR must be first")
    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        _fail("invalid IHDR length")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    if compression != 0 or filtering != 0 or interlace != 0:
        _fail("unsupported PNG coding")
    if bit_depth != 8 or color_type not in {2, 6}:
        _fail("fixture validator supports only 8-bit RGB/RGBA")

    result: dict[str, Any] = {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "pixel_count": width * height,
    }
    if not decode_pixels:
        return result

    bytes_per_pixel = 3 if color_type == 2 else 4
    compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        _fail(f"zlib decode failed: {exc}")
    stride = width * bytes_per_pixel
    expected_size = height * (stride + 1)
    if len(raw) != expected_size:
        _fail(f"decoded byte size mismatch: {len(raw)} != {expected_size}")

    previous = bytearray(stride)
    unique: set[bytes] = set()
    alpha_zero = alpha_partial = alpha_full = 0
    dark_pixels = light_pixels = 0
    offset = 0

    def paeth(left: int, up: int, up_left: int) -> int:
        estimate = left + up - up_left
        distance_left = abs(estimate - left)
        distance_up = abs(estimate - up)
        distance_up_left = abs(estimate - up_left)
        if distance_left <= distance_up and distance_left <= distance_up_left:
            return left
        if distance_up <= distance_up_left:
            return up
        return up_left

    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        encoded = raw[offset : offset + stride]
        offset += stride
        row = bytearray(stride)
        for index, value in enumerate(encoded):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            up_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 0:
                decoded = value
            elif filter_type == 1:
                decoded = (value + left) & 0xFF
            elif filter_type == 2:
                decoded = (value + up) & 0xFF
            elif filter_type == 3:
                decoded = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                decoded = (value + paeth(left, up, up_left)) & 0xFF
            else:
                _fail(f"unsupported filter type {filter_type}")
            row[index] = decoded

        for index in range(0, stride, bytes_per_pixel):
            pixel = bytes(row[index : index + bytes_per_pixel])
            rgba = pixel + b"\xff" if color_type == 2 else pixel
            unique.add(rgba)
            red, green, blue, alpha = rgba
            if alpha == 0:
                alpha_zero += 1
            elif alpha == 255:
                alpha_full += 1
            else:
                alpha_partial += 1
            luminance = (299 * red + 587 * green + 114 * blue) // 1000
            if luminance <= 60:
                dark_pixels += 1
            if luminance >= 220:
                light_pixels += 1
        previous = row

    result.update(
        {
            "unique_rgba": len(unique),
            "alpha_zero": alpha_zero,
            "alpha_partial": alpha_partial,
            "alpha_full": alpha_full,
            "dark_pixels": dark_pixels,
            "light_pixels": light_pixels,
        }
    )
    return result


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        _fail(f"{label}: {actual!r} != {expected!r}")


def _require_min(actual: int, minimum: int, label: str) -> None:
    if actual < minimum:
        _fail(f"{label}: {actual} < {minimum}")


def _require_max(actual: int, maximum: int, label: str) -> None:
    if actual > maximum:
        _fail(f"{label}: {actual} > {maximum}")


def validate_frozen_set() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    _require_equal(manifest["schema_version"], 1, "schema_version")
    _require_equal(manifest["pilot_set_id"], "FROZEN_PILOT_SET_V1", "pilot_set_id")
    _require_equal(manifest["benchmark_status"], "NOT_STARTED", "benchmark_status")
    _require_equal(manifest["claims"]["pilot_alpha_pass"], False, "pilot_alpha_pass")
    _require_equal(manifest["claims"]["release_authorized"], False, "release_authorized")
    _require_equal(
        _sha256(GENERATOR.read_bytes()),
        manifest["generator"]["sha256"],
        "generator sha256",
    )

    fixtures = manifest["fixtures"]
    counts = manifest["required_counts"]
    _require_equal(len(fixtures), counts["total"], "fixture count")
    representative = sum(item["classification"] == "representative" for item in fixtures)
    adversarial = sum(item["classification"] == "adversarial" for item in fixtures)
    _require_equal(representative, counts["representative"], "representative count")
    _require_equal(adversarial, counts["adversarial"], "adversarial count")

    ids = [item["id"] for item in fixtures]
    files = [item["file"] for item in fixtures]
    coverage = [item["coverage"] for item in fixtures]
    _require_equal(len(ids), len(set(ids)), "unique fixture ids")
    _require_equal(len(files), len(set(files)), "unique fixture paths")
    _require_equal(set(coverage), set(manifest["required_coverage"]), "coverage")

    results: dict[str, Any] = {}
    for item in fixtures:
        relative = Path(item["file"])
        if relative.is_absolute() or ".." in relative.parts:
            _fail(f"unsafe fixture path: {relative}")
        path = GENERATED_ROOT / relative
        data = path.read_bytes()
        _require_equal(len(data), item["size_bytes"], f"{item['id']} size")
        _require_equal(_sha256(data), item["sha256"], f"{item['id']} sha256")

        expected = item["expected"]
        thresholds = item["thresholds"]
        if not expected["png_valid"]:
            try:
                _parse_png(data, decode_pixels=True)
            except FrozenSetError as exc:
                required_fragment = thresholds["validation_error_contains"]
                if required_fragment not in str(exc).casefold():
                    _fail(
                        f"{item['id']} error {str(exc)!r} does not contain "
                        f"{required_fragment!r}"
                    )
                results[item["id"]] = {"expected_invalid": True, "error": str(exc)}
                continue
            _fail(f"{item['id']} unexpectedly parsed as valid PNG")

        decode_pixels = not thresholds.get("skip_pixel_decode", False)
        parsed = _parse_png(data, decode_pixels=decode_pixels)
        for key in ("width", "height", "bit_depth", "color_type"):
            _require_equal(parsed[key], expected[key], f"{item['id']} {key}")

        for metric in (
            "alpha_zero",
            "alpha_partial",
            "alpha_full",
            "unique_rgba",
            "dark_pixels",
            "light_pixels",
            "pixel_count",
        ):
            minimum_key = f"{metric}_min"
            maximum_key = f"{metric}_max"
            if minimum_key in thresholds:
                _require_min(parsed[metric], thresholds[minimum_key], f"{item['id']} {metric}")
            if maximum_key in thresholds:
                _require_max(parsed[metric], thresholds[maximum_key], f"{item['id']} {metric}")

        if "max_dimension_max" in thresholds:
            _require_max(
                max(parsed["width"], parsed["height"]),
                thresholds["max_dimension_max"],
                f"{item['id']} max_dimension",
            )
        if "pixel_count_limit" in thresholds:
            if parsed["pixel_count"] <= thresholds["pixel_count_limit"]:
                _fail(
                    f"{item['id']} pixel_count does not exceed frozen limit "
                    f"{thresholds['pixel_count_limit']}"
                )
        results[item["id"]] = parsed

    first = fixtures[0]
    original = (GENERATED_ROOT / first["file"]).read_bytes()
    mutated = bytes([original[0] ^ 0x01]) + original[1:]
    if _sha256(mutated) == first["sha256"]:
        _fail("negative hash self-test did not detect mutation")

    return {
        "pilot_set_id": manifest["pilot_set_id"],
        "fixture_count": len(fixtures),
        "representative": representative,
        "adversarial": adversarial,
        "results": results,
    }


def main() -> int:
    try:
        report = validate_frozen_set()
    except (FrozenSetError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"FROZEN_PILOT_SET_V1: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "FROZEN_PILOT_SET_V1: PASS "
        f"fixtures={report['fixture_count']} "
        f"representative={report['representative']} "
        f"adversarial={report['adversarial']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
