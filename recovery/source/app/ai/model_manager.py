from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.ai.providers import HardwarePolicy, ProviderContractError, ProviderDescriptor, ProviderRegistry


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_PACK_FILES = 10_000
_MAX_PACK_BYTES = 64 * 1024 * 1024 * 1024


class ModelPackError(RuntimeError):
    """Fail-closed M3 model-pack validation/install error."""


@dataclass(frozen=True)
class LicenseEvidence:
    identifier: str
    evidence: str
    commercial_use: str
    attribution: str
    verified: bool

    @classmethod
    def parse(cls, raw: Any, label: str) -> "LicenseEvidence":
        if not isinstance(raw, dict):
            raise ModelPackError(f"{label} license evidence is required")
        value = cls(
            identifier=str(raw.get("identifier", "")).strip(),
            evidence=str(raw.get("evidence", "")).strip(),
            commercial_use=str(raw.get("commercial_use", "")).strip().lower(),
            attribution=str(raw.get("attribution", "")).strip(),
            verified=raw.get("verified") is True,
        )
        if not value.identifier or not value.evidence:
            raise ModelPackError(f"{label} license identifier/evidence is required")
        if not value.verified:
            raise ModelPackError(f"{label} license must be verified before activation")
        if value.commercial_use != "allowed":
            raise ModelPackError(f"{label} commercial use must be explicitly allowed")
        if not value.attribution:
            raise ModelPackError(f"{label} attribution policy is required")
        return value


@dataclass(frozen=True)
class PackFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ModelPackManifest:
    pack_id: str
    version: str
    source_repository: str
    source_revision: str
    provider_id: str
    provider_runtime: str
    tasks: tuple[str, ...]
    nested_dependencies: tuple[dict[str, str], ...]
    binary_provenance: str
    security_review_evidence: str
    windows_path_policy: str
    code_license: LicenseEvidence
    weights_license: LicenseEvidence
    files: tuple[PackFile, ...]
    sbom_path: str
    sbom_sha256: str
    hardware: HardwarePolicy
    rollback_strategy: str

    @staticmethod
    def _safe_relpath(raw: Any, label: str) -> str:
        if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
            raise ModelPackError(f"Invalid {label} path")
        path = PurePosixPath(raw)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise ModelPackError(f"Unsafe {label} path")
        return path.as_posix()

    @classmethod
    def parse(cls, raw: Any) -> "ModelPackManifest":
        if not isinstance(raw, dict) or raw.get("schema") != 1:
            raise ModelPackError("Unsupported model-pack manifest schema")
        pack_id = str(raw.get("pack_id", "")).strip()
        version = str(raw.get("version", "")).strip()
        if not _ID_RE.fullmatch(pack_id) or not _ID_RE.fullmatch(version):
            raise ModelPackError("Invalid pack_id/version")

        source = raw.get("source")
        if not isinstance(source, dict):
            raise ModelPackError("Source provenance is required")
        source_repository = str(source.get("repository", "")).strip()
        source_revision = str(source.get("revision", "")).strip()
        if not source_repository or not source_revision:
            raise ModelPackError("Exact source repository/revision is required")

        provider = raw.get("provider")
        if not isinstance(provider, dict):
            raise ModelPackError("Provider contract is required")
        provider_id = str(provider.get("id", "")).strip()
        provider_runtime = str(provider.get("runtime", "")).strip()
        tasks_raw = provider.get("tasks")
        if not provider_id or not provider_runtime or not isinstance(tasks_raw, list) or not tasks_raw:
            raise ModelPackError("Provider id/runtime/tasks are required")
        tasks = tuple(str(item).strip() for item in tasks_raw)
        if any(not item for item in tasks) or len(set(tasks)) != len(tasks):
            raise ModelPackError("Provider tasks must be non-empty and unique")

        dependencies_raw = raw.get("nested_dependencies")
        if not isinstance(dependencies_raw, list):
            raise ModelPackError("nested_dependencies declaration is required")
        dependencies: list[dict[str, str]] = []
        for item in dependencies_raw:
            if not isinstance(item, dict):
                raise ModelPackError("Invalid nested dependency record")
            required = {
                "name": str(item.get("name", "")).strip(),
                "version": str(item.get("version", "")).strip(),
                "source": str(item.get("source", "")).strip(),
                "sha256": str(item.get("sha256", "")).strip().lower(),
                "license": str(item.get("license", "")).strip(),
            }
            if not all(required.values()) or not _SHA256_RE.fullmatch(required["sha256"]):
                raise ModelPackError("Incomplete nested dependency provenance")
            dependencies.append(required)

        binary = raw.get("binary_provenance")
        if not isinstance(binary, dict):
            raise ModelPackError("Binary provenance is required")
        binary_kind = str(binary.get("kind", "")).strip()
        binary_evidence = str(binary.get("evidence", "")).strip()
        if binary_kind not in {"source_generated", "verified_prebuilt", "no_native_binary"} or not binary_evidence:
            raise ModelPackError("Binary provenance must be explicit and evidence-backed")
        binary_provenance = f"{binary_kind}:{binary_evidence}"

        security = raw.get("security_review")
        if not isinstance(security, dict) or str(security.get("status", "")).strip().lower() != "pass":
            raise ModelPackError("Security/vulnerability review PASS is required")
        security_review_evidence = str(security.get("evidence", "")).strip()
        if not security_review_evidence:
            raise ModelPackError("Security/vulnerability review evidence is required")

        windows = raw.get("windows")
        if not isinstance(windows, dict) or windows.get("compatible") is not True:
            raise ModelPackError("Windows compatibility declaration is required")
        if windows.get("unicode_paths") is not True or windows.get("spaces_paths") is not True:
            raise ModelPackError("Windows Unicode/spaces path support must be declared")
        windows_path_policy = str(windows.get("long_paths", "")).strip().lower()
        if windows_path_policy not in {"supported", "bounded"}:
            raise ModelPackError("Windows long-path policy must be supported or bounded")

        policy = raw.get("install_policy")
        if not isinstance(policy, dict):
            raise ModelPackError("Install policy is required")
        required_false = ("runtime_auto_download", "hidden_cloud_fallback", "checksum_bypass", "silent_telemetry")
        if policy.get("offline_only") is not True or any(policy.get(key) is not False for key in required_false):
            raise ModelPackError("Model pack violates offline/no-hidden-network policy")

        raw_files = raw.get("files")
        if not isinstance(raw_files, list) or not raw_files or len(raw_files) > _MAX_PACK_FILES:
            raise ModelPackError("Model-pack file list is invalid")
        files: list[PackFile] = []
        seen: set[str] = set()
        total = 0
        for item in raw_files:
            if not isinstance(item, dict):
                raise ModelPackError("Invalid model-pack file record")
            rel = cls._safe_relpath(item.get("path"), "model-pack")
            digest = str(item.get("sha256", "")).strip().lower()
            size = item.get("size")
            if rel in seen:
                raise ModelPackError(f"Duplicate model-pack path: {rel}")
            if not _SHA256_RE.fullmatch(digest):
                raise ModelPackError(f"Invalid SHA-256 for {rel}")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ModelPackError(f"Invalid size for {rel}")
            total += size
            if total > _MAX_PACK_BYTES:
                raise ModelPackError("Model pack exceeds bounded size")
            seen.add(rel)
            files.append(PackFile(rel, digest, size))

        sbom = raw.get("sbom")
        if not isinstance(sbom, dict):
            raise ModelPackError("SBOM binding is required")
        sbom_path = cls._safe_relpath(sbom.get("path"), "SBOM")
        sbom_sha256 = str(sbom.get("sha256", "")).strip().lower()
        if not _SHA256_RE.fullmatch(sbom_sha256):
            raise ModelPackError("Invalid SBOM SHA-256")
        if sbom_path not in seen:
            raise ModelPackError("SBOM must be part of the verified file set")

        hardware_raw = raw.get("hardware")
        if not isinstance(hardware_raw, dict):
            raise ModelPackError("Hardware policy is required")
        if not isinstance(hardware_raw.get("cpu_required"), bool) or not isinstance(hardware_raw.get("gpu_optional"), bool):
            raise ModelPackError("Hardware boolean policy fields are required")
        try:
            hardware = HardwarePolicy(
                min_ram_mb=hardware_raw.get("min_ram_mb"),
                min_vram_mb=hardware_raw.get("min_vram_mb"),
                min_disk_mb=hardware_raw.get("min_disk_mb"),
                max_runtime_seconds=hardware_raw.get("max_runtime_seconds"),
                cpu_required=hardware_raw["cpu_required"],
                gpu_optional=hardware_raw["gpu_optional"],
            )
        except ProviderContractError as exc:
            raise ModelPackError(str(exc)) from exc

        rollback = raw.get("rollback")
        if not isinstance(rollback, dict) or rollback.get("strategy") != "previous_active_pack":
            raise ModelPackError("Rollback strategy must be previous_active_pack")

        return cls(
            pack_id=pack_id,
            version=version,
            source_repository=source_repository,
            source_revision=source_revision,
            provider_id=provider_id,
            provider_runtime=provider_runtime,
            tasks=tasks,
            nested_dependencies=tuple(dependencies),
            binary_provenance=binary_provenance,
            security_review_evidence=security_review_evidence,
            windows_path_policy=windows_path_policy,
            code_license=LicenseEvidence.parse(raw.get("code_license"), "code"),
            weights_license=LicenseEvidence.parse(raw.get("weights_license"), "weights"),
            files=tuple(files),
            sbom_path=sbom_path,
            sbom_sha256=sbom_sha256,
            hardware=hardware,
            rollback_strategy="previous_active_pack",
        )


class ModelManager:
    MANIFEST_NAME = "model-pack.json"
    STATE_NAME = "state.json"

    def __init__(self, install_root: Path, providers: ProviderRegistry) -> None:
        self.install_root = Path(install_root)
        self.providers = providers

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelPackError(f"Invalid JSON: {path.name}") from exc
        if not isinstance(raw, dict):
            raise ModelPackError(f"JSON object required: {path.name}")
        return raw

    def load_manifest(self, source_dir: Path) -> ModelPackManifest:
        source_dir = Path(source_dir).resolve()
        manifest_path = source_dir / self.MANIFEST_NAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ModelPackError("model-pack.json is missing")
        manifest = ModelPackManifest.parse(self._load_json(manifest_path))
        self._verify_provider(manifest)
        self.verify_files(source_dir, manifest)
        return manifest

    def _verify_provider(self, manifest: ModelPackManifest) -> ProviderDescriptor:
        try:
            provider = self.providers.get(manifest.provider_id)
            for task in manifest.tasks:
                self.providers.require_task(manifest.provider_id, task)
        except ProviderContractError as exc:
            raise ModelPackError(str(exc)) from exc
        if provider.runtime != manifest.provider_runtime:
            raise ModelPackError("Pack runtime does not match provider contract")
        if provider.hardware != manifest.hardware:
            raise ModelPackError("Pack hardware policy does not match provider contract")
        return provider

    def verify_files(self, source_dir: Path, manifest: ModelPackManifest) -> None:
        source_dir = Path(source_dir).resolve()
        for item in manifest.files:
            candidate = source_dir / Path(*PurePosixPath(item.path).parts)
            cursor = candidate
            while cursor != source_dir:
                if cursor.is_symlink():
                    raise ModelPackError(f"Verified pack file missing or unsafe: {item.path}")
                cursor = cursor.parent
            path = candidate.resolve()
            try:
                path.relative_to(source_dir)
            except ValueError as exc:
                raise ModelPackError(f"Path escapes pack root: {item.path}") from exc
            if not path.is_file():
                raise ModelPackError(f"Verified pack file missing or unsafe: {item.path}")
            stat = path.stat()
            if stat.st_size != item.size:
                raise ModelPackError(f"Size mismatch: {item.path}")
            if self._sha256(path) != item.sha256:
                raise ModelPackError(f"SHA-256 mismatch: {item.path}")
        sbom = source_dir / Path(*PurePosixPath(manifest.sbom_path).parts)
        if self._sha256(sbom) != manifest.sbom_sha256:
            raise ModelPackError("SBOM binding mismatch")

    def _state_path(self) -> Path:
        return self.install_root / self.STATE_NAME

    def _read_state(self) -> dict[str, Any]:
        path = self._state_path()
        if not path.exists():
            return {"schema": 1, "active": None, "previous": None}
        raw = self._load_json(path)
        if raw.get("schema") != 1:
            raise ModelPackError("Unsupported model-manager state schema")
        for key in ("active", "previous"):
            value = raw.get(key)
            if value is not None and (not isinstance(value, str) or not value.startswith("packs/")):
                raise ModelPackError("Invalid model-manager state path")
        return raw

    def _write_state_atomic(self, state: dict[str, Any]) -> None:
        self.install_root.mkdir(parents=True, exist_ok=True)
        tmp = self.install_root / f".{self.STATE_NAME}.{uuid.uuid4().hex}.tmp"
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._state_path())
        finally:
            tmp.unlink(missing_ok=True)

    def install_from_directory(self, source_dir: Path) -> dict[str, Any]:
        source_dir = Path(source_dir).resolve()
        manifest = self.load_manifest(source_dir)  # license/hash/SBOM/provider checks happen before any activation
        self.install_root.mkdir(parents=True, exist_ok=True)
        packs_root = self.install_root / "packs" / manifest.pack_id
        target = packs_root / manifest.version
        relative_target = target.relative_to(self.install_root).as_posix()
        if target.exists():
            raise ModelPackError("Pack version is already installed")

        stage = self.install_root / f".staging-{uuid.uuid4().hex}"
        state_before = self._read_state()
        try:
            stage.mkdir(parents=False, exist_ok=False)
            shutil.copy2(source_dir / self.MANIFEST_NAME, stage / self.MANIFEST_NAME)
            for item in manifest.files:
                rel = Path(*PurePosixPath(item.path).parts)
                destination = stage / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_dir / rel, destination)
            staged = self.load_manifest(stage)
            if staged != manifest:
                raise ModelPackError("Staged manifest changed during installation")
            packs_root.mkdir(parents=True, exist_ok=True)
            os.replace(stage, target)
            next_state = {
                "schema": 1,
                "active": relative_target,
                "previous": state_before.get("active"),
            }
            try:
                self._write_state_atomic(next_state)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        return self.health()

    def rollback(self) -> dict[str, Any]:
        state = self._read_state()
        previous = state.get("previous")
        active = state.get("active")
        if not previous or not active:
            raise ModelPackError("No verified previous model pack is available for rollback")
        previous_dir = (self.install_root / previous).resolve()
        try:
            previous_dir.relative_to(self.install_root.resolve())
        except ValueError as exc:
            raise ModelPackError("Rollback path escapes install root") from exc
        manifest = self.load_manifest(previous_dir)
        self._write_state_atomic({"schema": 1, "active": previous, "previous": active})
        result = self.health()
        result["rollback_to"] = f"{manifest.pack_id}@{manifest.version}"
        return result

    def health(self) -> dict[str, Any]:
        state = self._read_state()
        active = state.get("active")
        if not active:
            return {"status": "empty", "active": None, "previous": state.get("previous")}
        active_dir = (self.install_root / active).resolve()
        try:
            active_dir.relative_to(self.install_root.resolve())
        except ValueError as exc:
            raise ModelPackError("Active pack path escapes install root") from exc
        manifest = self.load_manifest(active_dir)
        return {
            "status": "ready",
            "active": f"{manifest.pack_id}@{manifest.version}",
            "previous": state.get("previous"),
            "provider": manifest.provider_id,
            "tasks": list(manifest.tasks),
            "source_revision": manifest.source_revision,
            "provider_runtime": manifest.provider_runtime,
            "nested_dependency_count": len(manifest.nested_dependencies),
            "binary_provenance": manifest.binary_provenance,
            "security_review": "pass",
            "windows_path_policy": manifest.windows_path_policy,
            "code_license_verified": manifest.code_license.verified,
            "weights_license_verified": manifest.weights_license.verified,
            "sbom_sha256": manifest.sbom_sha256,
            "hardware": {
                "min_ram_mb": manifest.hardware.min_ram_mb,
                "min_vram_mb": manifest.hardware.min_vram_mb,
                "min_disk_mb": manifest.hardware.min_disk_mb,
                "max_runtime_seconds": manifest.hardware.max_runtime_seconds,
                "cpu_required": manifest.hardware.cpu_required,
                "gpu_optional": manifest.hardware.gpu_optional,
            },
            "network_policy": "offline_only",
        }
