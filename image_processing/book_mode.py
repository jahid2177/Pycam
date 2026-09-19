"""Book-spread splitting and conservative curved-page flattening.

No extra dependency is required beyond OpenCV/NumPy already used by Pycam.
The functions deliberately fall back to a normal split when page-boundary
confidence is weak so a failed dewarp never destroys the captured scan.
"""

from __future__ import annotations

import os
from typing import Tuple

import cv2
import numpy as np


def _smooth_1d(values: np.ndarray, kernel: int = 41) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32).reshape(1, -1)
    kernel = max(5, int(kernel) | 1)
    return cv2.GaussianBlur(values, (kernel, 1), 0).reshape(-1)


def detect_book_gutter(image_bgr: np.ndarray) -> int:
    """Return a stable center gutter x-coordinate.

    Looks only in the central 36% of the image. A book gutter is commonly a
    darker vertical band with persistent vertical contrast; the score combines
    darkness and x-gradient energy and falls back to the geometric center.
    """
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Invalid image")

    h, w = image_bgr.shape[:2]
    if w < 80:
        return w // 2

    scale = min(1.0, 900.0 / max(h, w))
    if scale < 1.0:
        small = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        small = image_bgr

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    sh, sw = gray.shape

    # Ignore top/bottom margins where headers, fingers or background may bias.
    y0, y1 = int(sh * 0.12), int(sh * 0.88)
    roi = gray[y0:y1]
    if roi.size == 0:
        return w // 2

    col_mean = roi.mean(axis=0).astype(np.float32)
    darkness = 255.0 - col_mean
    darkness = _smooth_1d(darkness, max(15, int(sw * 0.025)))

    gx = cv2.Sobel(roi, cv2.CV_32F, 1, 0, ksize=3)
    edge_energy = np.mean(np.abs(gx), axis=0)
    edge_energy = _smooth_1d(edge_energy, max(15, int(sw * 0.02)))

    # Normalise the two signals. A real gutter is often dark and bounded by
    # vertical edges; either clue alone is too easy to confuse with text.
    def norm(v):
        lo, hi = np.percentile(v, [10, 90])
        if hi - lo < 1e-5:
            return np.zeros_like(v)
        return np.clip((v - lo) / (hi - lo), 0.0, 1.0)

    score = 0.72 * norm(darkness) + 0.28 * norm(edge_energy)
    score = _smooth_1d(score, max(11, int(sw * 0.012)))

    x0, x1 = int(sw * 0.32), int(sw * 0.68)
    if x1 <= x0:
        return w // 2
    local = score[x0:x1]
    candidate = x0 + int(np.argmax(local))

    # If central evidence is weak, the geometric centre is safer.
    centre = sw // 2
    if float(score[candidate]) < 0.52:
        candidate = centre

    x = int(round(candidate / scale)) if scale > 0 else w // 2
    return int(np.clip(x, int(w * 0.30), int(w * 0.70)))


def _page_mask(gray: np.ndarray) -> np.ndarray:
    """Best-effort mask for a bright paper page inside one book half."""
    h, w = gray.shape
    border = np.concatenate([
        gray[: max(2, h // 25), :].reshape(-1),
        gray[-max(2, h // 25):, :].reshape(-1),
        gray[:, : max(2, w // 25)].reshape(-1),
        gray[:, -max(2, w // 25):].reshape(-1),
    ])
    border_med = float(np.median(border)) if border.size else float(np.median(gray))
    page_med = float(np.percentile(gray, 70))

    # Bright-page assumption is the common scanner/book case. If there is no
    # useful separation, Otsu is still allowed to find a coherent region.
    if page_med - border_med >= 10:
        threshold = int(np.clip((page_med + border_med) * 0.5, 1, 254))
        mask = (gray >= threshold).astype(np.uint8) * 255
    else:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if mask.mean() < 90:  # ensure the likely paper is white in the mask
            mask = cv2.bitwise_not(mask)

    k = max(3, int(min(h, w) * 0.012)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.zeros_like(mask)
    largest = max(contours, key=cv2.contourArea)
    out = np.zeros_like(mask)
    cv2.drawContours(out, [largest], -1, 255, thickness=-1)
    return out


def flatten_curved_page(image_bgr: np.ndarray) -> Tuple[np.ndarray, bool]:
    """Conservatively straighten curved top/bottom page boundaries.

    This is not a neural dewarper. It performs a column-wise vertical remap only
    when a coherent paper boundary is visible across most columns. It is useful
    for mild book curvature while remaining safe on ordinary flat pages.
    """
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Invalid image")

    h, w = image_bgr.shape[:2]
    if h < 120 or w < 120:
        return image_bgr, False

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    mask = _page_mask(gray)

    top = np.full(w, np.nan, dtype=np.float32)
    bottom = np.full(w, np.nan, dtype=np.float32)
    for x in range(w):
        ys = np.flatnonzero(mask[:, x] > 0)
        if ys.size >= h * 0.35:
            top[x] = float(ys[0])
            bottom[x] = float(ys[-1])

    valid = np.isfinite(top) & np.isfinite(bottom)
    if float(valid.mean()) < 0.68:
        return image_bgr, False

    idx = np.arange(w, dtype=np.float32)
    top = np.interp(idx, idx[valid], top[valid]).astype(np.float32)
    bottom = np.interp(idx, idx[valid], bottom[valid]).astype(np.float32)

    # Smooth heavily so text/holes in the mask cannot ripple the page.
    k = max(31, int(w * 0.08)) | 1
    top = _smooth_1d(top, k)
    bottom = _smooth_1d(bottom, k)
    heights = bottom - top
    if float(np.percentile(heights, 10)) < h * 0.38:
        return image_bgr, False

    # Skip nearly-flat pages: no need to resample good pixels.
    curvature = max(float(np.ptp(top)), float(np.ptp(bottom))) / max(h, 1)
    if curvature < 0.018:
        return image_bgr, False

    target_h = int(np.clip(np.median(heights), h * 0.55, h))
    target_w = w
    x_grid = np.tile(np.arange(target_w, dtype=np.float32), (target_h, 1))
    t = np.linspace(0.0, 1.0, target_h, dtype=np.float32)[:, None]
    y_grid = top[None, :] + t * heights[None, :]

    flattened = cv2.remap(
        image_bgr,
        x_grid,
        y_grid.astype(np.float32),
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return flattened, True


def split_book_spread(image_path: str, output_dir: str) -> Tuple[str, str]:
    """Split one photographed book spread into left/right page images."""
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read book image: {image_path}")

    h, w = image.shape[:2]
    if w < 200 or h < 200:
        raise ValueError("Book image is too small")

    gutter = detect_book_gutter(image)
    # Keep a tiny overlap so characters near the binding are not clipped.
    overlap = max(2, int(w * 0.008))
    left = image[:, : min(w, gutter + overlap)].copy()
    right = image[:, max(0, gutter - overlap):].copy()

    left_flat, _ = flatten_curved_page(left)
    right_flat, _ = flatten_curved_page(right)

    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    left_path = os.path.join(output_dir, f"{stem}_book_left.jpg")
    right_path = os.path.join(output_dir, f"{stem}_book_right.jpg")

    if not cv2.imwrite(left_path, left_flat, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise IOError("Could not save left book page")
    if not cv2.imwrite(right_path, right_flat, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise IOError("Could not save right book page")
    return left_path, right_path
