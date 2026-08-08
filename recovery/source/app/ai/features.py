from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image


def pil_to_rgb_alpha(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    return rgba[:, :, :3].copy(), rgba[:, :, 3].copy()


def image_features(rgb: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    if alpha is None:
        alpha = np.full((h, w), 255, dtype=np.uint8)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    edges = cv2.Canny(gray, 60, 150)
    hist = cv2.calcHist([gray], [0], None, [32], [0, 256]).ravel().astype(np.float64)
    hist /= max(hist.sum(), 1)
    entropy = float(-(hist[hist > 0] * np.log2(hist[hist > 0])).sum()) / 5.0
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]], axis=0).astype(np.float32)
    center = rgb[h // 4:3 * h // 4, w // 4:3 * w // 4].reshape(-1, 3).astype(np.float32)
    block = gray.astype(np.float32)
    if w >= 16 and h >= 16:
        right = block[:, 8::8]
        left = block[:, 7:-1:8]
        bottom = block[8::8, :]
        top = block[7:-1:8, :]
        vertical = np.abs(right - left).mean() if right.size and left.shape == right.shape else 0.0
        horizontal = np.abs(bottom - top).mean() if bottom.size and top.shape == bottom.shape else 0.0
        blockiness = (vertical + horizontal) / 510.0
    else:
        blockiness = 0.0
    return np.array([
        *(rgb.mean(axis=(0, 1)) / 255.0),
        *(rgb.std(axis=(0, 1)) / 128.0),
        hsv[:, :, 1].mean() / 255.0,
        hsv[:, :, 1].std() / 128.0,
        gray.mean() / 255.0,
        gray.std() / 128.0,
        min(float(lap.var()) / 5000.0, 4.0),
        float((edges > 0).mean()),
        float((alpha > 16).mean()),
        float(border.std()) / 128.0,
        float(np.linalg.norm(center.mean(axis=0) - border.mean(axis=0))) / 441.7,
        entropy,
        blockiness,
        math.log(max(w / max(h, 1), 1e-4)),
        min(math.log2(max(w, 1)) / 16.0, 1.0),
        min(math.log2(max(h, 1)) / 16.0, 1.0),
    ], dtype=np.float32)


def pixel_features(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    rgbf = rgb.astype(np.float32) / 255.0
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[:, :, 0] /= 180.0
    hsv[:, :, 1:] /= 255.0
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32) / 255.0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    local_mean = cv2.GaussianBlur(gray, (0, 0), 2.0)
    local_sq = cv2.GaussianBlur(gray * gray, (0, 0), 2.0)
    local_std = np.sqrt(np.clip(local_sq - local_mean * local_mean, 0, None))
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edge = np.sqrt(gx * gx + gy * gy)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xx /= max(w - 1, 1)
    yy /= max(h - 1, 1)
    border_dist = np.minimum.reduce([xx, yy, 1 - xx, 1 - yy])
    border = np.concatenate([rgbf[0], rgbf[-1], rgbf[:, 0], rgbf[:, -1]], axis=0)
    border_median = np.median(border, axis=0)
    color_border_dist = np.linalg.norm(rgbf - border_median[None, None, :], axis=2) / math.sqrt(3)
    features = np.dstack([
        rgbf,
        hsv,
        lab,
        local_mean,
        local_std,
        np.clip(edge, 0, 2),
        xx,
        yy,
        border_dist,
        color_border_dist,
    ])
    return features.reshape(-1, features.shape[2]).astype(np.float32)


def binary_edge_map(channel: np.ndarray, threshold: int = 20) -> np.ndarray:
    """Return a thread-safe binary edge map without invoking OpenCV Canny.

    Some OpenCV builds abort the interpreter when Canny is called repeatedly on
    alpha arrays from different ASGI worker threads. Adjacent-pixel gradients are
    sufficient for the QA structural checks and remain deterministic.
    """
    array = np.ascontiguousarray(channel, dtype=np.uint8).astype(np.int16)
    if array.ndim != 2 or array.size == 0:
        return np.zeros(array.shape[:2], dtype=bool)
    edges = np.zeros(array.shape, dtype=bool)
    horizontal = np.abs(array[:, 1:] - array[:, :-1]) >= int(threshold)
    vertical = np.abs(array[1:, :] - array[:-1, :]) >= int(threshold)
    edges[:, 1:] |= horizontal
    edges[:, :-1] |= horizontal
    edges[1:, :] |= vertical
    edges[:-1, :] |= vertical
    return edges


def operation_qa_features(rgb: np.ndarray, alpha: np.ndarray, operation: str) -> np.ndarray:
    operation_map = {"background": 0, "extract_print": 1, "halftone": 2, "vectorize": 3}
    one_hot = np.zeros(4, dtype=np.float32)
    one_hot[operation_map.get(operation, 3)] = 1.0
    coverage = float((alpha > 16).mean())
    alpha_edge = float(binary_edge_map(alpha, 20).mean())
    return np.concatenate([image_features(rgb, alpha), one_hot, [coverage, alpha_edge]]).astype(np.float32)
