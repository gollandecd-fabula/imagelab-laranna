from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _png_bytes(width: int, height: int, color_type: int, rows) -> bytes:
    channels = 4 if color_type == 6 else 3
    compressor = zlib.compressobj(level=9, wbits=15)
    compressed = bytearray()
    row_count = 0
    for row in rows:
        if len(row) != width * channels:
            raise ValueError(f"row length {len(row)} != {width * channels}")
        compressed.extend(compressor.compress(b"\x00" + row))
        row_count += 1
    if row_count != height:
        raise ValueError(f"row count {row_count} != {height}")
    compressed.extend(compressor.flush())
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", bytes(compressed))
        + _chunk(b"IEND", b"")
    )


def _write(path: Path, data: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "file": path.name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _transparency_rows():
    width = height = 256
    for y in range(height):
        row = bytearray()
        for x in range(width):
            dx = x - 128
            dy = y - 128
            radius2 = dx * dx + dy * dy
            if 72 * 72 <= radius2 <= 100 * 100:
                rgba = (20, 120, 220, 96)
            elif radius2 < 72 * 72:
                rgba = (240, 80, 60, 255)
            else:
                rgba = (0, 0, 0, 0)
            if 108 <= x < 148 and 20 <= y < 236:
                rgba = (255, 255, 255, 160)
            row.extend(rgba)
        yield bytes(row)


def _difficult_edge_rows():
    width = height = 512
    for y in range(height):
        row = bytearray()
        for x in range(width):
            diagonal = abs((x + y) - 500)
            ribbon_alpha = max(0, min(255, int((8.0 - diagonal) * 48)))
            wave = 250 + int(70 * (((x * 37) % 211) / 210.0 - 0.5))
            hair_distance = abs(y - (wave + (x - 256) * (x - 256) // 1800))
            hair_alpha = max(0, min(255, int((2.5 - hair_distance) * 110)))
            spike = 0
            if 80 <= x <= 440 and 340 <= y <= 450:
                for origin in range(80, 441, 12):
                    line_y = 430 - 2 * max(0, x - origin)
                    if origin <= x <= origin + 40:
                        spike = max(spike, max(0, 255 - abs(y - line_y) * 90))
            alpha = max(ribbon_alpha, hair_alpha, spike)
            if alpha == 0:
                row.extend((0, 0, 0, 0))
            elif ribbon_alpha >= max(hair_alpha, spike):
                row.extend((30, 160, 90, alpha))
            else:
                row.extend((25, 25, 25, alpha))
        yield bytes(row)


FONT_5X7 = {
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
}


def _text_logo_rows():
    width, height = 640, 320
    text = "LARANNA"
    pixel = 9
    for y in range(height):
        row = bytearray()
        for x in range(width):
            rgb = (245, 245, 240)
            if x < 20 or x >= 620 or y < 20 or y >= 300:
                rgb = (245, 245, 240)
            elif x < 28 or x >= 612 or y < 28 or y >= 292:
                rgb = (20, 20, 20)

            dx = x - 120
            dy = y - 140
            radius2 = dx * dx + dy * dy
            if radius2 <= 70 * 70:
                rgb = (30, 30, 30)
            if radius2 <= 42 * 42:
                rgb = (245, 245, 240)
            if 112 <= x < 128 and 50 <= y < 230:
                rgb = (200, 40, 60)

            origin_x, origin_y = 230, 95
            for index, char in enumerate(text):
                char_x = origin_x + index * 6 * pixel
                local_x = x - char_x
                local_y = y - origin_y
                if 0 <= local_x < 5 * pixel and 0 <= local_y < 7 * pixel:
                    column = local_x // pixel
                    row_index = local_y // pixel
                    if FONT_5X7[char][row_index][column] == "1":
                        rgb = (25, 25, 25)
            if 230 <= x < 565 and 190 <= y < 205:
                rgb = (200, 40, 60)
            row.extend(rgb)
        yield bytes(row)


def _low_resolution_rows():
    width = height = 32
    for y in range(height):
        row = bytearray()
        for x in range(width):
            rgb = (250, 245, 230)
            if (x // 4 + y // 4) % 2:
                rgb = (30, 90, 170)
            if 8 <= x < 24 and 8 <= y < 24:
                rgb = (220, 60, 50) if (x + y) % 3 else (255, 220, 80)
            row.extend(rgb)
        yield bytes(row)


def _non_uniform_rows():
    width, height = 512, 384
    for y in range(height):
        row = bytearray()
        for x in range(width):
            noise = (((x * 1103515245 + y * 12345 + 1337) >> 16) % 21) - 10
            red = max(0, min(255, 30 + (170 * x) // (width - 1) + noise))
            green = max(0, min(255, 60 + (120 * y) // (height - 1) + noise))
            blue = max(
                0,
                min(255, 120 + (90 * (x + y)) // (width + height - 2) + noise),
            )
            rgb = (red, green, blue)
            if 130 <= x <= 380 and 70 <= y <= 320:
                corner_dx = max(130 - x, 0, x - 380)
                corner_dy = max(70 - y, 0, y - 320)
                if corner_dx * corner_dx + corner_dy * corner_dy <= 45 * 45:
                    rgb = (245, 245, 238)
            dx = x - 255
            dy = y - 170
            if dx * dx + dy * dy <= 50 * 50:
                rgb = (220, 60, 70)
            if 220 <= x < 290 and 220 <= y < 290:
                rgb = (30, 30, 30)
            row.extend(rgb)
        yield bytes(row)


def _large_rows():
    width, height = 12001, 10001
    row = bytes((127, 127, 127)) * width
    for _ in range(height):
        yield row


def _corrupt_crc(valid_png: bytes) -> bytes:
    data = bytearray(valid_png)
    position = len(PNG_SIGNATURE)
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = bytes(data[position + 4 : position + 8])
        if kind == b"IDAT" and length > 4:
            data[position + 8 + length // 2] ^= 0x01
            return bytes(data)
        position += 12 + length
    raise ValueError("IDAT not found")


def generate(target: Path) -> list[dict[str, object]]:
    outputs = []
    transparency = _png_bytes(256, 256, 6, _transparency_rows())
    difficult = _png_bytes(512, 512, 6, _difficult_edge_rows())
    text_logo = _png_bytes(640, 320, 2, _text_logo_rows())
    low_resolution = _png_bytes(32, 32, 2, _low_resolution_rows())
    non_uniform = _png_bytes(512, 384, 2, _non_uniform_rows())
    large = _png_bytes(12001, 10001, 2, _large_rows())

    outputs.append(_write(target / "rep_transparency.png", transparency))
    outputs.append(_write(target / "rep_difficult_edge.png", difficult))
    outputs.append(_write(target / "rep_text_logo.png", text_logo))
    outputs.append(_write(target / "rep_low_resolution.png", low_resolution))
    outputs.append(_write(target / "rep_non_uniform_background.png", non_uniform))
    outputs.append(_write(target / "adv_large_dimensions.png", large))
    outputs.append(_write(target / "adv_truncated.png", transparency[:80]))
    outputs.append(_write(target / "adv_crc_corrupt.png", _corrupt_crc(low_resolution)))
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "pilot_v1"
        / "generated",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = generate(args.target)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"generated {len(report)} frozen pilot fixtures in {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
