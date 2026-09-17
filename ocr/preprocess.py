"""
OCR preprocessing helpers for Pycam.

This module is deliberately Android-independent and uses only OpenCV/NumPy,
which are already part of the existing project.

The goal is not to turn every page into harsh black/white. OCR generally
benefits from:
- reduced uneven illumination/shadows;
- improved local contrast;
- mild denoise;
- mild sharpening;
- preserved thin English/Bengali strokes.

Public helpers:
    prepare_ocr_image(input_path, output_path) -> str
    text_quality_score(text) -> float
"""

import cv2
import numpy as np


def _odd(value: int, minimum: int = 21, maximum: int = 121) -> int:
    value = int(
        np.clip(
            value,
            minimum,
            maximum,
        )
    )
    if value % 2 == 0:
        value += 1
    return min(
        value,
        maximum if maximum % 2 else maximum - 1,
    )


def _normalize_illumination(gray: np.ndarray) -> np.ndarray:
    """
    Normalize slow lighting gradients without destroying text strokes.
    """
    h, w = gray.shape[:2]
    kernel_size = _odd(
        min(h, w) // 18,
        minimum=21,
        maximum=121,
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (kernel_size, kernel_size),
    )

    # Closing suppresses dark text while retaining broad page illumination.
    background = cv2.morphologyEx(
        gray,
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

    normalized = (
        gray.astype(np.float32)
        / (
            background.astype(np.float32)
            + 1.0
        )
    ) * 225.0

    return np.clip(
        normalized,
        0,
        255,
    ).astype(np.uint8)


def _mild_unsharp(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(
        gray,
        (0, 0),
        sigmaX=1.0,
        sigmaY=1.0,
    )

    return cv2.addWeighted(
        gray,
        1.22,
        blurred,
        -0.22,
        0,
    )


def prepare_ocr_image(
    input_path: str,
    output_path: str,
) -> str:
    """
    Create an OCR-friendly grayscale PNG/JPG from one document page.

    The preprocessing is intentionally conservative so Bengali conjuncts,
    punctuation, signatures, and faint printed strokes are not destroyed.
    """
    image = cv2.imread(
        input_path,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError(
            f"Could not decode OCR image: {input_path}"
        )

    h, w = image.shape[:2]
    if h < 24 or w < 24:
        raise ValueError(
            f"OCR image is too small: {input_path}"
        )

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    normalized = _normalize_illumination(
        gray
    )

    # CLAHE improves faint text but a low clip limit avoids amplifying noise.
    clahe = cv2.createCLAHE(
        clipLimit=1.55,
        tileGridSize=(8, 8),
    )
    enhanced = clahe.apply(
        normalized
    )

    # Bilateral filtering removes camera grain while preserving character
    # boundaries.
    enhanced = cv2.bilateralFilter(
        enhanced,
        5,
        24,
        24,
    )

    enhanced = _mild_unsharp(
        enhanced
    )

    # Upscale small captures because both ML Kit and Tesseract benefit when
    # character strokes are not only a few pixels wide. Do not enlarge large
    # pages and waste memory.
    long_edge = max(
        enhanced.shape[:2]
    )
    if long_edge < 1400:
        scale = min(
            1.65,
            1400.0 / float(long_edge),
        )
        enhanced = cv2.resize(
            enhanced,
            (
                max(
                    1,
                    int(
                        round(
                            enhanced.shape[1]
                            * scale
                        )
                    ),
                ),
                max(
                    1,
                    int(
                        round(
                            enhanced.shape[0]
                            * scale
                        )
                    ),
                ),
            ),
            interpolation=cv2.INTER_CUBIC,
        )

    success = cv2.imwrite(
        output_path,
        enhanced,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            96,
        ],
    )

    if not success:
        raise IOError(
            f"Could not save OCR preprocessing image: {output_path}"
        )

    return output_path


def text_quality_score(text: str) -> float:
    """
    Lightweight text-result heuristic used only to choose between enhanced
    and original OCR passes. It is script-neutral enough for English/Bengali.
    """
    if not text:
        return 0.0

    stripped = text.strip()
    if not stripped:
        return 0.0

    printable = sum(
        1
        for ch in stripped
        if ch.isprintable()
    )
    alpha_numeric = sum(
        1
        for ch in stripped
        if ch.isalnum()
    )
    whitespace = sum(
        1
        for ch in stripped
        if ch.isspace()
    )

    # Reward usable content length and letters/digits, while not penalising
    # legitimate whitespace too strongly.
    return (
        float(printable)
        + 0.8 * float(alpha_numeric)
        + 0.08 * float(whitespace)
    )
