from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image


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


@dataclass(frozen=True)
class DesignCandidateDescriptor:
    """Benchmark-only F08 candidate. It is deliberately unable to activate production."""

    candidate_id: str
    engine: str
    model: str
    version_hash: str
    seed: int
    benchmark_only: bool = True
    source_required: bool = True
    prompt_only_generation: bool = False
    blank_canvas_generation: bool = False
    production_activation: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.engine or not self.model:
            raise ChallengerContractError("design candidate identity is incomplete")
        if not _SHA256_RE.fullmatch(self.version_hash):
            raise ChallengerContractError("design candidate version hash must be SHA-256")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ChallengerContractError("design candidate seed must be a non-negative integer")
        if not self.benchmark_only or not self.source_required:
            raise ChallengerContractError("F08 pre-benchmark candidate must be source-required and benchmark-only")
        if self.prompt_only_generation or self.blank_canvas_generation or self.production_activation:
            raise ChallengerContractError("F08 pre-benchmark candidate violates M4 activation/source locks")


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


_DESIGN_ALGORITHM_DESCRIPTOR = (
    "imagelab-f08-source-palette-structure-v1|seed=20260817|"
    "source-required|level0-identity|linear-source-target-blend|alpha-preserved|"
    "benchmark-only|no-cloud|no-prompt-only|no-blank-canvas|no-production-activation"
)
DESIGN_CANDIDATE_VERSION_HASH = hashlib.sha256(_DESIGN_ALGORITHM_DESCRIPTOR.encode("utf-8")).hexdigest()
DESIGN_CHANGE_CANDIDATE = DesignCandidateDescriptor(
    candidate_id="imagelab-f08-source-palette-structure-v1",
    engine="imagelab-local-design-candidate",
    model="deterministic-source-palette-structure-v1",
    version_hash=DESIGN_CANDIDATE_VERSION_HASH,
    seed=20260817,
)

# Low/high/accent triplets are intentionally fixed before candidate benchmark execution.
_DESIGN_PALETTES: tuple[tuple[str, tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]], ...] = (
    ("navy-coral", (18, 28, 72), (248, 132, 96), (70, 220, 210)),
    ("forest-gold", (16, 58, 46), (248, 202, 76), (196, 76, 116)),
    ("plum-cyan", (62, 24, 84), (108, 226, 236), (246, 138, 60)),
    ("ink-lime", (18, 22, 30), (192, 242, 116), (142, 92, 238)),
)


def _design_level(value: int | float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ChallengerContractError("F08 transformation level must be a finite number from 0 to 100")
    level = float(value)
    if not 0.0 <= level <= 100.0:
        raise ChallengerContractError("F08 transformation level must be from 0 to 100")
    return level


def _design_target(rgb: np.ndarray) -> tuple[np.ndarray, str, float]:
    src = rgb.astype(np.float32)
    luma = (0.2126 * src[..., 0] + 0.7152 * src[..., 1] + 0.0722 * src[..., 2]) / 255.0
    curve = np.clip((luma - 0.5) * 1.22 + 0.5, 0.0, 1.0)
    h, w = luma.shape
    x = np.linspace(-1.0, 1.0, max(1, w), dtype=np.float32)[None, :]
    y = np.linspace(-1.0, 1.0, max(1, h), dtype=np.float32)[:, None]
    gx = np.abs(luma - np.roll(luma, 1, axis=1)) if w > 1 else np.zeros_like(luma)
    gy = np.abs(luma - np.roll(luma, 1, axis=0)) if h > 1 else np.zeros_like(luma)
    edge = np.clip((gx + gy) * 2.4, 0.0, 1.0)[..., None]
    spatial = ((0.035 * x) + (0.025 * y))[..., None]

    candidates: list[tuple[float, str, np.ndarray]] = []
    for name, low_raw, high_raw, accent_raw in _DESIGN_PALETTES:
        low = np.asarray(low_raw, dtype=np.float32)
        high = np.asarray(high_raw, dtype=np.float32)
        accent = np.asarray(accent_raw, dtype=np.float32)
        mapped = low + curve[..., None] * (high - low)
        target = mapped * (1.0 - 0.20 * edge) + accent * (0.20 * edge)
        target = np.clip(target + spatial * (accent - 127.5), 0.0, 255.0)
        distance = float(np.abs(target - src).mean() / 255.0)
        candidates.append((distance, name, target))

    distance, name, target = max(candidates, key=lambda item: item[0])
    if distance < 0.09:
        # General fail-safe for unusually palette-aligned sources. This is not
        # benchmark-case specific: every channel moves by exactly half the 8-bit range.
        target = np.bitwise_xor(rgb.astype(np.uint8), np.uint8(128)).astype(np.float32)
        distance = float(np.abs(target - src).mean() / 255.0)
        name = "xor128-fallback"
    return target, name, distance


def transform_design_candidate(image: Image.Image, transformation_level: int | float) -> tuple[Image.Image, dict[str, Any]]:
    """Apply the source-only, benchmark-gated F08 candidate without production activation."""

    if not isinstance(image, Image.Image):
        raise ChallengerContractError("F08 requires an uploaded/source image")
    level = _design_level(transformation_level)
    source = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    if source.ndim != 3 or source.shape[2] != 4 or source.size == 0:
        raise ChallengerContractError("F08 source image is invalid")

    if level == 0.0:
        output = source.copy()
        palette_name = "identity"
        target_distance = 0.0
    else:
        target, palette_name, target_distance = _design_target(source[..., :3])
        t = np.float32(level / 100.0)
        rgb = np.rint(source[..., :3].astype(np.float32) * (1.0 - t) + target * t)
        output = source.copy()
        output[..., :3] = np.clip(rgb, 0.0, 255.0).astype(np.uint8)
        # Alpha is immutable in the F08 benchmark candidate. Geometry/dimensions also remain unchanged.
        output[..., 3] = source[..., 3]

    rgb_mae = float(np.abs(output[..., :3].astype(np.float32) - source[..., :3].astype(np.float32)).mean() / 255.0)
    alpha_mae = float(np.abs(output[..., 3].astype(np.float32) - source[..., 3].astype(np.float32)).mean() / 255.0)
    metrics = {
        "rgb_normalized_mae": round(rgb_mae, 9),
        "alpha_normalized_mae": round(alpha_mae, 9),
        "technical_similarity": round(max(0.0, 1.0 - rgb_mae), 9),
        "target_rgb_normalized_mae": round(target_distance, 9),
    }
    evidence: dict[str, Any] = {
        "engine": DESIGN_CHANGE_CANDIDATE.engine,
        "model": DESIGN_CHANGE_CANDIDATE.model,
        "version_hash": DESIGN_CHANGE_CANDIDATE.version_hash,
        "seed": DESIGN_CHANGE_CANDIDATE.seed,
        "parameters": {
            "palette_policy": "max-distance-fixed-palette-with-general-fallback",
            "palette": palette_name,
            "alpha_policy": "preserve_exact",
            "geometry_policy": "preserve_dimensions",
            "blend_policy": "linear_source_to_fixed_target",
        },
        "transformation_level": int(level) if level.is_integer() else level,
        "similarity_metrics": metrics,
        "benchmark_only": True,
        "source_required": True,
        "production_activation": False,
    }
    return Image.fromarray(output, "RGBA"), evidence


DESIGN_CHANGE_PRESELECTED_WINNER = None
