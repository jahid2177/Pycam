"""Passport photo processing utilities for Pycam.

Provides:
- country/size presets
- optional face-aware crop with safe center-crop fallback
- simple background replacement using GrabCut
- 300-DPI output sizing
- 4x6 / A4 print-sheet generation
"""

from __future__ import annotations

import math
from typing import Dict, Tuple, Optional, List

import cv2
import numpy as np


PRESETS: Dict[str, Tuple[float, float]] = {
    "bangladesh": (35.0, 45.0),
    "india": (35.0, 45.0),
    "schengen": (35.0, 45.0),
    "uk": (35.0, 45.0),
    "usa": (51.0, 51.0),
}

BACKGROUND_COLORS = {
    "white": (255, 255, 255),
    "blue": (235, 205, 120),  # BGR soft passport blue
    "light_gray": (238, 238, 238),
}


def _mm_to_px(mm: float, dpi: int = 300) -> int:
    return max(1, int(round(mm / 25.4 * dpi)))


def get_preset_mm(name: str) -> Tuple[float, float]:
    key = str(name or "bangladesh").strip().lower()
    return PRESETS.get(key, PRESETS["bangladesh"])


def _detect_face(image: np.ndarray):
    """Best-effort Haar face detection. Returns (x,y,w,h) or None."""
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(40, 40),
        )
        if len(faces) == 0:
            return None
        # Prefer the largest face because passport photos normally contain one subject.
        return max(faces, key=lambda r: int(r[2]) * int(r[3]))
    except Exception:
        return None


def _detect_eye_pair(image: np.ndarray, face) -> Optional[List[Tuple[float, float]]]:
    """Return the best left/right eye-center pair inside *face*, if available."""
    if face is None:
        return None
    try:
        x, y, fw, fh = [int(v) for v in face]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Eyes should be in roughly the upper 60% of the face rectangle.
        roi = gray[y:y + max(1, int(fh * 0.65)), x:x + fw]
        if roi.size == 0:
            return None
        cascade_path = cv2.data.haarcascades + "haarcascade_eye.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return None
        eyes = cascade.detectMultiScale(
            cv2.equalizeHist(roi),
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(max(10, fw // 10), max(8, fh // 12)),
        )
        centers = []
        for ex, ey, ew, eh in eyes:
            centers.append((x + ex + ew / 2.0, y + ey + eh / 2.0, ew * eh))
        if len(centers) < 2:
            return None

        best = None
        best_score = -1.0
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                a, b = centers[i], centers[j]
                dx = abs(a[0] - b[0])
                dy = abs(a[1] - b[1])
                # Reject vertically stacked / implausibly close detections.
                if dx < fw * 0.22 or dx > fw * 0.85 or dy > fh * 0.18:
                    continue
                score = dx - dy * 1.8 + min(a[2], b[2]) * 0.001
                if score > best_score:
                    best_score = score
                    best = [(a[0], a[1]), (b[0], b[1])]
        if not best:
            return None
        best.sort(key=lambda pt: pt[0])
        return best
    except Exception:
        return None


def _rotate_from_eye_pair(image: np.ndarray, eyes) -> Tuple[np.ndarray, float]:
    if not eyes or len(eyes) != 2:
        return image.copy(), 0.0
    left, right = eyes
    angle = math.degrees(math.atan2(right[1] - left[1], right[0] - left[0]))
    # Ignore tiny tilt and implausibly large corrections.
    if abs(angle) < 0.8 or abs(angle) > 18.0:
        return image.copy(), 0.0
    center = ((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    h, w = image.shape[:2]
    rotated = cv2.warpAffine(
        image,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated, float(angle)


def _crop_to_ratio(image: np.ndarray, target_ratio: float) -> np.ndarray:
    """Face-aware passport framing with center-crop fallback.

    When a face is found, the crop aims to place the eyes around 40% from
    the top and keep enough shoulder/chest area below the chin.  This is a
    visual framing aid, not a claim of government-photo compliance.
    """
    h, w = image.shape[:2]
    face = _detect_face(image)

    if face is None:
        cx, cy = w / 2.0, h / 2.0
        current_ratio = w / float(h)
        if current_ratio >= target_ratio:
            crop_h = h
            crop_w = min(w, int(round(crop_h * target_ratio)))
        else:
            crop_w = w
            crop_h = min(h, int(round(crop_w / target_ratio)))
        x0 = int(round(cx - crop_w / 2.0))
        y0 = int(round(cy - crop_h / 2.0))
        x0 = max(0, min(x0, w - crop_w))
        y0 = max(0, min(y0, h - crop_h))
        return image[y0:y0 + crop_h, x0:x0 + crop_w].copy()

    x, y, fw, fh = [float(v) for v in face]
    eyes = _detect_eye_pair(image, face)
    face_cx = x + fw / 2.0

    # Keep the face width around 45-52% of the final portrait width.
    crop_w = max(fw / 0.48, fw * 1.75)
    crop_h = crop_w / target_ratio
    # Also keep face height around half of the output height.
    crop_h = max(crop_h, fh / 0.52)
    crop_w = crop_h * target_ratio

    # Fit the crop inside the available source image without distorting ratio.
    scale = min(1.0, w / crop_w, h / crop_h)
    crop_w *= scale
    crop_h *= scale

    if eyes:
        eye_y = (eyes[0][1] + eyes[1][1]) / 2.0
        desired_eye_y = crop_h * 0.40
        y0 = eye_y - desired_eye_y
    else:
        # Face top around 16% from top gives a conservative head margin.
        y0 = y - crop_h * 0.16

    x0 = face_cx - crop_w / 2.0
    x0 = max(0.0, min(x0, w - crop_w))
    y0 = max(0.0, min(y0, h - crop_h))
    x1 = int(round(x0 + crop_w))
    y1 = int(round(y0 + crop_h))
    return image[int(round(y0)):y1, int(round(x0)):x1].copy()


def analyze_passport_alignment(image: np.ndarray) -> Dict[str, object]:
    """Return non-biometric framing metrics used for user guidance."""
    face = _detect_face(image)
    if face is None:
        return {
            "face_detected": False,
            "eyes_detected": False,
            "roll_degrees": 0.0,
            "eye_line_ratio": None,
            "face_height_ratio": None,
            "guidance": "Face not detected; center-crop fallback used.",
        }
    x, y, fw, fh = [float(v) for v in face]
    h, w = image.shape[:2]
    eyes = _detect_eye_pair(image, face)
    roll = 0.0
    eye_ratio = None
    if eyes:
        left, right = eyes
        roll = math.degrees(math.atan2(right[1] - left[1], right[0] - left[0]))
        eye_ratio = ((left[1] + right[1]) / 2.0) / max(1.0, float(h))
    face_ratio = fh / max(1.0, float(h))
    notes = []
    if eyes and abs(roll) > 5.0:
        notes.append("Head tilt auto-corrected")
    if face_ratio < 0.24:
        notes.append("Face is small; use a closer photo for best ID framing")
    elif face_ratio > 0.72:
        notes.append("Face is very close; more shoulder area may be needed")
    if not eyes:
        notes.append("Eyes not confidently detected; face-based alignment used")
    if not notes:
        notes.append("Face and eye alignment look suitable for automatic framing")
    return {
        "face_detected": True,
        "eyes_detected": bool(eyes),
        "roll_degrees": float(roll),
        "eye_line_ratio": eye_ratio,
        "face_height_ratio": float(face_ratio),
        "guidance": "; ".join(notes),
    }


def auto_align_face(image: np.ndarray) -> Tuple[np.ndarray, Dict[str, object]]:
    """Best-effort eye-line leveling before passport crop."""
    metrics = analyze_passport_alignment(image)
    face = _detect_face(image)
    eyes = _detect_eye_pair(image, face) if face is not None else None
    aligned, applied = _rotate_from_eye_pair(image, eyes)
    metrics = dict(metrics)
    metrics["applied_rotation_degrees"] = float(applied)
    return aligned, metrics


def replace_background(image: np.ndarray, color_name: str = "white") -> np.ndarray:
    """Best-effort foreground extraction with GrabCut; returns original on failure."""
    color = BACKGROUND_COLORS.get(str(color_name).strip().lower(), BACKGROUND_COLORS["white"])
    h, w = image.shape[:2]
    if h < 80 or w < 80:
        return image.copy()

    try:
        mask = np.zeros((h, w), np.uint8)
        bg_model = np.zeros((1, 65), np.float64)
        fg_model = np.zeros((1, 65), np.float64)
        mx = max(2, int(w * 0.035))
        my = max(2, int(h * 0.025))
        rect = (mx, my, max(1, w - 2 * mx), max(1, h - 2 * my))
        cv2.grabCut(image, mask, rect, bg_model, fg_model, 4, cv2.GC_INIT_WITH_RECT)
        fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
        # Feather boundaries slightly.
        alpha = cv2.GaussianBlur((fg * 255).astype(np.uint8), (0, 0), 1.2).astype(np.float32) / 255.0
        alpha = alpha[..., None]
        bg = np.empty_like(image)
        bg[:] = color
        out = image.astype(np.float32) * alpha + bg.astype(np.float32) * (1.0 - alpha)
        return np.clip(out, 0, 255).astype(np.uint8)
    except Exception:
        return image.copy()


def create_passport_photo(
    image: np.ndarray,
    preset: str = "bangladesh",
    background: str = "white",
    dpi: int = 300,
) -> Tuple[np.ndarray, Tuple[float, float]]:
    width_mm, height_mm = get_preset_mm(preset)
    target_ratio = width_mm / float(height_mm)
    aligned, _ = auto_align_face(image)
    cropped = _crop_to_ratio(aligned, target_ratio)
    processed = replace_background(cropped, background)
    out_w, out_h = _mm_to_px(width_mm, dpi), _mm_to_px(height_mm, dpi)
    output = cv2.resize(processed, (out_w, out_h), interpolation=cv2.INTER_CUBIC)
    return output, (width_mm, height_mm)


def create_print_sheet(photo: np.ndarray, sheet: str = "4x6", dpi: int = 300) -> np.ndarray:
    key = str(sheet or "4x6").strip().lower()
    if key == "a4":
        sw, sh = _mm_to_px(210, dpi), _mm_to_px(297, dpi)
    else:
        sw, sh = int(round(4 * dpi)), int(round(6 * dpi))

    canvas = np.full((sh, sw, 3), 255, np.uint8)
    ph, pw = photo.shape[:2]
    gap = max(12, int(0.08 * dpi))
    margin = max(gap, int(0.12 * dpi))

    cols = max(1, (sw - 2 * margin + gap) // (pw + gap))
    rows = max(1, (sh - 2 * margin + gap) // (ph + gap))

    total_w = cols * pw + (cols - 1) * gap
    total_h = rows * ph + (rows - 1) * gap
    start_x = max(margin, (sw - total_w) // 2)
    start_y = max(margin, (sh - total_h) // 2)

    for r in range(rows):
        for c in range(cols):
            x = start_x + c * (pw + gap)
            y = start_y + r * (ph + gap)
            if x + pw <= sw and y + ph <= sh:
                canvas[y:y + ph, x:x + pw] = photo
                cv2.rectangle(canvas, (x, y), (x + pw - 1, y + ph - 1), (210, 210, 210), 1)
    return canvas
