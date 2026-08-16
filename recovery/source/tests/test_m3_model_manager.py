from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.ai.model_manager import ModelManager, ModelPackError
from app.ai.providers import HardwarePolicy, ProviderContractError, ProviderDescriptor, ProviderRegistry


POLICY = HardwarePolicy(
    min_ram_mb=512,
    min_vram_mb=0,
    min_disk_mb=32,
    max_runtime_seconds=60,
    cpu_required=True,
    gpu_optional=True,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider() -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id="test-local",
        runtime="test-runtime",
        tasks=("segmentation", "restoration"),
        hardware=POLICY,
        local_only=True,
        allows_network=False,
        supports_cpu=True,
        supports_gpu=False,
    )


def _build_pack(root: Path, version: str = "1.0.0", *, verified: bool = True) -> Path:
    pack = root / f"pack-{version}"
    pack.mkdir(parents=True)
    (pack / "weights").mkdir()
    (pack / "weights" / "model.bin").write_bytes((f"model-{version}" * 64).encode("utf-8"))
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [{"name": "test-model", "version": version}],
    }
    (pack / "sbom.json").write_text(json.dumps(sbom, sort_keys=True), encoding="utf-8")
    files = []
    for rel in ("weights/model.bin", "sbom.json"):
        path = pack / rel
        files.append({"path": rel, "sha256": _sha(path), "size": path.stat().st_size})
    license_record = {
        "identifier": "TEST-OPEN-LICENSE",
        "evidence": "fixture://verified-license",
        "commercial_use": "allowed",
        "attribution": "NONE_REQUIRED_FOR_FIXTURE",
        "verified": verified,
    }
    manifest = {
        "schema": 1,
        "pack_id": "fixture-pack",
        "version": version,
        "source": {"repository": "fixture://repo", "revision": f"fixture-{version}"},
        "provider": {"id": "test-local", "runtime": "test-runtime", "tasks": ["segmentation"]},
        "nested_dependencies": [],
        "binary_provenance": {"kind": "no_native_binary", "evidence": "fixture://python-json-only"},
        "security_review": {"status": "pass", "evidence": "fixture://security-review"},
        "windows": {"compatible": True, "unicode_paths": True, "spaces_paths": True, "long_paths": "bounded"},
        "code_license": license_record,
        "weights_license": license_record,
        "files": files,
        "sbom": {"path": "sbom.json", "sha256": _sha(pack / "sbom.json")},
        "install_policy": {
            "offline_only": True,
            "runtime_auto_download": False,
            "hidden_cloud_fallback": False,
            "checksum_bypass": False,
            "silent_telemetry": False,
        },
        "hardware": {
            "min_ram_mb": POLICY.min_ram_mb,
            "min_vram_mb": POLICY.min_vram_mb,
            "min_disk_mb": POLICY.min_disk_mb,
            "max_runtime_seconds": POLICY.max_runtime_seconds,
            "cpu_required": POLICY.cpu_required,
            "gpu_optional": POLICY.gpu_optional,
        },
        "rollback": {"strategy": "previous_active_pack"},
    }
    (pack / "model-pack.json").write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    return pack


def _manager(root: Path) -> ModelManager:
    return ModelManager(root, ProviderRegistry([_provider()]))


def test_valid_pack_installs_and_health_is_offline(tmp_path: Path) -> None:
    source = _build_pack(tmp_path / "sources")
    manager = _manager(tmp_path / "installed")
    health = manager.install_from_directory(source)
    assert health["status"] == "ready"
    assert health["active"] == "fixture-pack@1.0.0"
    assert health["provider"] == "test-local"
    assert health["code_license_verified"] is True
    assert health["weights_license_verified"] is True
    assert health["network_policy"] == "offline_only"


@pytest.mark.parametrize("license_field", ["code_license", "weights_license"])
def test_unverified_code_and_weights_licenses_fail_separately(tmp_path: Path, license_field: str) -> None:
    source = _build_pack(tmp_path / "sources")
    raw = json.loads((source / "model-pack.json").read_text("utf-8"))
    raw[license_field]["verified"] = False
    (source / "model-pack.json").write_text(json.dumps(raw), encoding="utf-8")
    install_root = tmp_path / "installed"
    with pytest.raises(ModelPackError, match="license must be verified"):
        _manager(install_root).install_from_directory(source)
    assert not (install_root / "state.json").exists()
    assert not (install_root / "packs").exists()


def test_bad_hash_fails_closed_without_active_change(tmp_path: Path) -> None:
    source = _build_pack(tmp_path / "sources")
    (source / "weights" / "model.bin").write_bytes(b"tampered")
    install_root = tmp_path / "installed"
    with pytest.raises(ModelPackError, match="Size mismatch|SHA-256 mismatch"):
        _manager(install_root).install_from_directory(source)
    assert not (install_root / "state.json").exists()


def test_path_traversal_duplicate_and_symlink_are_rejected(tmp_path: Path) -> None:
    source = _build_pack(tmp_path / "sources")
    raw = json.loads((source / "model-pack.json").read_text("utf-8"))
    raw["files"][0]["path"] = "../escape.bin"
    (source / "model-pack.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ModelPackError, match="Unsafe model-pack path"):
        _manager(tmp_path / "installed").install_from_directory(source)

    source2 = _build_pack(tmp_path / "sources2")
    raw2 = json.loads((source2 / "model-pack.json").read_text("utf-8"))
    raw2["files"].append(dict(raw2["files"][0]))
    (source2 / "model-pack.json").write_text(json.dumps(raw2), encoding="utf-8")
    with pytest.raises(ModelPackError, match="Duplicate"):
        _manager(tmp_path / "installed2").install_from_directory(source2)

    source3 = _build_pack(tmp_path / "sources3")
    external = tmp_path / "outside.bin"
    external.write_bytes(b"outside")
    model_file = source3 / "weights" / "model.bin"
    model_file.unlink()
    model_file.symlink_to(external)
    with pytest.raises(ModelPackError, match="missing or unsafe"):
        _manager(tmp_path / "installed3").install_from_directory(source3)


def test_hidden_network_or_checksum_bypass_policy_is_rejected(tmp_path: Path) -> None:
    for field in ("runtime_auto_download", "hidden_cloud_fallback", "checksum_bypass", "silent_telemetry"):
        source = _build_pack(tmp_path / field)
        raw = json.loads((source / "model-pack.json").read_text("utf-8"))
        raw["install_policy"][field] = True
        (source / "model-pack.json").write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ModelPackError, match="offline/no-hidden-network"):
            _manager(tmp_path / f"installed-{field}").install_from_directory(source)


def test_atomic_update_and_rollback_preserve_pack_bytes(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    first = _build_pack(sources, "1.0.0")
    second = _build_pack(sources, "1.1.0")
    manager = _manager(tmp_path / "installed")
    first_sha = _sha(first / "weights" / "model.bin")
    second_sha = _sha(second / "weights" / "model.bin")
    manager.install_from_directory(first)
    manager.install_from_directory(second)
    assert manager.health()["active"] == "fixture-pack@1.1.0"
    assert _sha(tmp_path / "installed/packs/fixture-pack/1.0.0/weights/model.bin") == first_sha
    assert _sha(tmp_path / "installed/packs/fixture-pack/1.1.0/weights/model.bin") == second_sha
    result = manager.rollback()
    assert result["active"] == "fixture-pack@1.0.0"
    assert result["rollback_to"] == "fixture-pack@1.0.0"
    assert _sha(tmp_path / "installed/packs/fixture-pack/1.0.0/weights/model.bin") == first_sha


def test_hardware_policy_must_match_provider_contract(tmp_path: Path) -> None:
    source = _build_pack(tmp_path / "sources")
    raw = json.loads((source / "model-pack.json").read_text("utf-8"))
    raw["hardware"]["min_ram_mb"] += 1
    (source / "model-pack.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ModelPackError, match="hardware policy"):
        _manager(tmp_path / "installed").install_from_directory(source)


def test_sbom_binding_is_mandatory_and_exact(tmp_path: Path) -> None:
    source = _build_pack(tmp_path / "sources")
    raw = json.loads((source / "model-pack.json").read_text("utf-8"))
    raw["sbom"]["sha256"] = "0" * 64
    (source / "model-pack.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ModelPackError, match="SBOM binding mismatch"):
        _manager(tmp_path / "installed").install_from_directory(source)


@pytest.mark.parametrize("field", ["nested_dependencies", "binary_provenance", "security_review", "windows"])
def test_supply_chain_declarations_are_mandatory(tmp_path: Path, field: str) -> None:
    source = _build_pack(tmp_path / f"sources-{field}")
    raw = json.loads((source / "model-pack.json").read_text("utf-8"))
    raw.pop(field)
    (source / "model-pack.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ModelPackError):
        _manager(tmp_path / f"installed-{field}").install_from_directory(source)


def test_provider_runtime_must_match_pack_contract(tmp_path: Path) -> None:
    source = _build_pack(tmp_path / "sources-runtime")
    raw = json.loads((source / "model-pack.json").read_text("utf-8"))
    raw["provider"]["runtime"] = "silent-substitute-runtime"
    (source / "model-pack.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ModelPackError, match="runtime does not match"):
        _manager(tmp_path / "installed-runtime").install_from_directory(source)


def test_provider_registry_rejects_cloud_provider_and_unknown_task() -> None:
    with pytest.raises(ProviderContractError, match="local-only"):
        ProviderDescriptor(
            provider_id="cloud",
            runtime="http",
            tasks=("segmentation",),
            hardware=POLICY,
            local_only=False,
            allows_network=True,
            supports_cpu=True,
        )
    registry = ProviderRegistry([_provider()])
    with pytest.raises(ProviderContractError, match="does not support"):
        registry.require_task("test-local", "vector")


def test_unrelated_directory_is_never_mutated(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    marker = unrelated / "keep.bin"
    marker.write_bytes(b"immutable")
    before = _sha(marker)
    source = _build_pack(tmp_path / "sources")
    _manager(tmp_path / "installed").install_from_directory(source)
    assert _sha(marker) == before
