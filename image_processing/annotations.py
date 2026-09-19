"""Lightweight document annotations using OpenCV only.

The functions here intentionally avoid extra Android dependencies.  They are
used by PreviewScreen for quick stamps/shapes before a document is saved.
"""
from __future__ import annotations

from datetime import datetime
from typing import Tuple

import cv2
import numpy as np


def _load(path: str) -> np.ndarray:
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    return image


def _save(path: str, image: np.ndarray) -> None:
    if not cv2.imwrite(path, image, [int(cv2.IMWRITE_JPEG_QUALITY), 96]):
        raise IOError(f"Could not save image: {path}")


def _scale(image: np.ndarray) -> float:
    h, w = image.shape[:2]
    return max(0.7, min(2.4, min(h, w) / 900.0))


def add_text_stamp(path: str, text: str, position: str = "bottom-right") -> None:
    image = _load(path)
    h, w = image.shape[:2]
    scale = _scale(image)
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = max(1, int(round(scale * 2)))
    text = (text or "Note").strip()[:120]
    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    margin = max(14, int(min(h, w) * 0.025))

    positions = {
        "top-left": (margin, margin + th),
        "top-right": (max(margin, w - tw - margin), margin + th),
        "bottom-left": (margin, max(th + margin, h - margin)),
        "bottom-right": (max(margin, w - tw - margin), max(th + margin, h - margin)),
        "center": (max(margin, (w - tw) // 2), max(th + margin, h // 2)),
    }
    x, y = positions.get(position, positions["bottom-right"])

    pad = max(5, int(scale * 5))
    x1, y1 = max(0, x - pad), max(0, y - th - pad)
    x2, y2 = min(w - 1, x + tw + pad), min(h - 1, y + baseline + pad)
    overlay = image.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 255, 255), -1)
    image = cv2.addWeighted(overlay, 0.78, image, 0.22, 0)
    cv2.putText(image, text, (x, y), font, scale, (20, 20, 20), thickness, cv2.LINE_AA)
    _save(path, image)


def add_date_stamp(path: str, position: str = "bottom-right") -> None:
    add_text_stamp(path, datetime.now().strftime("%Y-%m-%d %H:%M"), position)


def add_shape(path: str, shape: str) -> None:
    image = _load(path)
    h, w = image.shape[:2]
    cx, cy = w // 2, h // 2
    box_w, box_h = int(w * 0.62), int(h * 0.26)
    x1, y1 = max(0, cx - box_w // 2), max(0, cy - box_h // 2)
    x2, y2 = min(w - 1, cx + box_w // 2), min(h - 1, cy + box_h // 2)
    thickness = max(2, int(min(h, w) * 0.006))
    color = (0, 0, 220)
    key = (shape or "rectangle").lower()

    if key == "circle":
        cv2.ellipse(image, (cx, cy), (box_w // 2, box_h // 2), 0, 0, 360, color, thickness, cv2.LINE_AA)
    elif key == "highlight":
        overlay = image.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (40, 230, 255), -1)
        image = cv2.addWeighted(overlay, 0.28, image, 0.72, 0)
    elif key == "arrow":
        cv2.arrowedLine(image, (x1, cy), (x2, cy), color, thickness, cv2.LINE_AA, tipLength=0.12)
    else:
        cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)
    _save(path, image)


def apply_freehand_strokes(path: str, strokes, jpeg_quality: int = 96) -> None:
    """Apply normalized freehand strokes to an image in-place.

    Each stroke is a mapping with:
      mode: ``pen`` | ``highlight`` | ``erase`` | ``restore``
      points: iterable of ``(x_norm, y_norm)`` where both values are 0..1
              and y_norm is measured from the *bottom* of the preview.
      brush: normalized brush diameter relative to the image's short side.

    Restore always samples from the image as it existed when this call started,
    making it useful as a non-destructive repair brush within one edit session.
    """
    image = _load(path)
    original = image.copy()
    h, w = image.shape[:2]
    short_side = max(1, min(h, w))

    def _pixel_points(items):
        out = []
        for item in items or ():
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            try:
                nx = max(0.0, min(1.0, float(item[0])))
                ny = max(0.0, min(1.0, float(item[1])))
            except (TypeError, ValueError):
                continue
            x = int(round(nx * (w - 1)))
            # Preview coordinates use a bottom-left origin; OpenCV is top-left.
            y = int(round((1.0 - ny) * (h - 1)))
            out.append((x, y))
        return out

    for stroke in strokes or ():
        if not isinstance(stroke, dict):
            continue
        mode = str(stroke.get("mode", "pen")).strip().lower()
        pts = _pixel_points(stroke.get("points"))
        if not pts:
            continue
        try:
            brush = float(stroke.get("brush", 0.012))
        except (TypeError, ValueError):
            brush = 0.012
        thickness = max(2, int(round(max(0.002, min(0.12, brush)) * short_side)))
        arr = np.asarray(pts, dtype=np.int32).reshape((-1, 1, 2))

        if mode == "highlight":
            overlay = image.copy()
            color = (20, 230, 255)  # yellow-ish in BGR
            if len(pts) == 1:
                cv2.circle(overlay, pts[0], max(1, thickness // 2), color, -1, cv2.LINE_AA)
            else:
                cv2.polylines(overlay, [arr], False, color, thickness, cv2.LINE_AA)
            image = cv2.addWeighted(overlay, 0.32, image, 0.68, 0)
            continue

        if mode in ("erase", "restore"):
            mask = np.zeros((h, w), dtype=np.uint8)
            if len(pts) == 1:
                cv2.circle(mask, pts[0], max(1, thickness // 2), 255, -1, cv2.LINE_AA)
            else:
                cv2.polylines(mask, [arr], False, 255, thickness, cv2.LINE_AA)

            if mode == "erase":
                # Telea inpainting removes the selected mark/object using nearby
                # page pixels instead of painting an obvious white stripe.
                radius = max(2.0, min(12.0, thickness * 0.42))
                image = cv2.inpaint(image, mask, radius, cv2.INPAINT_TELEA)
            else:
                # Feather the restore edge so it blends naturally with edits.
                sigma = max(0.8, thickness * 0.12)
                soft = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma).astype(np.float32) / 255.0
                alpha = soft[..., None]
                image = np.clip(
                    original.astype(np.float32) * alpha
                    + image.astype(np.float32) * (1.0 - alpha),
                    0,
                    255,
                ).astype(np.uint8)
            continue

        # Default pen mode: red, document-friendly annotation.
        color = (30, 30, 220)
        if len(pts) == 1:
            cv2.circle(image, pts[0], max(1, thickness // 2), color, -1, cv2.LINE_AA)
        else:
            cv2.polylines(image, [arr], False, color, thickness, cv2.LINE_AA)

    if not cv2.imwrite(path, image, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]):
        raise IOError(f"Could not save image: {path}")
