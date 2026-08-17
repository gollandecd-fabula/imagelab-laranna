from __future__ import annotations

import pytest

from app.ai.challengers import (
    DESIGN_CHANGE_PRESELECTED_WINNER,
    ChallengerContractError,
    ChallengerDescriptor,
    WinnerEvidence,
    frozen_m4_challengers,
    promotion_eligible,
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
