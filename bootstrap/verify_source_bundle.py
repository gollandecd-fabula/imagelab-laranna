#!/usr/bin/env python3
"""Fail-closed verifier for the exact ImageLab bootstrap source bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import zipfile

MAX_MEMBERS = 5_000
MAX_UNCOMPRESSED_BYTES = 1_000_000_000
REQUIRED_FILES = (
    "app/main.py",
    "app/config.py",
    "release_gate/source_gate.py",
    "release_gate/run_clean_install_gate.ps1",
    "scripts/build_zero_trust_candidate.py",
    "windows_installer/installer/main.go",
    "requirements.txt",
)
FORBIDDEN_PREFIXES = (
    "data/",
    "output/",
    "dist/",
    "build/",
    "evidence/",
)
FORBIDDEN_BASENAMES = {
    ".env",
    "launcher.log",
    "feedback.json",
    "audit.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_unsafe_member(member: zipfile.ZipInfo) -> bool:
    path = PurePosixPath(member.filename)
    parts = tuple(part for part in path.parts if part not in {"", "."})
    mode = (member.external_attr >> 16) & 0xFFFF
    return (
        path.is_absolute()
        or ".." in parts
        or "\\" in member.filename
        or stat.S_ISLNK(mode)
    )


def is_forbidden_member(name: str) -> bool:
    path = PurePosixPath(name)
    normalized = path.as_posix().lstrip("./")
    lower = normalized.lower()
    parts = {part.lower() for part in path.parts}
    return (
        lower.startswith(FORBIDDEN_PREFIXES)
        or "__pycache__" in parts
        or lower.endswith((".pyc", ".pyo"))
        or path.name.lower() in FORBIDDEN_BASENAMES
    )


def write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extract-to", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-build-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected_sha256 = args.expected_sha256.lower()
    failures: list[str] = []
    evidence: dict[str, object] = {
        "schema": 3,
        "status": "FAIL",
        "expected": {
            "sha256": expected_sha256,
            "version": args.expected_version,
            "build_id": args.expected_build_id,
        },
        "failures": failures,
        "extract_state": "NOT_ATTEMPTED",
    }
    stage: Path | None = None

    try:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            failures.append("EXPECTED_SHA256_INVALID")
        if not args.archive.is_file():
            failures.append("SOURCE_ARCHIVE_MISSING")
        if not args.checksum.is_file():
            failures.append("SOURCE_CHECKSUM_FILE_MISSING")
        if failures:
            raise RuntimeError("bootstrap input admission failed")

        checksum_tokens = args.checksum.read_text(encoding="utf-8").strip().split()
        if len(checksum_tokens) != 2:
            failures.append("SOURCE_CHECKSUM_FORMAT_INVALID")
            raise RuntimeError("checksum file must contain SHA-256 and filename")
        pinned_sha256 = checksum_tokens[0].lower()
        pinned_filename = checksum_tokens[1].lstrip("*")
        actual_sha256 = sha256_file(args.archive)
        evidence["observed"] = {
            "pinned_sha256": pinned_sha256,
            "actual_sha256": actual_sha256,
            "pinned_filename": pinned_filename,
        }
        if not re.fullmatch(r"[0-9a-f]{64}", pinned_sha256):
            failures.append("SOURCE_CHECKSUM_NOT_SHA256")
        if pinned_filename != args.archive.name:
            failures.append("SOURCE_CHECKSUM_FILENAME_MISMATCH")
        if pinned_sha256 != expected_sha256:
            failures.append("SOURCE_PINNED_SHA256_MISMATCH")
        if actual_sha256 != expected_sha256:
            failures.append("SOURCE_EXACT_SHA256_MISMATCH")

        with zipfile.ZipFile(args.archive) as bundle:
            members = bundle.infolist()
            names = [member.filename for member in members]
            bad_crc = bundle.testzip()
            total_uncompressed = sum(int(member.file_size) for member in members)
            duplicate_names = sorted(
                name for name in set(names) if names.count(name) > 1
            )
            unsafe = sorted(
                member.filename for member in members if is_unsafe_member(member)
            )
            forbidden = sorted(
                member.filename
                for member in members
                if is_forbidden_member(member.filename)
            )
            evidence["archive"] = {
                "member_count": len(members),
                "total_uncompressed_bytes": total_uncompressed,
                "members_sha256": hashlib.sha256(
                    "\n".join(sorted(names)).encode("utf-8")
                ).hexdigest(),
                "crc_failure": bad_crc,
                "duplicate_members": duplicate_names,
                "unsafe_members": unsafe,
                "forbidden_members": forbidden,
            }
            if bad_crc is not None:
                failures.append("SOURCE_ZIP_CRC_FAILURE")
            if len(members) > MAX_MEMBERS:
                failures.append("SOURCE_ZIP_MEMBER_LIMIT_EXCEEDED")
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                failures.append("SOURCE_ZIP_UNCOMPRESSED_LIMIT_EXCEEDED")
            if duplicate_names:
                failures.append("SOURCE_ZIP_DUPLICATE_MEMBER")
            if unsafe:
                failures.append("SOURCE_ZIP_UNSAFE_MEMBER")
            if forbidden:
                failures.append("SOURCE_BUNDLE_PRIVACY_DENYLIST_VIOLATION")

            if failures:
                evidence["extract_state"] = "BLOCKED_BY_ARCHIVE_ADMISSION"
            else:
                args.extract_to.parent.mkdir(parents=True, exist_ok=True)
                stage = Path(
                    tempfile.mkdtemp(
                        prefix=f".{args.extract_to.name}-",
                        suffix=".tmp",
                        dir=args.extract_to.parent,
                    )
                )
                evidence["extract_state"] = "STAGING"
                for member in members:
                    target = stage / PurePosixPath(member.filename)
                    target_resolved = target.resolve()
                    stage_resolved = stage.resolve()
                    if (
                        target_resolved != stage_resolved
                        and stage_resolved not in target_resolved.parents
                    ):
                        failures.append("ZIP_EXTRACTION_ESCAPE")
                        break
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with bundle.open(member) as source, target.open("xb") as destination:
                            shutil.copyfileobj(source, destination)

        if not failures and stage is not None:
            missing = [item for item in REQUIRED_FILES if not (stage / item).is_file()]
            evidence["required_files"] = list(REQUIRED_FILES)
            evidence["missing_required_files"] = missing
            if missing:
                failures.append("SOURCE_REQUIRED_FILES_MISSING")

            config_path = stage / "app/config.py"
            if config_path.is_file():
                config_text = config_path.read_text(encoding="utf-8")
                version_present = args.expected_version in config_text
                build_id_present = args.expected_build_id in config_text
            else:
                version_present = False
                build_id_present = False
            evidence["identity"] = {
                "expected_version_text_present": version_present,
                "expected_build_id_text_present": build_id_present,
            }
            if not version_present:
                failures.append("SOURCE_VERSION_IDENTITY_MISMATCH")
            if not build_id_present:
                failures.append("SOURCE_BUILD_IDENTITY_MISMATCH")

        if not failures and stage is not None:
            shutil.rmtree(args.extract_to, ignore_errors=True)
            os.replace(stage, args.extract_to)
            stage = None
            evidence["extract_state"] = "PUBLISHED_ATOMICALLY"

    except Exception as exc:
        evidence["exception_type"] = type(exc).__name__
        evidence["exception"] = str(exc)
        if not failures:
            failures.append("SOURCE_BUNDLE_VERIFICATION_EXCEPTION")
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        evidence["status"] = "PASS" if not failures else "FAIL"
        write_evidence(args.output, evidence)
        print(args.output.read_text(encoding="utf-8"))

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
