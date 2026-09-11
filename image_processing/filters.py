"""
Post-crop image enhancement filters - the "make it look like a clean
scan" step real scanner apps apply after perspective correction.

Every filter takes and returns a BGR uint8 array (same convention as
the rest of image_processing/ and scanner/), so they compose directly
with `image_processing.perspective`'s output and can be swapped in the
UI without any format conversion at the call site.

Pure OpenCV/numpy, no Kivy dependency - testable against a plain array
or image file with no app running.
"""

import numpy as np
import cv2


def apply_original(image_bgr: np.ndarray) -> np.ndarray:
    """No-op filter - kept in the registry so "Original" is a normal
    entry rather than a special case the UI has to know about."""
    return image_bgr


def apply_grayscale(image_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def apply_black_white(
    image_bgr: np.ndarray, block_size: int = 35, c: int = 15
) -> np.ndarray:
    """Classic "text document" look: adaptive thresholding rather than
    a single global threshold, so it holds up across a page with
    uneven lighting (a common real-world scan condition)."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    block_size = block_size if block_size % 2 == 1 else block_size + 1  # must be odd
    binarized = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        c,
    )
    return cv2.cvtColor(binarized, cv2.COLOR_GRAY2BGR)


def apply_auto_enhance(image_bgr: np.ndarray) -> np.ndarray:
    """Auto contrast + illumination correction + mild sharpening.

    Estimating the page's overall lighting with a plain Gaussian blur
    causes visible halos around dark features (text strokes, a stamp,
    a photo) close in scale to the blur radius - the blur "sees" that
    dark content and dips there instead of representing pure lighting.
    Morphological closing with a large kernel is the standard fix used
    in document-scanning pipelines: it fills over small dark features
    with their light surroundings first, so the resulting background
    estimate reflects lighting only. That estimate is what we divide
    the lightness channel by, flattening large-scale unevenness (a
    shadow, a gradient from an angled light) while leaving small-scale
    contrast (actual text/edges) intact. Finishes with a light
    unsharp-mask pass to crisp up text edges.
    """
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)

    kernel_size = max(15, min(image_bgr.shape[:2]) // 15)
    kernel_size += 1 - kernel_size % 2  # must be odd
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    background = cv2.morphologyEx(l_channel, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), sigmaX=kernel_size / 3)

    normalized = l_channel.astype(np.float32) / (background.astype(np.float32) + 1.0)
    normalized = normalized * 200.0  # target ~200/255 lightness for "white" paper
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(normalized)

    enhanced_lab = cv2.merge((l_enhanced, a_channel, b_channel))
    enhanced_bgr = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    blurred = cv2.GaussianBlur(enhanced_bgr, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(enhanced_bgr, 1.5, blurred, -0.5, 0)
    return sharpened


def apply_color_boost(image_bgr: np.ndarray) -> np.ndarray:
    """"Magic color" style filter for documents that should stay in
    color (photos, colored forms, ID cards): boosts saturation and
    evens out lightness, without going fully to the auto-enhance
    filter's sharpening (color photos don't want the same crisp-text
    treatment a text page does)."""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    h, s, v = cv2.split(hsv)

    s = np.clip(s * 1.35, 0, 255)

    v_uint8 = v.astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    v = clahe.apply(v_uint8).astype(np.float32)

    boosted_hsv = cv2.merge((h, s, v)).astype(np.uint8)
    return cv2.cvtColor(boosted_hsv, cv2.COLOR_HSV2BGR)


FILTERS = {
    "original": apply_original,
    "auto": apply_auto_enhance,
    "grayscale": apply_grayscale,
    "bw": apply_black_white,
    "color_boost": apply_color_boost,
}

FILTER_LABELS = {
    "original": "Original",
    "auto": "Auto Enhance",
    "grayscale": "Grayscale",
    "bw": "B & W",
    "color_boost": "Color Boost",
}


def apply_filter(image_bgr: np.ndarray, filter_name: str) -> np.ndarray:
    func = FILTERS.get(filter_name)
    if func is None:
        raise ValueError(f"Unknown filter: {filter_name!r}")
    return func(image_bgr)


def rotate_image_file(path: str, clockwise: bool = True) -> None:
    """Rotate an image file 90 degrees in place - used by the
    multi-page editor (step 9) to fix a page's orientation after
    capture. Overwrites `path` directly since a page's path may
    already point at a filtered variant (e.g. `_bw.jpg`); rotating
    in place keeps whichever filter was selected intact."""
    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    rotated = cv2.rotate(
        image, cv2.ROTATE_90_CLOCKWISE if clockwise else cv2.ROTATE_90_COUNTERCLOCKWISE
    )
    cv2.imwrite(path, rotated)
