from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.linear_models import BinaryLogisticModel, train_binary_logistic
from app.config import settings


class AIFeedbackError(ValueError):
    pass


MAX_FEATURES = 128
MAX_ROWS = 10_000
MAX_DATASET_BYTES = 20 * 1024 * 1024


def _sanitize_metadata(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[depth-limit]"
    if value is None or isinstance(value, (str, bool)):
        return value[:512] if isinstance(value, str) else value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number) or abs(number) > 1_000_000_000:
            raise AIFeedbackError("Параметры AI-feedback содержат некорректное число")
        return value
    if isinstance(value, list):
        return [_sanitize_metadata(item, depth + 1) for item in value[:64]]
    if isinstance(value, dict):
        return {str(key)[:64]: _sanitize_metadata(item, depth + 1) for key, item in list(value.items())[:64]}
    return str(value)[:512]


class AIFeedbackStore:
    def __init__(self) -> None:
        settings.ai_feedback_dir.mkdir(parents=True, exist_ok=True)
        settings.ai_promoted_model_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _safe_module(module: str) -> str:
        if not isinstance(module, str) or not (1 <= len(module) <= 64):
            raise AIFeedbackError("Некорректный модуль AI-feedback")
        safe = "".join(ch for ch in module if ch.isalnum() or ch in {"-", "_"})
        if not safe or safe != module:
            raise AIFeedbackError("Некорректный модуль AI-feedback")
        return safe

    def _dataset_path(self, module: str) -> Path:
        safe = self._safe_module(module)
        return settings.ai_feedback_dir / f"{safe}.jsonl"

    @staticmethod
    def _validate_features(features: Any, *, expected: int | None = None) -> list[float]:
        if not isinstance(features, list) or not features or len(features) > MAX_FEATURES:
            raise AIFeedbackError(f"Вектор AI-признаков должен содержать 1–{MAX_FEATURES} чисел")
        values: list[float] = []
        for raw in features:
            if isinstance(raw, bool):
                raise AIFeedbackError("AI-признаки должны быть числами, а не логическими значениями")
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise AIFeedbackError("AI-признаки должны быть числами") from exc
            if not math.isfinite(value) or abs(value) > 1_000_000:
                raise AIFeedbackError("AI-признаки содержат NaN, Infinity или чрезмерное значение")
            values.append(value)
        if expected is not None and len(values) != expected:
            raise AIFeedbackError(f"Размер вектора AI-признаков должен быть {expected}, получено {len(values)}")
        return values

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def add(self, module: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._dataset_path(module)
        accepted = payload.get("accepted")
        if not isinstance(accepted, bool):
            raise AIFeedbackError("Поле accepted должно быть логическим")
        with self._lock:
            rows = self._read_rows_locked(path)
            expected = len(rows[0]["features"]) if rows else None
            features = self._validate_features(payload.get("features"), expected=expected)
            asset_id = str(payload.get("asset_id") or "")[:64] or None
            correction_asset_id = str(payload.get("correction_asset_id") or "")[:64] or None
            duplicate = next((row for row in rows if row.get("accepted") is accepted and row.get("asset_id") == asset_id and row.get("features") == features), None)
            if duplicate is not None:
                raise AIFeedbackError("Такой AI-feedback уже сохранён; повтор не добавлен")
            if len(rows) >= MAX_ROWS or (path.exists() and path.stat().st_size >= MAX_DATASET_BYTES):
                raise AIFeedbackError("Локальный датасет достиг безопасного лимита; экспортируйте или очистите его")
            quality_raw = payload.get("quality_score")
            quality_score = None
            if quality_raw is not None:
                try:
                    quality_score = float(quality_raw)
                except (TypeError, ValueError) as exc:
                    raise AIFeedbackError("Некорректная оценка качества AI-feedback") from exc
                if not math.isfinite(quality_score) or not 0.0 <= quality_score <= 100.0:
                    raise AIFeedbackError("Оценка качества AI-feedback должна быть от 0 до 100")
            evidence_raw = payload.get("evidence_codes") or []
            if not isinstance(evidence_raw, list):
                raise AIFeedbackError("evidence_codes должен быть списком")
            parameters = _sanitize_metadata(payload.get("parameters") or {})
            if not isinstance(parameters, dict):
                raise AIFeedbackError("parameters должен быть объектом")
            if len(json.dumps(parameters, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 16 * 1024:
                raise AIFeedbackError("Параметры AI-feedback превышают безопасный лимит")
            item = {
                "id": uuid.uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "module": module,
                "accepted": accepted,
                "features": features,
                "asset_id": asset_id,
                "correction_asset_id": correction_asset_id,
                "note": str(payload.get("note") or "")[:1000],
                "label_source": str(payload.get("label_source") or "user_feedback")[:64],
                "quality_score": quality_score,
                "operation": str(payload.get("operation") or "")[:64] or None,
                "evidence_codes": [str(code)[:64] for code in evidence_raw[:64]],
                "parameters": parameters,
            }
            line = json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            return item

    def _read_rows_locked(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        if path.stat().st_size > MAX_DATASET_BYTES:
            raise AIFeedbackError("Файл AI-feedback превышает безопасный лимит")
        rows: list[dict[str, Any]] = []
        expected: int | None = None
        try:
            lines = path.read_text("utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise AIFeedbackError("Датасет AI-feedback повреждён") from exc
        if len(lines) > MAX_ROWS:
            raise AIFeedbackError("Датасет AI-feedback содержит слишком много строк")
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AIFeedbackError(f"Датасет AI-feedback повреждён в строке {number}") from exc
            if not isinstance(row, dict) or not isinstance(row.get("accepted"), bool):
                raise AIFeedbackError(f"Некорректная строка AI-feedback: {number}")
            values = self._validate_features(row.get("features"), expected=expected)
            expected = expected or len(values)
            row["features"] = values
            rows.append(row)
        return rows

    def list(self, module: str) -> list[dict[str, Any]]:
        path = self._dataset_path(module)
        with self._lock:
            return self._read_rows_locked(path)

    @staticmethod
    def _balanced_accuracy(payload: dict[str, Any], x: np.ndarray, y: np.ndarray) -> float:
        model = BinaryLogisticModel.from_payload(payload)
        prediction = (model.predict_proba(x) >= 0.5).astype(np.int32)
        recalls: list[float] = []
        for label in (0, 1):
            selected = y == label
            if np.any(selected):
                recalls.append(float((prediction[selected] == label).mean()))
        return float(sum(recalls) / len(recalls)) if recalls else 0.0

    @staticmethod
    def _stratified_folds(y: np.ndarray, seed: int) -> list[np.ndarray]:
        rng = np.random.default_rng(seed)
        class_indices: list[np.ndarray] = []
        for label in (0, 1):
            indices = np.flatnonzero(y == label)
            rng.shuffle(indices)
            class_indices.append(indices)
        folds_count = min(5, *(len(indices) for indices in class_indices))
        if folds_count < 2:
            raise AIFeedbackError("Для benchmark нужно минимум два примера каждого класса")
        buckets = [[] for _ in range(folds_count)]
        for indices in class_indices:
            for position, index in enumerate(indices):
                buckets[position % folds_count].append(int(index))
        return [np.asarray(sorted(bucket), dtype=np.int32) for bucket in buckets]

    @classmethod
    def _cross_validated_score(cls, x: np.ndarray, y: np.ndarray, seed: int) -> float:
        predictions = np.zeros(len(y), dtype=np.int32)
        observed = np.zeros(len(y), dtype=bool)
        for valid_idx in cls._stratified_folds(y, seed):
            train_mask = np.ones(len(y), dtype=bool)
            train_mask[valid_idx] = False
            payload = train_binary_logistic(x[train_mask], y[train_mask])
            model = BinaryLogisticModel.from_payload(payload)
            predictions[valid_idx] = (model.predict_proba(x[valid_idx]) >= 0.5).astype(np.int32)
            observed[valid_idx] = True
        if not observed.all():
            raise AIFeedbackError("Не удалось сформировать полный validation benchmark")
        recalls = [float((predictions[y == label] == label).mean()) for label in (0, 1)]
        return float(sum(recalls) / 2.0)

    @classmethod
    def _validate_calibrator_payload(cls, payload: dict[str, Any], expected_features: int | None = None) -> None:
        if payload.get("kind") != "binary_logistic":
            raise AIFeedbackError("Некорректный тип адаптационной модели")
        features = cls._validate_features(payload.get("coef"), expected=expected_features)
        cls._validate_features(payload.get("mean"), expected=len(features))
        scale = cls._validate_features(payload.get("scale"), expected=len(features))
        if any(value <= 0 for value in scale):
            raise AIFeedbackError("Некорректный scale адаптационной модели")
        try:
            intercept = float(payload.get("intercept"))
        except (TypeError, ValueError) as exc:
            raise AIFeedbackError("Некорректный intercept адаптационной модели") from exc
        if not math.isfinite(intercept):
            raise AIFeedbackError("Некорректный intercept адаптационной модели")

    def train(self, module: str) -> dict[str, Any]:
        module = self._safe_module(module)
        with self._lock:
            raw_rows = self._read_rows_locked(self._dataset_path(module))
            unique_by_vector: dict[tuple[float, ...], dict[str, Any]] = {}
            labels_by_vector: dict[tuple[float, ...], bool] = {}
            for row in raw_rows:
                vector = tuple(float(value) for value in row["features"])
                label = bool(row["accepted"])
                if vector in labels_by_vector and labels_by_vector[vector] is not label:
                    raise AIFeedbackError("Датасет содержит противоречивые метки для одинаковых AI-признаков")
                labels_by_vector[vector] = label
                unique_by_vector.setdefault(vector, row)
            rows = list(unique_by_vector.values())
            if len(rows) < 8:
                raise AIFeedbackError("Для адаптации требуется минимум 8 уникальных подтверждённых примеров")
            x = np.asarray([row["features"] for row in rows], dtype=np.float64)
            y = np.asarray([1 if row["accepted"] else 0 for row in rows], dtype=np.int32)
            counts = {label: int((y == label).sum()) for label in (0, 1)}
            if min(counts.values()) < 2:
                raise AIFeedbackError("Для benchmark нужно минимум два принятых и два отклонённых результата")

            seed = 20260723 + len(rows) + sum(ord(ch) for ch in module)
            validation_balanced_accuracy = self._cross_validated_score(x, y, seed)
            final_payload = train_binary_logistic(x, y)
            self._validate_calibrator_payload(final_payload, x.shape[1])
            train_balanced_accuracy = self._balanced_accuracy(final_payload, x, y)

            module_dir = settings.ai_promoted_model_dir / module
            module_dir.mkdir(parents=True, exist_ok=True)
            current_path = module_dir / "current.json"
            current_score = -1.0
            if current_path.exists():
                try:
                    current = json.loads(current_path.read_text("utf-8"))
                    self._validate_calibrator_payload(current, x.shape[1])
                    current_score = self._balanced_accuracy(current, x, y)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, AIFeedbackError) as exc:
                    raise AIFeedbackError("Активная адаптационная модель повреждена; выполните восстановление") from exc

            promoted = validation_balanced_accuracy >= max(0.65, current_score + 0.02)
            version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
            candidate = {
                **final_payload,
                "id": f"feedback_calibrator_{module}",
                "version": version,
                "module": module,
                "train_balanced_accuracy": train_balanced_accuracy,
                "validation_balanced_accuracy": validation_balanced_accuracy,
                "validation_accuracy": validation_balanced_accuracy,
                "current_benchmark": current_score,
                "sample_count": len(rows),
                "class_counts": {"rejected": counts[0], "accepted": counts[1]},
                "promotion_rule": "cv_balanced_accuracy >= max(0.65, current_benchmark + 0.02)",
                "promoted": promoted,
            }
            candidate_path = module_dir / f"candidate-{version}.json"
            self._atomic_json(candidate_path, candidate)
            if promoted:
                if current_path.exists():
                    rollback_path = module_dir / f"rollback-{version}.json"
                    shutil.copy2(current_path, rollback_path)
                self._atomic_json(current_path, candidate)
            return candidate

    def rollback(self, module: str) -> dict[str, Any]:
        module = self._safe_module(module)
        with self._lock:
            module_dir = settings.ai_promoted_model_dir / module
            current_path = module_dir / "current.json"
            rollback_files = sorted(module_dir.glob("rollback-*.json"), reverse=True)
            if not rollback_files:
                raise AIFeedbackError("Нет модели для отката")
            previous = rollback_files[0]
            try:
                payload = json.loads(previous.read_text("utf-8"))
                self._validate_calibrator_payload(payload)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AIFeedbackError) as exc:
                raise AIFeedbackError("Файл отката повреждён") from exc
            if current_path.exists():
                try:
                    current = json.loads(current_path.read_text("utf-8"))
                    self._validate_calibrator_payload(current)
                    redo = module_dir / f"redo-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
                    self._atomic_json(redo, current)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, AIFeedbackError) as exc:
                    raise AIFeedbackError("Активная модель повреждена; откат остановлен без изменения") from exc
            self._atomic_json(current_path, payload)
            previous.unlink()
            return {**payload, "rolled_back_from": previous.name}

    def _current_payload(self, module: str) -> dict[str, Any] | None:
        path = settings.ai_promoted_model_dir / self._safe_module(module) / "current.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text("utf-8"))
            self._validate_calibrator_payload(payload)
            return payload
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AIFeedbackError):
            return None

    def acceptance_score(self, module: str, features: np.ndarray, default: float = 0.5) -> float:
        with self._lock:
            payload = self._current_payload(module)
            if payload is None:
                return float(default)
            vector = np.asarray(features, dtype=np.float64).reshape(1, -1)
            if not np.isfinite(vector).all() or vector.shape[1] != len(payload.get("coef", [])):
                return float(default)
            model = BinaryLogisticModel.from_payload(payload)
            probability = float(model.predict_proba(vector)[0])
            return probability if math.isfinite(probability) else float(default)

    def calibrate(self, module: str, features: np.ndarray, confidence: float) -> float:
        if not math.isfinite(float(confidence)):
            confidence = 0.0
        acceptance = self.acceptance_score(module, features, 0.5)
        return float(np.clip(confidence * 0.65 + acceptance * 0.35, 0.0, 1.0))

    def adaptive_factor(self, module: str, features: np.ndarray, span: float = 0.25) -> float:
        """Map a promoted feedback model to a bounded parameter multiplier."""
        span = float(np.clip(span, 0.0, 0.5))
        score = self.acceptance_score(module, features, 0.5)
        return float(np.clip(1.0 + (score - 0.5) * 2.0 * span, 1.0 - span, 1.0 + span))
