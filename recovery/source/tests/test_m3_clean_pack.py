from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.ai.model_manager import ModelManager, ModelPackError
from app.ai.providers import PRODUCTION_BUILTIN_PROVIDER, production_provider_registry
import app.ai.registry as registry_module
from app.ai.registry import AIModelRegistry, EXPECTED_MANIFEST_SHA256, EXPECTED_MODEL_PACK_SHA256
from app.config import settings


MODELS = Path(__file__).resolve().parents[1] / "models"
V2_IDS = {
    "pixel_subject", "pixel_print", "content_classifier", "quality_risk",
    "restoration_profile", "tiny_restorer", "halftone_recommender",
    "vector_recommender", "export_recommender", "size_assistant", "qa_anomaly",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_clean_pack_is_exact_trusted_production_pack() -> None:
    assert _sha(MODELS / "model-pack.json") == EXPECTED_MODEL_PACK_SHA256
    assert _sha(MODELS / "manifest.json") == EXPECTED_MANIFEST_SHA256
    pack = json.loads((MODELS / "model-pack.json").read_text("utf-8"))
    manifest = json.loads((MODELS / "manifest.json").read_text("utf-8"))
    assert pack["pack_id"] == "imagelab-builtin-clean"
    assert pack["version"] == "2.0.0"
    assert manifest["version"] == "2.0.0"
    assert {item["id"] for item in manifest["models"]} == V2_IDS
    assert all(item["version"] == "2.0.0" and item["filename"].endswith("_v2.json") for item in manifest["models"])


def test_clean_pack_has_separate_verified_commercial_code_and_weights_licenses() -> None:
    pack = json.loads((MODELS / "model-pack.json").read_text("utf-8"))
    for key, filename in (("code_license", "LICENSE-CODE-MIT-0.txt"), ("weights_license", "LICENSE-WEIGHTS-MIT-0.txt")):
        item = pack[key]
        assert item["identifier"] == "MIT-0"
        assert item["commercial_use"] == "allowed"
        assert item["verified"] is True
        assert Path(item["evidence"]).name == filename
        assert (MODELS / item["evidence"]).is_file()


def test_clean_pack_provider_is_local_cpu_and_network_disabled() -> None:
    provider = PRODUCTION_BUILTIN_PROVIDER
    assert provider.provider_id == "builtin-numpy-local"
    assert provider.runtime == "numpy-linear-ml"
    assert provider.local_only is True
    assert provider.allows_network is False
    assert provider.supports_cpu is True
    assert provider.supports_gpu is False
    assert provider.hardware.min_ram_mb == 512
    assert provider.hardware.min_vram_mb == 0
    assert provider.hardware.min_disk_mb == 32
    assert provider.hardware.max_runtime_seconds == 60


def test_model_manager_validates_current_pack_and_health_contract(tmp_path: Path) -> None:
    manager = ModelManager(tmp_path / "installed", production_provider_registry())
    manifest = manager.load_manifest(MODELS)
    assert manifest.pack_id == "imagelab-builtin-clean"
    assert manifest.version == "2.0.0"
    assert manifest.code_license.verified is True
    assert manifest.weights_license.verified is True
    assert manifest.provider_id == "builtin-numpy-local"
    assert manifest.provider_runtime == "numpy-linear-ml"
    assert manifest.security_review_evidence == "provenance/security-review.json"
    assert manifest.binary_provenance == "no_native_binary:provenance/security-review.json"


def test_runtime_registry_loads_only_clean_v2_models() -> None:
    registry = AIModelRegistry()
    health = registry.health()
    assert health["version"] == "2.0.0"
    assert {item["id"] for item in health["models"]} == V2_IDS
    assert all(item["version"] == "2.0.0" for item in health["models"])


def test_legacy_v1_weights_are_absent() -> None:
    assert not list(MODELS.glob("*_v1.json"))


def test_generator_and_sbom_are_sha_bound() -> None:
    pack = json.loads((MODELS / "model-pack.json").read_text("utf-8"))
    bound = {item["path"]: item for item in pack["files"]}
    for rel in ("provenance/train_builtin_ai_v2.py", "sbom.json", "provenance/security-review.json", "provenance/license-verification.json"):
        assert rel in bound
        path = MODELS / rel
        assert path.stat().st_size == bound[rel]["size"]
        assert _sha(path) == bound[rel]["sha256"]
    sbom = json.loads((MODELS / "sbom.json").read_text("utf-8"))
    assert sbom["specVersion"] == "1.5"


def test_pack_policy_forbids_hidden_network_and_checksum_bypass() -> None:
    pack = json.loads((MODELS / "model-pack.json").read_text("utf-8"))
    policy = pack["install_policy"]
    assert policy == {
        "checksum_bypass": False,
        "hidden_cloud_fallback": False,
        "offline_only": True,
        "runtime_auto_download": False,
        "silent_telemetry": False,
    }


def test_tampered_model_is_blocked_before_activation(tmp_path: Path) -> None:
    copy = tmp_path / "pack"
    shutil.copytree(MODELS, copy)
    target = copy / "pixel_subject_v2.json"
    target.write_bytes(target.read_bytes() + b"\n")
    manager = ModelManager(tmp_path / "installed", production_provider_registry())
    with pytest.raises(ModelPackError, match="(Size mismatch|SHA-256 mismatch)"):
        manager.load_manifest(copy)


def test_tampered_pack_manifest_is_rejected_by_runtime_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copy = tmp_path / "models"
    shutil.copytree(MODELS, copy)
    pack = copy / "model-pack.json"
    pack.write_bytes(pack.read_bytes() + b"\n")
    runtime = replace(settings, ai_model_dir=copy)
    monkeypatch.setattr(registry_module, "settings", runtime)
    with pytest.raises(Exception, match="доверенный SHA-256"):
        AIModelRegistry()
