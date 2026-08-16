from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.linear_models import BinaryLogisticModel, LinearRegressionModel, SoftmaxModel
from app.ai.model_manager import ModelManager, ModelPackError
from app.ai.providers import production_provider_registry
from app.config import settings


class AIModelError(RuntimeError):
    pass


# Trusted root for the built-in suite shipped with this source tree. This protects
# against accidental or partial replacement of both a model and the mutable
# manifest. It is not a defence against an attacker who can also modify code.
EXPECTED_MANIFEST_SHA256 = "b9d8315e8247ad0928e14b8e9d8a82d07feee9c898e8ea257163ba9abc6f29d6"
EXPECTED_MODEL_PACK_SHA256 = "604aae52d0f81b16aaca4b261dc23ccc92f16591ae1b4c3922e14c5991314a1f"
EXPECTED_MODEL_IDS = {
    "pixel_subject",
    "pixel_print",
    "content_classifier",
    "quality_risk",
    "restoration_profile",
    "tiny_restorer",
    "halftone_recommender",
    "vector_recommender",
    "export_recommender",
    "size_assistant",
    "qa_anomaly",
}


@dataclass(frozen=True)
class ModelSpec:
    id: str
    version: str
    task: str
    filename: str
    sha256: str
    runtime: str


class AIModelRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._manifest: dict[str, Any] = {}
        self._specs: dict[str, ModelSpec] = {}
        self._payloads: dict[str, dict[str, Any]] = {}
        self.reload()

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _safe_model_path(filename: str) -> Path:
        if not filename or Path(filename).name != filename or any(ch in filename for ch in ("/", "\\", "\x00")):
            raise AIModelError("Некорректное имя файла AI-модели")
        base = settings.ai_model_dir.resolve()
        path = (base / filename).resolve()
        if path.parent != base:
            raise AIModelError("Путь AI-модели выходит за каталог моделей")
        return path

    def _load_manifest(self) -> dict[str, Any]:
        pack_path = settings.ai_model_dir / "model-pack.json"
        if not pack_path.exists():
            raise AIModelError("Манифест production model-pack отсутствует")
        if self._sha256(pack_path) != EXPECTED_MODEL_PACK_SHA256:
            raise AIModelError("Production model-pack изменён: доверенный SHA-256 не совпадает")
        try:
            manager = ModelManager(settings.ai_model_dir / ".runtime-state", production_provider_registry())
            pack = manager.load_manifest(settings.ai_model_dir)
        except ModelPackError as exc:
            raise AIModelError(f"Production model-pack не прошёл M3 validation: {exc}") from exc
        if pack.pack_id != "imagelab-builtin-clean" or pack.version != "2.0.0":
            raise AIModelError("Неожиданный production model-pack")

        path = settings.ai_model_dir / "manifest.json"
        if not path.exists():
            raise AIModelError("Манифест встроенных AI-моделей отсутствует")
        actual = self._sha256(path)
        if actual != EXPECTED_MANIFEST_SHA256:
            raise AIModelError("Манифест AI-моделей изменён: доверенный SHA-256 не совпадает")
        try:
            manifest = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIModelError("Манифест AI-моделей повреждён") from exc
        if manifest.get("schema") != 1 or not isinstance(manifest.get("models"), list):
            raise AIModelError("Неподдерживаемая схема манифеста AI-моделей")
        return manifest

    @staticmethod
    def _finite_array(value: Any, name: str, *, ndim: int | None = None) -> np.ndarray:
        try:
            array = np.asarray(value, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise AIModelError(f"Некорректные параметры модели: {name}") from exc
        if ndim is not None and array.ndim != ndim:
            raise AIModelError(f"Некорректная размерность модели: {name}")
        if array.size == 0 or array.size > 2_000_000 or not np.isfinite(array).all():
            raise AIModelError(f"Некорректные или чрезмерные параметры модели: {name}")
        return array

    @classmethod
    def _validate_binary(cls, payload: dict[str, Any]) -> None:
        mean = cls._finite_array(payload.get("mean"), "mean", ndim=1)
        scale = cls._finite_array(payload.get("scale"), "scale", ndim=1)
        coef = cls._finite_array(payload.get("coef"), "coef", ndim=1)
        if not (len(mean) == len(scale) == len(coef)):
            raise AIModelError("Несогласованные размеры binary AI-модели")
        if np.any(scale <= 0):
            raise AIModelError("Scale binary AI-модели должен быть строго положительным")
        if not math.isfinite(float(payload.get("intercept"))):
            raise AIModelError("Некорректный intercept AI-модели")

    @classmethod
    def _validate_softmax(cls, payload: dict[str, Any]) -> None:
        classes = payload.get("classes")
        if not isinstance(classes, list) or len(classes) < 2 or len(set(map(str, classes))) != len(classes):
            raise AIModelError("Некорректный список классов AI-модели")
        mean = cls._finite_array(payload.get("mean"), "mean", ndim=1)
        scale = cls._finite_array(payload.get("scale"), "scale", ndim=1)
        coef = cls._finite_array(payload.get("coef"), "coef", ndim=2)
        intercept = cls._finite_array(payload.get("intercept"), "intercept", ndim=1)
        if len(mean) != len(scale) or coef.shape != (len(classes), len(mean)) or len(intercept) != len(classes):
            raise AIModelError("Несогласованные размеры softmax AI-модели")
        if np.any(scale <= 0):
            raise AIModelError("Scale softmax AI-модели должен быть строго положительным")

    @classmethod
    def _validate_regression(cls, payload: dict[str, Any]) -> None:
        outputs = payload.get("outputs")
        if not isinstance(outputs, list) or not outputs or len(set(map(str, outputs))) != len(outputs):
            raise AIModelError("Некорректный список выходов AI-модели")
        mean = cls._finite_array(payload.get("mean"), "mean", ndim=1)
        scale = cls._finite_array(payload.get("scale"), "scale", ndim=1)
        coef = cls._finite_array(payload.get("coef"), "coef", ndim=2)
        intercept = cls._finite_array(payload.get("intercept"), "intercept", ndim=1)
        if len(mean) != len(scale) or coef.shape != (len(outputs), len(mean)) or len(intercept) != len(outputs):
            raise AIModelError("Несогласованные размеры regression AI-модели")
        if np.any(scale <= 0):
            raise AIModelError("Scale regression AI-модели должен быть строго положительным")

    @classmethod
    def _validate_payload(cls, model_id: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise AIModelError(f"AI-модель {model_id} имеет неверный формат")
        kind = payload.get("kind")
        if kind == "binary_logistic":
            cls._validate_binary(payload)
        elif kind == "softmax":
            cls._validate_softmax(payload)
        elif kind == "linear_regression":
            cls._validate_regression(payload)
        elif kind == "multi_binary":
            models = payload.get("models")
            if not isinstance(models, dict) or not models:
                raise AIModelError("Пустой набор quality AI-моделей")
            for name, nested in models.items():
                if not isinstance(name, str) or not name:
                    raise AIModelError("Некорректное имя quality AI-модели")
                cls._validate_binary(nested)
        elif kind == "conv3x3_linear":
            coef = cls._finite_array(payload.get("coef"), "coef", ndim=4)
            intercept = cls._finite_array(payload.get("intercept"), "intercept", ndim=1)
            if coef.shape != (3, 3, 3, 3) or intercept.shape != (3,):
                raise AIModelError("Некорректная форма tiny-restorer модели")
        else:
            raise AIModelError(f"Неподдерживаемый тип AI-модели {model_id}: {kind}")

    def reload(self) -> None:
        with self._lock:
            manifest = self._load_manifest()
            specs: dict[str, ModelSpec] = {}
            payloads: dict[str, dict[str, Any]] = {}
            raw_models = manifest.get("models", [])
            for raw in raw_models:
                if not isinstance(raw, dict):
                    raise AIModelError("Некорректная запись в манифесте AI-моделей")
                try:
                    spec = ModelSpec(**raw)
                except TypeError as exc:
                    raise AIModelError("Некорректные поля модели в манифесте") from exc
                if spec.id in specs:
                    raise AIModelError(f"Дублирующийся ID AI-модели: {spec.id}")
                if not spec.id or not spec.version or spec.runtime != "numpy-linear-ml":
                    raise AIModelError(f"Некорректная спецификация AI-модели: {spec.id}")
                path = self._safe_model_path(spec.filename)
                if not path.exists():
                    raise AIModelError(f"AI-модель {spec.id} отсутствует")
                actual = self._sha256(path)
                if actual != spec.sha256:
                    raise AIModelError(f"AI-модель {spec.id} повреждена: SHA-256 не совпадает")
                try:
                    payload = json.loads(path.read_text("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise AIModelError(f"AI-модель {spec.id} повреждена") from exc
                self._validate_payload(spec.id, payload)
                specs[spec.id] = spec
                payloads[spec.id] = payload
            if set(specs) != EXPECTED_MODEL_IDS:
                missing = sorted(EXPECTED_MODEL_IDS - set(specs))
                extra = sorted(set(specs) - EXPECTED_MODEL_IDS)
                raise AIModelError(f"Неполный набор AI-моделей; missing={missing}, extra={extra}")
            self._manifest = manifest
            self._specs = specs
            self._payloads = payloads

    @property
    def manifest(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._manifest))

    def spec(self, model_id: str) -> ModelSpec:
        try:
            return self._specs[model_id]
        except KeyError as exc:
            raise AIModelError(f"AI-модель {model_id} не зарегистрирована") from exc

    def payload(self, model_id: str) -> dict[str, Any]:
        try:
            return json.loads(json.dumps(self._payloads[model_id], allow_nan=False))
        except KeyError as exc:
            raise AIModelError(f"AI-модель {model_id} не загружена") from exc

    def binary(self, model_id: str) -> BinaryLogisticModel:
        return BinaryLogisticModel.from_payload(self.payload(model_id))

    def softmax(self, model_id: str) -> SoftmaxModel:
        return SoftmaxModel.from_payload(self.payload(model_id))

    def regression(self, model_id: str) -> LinearRegressionModel:
        return LinearRegressionModel.from_payload(self.payload(model_id))

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "suite": self._manifest.get("suite"),
            "version": self._manifest.get("version"),
            "runtime": "numpy-linear-ml",
            "provider": "CPU",
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "models": [
                {"id": spec.id, "version": spec.version, "task": spec.task, "verified": True}
                for spec in self._specs.values()
            ],
            "metrics": self._manifest.get("metrics", {}),
            "limitations": self._manifest.get("limitations", []),
        }
