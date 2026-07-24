from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


def _sigmoid(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-value))


def _softmax(value: np.ndarray) -> np.ndarray:
    value = value - np.max(value, axis=-1, keepdims=True)
    exp = np.exp(np.clip(value, -60.0, 60.0))
    return exp / np.maximum(exp.sum(axis=-1, keepdims=True), 1e-12)


@dataclass(frozen=True)
class BinaryLogisticModel:
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BinaryLogisticModel":
        return cls(
            mean=np.asarray(payload["mean"], dtype=np.float32),
            scale=np.maximum(np.asarray(payload["scale"], dtype=np.float32), 1e-8),
            coef=np.asarray(payload["coef"], dtype=np.float32),
            intercept=float(payload["intercept"]),
        )

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        x = (np.asarray(features, dtype=np.float32) - self.mean) / self.scale
        return _sigmoid(x @ self.coef + self.intercept)


@dataclass(frozen=True)
class SoftmaxModel:
    classes: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: np.ndarray

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SoftmaxModel":
        return cls(
            classes=tuple(str(item) for item in payload["classes"]),
            mean=np.asarray(payload["mean"], dtype=np.float32),
            scale=np.maximum(np.asarray(payload["scale"], dtype=np.float32), 1e-8),
            coef=np.asarray(payload["coef"], dtype=np.float32),
            intercept=np.asarray(payload["intercept"], dtype=np.float32),
        )

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        x = (np.asarray(features, dtype=np.float32) - self.mean) / self.scale
        logits = x @ self.coef.T + self.intercept
        return _softmax(logits)

    def predict(self, features: np.ndarray) -> tuple[str, float, dict[str, float]]:
        probabilities = self.predict_proba(np.asarray(features, dtype=np.float32).reshape(1, -1))[0]
        index = int(np.argmax(probabilities))
        return self.classes[index], float(probabilities[index]), {
            name: float(probabilities[i]) for i, name in enumerate(self.classes)
        }


@dataclass(frozen=True)
class LinearRegressionModel:
    outputs: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: np.ndarray

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LinearRegressionModel":
        return cls(
            outputs=tuple(str(item) for item in payload["outputs"]),
            mean=np.asarray(payload["mean"], dtype=np.float32),
            scale=np.maximum(np.asarray(payload["scale"], dtype=np.float32), 1e-8),
            coef=np.asarray(payload["coef"], dtype=np.float32),
            intercept=np.asarray(payload["intercept"], dtype=np.float32),
        )

    def predict(self, features: np.ndarray) -> dict[str, float]:
        x = (np.asarray(features, dtype=np.float32) - self.mean) / self.scale
        values = self.coef @ x + self.intercept
        return {name: float(values[i]) for i, name in enumerate(self.outputs)}


def train_binary_logistic(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    iterations: int = 600,
    learning_rate: float = 0.08,
    l2: float = 0.002,
) -> dict[str, Any]:
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64).reshape(-1)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    weights = np.zeros(z.shape[1], dtype=np.float64)
    bias = 0.0
    positive = max(float((y > 0.5).sum()), 1.0)
    negative = max(float((y <= 0.5).sum()), 1.0)
    sample_weight = np.where(y > 0.5, len(y) / (2 * positive), len(y) / (2 * negative))
    for _ in range(iterations):
        probability = _sigmoid(z @ weights + bias)
        error = (probability - y) * sample_weight
        grad_w = z.T @ error / len(y) + l2 * weights
        grad_b = float(error.mean())
        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b
    return {
        "kind": "binary_logistic",
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "coef": weights.tolist(),
        "intercept": bias,
    }
