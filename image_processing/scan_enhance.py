"""Scan-quality enhancement helpers for captured document pages.

OpenCV/NumPy only so it remains python-for-android friendly.
The functions are intentionally conservative: they normalize uneven page
illumination and recover local contrast without aggressively destroying text.
"""

from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np


def _odd_kernel_for(shape, fraction: float = 0.08, minimum: int = 31, maximum: int = 151) -> int:
    h, w = shape[:2]
    k = int(max(h, w) * float(fraction))
    k = max(minimum, min(maximum, k))
    if k % 2 == 0:
        k += 1
    return k


def normalize_page_illumination(image_bgr: np.ndarray) -> np.ndarray:
    """Reduce broad shadows/uneven lighting while keeping document colors."""
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Empty image")

    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    k = _odd_kernel_for(l.shape, fraction=0.075, minimum=31, maximum=151)
    background = cv2.GaussianBlur(l, (k, k), 0)
    background = np.maximum(background, 8)

    # Division normalization flattens slow illumination gradients but retains
    # fine text/edge detail much better than hard thresholding.
    corrected_l = cv2.divide(l, background, scale=205.0)

    # Bring the page luminance back to a natural range and improve local text
    # contrast. CLAHE is deliberately mild to avoid noisy halos.
    p5, p95 = np.percentile(corrected_l, [5, 95])
    if p95 > p5 + 8:
        corrected_l = np.clip(
            (corrected_l.astype(np.float32) - p5) * (220.0 / (p95 - p5)) + 22.0,
            0,
            255,
        ).astype(np.uint8)

    clahe = cv2.createCLAHE(clipLimit=1.35, tileGridSize=(8, 8))
    corrected_l = clahe.apply(corrected_l)

    merged = cv2.merge([corrected_l, a, b])
    result = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    # Mild sharpening only. Scanner text benefits while avoiding overshoot.
    blurred = cv2.GaussianBlur(result, (0, 0), 0.8)
    result = cv2.addWeighted(result, 1.12, blurred, -0.12, 0)
    return result


def enhance_document_file(input_path: str, output_path: Optional[str] = None) -> str:
    """Enhance one captured document and return the written file path."""
    if not input_path or not os.path.isfile(input_path):
        raise FileNotFoundError(input_path)

    image = cv2.imread(input_path, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode image: {input_path}")

    enhanced = normalize_page_illumination(image)
    target = output_path or input_path
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)

    ext = os.path.splitext(target)[1].lower()
    if ext in (".jpg", ".jpeg"):
        ok = cv2.imwrite(target, enhanced, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    elif ext == ".png":
        ok = cv2.imwrite(target, enhanced, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])
    else:
        ok = cv2.imwrite(target, enhanced)

    if not ok:
        raise IOError(f"Could not write enhanced scan: {target}")
    return target
