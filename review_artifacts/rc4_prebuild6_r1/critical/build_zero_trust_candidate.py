from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from release_capability_preflight import assert_source_test_runtime_capability
from source_release_gate import compute_source_tree, run_full_source_gate
from l3_dependency_intake import compute_runtime_tree

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_PILLOW_HEIF_REL = Path("vendor/wheels/pillow_heif-1.6.0-cp313-cp313-win_amd64.whl")
BUNDLED_PILLOW_HEIF_SHA256 = "ed1e176cb73d245f58a2134129e8673023aefba89ff566fd65467048e4390ad5"
BUNDLED_PSD_TOOLS_REL = Path("vendor/wheels/psd_tools-1.19.0-cp313-cp313-win_amd64.whl")
BUNDLED_PSD_TOOLS_SHA256 = "da103a304a23842aaddd5b99563a7e4f5660376b713f9fc70f38dba49ab8c20a"
BUNDLED_STET_EXE_REL = Path("vendor/tools/stet/stet.exe")
BUNDLED_STET_SHA256 = "3ad883e898386fba1b4e81a182c32da9ce437b4c5a2322530788e6159c76d30f"
BUNDLED_STET_LINUX_REL = Path("vendor/tools/stet/stet-linux-x64")
BUNDLED_STET_LINUX_SHA256 = "9561cf9f4cb887c9cdf4213cf13fe24924d67d17625ca6126e2278d3e53fb4fa"
FIXED_TIME = (2026, 7, 24, 0, 0, 0)
EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", ".git", ".slu_backup", ".slu_m6_build",
    ".plateau_build", ".core_recovery_build", ".update_lock_build", ".update_lock_backup",
    ".zero_trust_build", "dist", ".venv", "venv", ".verified_l3_runtime",
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


def payload_file(path: Path, root: Path = ROOT) -> bool:
    root = root.resolve()
    rel = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in rel.parts) or path.suffix in {".pyc", ".pyo"}:
        return False
    return path.is_file() and (
        (rel.parts and rel.parts[0] in {"app", "models"})
        or rel.parts[:2] == ("vendor", "wheels")
        or (rel.parts[:2] == ("vendor", "tools") and rel != BUNDLED_STET_LINUX_REL)
        or rel in {Path("bootstrap.py"), Path("requirements.txt"), Path("README.md")}
    )


def source_file(path: Path, root: Path = ROOT) -> bool:
    root = root.resolve()
    rel = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.suffix in {".pyc", ".pyo"} or path.name == ".coverage":
        return False
    if path.suffix == ".exe" and rel != BUNDLED_STET_EXE_REL:
        return False
    if rel.parts and rel.parts[0] == "data":
        return False
    if rel == Path("windows_installer/installer/payload.zip"):
        return False
    if rel.parts and rel.parts[0].startswith("evidence"):
        return False
    return path.is_file()


def copy_source_snapshot(source_root: Path, snapshot_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    snapshot_root = snapshot_root.resolve()
    before = compute_source_tree(source_root)
    for path in source_root.rglob("*"):
        if not source_file(path, source_root):
            continue
        rel = path.relative_to(source_root)
        target = snapshot_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    after = compute_source_tree(source_root)
    snapshot = compute_source_tree(snapshot_root)
    if before != after or snapshot != before:
        raise RuntimeError(
            f"source changed while creating tested snapshot: before={before}, after={after}, snapshot={snapshot}"
        )
    return snapshot


def assert_build_inputs_unchanged(*, build_root: Path, runtime_dir: Path, approved_source_tree: dict[str, object], approved_runtime_tree: dict[str, object]) -> None:
    source_now = compute_source_tree(build_root)
    runtime_now = compute_runtime_tree(runtime_dir)
    if source_now != approved_source_tree:
        raise RuntimeError(f"tested source snapshot changed during build: expected {approved_source_tree}, got {source_now}")
    if runtime_now != approved_runtime_tree:
        raise RuntimeError(f"verified runtime changed during build: expected {approved_runtime_tree}, got {runtime_now}")


def cleanup_candidate_outputs(output_dir: Path, label: str) -> None:
    safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
    names = {f"ImageLab_by_LarannA_{safe_label}_Setup_x64.exe", f"ImageLab_by_LarannA_{safe_label}_SOURCE.zip", "candidate-manifest.json", "installer-sha256.txt"}
    for name in names:
        path = output_dir / name
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except OSError:
            pass


def pe_info(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 0x40:
        raise RuntimeError("installer is too small to be a PE file")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    return {"mz": data[:2] == b"MZ", "pe": data[offset:offset + 4] == b"PE\0\0", "machine_x64": struct.unpack_from("<H", data, offset + 4)[0] == 0x8664, "pe32_plus": struct.unpack_from("<H", data, offset + 24)[0] == 0x20B, "size_bytes": len(data)}


def build_go(source: Path, output: Path, *, gui: bool) -> None:
    # GO111MODULE=off embeds an absolute pseudo-import path when building a package
    # from an arbitrary temporary directory. Build from a stable GOPATH import path
    # so identical source bytes produce identical Windows binaries across snapshots.
    with tempfile.TemporaryDirectory(prefix="imagelab-go-build-") as tmp:
        gopath = Path(tmp)
        package_dir = gopath / "src" / "imagelab" / source.name
        shutil.copytree(source, package_dir)
        env = dict(os.environ)
        env.update({"GOPATH": str(gopath), "GO111MODULE": "off", "GOOS": "windows", "GOARCH": "amd64"})
        flags = "-s -w -buildid=" + (" -H=windowsgui" if gui else "")
        command = ["go", "build", "-trimpath", "-ldflags", flags, "-o", str(output), "."]
        result = subprocess.run(command, cwd=package_dir, env=env, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(f"Go build failed for {source}:\n{result.stdout}\n{result.stderr}")


def read_identity(root: Path = ROOT) -> dict[str, str]:
    root = root.resolve()
    code = "import json; from app.config import settings; print(json.dumps({'app':str(settings.app_name),'version':str(settings.app_version),'build_id':str(settings.build_id)}))"
    env = dict(os.environ); env["PYTHONPATH"] = str(root)
    completed = subprocess.run([sys.executable, "-P", "-c", code], cwd=root.parent, env=env, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(f"failed to read build identity from tested snapshot: {completed.stderr}")
    return json.loads(completed.stdout.strip())


def _verify_pinned_file(build_root: Path, rel: Path, expected_sha: str, label: str) -> Path:
    path = build_root / rel
    if not path.is_file():
        raise RuntimeError(f"mandatory {label} missing: {path}")
    actual = sha256(path)
    if actual != expected_sha:
        raise RuntimeError(f"{label} SHA-256 mismatch: expected {expected_sha}, got {actual}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=Path, default=ROOT / "dist"); parser.add_argument("--label", default="ZERO_TRUST"); parser.add_argument("--l3-runtime", type=Path); args = parser.parse_args()
    if args.l3_runtime is None:
        assert_source_test_runtime_capability(); raise RuntimeError("verified L3 runtime is required before candidate build")
    runtime_dir = args.l3_runtime.resolve(); assert_source_test_runtime_capability(extra_runtime=runtime_dir)
    with tempfile.TemporaryDirectory(prefix="imagelab-build-snapshot-") as tmp:
        temp_root = Path(tmp); build_root = temp_root / "source"; snapshot_tree = copy_source_snapshot(ROOT, build_root); source_gate_receipt = temp_root / "source-gate-receipt.json"
        gate = run_full_source_gate(root=build_root, runtime_dir=runtime_dir, receipt_path=source_gate_receipt, expected_source_tree=snapshot_tree)
        approved_source_tree = dict(gate["source_tree"]); approved_runtime_tree = dict(gate["runtime_tree"])
        if approved_source_tree != snapshot_tree: raise RuntimeError(f"source gate approved a tree different from the immutable snapshot: snapshot={snapshot_tree}, approved={approved_source_tree}")
        if compute_source_tree(build_root) != snapshot_tree: raise RuntimeError("tested source snapshot changed after source gate")
        output_dir = args.output_dir.resolve(); output_parent = output_dir.parent; output_parent.mkdir(parents=True, exist_ok=True); safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.label)
        final_installer_path = output_dir / f"ImageLab_by_LarannA_{safe_label}_Setup_x64.exe"; final_source_zip = output_dir / f"ImageLab_by_LarannA_{safe_label}_SOURCE.zip"; final_manifest_path = output_dir / "candidate-manifest.json"; final_sha_path = output_dir / "installer-sha256.txt"
        try:
            with tempfile.TemporaryDirectory(prefix=".imagelab-private-candidate-", dir=output_parent) as private_tmp:
                private_stage = Path(private_tmp)
                try: private_stage.chmod(0o700)
                except OSError: pass
                installer_path = private_stage / final_installer_path.name; source_zip = private_stage / final_source_zip.name; manifest_path = private_stage / final_manifest_path.name; sha_path = private_stage / final_sha_path.name; build_dir = temp_root / "build"; build_dir.mkdir(parents=True)
                _verify_pinned_file(build_root, BUNDLED_PILLOW_HEIF_REL, BUNDLED_PILLOW_HEIF_SHA256, "bundled pillow-heif wheel"); _verify_pinned_file(build_root, BUNDLED_PSD_TOOLS_REL, BUNDLED_PSD_TOOLS_SHA256, "bundled psd-tools wheel"); _verify_pinned_file(build_root, BUNDLED_STET_EXE_REL, BUNDLED_STET_SHA256, "bundled Stet EPS renderer"); _verify_pinned_file(build_root, BUNDLED_STET_LINUX_REL, BUNDLED_STET_LINUX_SHA256, "source-only Linux Stet EPS renderer")
                identity = read_identity(build_root); payload_path = build_root / "windows_installer" / "installer" / "payload.zip"; launcher = build_dir / "ImageLab.exe"; uninstaller = build_dir / "Uninstall.exe"; build_go(build_root / "windows_installer" / "launcher", launcher, gui=True); build_go(build_root / "windows_installer" / "uninstaller", uninstaller, gui=True)
                payload_entries = [("ImageLab.exe", launcher.read_bytes()), ("Uninstall.exe", uninstaller.read_bytes())]; payload_entries.extend((path.relative_to(build_root).as_posix(), path.read_bytes()) for path in build_root.rglob("*") if payload_file(path, build_root)); archive(payload_path, payload_entries, {"ImageLab.exe", "Uninstall.exe"}); build_go(build_root / "windows_installer" / "installer", installer_path, gui=False)
                source_entries = [(path.relative_to(build_root).as_posix(), path.read_bytes()) for path in build_root.rglob("*") if source_file(path, build_root)]; archive(source_zip, source_entries, {"vendor/tools/stet/stet-linux-x64"})
                with zipfile.ZipFile(payload_path) as archive_file: bad_payload = archive_file.testzip(); payload_names = set(archive_file.namelist())
                with zipfile.ZipFile(source_zip) as archive_file: bad_source = archive_file.testzip(); source_names = set(archive_file.namelist()); source_count = len(source_names)
                required = {"ImageLab.exe", "Uninstall.exe", "bootstrap.py", "requirements.txt", "app/config.py", "app/main.py", "app/release_selftest.py", "app/static/index.html", "app/static/app.js", "app/static/styles.css", "models/manifest.json", "vendor/tools/stet/stet.exe", "vendor/tools/stet/LICENSE-APACHE", "vendor/tools/stet/LICENSE-MIT"}; missing = sorted(required - payload_names); source_required = {"vendor/tools/stet/stet-linux-x64"}; missing_source = sorted(source_required - source_names)
                if "vendor/tools/stet/stet-linux-x64" in payload_names: raise RuntimeError("source-only Linux Stet renderer leaked into Windows payload")
                pe = pe_info(installer_path)
                if missing or missing_source or bad_payload or bad_source or not all(pe[key] for key in ("mz", "pe", "machine_x64", "pe32_plus")): raise RuntimeError(f"candidate package verification failed: missing={missing}, missing_source={missing_source}, payload_bad={bad_payload}, source_bad={bad_source}, pe={pe}")
                installer_sha = sha256(installer_path); source_sha = sha256(source_zip)
                candidate = {"schema": 3, "status": "PASS", "identity": identity, "source_gate": gate, "installer": {"path": str(final_installer_path), "name": final_installer_path.name, "sha256": installer_sha, "size_bytes": installer_path.stat().st_size, "pe": pe}, "payload": {"path": str(payload_path), "sha256": sha256(payload_path), "entries": len(payload_names), "crc_ok": bad_payload is None, "missing_required": missing}, "source": {"path": str(final_source_zip), "sha256": source_sha, "entries": source_count, "crc_ok": bad_source is None, "tested_snapshot_tree": approved_source_tree}}
                assert_build_inputs_unchanged(build_root=build_root, runtime_dir=runtime_dir, approved_source_tree=approved_source_tree, approved_runtime_tree=approved_runtime_tree)
                manifest_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), "utf-8"); sha_path.write_text(f"{installer_sha}  {final_installer_path.name}\n", "utf-8")
                output_dir.mkdir(parents=True, exist_ok=True); os.replace(installer_path, final_installer_path); os.replace(source_zip, final_source_zip); os.replace(manifest_path, final_manifest_path); os.replace(sha_path, final_sha_path); print(json.dumps(candidate, ensure_ascii=False, indent=2)); return 0
        except Exception:
            cleanup_candidate_outputs(output_dir, args.label); raise


if __name__ == "__main__":
    raise SystemExit(main())
