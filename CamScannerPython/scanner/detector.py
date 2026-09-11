"""
Document edge/corner detection.

Pure OpenCV + numpy - this module knows nothing about Kivy or the
camera. That's deliberate: `scanner/camera.py` feeds it frames and
draws the result, but the detection math itself is testable on its
own (e.g. against a folder of sample photos) without booting the app.

Algorithm (standard "document scanner" pipeline):
  1. Downscale for speed (detection resolution, not capture resolution)
  2. Grayscale + blur to suppress texture noise
  3. Canny edge detection + dilation to close small gaps in the outline
  4. Find contours, keep the largest few, approximate each to a polygon
  5. Accept the first 4-point convex polygon that's still a large
     fraction of the frame (rejects small rectangular objects in shot)
  6. Order corners (top-left, top-right, bottom-right, bottom-left) and
     rescale back to the original frame's coordinates

`order_points` is exported separately because step 6 (perspective
correction) needs the exact same corner ordering to build its
transform matrix.
"""

from typing import Optional

import numpy as np
import cv2


DETECTION_WIDTH = 480  # frames are downscaled to this width before analysis
MIN_AREA_RATIO = 0.15  # detected quad must cover at least this fraction of the frame


def order_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as [top-left, top-right, bottom-right, bottom-left].

    Uses the standard sum/difference trick: top-left has the smallest
    x+y, bottom-right the largest x+y; top-right has the smallest
    y-x, bottom-left the largest y-x.
    """
    pts = pts.reshape(4, 2).astype("float32")
    ordered = np.zeros((4, 2), dtype="float32")

    s = pts.sum(axis=1)
    ordered[0] = pts[np.argmin(s)]  # top-left
    ordered[2] = pts[np.argmax(s)]  # bottom-right

    diff = np.diff(pts, axis=1).reshape(-1)
    ordered[1] = pts[np.argmin(diff)]  # top-right
    ordered[3] = pts[np.argmax(diff)]  # bottom-left

    return ordered


class DocumentDetector:
    def __init__(
        self,
        detection_width: int = DETECTION_WIDTH,
        min_area_ratio: float = MIN_AREA_RATIO,
    ):
        self.detection_width = detection_width
        self.min_area_ratio = min_area_ratio

    def detect(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Return a (4, 2) float32 array of corner points in the
        ORIGINAL frame's coordinate space, or None if no document-like
        quadrilateral was found."""
        original_h, original_w = frame_bgr.shape[:2]
        if original_w == 0 or original_h == 0:
            return None

        scale = self.detection_width / float(original_w)
        small = cv2.resize(
            frame_bgr,
            (self.detection_width, max(1, int(original_h * scale))),
            interpolation=cv2.INTER_AREA,
        )

        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

        contours, _ = cv2.findContours(
            edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None

        small_area = small.shape[0] * small.shape[1]
        min_area = small_area * self.min_area_ratio

        candidates = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

        for contour in candidates:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                corners_small = order_points(approx)
                return corners_small / scale  # back to original frame scale

        return None
