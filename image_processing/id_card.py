"""
ID / NID front-back composition for Pycam.

Purpose:
    Combine exactly two already-corrected card images (front + back)
    onto one clean A4 portrait page without stretching either card.

No new dependency is introduced: OpenCV + NumPy only.

Public API:
    combine_id_card_front_back(front_path, back_path, output_path) -> str

The output canvas is A4 at 200 DPI:
    1654 x 2339 pixels
which matches the app's existing PDF export DPI assumption.
"""

from typing import Tuple

import cv2
import numpy as np


A4_WIDTH_PX = 1654
A4_HEIGHT_PX = 2339

PAGE_MARGIN_X = 150
PAGE_MARGIN_TOP = 210
PAGE_MARGIN_BOTTOM = 210
CARD_GAP = 160

BORDER_THICKNESS = 3
BORDER_COLOR = (205, 205, 205)
PAGE_COLOR = (255, 255, 255)

MIN_CARD_SIDE = 32


def _read_image(path: str) -> np.ndarray:
    image = cv2.imread(
        path,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError(
            f"Could not read ID card image: {path}"
        )

    h, w = image.shape[:2]
    if min(h, w) < MIN_CARD_SIDE:
        raise ValueError(
            f"ID card image is too small: {path}"
        )

    return image


def _fit_size(
    image_shape,
    max_width: int,
    max_height: int,
) -> Tuple[int, int]:
    """
    Fit image inside the target box while preserving aspect ratio.
    """
    h, w = image_shape[:2]

    if w <= 0 or h <= 0:
        raise ValueError(
            "Invalid ID card image dimensions."
        )

    scale = min(
        max_width / float(w),
        max_height / float(h),
    )

    scale = max(
        scale,
        1e-6,
    )

    target_w = max(
        1,
        int(round(w * scale)),
    )
    target_h = max(
        1,
        int(round(h * scale)),
    )

    return (
        target_w,
        target_h,
    )


def _resize_for_page(
    image: np.ndarray,
    max_width: int,
    max_height: int,
) -> np.ndarray:
    target_w, target_h = _fit_size(
        image.shape,
        max_width,
        max_height,
    )

    interpolation = (
        cv2.INTER_AREA
        if (
            target_w < image.shape[1]
            or target_h < image.shape[0]
        )
        else cv2.INTER_CUBIC
    )

    return cv2.resize(
        image,
        (target_w, target_h),
        interpolation=interpolation,
    )


def _paste_centered(
    page: np.ndarray,
    card: np.ndarray,
    center_y: int,
) -> Tuple[int, int, int, int]:
    """
    Paste a card centered horizontally around center_y.

    Returns bounding box (x0, y0, x1, y1).
    """
    page_h, page_w = page.shape[:2]
    card_h, card_w = card.shape[:2]

    x0 = int(
        round(
            (page_w - card_w) / 2.0
        )
    )
    y0 = int(
        round(
            center_y - card_h / 2.0
        )
    )

    x0 = max(
        0,
        min(
            x0,
            page_w - card_w,
        ),
    )
    y0 = max(
        0,
        min(
            y0,
            page_h - card_h,
        ),
    )

    x1 = x0 + card_w
    y1 = y0 + card_h

    page[
        y0:y1,
        x0:x1,
    ] = card

    # Thin neutral border makes white cards visible on the white A4 page.
    cv2.rectangle(
        page,
        (x0, y0),
        (x1 - 1, y1 - 1),
        BORDER_COLOR,
        BORDER_THICKNESS,
        cv2.LINE_AA,
    )

    return (
        x0,
        y0,
        x1,
        y1,
    )


def combine_id_card_images(
    front_bgr: np.ndarray,
    back_bgr: np.ndarray,
) -> np.ndarray:
    """
    Create one A4 page containing front and back.

    The two cards are stacked vertically because this works for both
    landscape ID/NID cards and portrait-style cards while remaining readable
    on phone screens and PDF printouts.
    """
    if front_bgr is None or back_bgr is None:
        raise ValueError(
            "Both front and back card images are required."
        )

    available_width = (
        A4_WIDTH_PX
        - 2 * PAGE_MARGIN_X
    )

    available_height = (
        A4_HEIGHT_PX
        - PAGE_MARGIN_TOP
        - PAGE_MARGIN_BOTTOM
        - CARD_GAP
    )

    # Give each card an equal vertical slot. Aspect ratio is never forced.
    slot_height = max(
        1,
        available_height // 2,
    )

    front = _resize_for_page(
        front_bgr,
        available_width,
        slot_height,
    )
    back = _resize_for_page(
        back_bgr,
        available_width,
        slot_height,
    )

    page = np.full(
        (
            A4_HEIGHT_PX,
            A4_WIDTH_PX,
            3,
        ),
        PAGE_COLOR,
        dtype=np.uint8,
    )

    top_slot_start = PAGE_MARGIN_TOP
    bottom_slot_start = (
        PAGE_MARGIN_TOP
        + slot_height
        + CARD_GAP
    )

    front_center_y = (
        top_slot_start
        + slot_height // 2
    )

    back_center_y = (
        bottom_slot_start
        + slot_height // 2
    )

    front_box = _paste_centered(
        page,
        front,
        front_center_y,
    )

    back_box = _paste_centered(
        page,
        back,
        back_center_y,
    )

    # Clear FRONT/BACK labels make the exported A4 page print-ready.
    for label, box in (("FRONT", front_box), ("BACK", back_box)):
        x0, y0, x1, y1 = box
        label_y = max(52, y0 - 34)
        cv2.putText(
            page,
            label,
            (x0, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (70, 70, 70),
            2,
            cv2.LINE_AA,
        )

    return page


def combine_id_card_front_back(
    front_path: str,
    back_path: str,
    output_path: str,
) -> str:
    """
    Read front/back card images, compose one A4 image, and save it.

    Returns output_path on success.
    """
    front = _read_image(
        front_path
    )
    back = _read_image(
        back_path
    )

    page = combine_id_card_images(
        front,
        back,
    )

    extension = (
        output_path.rsplit(".", 1)[-1].lower()
        if "." in output_path
        else "jpg"
    )

    if extension in (
        "jpg",
        "jpeg",
    ):
        success = cv2.imwrite(
            output_path,
            page,
            [
                int(
                    cv2.IMWRITE_JPEG_QUALITY
                ),
                96,
            ],
        )
    elif extension == "png":
        success = cv2.imwrite(
            output_path,
            page,
            [
                int(
                    cv2.IMWRITE_PNG_COMPRESSION
                ),
                3,
            ],
        )
    else:
        success = cv2.imwrite(
            output_path,
            page,
        )

    if not success:
        raise IOError(
            f"Could not save combined ID card page: {output_path}"
        )

    return output_path
