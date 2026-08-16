from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class ProviderContractError(ValueError):
    """Raised when a provider violates the local-first M3 contract."""


@dataclass(frozen=True)
class HardwarePolicy:
    min_ram_mb: int
    min_vram_mb: int
    min_disk_mb: int
    max_runtime_seconds: int
    cpu_required: bool = True
    gpu_optional: bool = True

    def __post_init__(self) -> None:
        for name in ("min_ram_mb", "min_vram_mb", "min_disk_mb", "max_runtime_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProviderContractError(f"Invalid hardware policy field: {name}")
        if self.max_runtime_seconds == 0:
            raise ProviderContractError("max_runtime_seconds must be greater than zero")


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    runtime: str
    tasks: tuple[str, ...]
    hardware: HardwarePolicy
    local_only: bool = True
    allows_network: bool = False
    supports_cpu: bool = True
    supports_gpu: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id or not self.provider_id.replace("-", "").replace("_", "").isalnum():
            raise ProviderContractError("provider_id must be a simple identifier")
        if not self.runtime.strip():
            raise ProviderContractError("runtime is required")
        if not self.tasks or any(not task.strip() for task in self.tasks):
            raise ProviderContractError("provider tasks are required")
        if len(set(self.tasks)) != len(self.tasks):
            raise ProviderContractError("provider tasks must be unique")
        if not self.local_only or self.allows_network:
            raise ProviderContractError("M3 production providers must be local-only and network-disabled")
        if not self.supports_cpu:
            raise ProviderContractError("M3 production providers must provide a CPU path")
        if self.hardware.cpu_required and not self.supports_cpu:
            raise ProviderContractError("hardware policy requires CPU support")
        if not self.hardware.gpu_optional and not self.supports_gpu:
            raise ProviderContractError("hardware policy requires GPU support")


class ProviderRegistry:
    """Small explicit allow-list; no plugin loading, shell commands or cloud fallback."""

    def __init__(self, providers: Iterable[ProviderDescriptor] = ()) -> None:
        self._providers: dict[str, ProviderDescriptor] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ProviderDescriptor) -> None:
        if provider.provider_id in self._providers:
            raise ProviderContractError(f"Duplicate provider: {provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> ProviderDescriptor:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderContractError(f"Unknown provider: {provider_id}") from exc

    def require_task(self, provider_id: str, task: str) -> ProviderDescriptor:
        provider = self.get(provider_id)
        if task not in provider.tasks:
            raise ProviderContractError(f"Provider {provider_id} does not support task {task}")
        return provider

    def snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "provider_id": item.provider_id,
                "runtime": item.runtime,
                "tasks": list(item.tasks),
                "local_only": item.local_only,
                "allows_network": item.allows_network,
                "supports_cpu": item.supports_cpu,
                "supports_gpu": item.supports_gpu,
                "hardware": {
                    "min_ram_mb": item.hardware.min_ram_mb,
                    "min_vram_mb": item.hardware.min_vram_mb,
                    "min_disk_mb": item.hardware.min_disk_mb,
                    "max_runtime_seconds": item.hardware.max_runtime_seconds,
                    "cpu_required": item.hardware.cpu_required,
                    "gpu_optional": item.hardware.gpu_optional,
                },
            }
            for item in sorted(self._providers.values(), key=lambda value: value.provider_id)
        ]

PRODUCTION_BUILTIN_PROVIDER = ProviderDescriptor(
    provider_id="builtin-numpy-local",
    runtime="numpy-linear-ml",
    tasks=("segmentation", "classification", "quality", "recommendation", "restoration", "qa"),
    hardware=HardwarePolicy(
        min_ram_mb=512,
        min_vram_mb=0,
        min_disk_mb=32,
        max_runtime_seconds=60,
        cpu_required=True,
        gpu_optional=True,
    ),
    local_only=True,
    allows_network=False,
    supports_cpu=True,
    supports_gpu=False,
)


def production_provider_registry() -> ProviderRegistry:
    """Return the fixed local-only provider registry for the bundled M3 production pack."""
    return ProviderRegistry((PRODUCTION_BUILTIN_PROVIDER,))
