"""
Perspective correction - turns a photo of a document taken at an angle
into a flat, cropped, top-down rectangle.

This is the classic "four-point transform": given the document's 4
corners, compute the output rectangle size from the corners themselves
(so we don't guess an aspect ratio), then warp the source image onto
that rectangle.

Pure OpenCV/numpy, no Kivy/camera dependency - like `scanner/detector.py`,
this can be tested against a plain image file with no app running.
"""

from typing import Optional, Tuple

import numpy as np
import cv2

from scanner.detector import DocumentDetector, order_points


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Warp `image` so the quadrilateral `pts` (any order - this
    re-orders them) becomes an axis-aligned rectangle filling the
    output image."""
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = max(int(width_a), int(width_b))

    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = max(int(height_a), int(height_b))

    max_width = max(max_width, 1)
    max_height = max(max_height, 1)

    destination = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype="float32",
    )

    matrix = cv2.getPerspectiveTransform(rect, destination)
    return cv2.warpPerspective(image, matrix, (max_width, max_height))


def correct_document(
    image_bgr: np.ndarray,
    detector: Optional[DocumentDetector] = None,
) -> Tuple[np.ndarray, bool]:
    """Detect the document in `image_bgr` and return (warped, True) if
    a quadrilateral was found, or (image_bgr, False) unchanged if not -
    callers should fall back to the raw capture rather than fail the
    whole scan when detection misses on a particular photo (different
    lighting/framing than the live preview can shift the result)."""
    detector = detector or DocumentDetector()
    quad = detector.detect(image_bgr)
    if quad is None:
        return image_bgr, False
    return four_point_transform(image_bgr, quad), True


def correct_document_file(
    input_path: str,
    output_path: str,
    detector: Optional[DocumentDetector] = None,
) -> bool:
    """File-based convenience wrapper used by the scanner screen after
    a capture. Returns True if perspective correction was applied,
    False if the original image was copied through unchanged."""
    image = cv2.imread(input_path)
    if image is None:
        raise ValueError(f"Could not read image: {input_path}")
    corrected, was_corrected = correct_document(image, detector=detector)
    cv2.imwrite(output_path, corrected)
    return was_corrected
