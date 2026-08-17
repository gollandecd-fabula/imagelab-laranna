from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.ai.challengers import (
    DESIGN_CHANGE_CANDIDATE,
    DESIGN_CHANGE_PRESELECTED_WINNER,
    ChallengerContractError,
    ChallengerDescriptor,
    WinnerEvidence,
    frozen_m4_challengers,
    promotion_eligible,
    transform_design_candidate,
)


def _winner(**overrides: object) -> WinnerEvidence:
    values: dict[str, object] = {
        "benchmark_executed": True,
        "technical_contracts_pass": True,
        "independent_oracle_pass": True,
        "new_p0_p1": 0,
        "per_class_nonregression": True,
        "aggregate_improvement_pass": True,
        "resource_stability_pass": True,
        "supply_chain_pass": True,
    }
    values.update(overrides)
    return WinnerEvidence(**values)  # type: ignore[arg-type]


def test_exact_frozen_challenger_identities_and_design_lock() -> None:
    rows = {item.task: item for item in frozen_m4_challengers()}
    assert set(rows) == {"background", "restore", "vector"}
    assert rows["background"].package_sha256 == "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"
    assert rows["restore"].package_sha256 == "caf96d62999e741194a28b514eb6202c09a39edcd9ced730e3f784c424cc0653"
    assert rows["vector"].package_sha256 == "26fb07c440aa6dd0a9ac57a83db6ee2924ddf308bccf451e76b324bb61780dba"
    assert DESIGN_CHANGE_PRESELECTED_WINNER is None


def test_all_challengers_are_benchmark_only_and_network_disabled() -> None:
    for item in frozen_m4_challengers():
        assert item.benchmark_only is True
        assert item.runtime_auto_download is False
        assert item.hidden_cloud_fallback is False
        assert item.checksum_bypass is False
        assert item.silent_telemetry is False


def test_static_supply_chain_blockers_prevent_promotion() -> None:
    rows = {item.task: item for item in frozen_m4_challengers()}
    assert promotion_eligible(rows["background"], _winner()) is False
    assert promotion_eligible(rows["restore"], _winner()) is False
    assert rows["background"].weights_license_status == "PARTIAL_EXACT_ARTIFACT_BINDING"
    assert rows["restore"].weights_license_status == "UNVERIFIED"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("benchmark_executed", False),
        ("technical_contracts_pass", False),
        ("independent_oracle_pass", False),
        ("new_p0_p1", 1),
        ("per_class_nonregression", False),
        ("aggregate_improvement_pass", False),
        ("resource_stability_pass", False),
        ("supply_chain_pass", False),
    ],
)
def test_every_qa_winner_condition_is_mandatory(field: str, value: object) -> None:
    vector = next(item for item in frozen_m4_challengers() if item.task == "vector")
    assert promotion_eligible(vector, _winner(**{field: value})) is False


def test_vector_can_only_become_eligible_after_all_predeclared_evidence_passes() -> None:
    vector = next(item for item in frozen_m4_challengers() if item.task == "vector")
    assert promotion_eligible(vector, _winner()) is True


def test_descriptor_rejects_hidden_network_or_invalid_sha() -> None:
    common = dict(
        challenger_id="probe",
        task="vector",
        source_repository="owner/repo",
        source_revision="abc123",
        package_sha256="0" * 64,
        code_license="MIT",
        weights_license_status="NOT_APPLICABLE_NO_WEIGHTS",
        benchmark_only=True,
        runtime_auto_download=False,
        hidden_cloud_fallback=False,
        checksum_bypass=False,
        silent_telemetry=False,
    )
    with pytest.raises(ChallengerContractError):
        ChallengerDescriptor(**{**common, "hidden_cloud_fallback": True})
    with pytest.raises(ChallengerContractError):
        ChallengerDescriptor(**{**common, "package_sha256": "bad"})


def test_winner_evidence_rejects_invalid_p0_p1_count() -> None:
    with pytest.raises(ChallengerContractError):
        _winner(new_p0_p1=-1)


def _design_source(kind: str) -> Image.Image:
    width, height = 192, 144
    if kind == "gradient":
        x = np.linspace(0, 255, width, dtype=np.uint8)
        red = np.tile(x, (height, 1))
        green = np.flipud(red)
        blue = np.roll(red, 29, axis=1)
        return Image.fromarray(np.dstack((red, green, blue, np.full_like(red, 255))), "RGBA")
    if kind == "palette":
        array = np.zeros((height, width, 4), dtype=np.uint8)
        array[..., 3] = 255
        array[:72, :96, :3] = (30, 40, 180)
        array[:72, 96:, :3] = (230, 80, 60)
        array[72:, :96, :3] = (30, 200, 110)
        array[72:, 96:, :3] = (240, 220, 70)
        return Image.fromarray(array, "RGBA")
    if kind == "text_logo":
        image = Image.new("RGBA", (width, height), (245, 245, 238, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 25, 170, 115), outline=(20, 20, 30, 255), width=6)
        draw.text((48, 58), "F08", fill=(15, 20, 25, 255))
        return image
    if kind == "illustration":
        image = Image.new("RGBA", (width, height), (35, 40, 55, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((20, 15, 120, 115), fill=(220, 80, 130, 255))
        draw.polygon([(95, 130), (170, 20), (185, 120)], fill=(45, 200, 180, 255))
        return image
    rng = np.random.default_rng(20260817)
    base = rng.normal(0, 18, (height, width, 3)) + np.linspace(40, 220, width)[None, :, None]
    rgb = np.clip(base, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack((rgb, np.full((height, width), 255, dtype=np.uint8))), "RGBA")


@pytest.mark.parametrize("kind", ["gradient", "palette", "text_logo", "illustration", "photo_like"])
def test_design_candidate_meets_frozen_monotonic_technical_shape(kind: str) -> None:
    source = _design_source(kind)
    source_array = np.asarray(source.convert("RGBA"), dtype=np.float32) / 255.0
    distances: list[float] = []
    for level in (0, 25, 50, 75, 100):
        output, evidence = transform_design_candidate(source, level)
        output_array = np.asarray(output.convert("RGBA"), dtype=np.float32) / 255.0
        assert output.size == source.size
        assert np.array_equal(output_array[..., 3], source_array[..., 3])
        distance = float(np.abs(output_array[..., :3] - source_array[..., :3]).mean())
        distances.append(distance)
        assert evidence["transformation_level"] == level
        assert evidence["benchmark_only"] is True
        assert evidence["source_required"] is True
        assert evidence["production_activation"] is False
        assert evidence["similarity_metrics"]["rgb_normalized_mae"] == pytest.approx(distance, abs=5e-8)
    assert distances[0] == 0.0
    assert all(b >= a + 0.005 - 1e-12 for a, b in zip(distances, distances[1:]))
    assert distances[-1] >= 0.06


def test_design_level_zero_is_exact_pixel_identity_and_candidate_is_not_production_ready() -> None:
    source = _design_source("photo_like")
    output, evidence = transform_design_candidate(source, 0)
    assert np.array_equal(np.asarray(output), np.asarray(source.convert("RGBA")))
    assert DESIGN_CHANGE_CANDIDATE.benchmark_only is True
    assert DESIGN_CHANGE_CANDIDATE.source_required is True
    assert DESIGN_CHANGE_CANDIDATE.prompt_only_generation is False
    assert DESIGN_CHANGE_CANDIDATE.blank_canvas_generation is False
    assert DESIGN_CHANGE_CANDIDATE.production_activation is False
    assert evidence["similarity_metrics"]["rgb_normalized_mae"] == 0.0
    assert evidence["similarity_metrics"]["alpha_normalized_mae"] == 0.0


@pytest.mark.parametrize("level", [-1, 101, float("nan"), True])
def test_design_candidate_rejects_invalid_transformation_level(level: object) -> None:
    with pytest.raises(ChallengerContractError):
        transform_design_candidate(_design_source("gradient"), level)  # type: ignore[arg-type]
