"""
Professional post-crop image enhancement filters for Pycam.

Public API preserved:
    apply_filter(image_bgr, filter_name) -> BGR uint8 image
    rotate_image_file(path, clockwise=True)

Available modes:
    Original
    Auto
    Document
    Magic Color
    Grayscale
    B&W
    Photo

Design goals:
- Pure OpenCV + NumPy only; no new Android/build dependency.
- Reduce uneven illumination/shadows without destroying thin text.
- Avoid excessive sharpening and repeated destructive processing.
- Keep every filter output in BGR uint8 format so the existing PreviewScreen
  can cache/save outputs without any caller changes.
"""

from typing import Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _validate_bgr(image_bgr: np.ndarray) -> np.ndarray:
    if image_bgr is None or not isinstance(image_bgr, np.ndarray):
        raise ValueError("A valid image array is required.")

    if image_bgr.ndim == 2:
        return cv2.cvtColor(
            image_bgr.astype(np.uint8),
            cv2.COLOR_GRAY2BGR,
        )

    if image_bgr.ndim != 3:
        raise ValueError("Unsupported image dimensions.")

    if image_bgr.shape[2] == 4:
        image_bgr = cv2.cvtColor(
            image_bgr,
            cv2.COLOR_BGRA2BGR,
        )
    elif image_bgr.shape[2] != 3:
        raise ValueError("Expected a BGR/BGRA image.")

    if image_bgr.dtype != np.uint8:
        image_bgr = np.clip(
            image_bgr,
            0,
            255,
        ).astype(np.uint8)

    return image_bgr


def _odd_kernel(
    value: int,
    minimum: int = 3,
    maximum: int = 151,
) -> int:
    value = int(
        np.clip(
            value,
            minimum,
            maximum,
        )
    )
    if value % 2 == 0:
        value += 1
    return min(value, maximum if maximum % 2 == 1 else maximum - 1)


def _document_kernel_size(
    image_bgr: np.ndarray,
    divisor: int = 18,
) -> int:
    h, w = image_bgr.shape[:2]
    short_edge = max(1, min(h, w))
    return _odd_kernel(
        short_edge // divisor,
        minimum=21,
        maximum=121,
    )


def _estimate_illumination(
    channel: np.ndarray,
    kernel_size: int,
) -> np.ndarray:
    """
    Estimate slowly varying page illumination.

    Morphological closing fills dark text strokes before Gaussian smoothing,
    making the estimate follow shadows/lighting rather than printed content.
    """
    kernel_size = _odd_kernel(
        kernel_size,
        minimum=15,
        maximum=151,
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (kernel_size, kernel_size),
    )

    background = cv2.morphologyEx(
        channel,
        cv2.MORPH_CLOSE,
        kernel,
    )

    background = cv2.GaussianBlur(
        background,
        (0, 0),
        sigmaX=max(
            2.0,
            kernel_size / 4.0,
        ),
        sigmaY=max(
            2.0,
            kernel_size / 4.0,
        ),
    )

    return background


def _normalize_illumination_gray(
    gray: np.ndarray,
    target_white: float = 225.0,
) -> np.ndarray:
    kernel_size = _odd_kernel(
        min(gray.shape[:2]) // 18,
        minimum=21,
        maximum=121,
    )

    background = _estimate_illumination(
        gray,
        kernel_size,
    )

    normalized = (
        gray.astype(np.float32)
        / (
            background.astype(np.float32)
            + 1.0
        )
    ) * float(target_white)

    return np.clip(
        normalized,
        0,
        255,
    ).astype(np.uint8)


def _normalize_lab_lightness(
    image_bgr: np.ndarray,
    target_white: float = 218.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2LAB,
    )
    l_channel, a_channel, b_channel = cv2.split(lab)

    kernel_size = _document_kernel_size(
        image_bgr,
        divisor=18,
    )
    background = _estimate_illumination(
        l_channel,
        kernel_size,
    )

    normalized = (
        l_channel.astype(np.float32)
        / (
            background.astype(np.float32)
            + 1.0
        )
    ) * float(target_white)

    normalized = np.clip(
        normalized,
        0,
        255,
    ).astype(np.uint8)

    return (
        normalized,
        a_channel,
        b_channel,
    )


def _clahe(
    channel: np.ndarray,
    clip_limit: float = 1.8,
) -> np.ndarray:
    clahe = cv2.createCLAHE(
        clipLimit=float(clip_limit),
        tileGridSize=(8, 8),
    )
    return clahe.apply(channel)


def _mild_unsharp(
    image_bgr: np.ndarray,
    amount: float = 0.35,
    sigma: float = 1.2,
) -> np.ndarray:
    blurred = cv2.GaussianBlur(
        image_bgr,
        (0, 0),
        sigmaX=float(sigma),
        sigmaY=float(sigma),
    )

    return cv2.addWeighted(
        image_bgr,
        1.0 + float(amount),
        blurred,
        -float(amount),
        0,
    )


def _gray_world_white_balance(
    image_bgr: np.ndarray,
    strength: float = 0.65,
) -> np.ndarray:
    """
    Conservative gray-world white balance.

    Strength below 1.0 avoids strongly changing intentional colored paper,
    stamps, signatures, and photographs.
    """
    image = image_bgr.astype(np.float32)

    means = image.reshape(-1, 3).mean(axis=0)
    global_mean = float(np.mean(means))

    scales = global_mean / np.maximum(
        means,
        1.0,
    )
    scales = (
        1.0
        + (
            scales - 1.0
        ) * float(strength)
    )

    balanced = image * scales.reshape(
        1,
        1,
        3,
    )

    return np.clip(
        balanced,
        0,
        255,
    ).astype(np.uint8)


def _gamma_adjust(
    image_bgr: np.ndarray,
    gamma: float,
) -> np.ndarray:
    gamma = float(max(0.1, gamma))
    inverse = 1.0 / gamma

    table = np.array(
        [
            (
                (i / 255.0) ** inverse
            ) * 255.0
            for i in range(256)
        ],
        dtype=np.uint8,
    )

    return cv2.LUT(
        image_bgr,
        table,
    )


def _image_statistics(
    image_bgr: np.ndarray,
) -> Tuple[float, float, float]:
    hsv = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2HSV,
    )

    saturation = float(
        np.mean(hsv[:, :, 1])
    )
    brightness = float(
        np.mean(hsv[:, :, 2])
    )

    gray = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2GRAY,
    )
    contrast = float(
        np.std(gray)
    )

    return (
        saturation,
        brightness,
        contrast,
    )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def apply_original(
    image_bgr: np.ndarray,
) -> np.ndarray:
    """
    Keep the original pixels unchanged.

    Returning a copy prevents an accidental in-place operation by a caller
    from modifying the cached original image.
    """
    image = _validate_bgr(
        image_bgr
    )
    return image.copy()


def apply_grayscale(
    image_bgr: np.ndarray,
) -> np.ndarray:
    image = _validate_bgr(
        image_bgr
    )

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    # Very light local contrast improvement preserves handwriting and faint
    # pencil strokes better than a raw grayscale conversion.
    gray = _clahe(
        gray,
        clip_limit=1.35,
    )

    return cv2.cvtColor(
        gray,
        cv2.COLOR_GRAY2BGR,
    )


def apply_black_white(
    image_bgr: np.ndarray,
    block_size: int = 0,
    c: int = 11,
) -> np.ndarray:
    """
    Smart document B&W.

    First removes large lighting/shadow gradients, then applies local
    thresholding. A tiny morphological cleanup removes isolated noise while
    preserving thin characters and handwriting.
    """
    image = _validate_bgr(
        image_bgr
    )

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    normalized = _normalize_illumination_gray(
        gray,
        target_white=232.0,
    )

    # Mild denoise before thresholding. Bilateral keeps text edges.
    normalized = cv2.bilateralFilter(
        normalized,
        5,
        28,
        28,
    )

    if block_size <= 0:
        block_size = _odd_kernel(
            min(
                normalized.shape[:2]
            ) // 22,
            minimum=25,
            maximum=71,
        )
    else:
        block_size = _odd_kernel(
            block_size,
            minimum=15,
            maximum=101,
        )

    binary = cv2.adaptiveThreshold(
        normalized,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        int(c),
    )

    # Remove only tiny isolated black/white specks. Larger kernels can eat
    # punctuation and Bengali/English thin strokes, so keep this at 2x2.
    cleanup = np.ones(
        (2, 2),
        dtype=np.uint8,
    )
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cleanup,
        iterations=1,
    )

    return cv2.cvtColor(
        binary,
        cv2.COLOR_GRAY2BGR,
    )


def apply_document(
    image_bgr: np.ndarray,
) -> np.ndarray:
    """
    Clean color-document mode.

    Stronger background/illumination normalization than Auto, but keeps
    colored ink, stamps, signatures, diagrams and highlights.
    """
    image = _validate_bgr(
        image_bgr
    )

    balanced = _gray_world_white_balance(
        image,
        strength=0.45,
    )

    (
        normalized_l,
        a_channel,
        b_channel,
    ) = _normalize_lab_lightness(
        balanced,
        target_white=228.0,
    )

    normalized_l = _clahe(
        normalized_l,
        clip_limit=1.65,
    )

    # Push only already-bright paper pixels a little closer to white.
    light = normalized_l.astype(
        np.float32
    )
    bright_mask = light >= 175.0
    light[
        bright_mask
    ] = (
        light[bright_mask]
        + (
            255.0
            - light[bright_mask]
        ) * 0.34
    )
    normalized_l = np.clip(
        light,
        0,
        255,
    ).astype(np.uint8)

    lab = cv2.merge(
        (
            normalized_l,
            a_channel,
            b_channel,
        )
    )

    result = cv2.cvtColor(
        lab,
        cv2.COLOR_LAB2BGR,
    )

    result = _mild_unsharp(
        result,
        amount=0.28,
        sigma=1.15,
    )

    return result


def apply_magic_color(
    image_bgr: np.ndarray,
) -> np.ndarray:
    """
    CamScanner-style vivid color document mode.

    Improves white balance/lightness and selectively boosts muted colors.
    Saturation is capped to avoid neon-looking stamps/highlighters.
    """
    image = _validate_bgr(
        image_bgr
    )

    balanced = _gray_world_white_balance(
        image,
        strength=0.62,
    )

    (
        normalized_l,
        a_channel,
        b_channel,
    ) = _normalize_lab_lightness(
        balanced,
        target_white=216.0,
    )

    normalized_l = _clahe(
        normalized_l,
        clip_limit=1.55,
    )

    lab = cv2.merge(
        (
            normalized_l,
            a_channel,
            b_channel,
        )
    )

    lit = cv2.cvtColor(
        lab,
        cv2.COLOR_LAB2BGR,
    )

    hsv = cv2.cvtColor(
        lit,
        cv2.COLOR_BGR2HSV,
    ).astype(np.float32)

    h, s, v = cv2.split(
        hsv
    )

    # More boost for weak colors, less for already-saturated ones.
    saturation_gain = (
        1.34
        - 0.20 * (
            s / 255.0
        )
    )
    s = np.clip(
        s * saturation_gain,
        0,
        235,
    )

    v = np.clip(
        v * 1.025,
        0,
        255,
    )

    hsv = cv2.merge(
        (
            h,
            s,
            v,
        )
    ).astype(np.uint8)

    result = cv2.cvtColor(
        hsv,
        cv2.COLOR_HSV2BGR,
    )

    return _mild_unsharp(
        result,
        amount=0.20,
        sigma=1.0,
    )


def apply_photo(
    image_bgr: np.ndarray,
) -> np.ndarray:
    """
    Natural-photo mode.

    Suitable for ID cards/passports/photos embedded in documents. Unlike
    Document mode it does not aggressively whiten the background.
    """
    image = _validate_bgr(
        image_bgr
    )

    balanced = _gray_world_white_balance(
        image,
        strength=0.35,
    )

    lab = cv2.cvtColor(
        balanced,
        cv2.COLOR_BGR2LAB,
    )
    l_channel, a_channel, b_channel = cv2.split(
        lab
    )

    l_channel = _clahe(
        l_channel,
        clip_limit=1.25,
    )

    lab = cv2.merge(
        (
            l_channel,
            a_channel,
            b_channel,
        )
    )

    result = cv2.cvtColor(
        lab,
        cv2.COLOR_LAB2BGR,
    )

    # Tiny saturation lift only.
    hsv = cv2.cvtColor(
        result,
        cv2.COLOR_BGR2HSV,
    ).astype(np.float32)

    h, s, v = cv2.split(
        hsv
    )
    s = np.clip(
        s * 1.07,
        0,
        255,
    )

    result = cv2.cvtColor(
        cv2.merge(
            (
                h,
                s,
                v,
            )
        ).astype(np.uint8),
        cv2.COLOR_HSV2BGR,
    )

    return _mild_unsharp(
        result,
        amount=0.14,
        sigma=1.0,
    )


def apply_auto_enhance(
    image_bgr: np.ndarray,
) -> np.ndarray:
    """
    Automatic mode.

    Chooses processing strength from simple image statistics rather than
    blindly applying one aggressive preset:
    - very low saturation + high contrast -> Document-like cleanup;
    - normal color documents -> balanced illumination + local contrast;
    - strongly saturated/photo-like pages -> gentler Photo enhancement.
    """
    image = _validate_bgr(
        image_bgr
    )

    saturation, brightness, contrast = (
        _image_statistics(
            image
        )
    )

    # Photo/ID-card-like content: preserve natural tonal transitions.
    if saturation >= 78.0:
        result = apply_photo(
            image
        )

        # Underexposed photo/card gets a small brightness correction.
        if brightness < 105.0:
            result = _gamma_adjust(
                result,
                gamma=1.12,
            )

        return result

    # Mostly neutral/text-heavy page.
    if saturation <= 38.0:
        result = apply_document(
            image
        )
    else:
        balanced = _gray_world_white_balance(
            image,
            strength=0.48,
        )

        (
            normalized_l,
            a_channel,
            b_channel,
        ) = _normalize_lab_lightness(
            balanced,
            target_white=220.0,
        )

        normalized_l = _clahe(
            normalized_l,
            clip_limit=1.45,
        )

        result = cv2.cvtColor(
            cv2.merge(
                (
                    normalized_l,
                    a_channel,
                    b_channel,
                )
            ),
            cv2.COLOR_LAB2BGR,
        )

        result = _mild_unsharp(
            result,
            amount=0.22,
            sigma=1.1,
        )

    # Global tonal correction only when genuinely needed.
    if brightness < 82.0:
        result = _gamma_adjust(
            result,
            gamma=1.16,
        )
    elif brightness > 222.0 and contrast < 35.0:
        result = _gamma_adjust(
            result,
            gamma=0.94,
        )

    return result


# Historical function name kept for callers/code that may still use it.
def apply_color_boost(
    image_bgr: np.ndarray,
) -> np.ndarray:
    return apply_magic_color(
        image_bgr
    )


# ---------------------------------------------------------------------------
# Registry consumed dynamically by ui.preview.PreviewScreen
# ---------------------------------------------------------------------------

FILTERS = {
    "original": apply_original,
    "auto": apply_auto_enhance,
    "document": apply_document,
    "magic_color": apply_magic_color,
    "grayscale": apply_grayscale,
    "bw": apply_black_white,
    "photo": apply_photo,

    # Backward-compatible alias for any previously cached/selected key.
    "color_boost": apply_magic_color,
}


# Only user-facing modes belong here. PreviewScreen iterates this mapping to
# create its filter buttons, so no Preview/KV modification is required.
FILTER_LABELS = {
    "original": "Original",
    "auto": "Auto",
    "document": "Document",
    "magic_color": "Magic Color",
    "grayscale": "Grayscale",
    "bw": "B&W",
    "photo": "Photo",
}


def apply_filter(
    image_bgr: np.ndarray,
    filter_name: str,
) -> np.ndarray:
    func = FILTERS.get(
        filter_name
    )

    if func is None:
        raise ValueError(
            f"Unknown filter: {filter_name!r}"
        )

    result = func(
        image_bgr
    )

    return _validate_bgr(
        result
    )


# ---------------------------------------------------------------------------
# Existing editor rotation helper
# ---------------------------------------------------------------------------

def rotate_image_file(
    path: str,
    clockwise: bool = True,
) -> None:
    """
    Rotate an image file 90 degrees in place.

    Existing EditorScreen behaviour is preserved.
    """
    image = cv2.imread(
        path,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError(
            f"Could not read image: {path}"
        )

    rotated = cv2.rotate(
        image,
        (
            cv2.ROTATE_90_CLOCKWISE
            if clockwise
            else cv2.ROTATE_90_COUNTERCLOCKWISE
        ),
    )

    success = cv2.imwrite(
        path,
        rotated,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            96,
        ],
    )

    if not success:
        raise IOError(
            f"Could not write rotated image: {path}"
        )
