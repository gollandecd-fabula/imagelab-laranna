from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = (2026, 7, 24, 0, 0, 0)
EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", ".git", ".slu_backup", ".slu_m6_build",
    ".plateau_build", ".core_recovery_build", ".update_lock_build", ".update_lock_backup",
    ".zero_trust_build", "dist", ".venv", "venv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive(output: Path, entries: list[tuple[str, bytes]], executable: set[str] | None = None) -> None:
    executable = executable or set()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive_file:
        for name, data in sorted(entries):
            normalized = name.replace("\\", "/")
            info = zipfile.ZipInfo(normalized, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if normalized in executable else 0o644) << 16
            archive_file.writestr(info, data)


def payload_file(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in rel.parts) or path.suffix in {".pyc", ".pyo"}:
        return False
    return path.is_file() and (
        (rel.parts and rel.parts[0] in {"app", "models"})
        or rel in {Path("bootstrap.py"), Path("requirements.txt"), Path("README.md")}
    )


def source_file(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.suffix in {".pyc", ".pyo", ".exe"} or path.name == ".coverage":
        return False
    if rel.parts and rel.parts[0] == "data":
        return False
    if rel == Path("windows_installer/installer/payload.zip"):
        return False
    if rel.parts and rel.parts[0].startswith("evidence"):
        return False
    return path.is_file()


def pe_info(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 0x40:
        raise RuntimeError("installer is too small to be a PE file")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    return {
        "mz": data[:2] == b"MZ",
        "pe": data[offset:offset + 4] == b"PE\0\0",
        "machine_x64": struct.unpack_from("<H", data, offset + 4)[0] == 0x8664,
        "pe32_plus": struct.unpack_from("<H", data, offset + 24)[0] == 0x20B,
        "size_bytes": len(data),
    }


def build_go(source: Path, output: Path, *, gui: bool) -> None:
    env = dict(os.environ)
    env.update({"GO111MODULE": "off", "GOOS": "windows", "GOARCH": "amd64"})
    flags = "-s -w -buildid=" + (" -H=windowsgui" if gui else "")
    command = ["go", "build", "-trimpath", "-ldflags", flags, "-o", str(output), "."]
    result = subprocess.run(command, cwd=source, env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Go build failed for {source}:\n{result.stdout}\n{result.stderr}")


def read_identity() -> dict[str, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.config import settings
    return {
        "app": str(settings.app_name),
        "version": str(settings.app_version),
        "build_id": str(settings.build_id),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--label", default="ZERO_TRUST")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_dir = ROOT / ".zero_trust_build"
    shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True)

    identity = read_identity()
    safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.label)
    installer_path = output_dir / f"ImageLab_by_LarannA_{safe_label}_Setup_x64.exe"
    source_zip = output_dir / f"ImageLab_by_LarannA_{safe_label}_SOURCE.zip"
    payload_path = ROOT / "windows_installer" / "installer" / "payload.zip"

    launcher = build_dir / "ImageLab.exe"
    uninstaller = build_dir / "Uninstall.exe"
    build_go(ROOT / "windows_installer" / "launcher", launcher, gui=True)
    build_go(ROOT / "windows_installer" / "uninstaller", uninstaller, gui=True)

    payload_entries = [("ImageLab.exe", launcher.read_bytes()), ("Uninstall.exe", uninstaller.read_bytes())]
    payload_entries.extend(
        (path.relative_to(ROOT).as_posix(), path.read_bytes())
        for path in ROOT.rglob("*") if payload_file(path)
    )
    archive(payload_path, payload_entries, {"ImageLab.exe", "Uninstall.exe"})
    build_go(ROOT / "windows_installer" / "installer", installer_path, gui=False)

    source_entries = [
        (path.relative_to(ROOT).as_posix(), path.read_bytes())
        for path in ROOT.rglob("*") if source_file(path)
    ]
    archive(source_zip, source_entries)

    with zipfile.ZipFile(payload_path) as archive_file:
        bad_payload = archive_file.testzip()
        payload_names = set(archive_file.namelist())
    with zipfile.ZipFile(source_zip) as archive_file:
        bad_source = archive_file.testzip()
        source_count = len(archive_file.namelist())

    required = {
        "ImageLab.exe", "Uninstall.exe", "bootstrap.py", "requirements.txt",
        "app/config.py", "app/main.py", "app/release_selftest.py",
        "app/static/index.html", "app/static/app.js", "app/static/styles.css",
        "models/manifest.json",
    }
    missing = sorted(required - payload_names)
    pe = pe_info(installer_path)
    if missing or bad_payload or bad_source or not all(pe[key] for key in ("mz", "pe", "machine_x64", "pe32_plus")):
        raise RuntimeError(f"candidate package verification failed: missing={missing}, payload_bad={bad_payload}, source_bad={bad_source}, pe={pe}")

    candidate = {
        "schema": 1,
        "status": "PASS",
        "identity": identity,
        "installer": {
            "path": str(installer_path),
            "name": installer_path.name,
            "sha256": sha256(installer_path),
            "size_bytes": installer_path.stat().st_size,
            "pe": pe,
        },
        "payload": {
            "path": str(payload_path),
            "sha256": sha256(payload_path),
            "entries": len(payload_names),
            "crc_ok": bad_payload is None,
            "missing_required": missing,
        },
        "source": {
            "path": str(source_zip),
            "sha256": sha256(source_zip),
            "entries": source_count,
            "crc_ok": bad_source is None,
        },
    }
    manifest_path = output_dir / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), "utf-8")
    (output_dir / "installer-sha256.txt").write_text(f"{candidate['installer']['sha256']}  {installer_path.name}\n", "utf-8")
    print(json.dumps(candidate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
