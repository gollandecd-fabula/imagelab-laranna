from __future__ import annotations

import re
from dataclasses import dataclass


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ChallengerContractError(ValueError):
    """Raised when an M4 benchmark challenger contract is malformed."""


@dataclass(frozen=True)
class ChallengerDescriptor:
    """Immutable M4 benchmark identity; this object cannot activate production engines."""

    challenger_id: str
    task: str
    source_repository: str
    source_revision: str
    package_sha256: str
    code_license: str
    weights_license_status: str
    benchmark_only: bool
    runtime_auto_download: bool
    hidden_cloud_fallback: bool
    checksum_bypass: bool
    silent_telemetry: bool
    static_promotion_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.challenger_id or not self.task:
            raise ChallengerContractError("challenger id/task are required")
        if not self.source_repository or not self.source_revision:
            raise ChallengerContractError("exact source repository/revision are required")
        if not _SHA256_RE.fullmatch(self.package_sha256):
            raise ChallengerContractError("exact package SHA-256 is required")
        if not self.code_license:
            raise ChallengerContractError("code license evidence is required")
        if not self.benchmark_only:
            raise ChallengerContractError("M4 challengers must enter as benchmark-only")
        if any((self.runtime_auto_download, self.hidden_cloud_fallback, self.checksum_bypass, self.silent_telemetry)):
            raise ChallengerContractError("M4 challenger violates local-first supply-chain locks")


@dataclass(frozen=True)
class WinnerEvidence:
    """Predeclared QA-WINNER inputs. No field may be inferred from a benchmark score."""

    benchmark_executed: bool
    technical_contracts_pass: bool
    independent_oracle_pass: bool
    new_p0_p1: int
    per_class_nonregression: bool
    aggregate_improvement_pass: bool
    resource_stability_pass: bool
    supply_chain_pass: bool

    def __post_init__(self) -> None:
        if isinstance(self.new_p0_p1, bool) or not isinstance(self.new_p0_p1, int) or self.new_p0_p1 < 0:
            raise ChallengerContractError("new_p0_p1 must be a non-negative integer")


def promotion_eligible(challenger: ChallengerDescriptor, evidence: WinnerEvidence) -> bool:
    """Return eligibility only; activation remains a separate, later gated operation."""

    return (
        not challenger.static_promotion_blockers
        and evidence.benchmark_executed
        and evidence.technical_contracts_pass
        and evidence.independent_oracle_pass
        and evidence.new_p0_p1 == 0
        and evidence.per_class_nonregression
        and evidence.aggregate_improvement_pass
        and evidence.resource_stability_pass
        and evidence.supply_chain_pass
    )


def frozen_m4_challengers() -> tuple[ChallengerDescriptor, ...]:
    """Exact pre-result M4 challenger identities bound by IL-M4-ENTRY-20260817-001."""

    return (
        ChallengerDescriptor(
            challenger_id="birefnet-tiny-v1",
            task="background",
            source_repository="ZhengPeng7/BiRefNet",
            source_revision="a0cf9925880620000aa2d1948d61bf659ddfdfaa",
            package_sha256="5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333",
            code_license="MIT",
            weights_license_status="PARTIAL_EXACT_ARTIFACT_BINDING",
            benchmark_only=True,
            runtime_auto_download=False,
            hidden_cloud_fallback=False,
            checksum_bypass=False,
            silent_telemetry=False,
            static_promotion_blockers=("WEIGHTS_LICENSE_EXACT_BINDING_PARTIAL",),
        ),
        ChallengerDescriptor(
            challenger_id="realesrgan-ncnn-vulkan-20211212",
            task="restore",
            source_repository="xinntao/Real-ESRGAN",
            source_revision="f07aaffda04c7e69f11e6bfaf8023a6435471459",
            package_sha256="caf96d62999e741194a28b514eb6202c09a39edcd9ced730e3f784c424cc0653",
            code_license="BSD-3-Clause / MIT runtime",
            weights_license_status="UNVERIFIED",
            benchmark_only=True,
            runtime_auto_download=False,
            hidden_cloud_fallback=False,
            checksum_bypass=False,
            silent_telemetry=False,
            static_promotion_blockers=("WEIGHTS_LICENSE_UNVERIFIED", "FULL_RESOURCE_BENCHMARK_PENDING"),
        ),
        ChallengerDescriptor(
            challenger_id="vtracer-1.0.0-alpha.3",
            task="vector",
            source_repository="visioncortex/vtracer",
            source_revision="58221025d5cfc6abbe12745942ae867b57ad3117",
            package_sha256="26fb07c440aa6dd0a9ac57a83db6ee2924ddf308bccf451e76b324bb61780dba",
            code_license="MIT",
            weights_license_status="NOT_APPLICABLE_NO_WEIGHTS",
            benchmark_only=True,
            runtime_auto_download=False,
            hidden_cloud_fallback=False,
            checksum_bypass=False,
            silent_telemetry=False,
            static_promotion_blockers=(),
        ),
    )


DESIGN_CHANGE_PRESELECTED_WINNER = None
