"""
Coordinate mapping between a Kivy Image widget (letterboxed,
`allow_stretch: True, keep_ratio: True`) and the original image's pixel
coordinates.

Kept as pure functions with no Kivy import so the mapping math - the
part most likely to have an off-by-one or a flipped axis - can be
tested with plain asserts instead of only being checkable by dragging
a finger around on a real device.

Coordinate conventions:
- "image space": origin top-left, y increases downward (row 0 = top -
  matches numpy/OpenCV, and how DocumentDetector's quads are expressed)
- "widget space": origin bottom-left, y increases upward (standard
  Kivy widget-local space, i.e. before adding the widget's own .pos)
"""

from typing import Tuple


def image_display_rect(
    widget_size: Tuple[float, float], image_size: Tuple[float, float]
) -> Tuple[float, float, float, float]:
    """Where the image is actually drawn inside the widget once fit
    with `allow_stretch: True, keep_ratio: True` (Kivy centers the
    scaled image, letterboxing whichever axis has leftover space).

    Returns (offset_x, offset_y, display_w, display_h) in widget-local
    coordinates.
    """
    widget_w, widget_h = widget_size
    image_w, image_h = image_size
    if image_w <= 0 or image_h <= 0 or widget_w <= 0 or widget_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)

    scale = min(widget_w / image_w, widget_h / image_h)
    display_w = image_w * scale
    display_h = image_h * scale
    offset_x = (widget_w - display_w) / 2.0
    offset_y = (widget_h - display_h) / 2.0
    return (offset_x, offset_y, display_w, display_h)


def image_to_widget(
    point: Tuple[float, float],
    widget_size: Tuple[float, float],
    image_size: Tuple[float, float],
) -> Tuple[float, float]:
    """Map an (x, y) point in image pixel space to widget-local space."""
    px, py = point
    image_w, image_h = image_size
    offset_x, offset_y, display_w, display_h = image_display_rect(widget_size, image_size)
    if image_w <= 0 or image_h <= 0:
        return (offset_x, offset_y)
    scale = display_w / image_w
    wx = offset_x + px * scale
    wy = offset_y + (image_h - py) * scale  # flip: image y-down -> widget y-up
    return (wx, wy)


def widget_to_image(
    point: Tuple[float, float],
    widget_size: Tuple[float, float],
    image_size: Tuple[float, float],
) -> Tuple[float, float]:
    """Map an (x, y) point in widget-local space back to image pixel
    space, clamped to the image's bounds (dragging a handle past the
    edge of the picture should stop it at the edge, not go negative or
    off the far side)."""
    wx, wy = point
    image_w, image_h = image_size
    offset_x, offset_y, display_w, display_h = image_display_rect(widget_size, image_size)
    if display_w <= 0 or display_h <= 0:
        return (0.0, 0.0)
    scale = display_w / image_w
    px = (wx - offset_x) / scale
    py = image_h - (wy - offset_y) / scale
    px = min(max(px, 0.0), image_w)
    py = min(max(py, 0.0), image_h)
    return (px, py)
