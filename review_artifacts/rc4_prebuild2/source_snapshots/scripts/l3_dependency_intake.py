from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class WheelRequirement:
    import_name: str
    distribution: str
    version: str
    filename: str
    sha256: str


EXACT_L3_WHEELS: dict[str, WheelRequirement] = {
    "pillow_heif": WheelRequirement(
        import_name="pillow_heif",
        distribution="pillow-heif",
        version="1.6.0",
        filename="pillow_heif-1.6.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        sha256="1629b5d5aaf484d5901297be024228abf8182c671e6c31dbbadf280faf1115c2",
    ),
    "psd_tools": WheelRequirement(
        import_name="psd_tools",
        distribution="psd-tools",
        version="1.19.0",
        filename="psd_tools-1.19.0-cp313-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl",
        sha256="36e9057f6c1e8e1092b83b6974f221577d8df0e49455f50cebaeca61bcbb4c69",
    ),
}

RECEIPT_NAME = "verified-runtime-receipt.json"
VERIFIED_WHEELS_DIR = ".verified_wheels"


def _canonical_name(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(".", "-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise RuntimeError(f"unsafe wheel member path: {info.filename}")
        members.append(info)
    return members


def _read_wheel_metadata(path: Path) -> dict[str, str]:
    try:
        with zipfile.ZipFile(path) as zf:
            metadata_names = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise RuntimeError(f"wheel METADATA count must be 1: {path.name}")
            text = zf.read(metadata_names[0]).decode("utf-8", errors="strict")
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise RuntimeError(f"wheel METADATA unreadable: {path.name}") from exc
    message = Parser().parsestr(text)
    return {"name": message.get("Name", ""), "version": message.get("Version", "")}


def _verify_wheel(path: Path, requirement: WheelRequirement) -> dict[str, str]:
    if path.name != requirement.filename:
        raise RuntimeError(f"exact wheel filename mismatch: expected {requirement.filename}, got {path.name}")
    if not path.is_file():
        raise RuntimeError(f"exact wheel missing: {path}")
    digest = _sha256(path)
    if digest != requirement.sha256:
        raise RuntimeError(
            f"exact wheel SHA-256 mismatch for {path.name}: expected {requirement.sha256}, got {digest}"
        )
    metadata = _read_wheel_metadata(path)
    if _canonical_name(metadata["name"]) != _canonical_name(requirement.distribution) or metadata["version"] != requirement.version:
        raise RuntimeError(
            f"wheel METADATA mismatch for {path.name}: expected Name={requirement.distribution} Version={requirement.version}, "
            f"got Name={metadata['name']} Version={metadata['version']}"
        )
    return {
        "import_name": requirement.import_name,
        "distribution": requirement.distribution,
        "version": requirement.version,
        "filename": requirement.filename,
        "sha256": digest,
    }


def compute_runtime_tree(runtime_dir: Path) -> dict[str, object]:
    runtime_dir = runtime_dir.resolve()
    if not runtime_dir.is_dir():
        raise RuntimeError(f"verified runtime directory missing: {runtime_dir}")
    files: list[Path] = []
    for path in runtime_dir.rglob("*"):
        if not path.is_file() or path.name == RECEIPT_NAME or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(runtime_dir).as_posix()):
        rel = path.relative_to(runtime_dir).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(4, "big")); digest.update(rel)
        file_digest = bytes.fromhex(_sha256(path))
        digest.update(file_digest)
    return {"sha256": digest.hexdigest(), "file_count": len(files)}


def build_verified_runtime(*, wheel_dir: Path, runtime_dir: Path, requirements: Mapping[str, WheelRequirement] = EXACT_L3_WHEELS) -> dict[str, object]:
    wheel_dir = wheel_dir.resolve(); runtime_dir = runtime_dir.resolve()
    verified: list[tuple[Path, WheelRequirement, dict[str, str]]] = []
    for key in sorted(requirements):
        req = requirements[key]
        wheel = wheel_dir / req.filename
        meta = _verify_wheel(wheel, req)
        verified.append((wheel, req, meta))

    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True)
    verified_dir = runtime_dir / VERIFIED_WHEELS_DIR
    verified_dir.mkdir()

    wheel_receipts: list[dict[str, str]] = []
    for wheel, req, meta in verified:
        copied = verified_dir / wheel.name
        shutil.copyfile(wheel, copied)
        _verify_wheel(copied, req)
        with zipfile.ZipFile(copied) as zf:
            members = _safe_members(zf)
            zf.extractall(runtime_dir, members=members)
        wheel_receipts.append(meta)

    tree = compute_runtime_tree(runtime_dir)
    receipt: dict[str, object] = {"schema": "imagelab.verified-l3-runtime.v1", "status": "PASS", "runtime_tree": tree, "wheels": wheel_receipts}
    (runtime_dir / RECEIPT_NAME).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), "utf-8")
    return receipt


def validate_verified_runtime(*, runtime_dir: Path, requirements: Mapping[str, WheelRequirement] = EXACT_L3_WHEELS) -> dict[str, object]:
    runtime_dir = runtime_dir.resolve()
    receipt_path = runtime_dir / RECEIPT_NAME
    if not receipt_path.is_file():
        raise RuntimeError(f"verified runtime receipt missing: {receipt_path}")
    try:
        receipt = json.loads(receipt_path.read_text("utf-8"))
    except Exception as exc:
        raise RuntimeError("verified runtime receipt unreadable") from exc
    if receipt.get("schema") != "imagelab.verified-l3-runtime.v1" or receipt.get("status") != "PASS":
        raise RuntimeError("verified runtime receipt schema/status invalid")

    verified_dir = runtime_dir / VERIFIED_WHEELS_DIR
    if not verified_dir.is_dir():
        raise RuntimeError("verified runtime exact wheel store missing")
    expected_names = {req.filename for req in requirements.values()}
    actual_names = {p.name for p in verified_dir.iterdir() if p.is_file()}
    if actual_names != expected_names:
        raise RuntimeError(f"verified wheel set mismatch: expected={sorted(expected_names)}, actual={sorted(actual_names)}")
    wheel_receipts: list[dict[str, str]] = []
    for key in sorted(requirements):
        req = requirements[key]
        wheel_receipts.append(_verify_wheel(verified_dir / req.filename, req))

    current_tree = compute_runtime_tree(runtime_dir)
    expected_tree = receipt.get("runtime_tree") or {}
    if current_tree.get("sha256") != expected_tree.get("sha256") or current_tree.get("file_count") != expected_tree.get("file_count"):
        raise RuntimeError(f"verified runtime tree hash mismatch: expected {expected_tree}, got {current_tree}")
    return {"schema": receipt["schema"], "status": "PASS", "runtime_tree": current_tree, "wheels": wheel_receipts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_verified_runtime(runtime_dir=args.runtime_dir) if args.verify_only else build_verified_runtime(wheel_dir=args.wheel_dir, runtime_dir=args.runtime_dir)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
