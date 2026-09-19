"""
Coordinate and rotation helpers for Pycam manual crop.

Coordinate conventions:
- image space: origin top-left, y increases downward (OpenCV/NumPy)
- widget space: origin bottom-left, y increases upward (Kivy local space)

The helpers are Kivy-free so they can be tested on desktop without Android.
"""

from typing import Iterable, List, Sequence, Tuple


Point = Tuple[float, float]


def image_display_rect(
    widget_size: Tuple[float, float],
    image_size: Tuple[float, float],
) -> Tuple[float, float, float, float]:
    """
    Return the actual displayed image rectangle inside a keep-ratio widget.

    Returns:
        (offset_x, offset_y, display_width, display_height)
    """
    widget_w, widget_h = widget_size
    image_w, image_h = image_size

    if (
        image_w <= 0
        or image_h <= 0
        or widget_w <= 0
        or widget_h <= 0
    ):
        return (0.0, 0.0, 0.0, 0.0)

    scale = min(
        widget_w / image_w,
        widget_h / image_h,
    )

    display_w = image_w * scale
    display_h = image_h * scale

    offset_x = (
        widget_w - display_w
    ) / 2.0
    offset_y = (
        widget_h - display_h
    ) / 2.0

    return (
        offset_x,
        offset_y,
        display_w,
        display_h,
    )


def image_to_widget(
    point: Point,
    widget_size: Tuple[float, float],
    image_size: Tuple[float, float],
) -> Point:
    """Map image pixel coordinates to widget-local coordinates."""
    px, py = point
    image_w, image_h = image_size

    (
        offset_x,
        offset_y,
        display_w,
        display_h,
    ) = image_display_rect(
        widget_size,
        image_size,
    )

    if image_w <= 0 or image_h <= 0:
        return (
            offset_x,
            offset_y,
        )

    scale = display_w / image_w

    wx = (
        offset_x
        + px * scale
    )
    wy = (
        offset_y
        + (
            image_h - py
        ) * scale
    )

    return (
        wx,
        wy,
    )


def widget_to_image(
    point: Point,
    widget_size: Tuple[float, float],
    image_size: Tuple[float, float],
) -> Point:
    """
    Map widget-local coordinates back to image coordinates.

    The result is clamped to image bounds so a crop handle cannot leave the
    visible source image.
    """
    wx, wy = point
    image_w, image_h = image_size

    (
        offset_x,
        offset_y,
        display_w,
        display_h,
    ) = image_display_rect(
        widget_size,
        image_size,
    )

    if (
        display_w <= 0
        or display_h <= 0
        or image_w <= 0
        or image_h <= 0
    ):
        return (
            0.0,
            0.0,
        )

    scale = display_w / image_w

    px = (
        wx - offset_x
    ) / scale
    py = (
        image_h
        - (
            wy - offset_y
        ) / scale
    )

    px = min(
        max(px, 0.0),
        image_w,
    )
    py = min(
        max(py, 0.0),
        image_h,
    )

    return (
        px,
        py,
    )


def rotate_point_90(
    point: Point,
    image_size: Tuple[float, float],
    clockwise: bool,
) -> Point:
    """
    Rotate one image-space point together with a 90-degree image rotation.

    For an original image W x H:
      clockwise:     (x, y) -> (H - y, x)
      counterclockwise: (x, y) -> (y, W - x)

    Continuous image bounds are used intentionally because crop handles may
    sit exactly on W/H edges, not only integer pixel centers.
    """
    x, y = point
    width, height = image_size

    if clockwise:
        return (
            height - y,
            x,
        )

    return (
        y,
        width - x,
    )


def _order_quad(
    points: Sequence[Point],
) -> List[Point]:
    """
    Order four points TL, TR, BR, BL without NumPy/Kivy dependency.
    """
    if len(points) != 4:
        raise ValueError(
            "Exactly four crop points are required."
        )

    points = [
        (
            float(p[0]),
            float(p[1]),
        )
        for p in points
    ]

    sums = [
        x + y
        for x, y in points
    ]
    diffs = [
        y - x
        for x, y in points
    ]

    tl = points[
        sums.index(min(sums))
    ]
    br = points[
        sums.index(max(sums))
    ]
    tr = points[
        diffs.index(min(diffs))
    ]
    bl = points[
        diffs.index(max(diffs))
    ]

    ordered = [
        tl,
        tr,
        br,
        bl,
    ]

    # If a symmetric quad causes duplicate assignments, sort around center.
    if len(set(ordered)) != 4:
        cx = sum(
            p[0]
            for p in points
        ) / 4.0
        cy = sum(
            p[1]
            for p in points
        ) / 4.0

        # Avoid importing math-heavy geometry elsewhere.
        import math

        ring = sorted(
            points,
            key=lambda p: math.atan2(
                p[1] - cy,
                p[0] - cx,
            ),
        )

        start = min(
            range(4),
            key=lambda i:
                ring[i][0]
                + ring[i][1],
        )

        ring = (
            ring[start:]
            + ring[:start]
        )

        # Image-space order after atan2 may be TL,TR,BR,BL or reverse.
        if (
            ring[1][0]
            < ring[-1][0]
        ):
            ring = [
                ring[0],
                ring[3],
                ring[2],
                ring[1],
            ]

        ordered = ring

    return ordered


def rotate_quad_90(
    quad: Sequence[Point],
    image_size: Tuple[float, float],
    clockwise: bool,
) -> List[Point]:
    """
    Rotate a manual crop quad without performing any new edge detection.

    This is the key behavior needed to preserve user adjustments after Rotate
    Left / Rotate Right.
    """
    rotated = [
        rotate_point_90(
            point,
            image_size,
            clockwise,
        )
        for point in quad
    ]

    return _order_quad(
        rotated
    )


def clamp_quad(
    quad: Sequence[Point],
    image_size: Tuple[float, float],
) -> List[Point]:
    width, height = image_size

    return [
        (
            min(
                max(float(x), 0.0),
                width,
            ),
            min(
                max(float(y), 0.0),
                height,
            ),
        )
        for x, y in quad
    ]


def quad_area(quad: Sequence[Point]) -> float:
    """Return absolute polygon area for a 4-point crop quad."""
    if len(quad) != 4:
        return 0.0
    area = 0.0
    for i in range(4):
        x1, y1 = quad[i]
        x2, y2 = quad[(i + 1) % 4]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def is_valid_crop_quad(
    quad: Sequence[Point],
    image_size: Tuple[float, float],
    min_area_ratio: float = 0.01,
    min_side_ratio: float = 0.025,
) -> bool:
    """Conservative validation used before perspective crop."""
    if len(quad) != 4:
        return False
    width, height = image_size
    if width <= 0 or height <= 0:
        return False
    ordered = _order_quad(quad)
    area = quad_area(ordered)
    if area < width * height * min_area_ratio:
        return False
    import math
    min_side = min(width, height) * min_side_ratio
    for i in range(4):
        x1, y1 = ordered[i]
        x2, y2 = ordered[(i + 1) % 4]
        if math.hypot(x2 - x1, y2 - y1) < min_side:
            return False
    # Opposite winding/crossing quads produce inconsistent cross signs.
    signs = []
    for i in range(4):
        ax, ay = ordered[i]
        bx, by = ordered[(i + 1) % 4]
        cx, cy = ordered[(i + 2) % 4]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) > 1e-6:
            signs.append(cross > 0)
    return bool(signs) and all(v == signs[0] for v in signs)
