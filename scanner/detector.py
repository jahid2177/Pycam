"""
Robust document boundary detection for Pycam.

Goals:
- Fast enough for live Camera4Kivy analysis.
- More tolerant of low contrast, shadows, textured pages and perspective.
- Reject small/implausible quadrilaterals.
- Return corners in source-image pixel coordinates in this order:
  top-left, top-right, bottom-right, bottom-left.

The detector deliberately has no Kivy dependency.
"""

from typing import Optional, Iterable, List, Tuple

import cv2
import numpy as np


DETECTION_LONG_EDGE = 720
MIN_AREA_RATIO = 0.12
MAX_AREA_RATIO = 0.98


def order_points(pts: np.ndarray) -> np.ndarray:
    """Return 4 points ordered TL, TR, BR, BL."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)

    ordered = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)

    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(d)]
    ordered[3] = pts[np.argmax(d)]
    return ordered


def _polygon_area(quad: np.ndarray) -> float:
    return float(abs(cv2.contourArea(quad.astype(np.float32))))


def _side_lengths(quad: np.ndarray) -> np.ndarray:
    q = order_points(quad)
    return np.array(
        [
            np.linalg.norm(q[1] - q[0]),
            np.linalg.norm(q[2] - q[1]),
            np.linalg.norm(q[3] - q[2]),
            np.linalg.norm(q[0] - q[3]),
        ],
        dtype=np.float32,
    )


def _angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle ABC in degrees."""
    ba = a - b
    bc = c - b
    denom = (np.linalg.norm(ba) * np.linalg.norm(bc)) + 1e-6
    cosv = float(np.dot(ba, bc) / denom)
    cosv = max(-1.0, min(1.0, cosv))
    return float(np.degrees(np.arccos(cosv)))


def _quad_angles(quad: np.ndarray) -> List[float]:
    q = order_points(quad)
    return [
        _angle_deg(q[3], q[0], q[1]),
        _angle_deg(q[0], q[1], q[2]),
        _angle_deg(q[1], q[2], q[3]),
        _angle_deg(q[2], q[3], q[0]),
    ]


def _touches_frame_too_much(quad: np.ndarray, w: int, h: int) -> bool:
    """Reject contours that are basically the whole camera frame."""
    q = order_points(quad)
    margin_x = max(2.0, w * 0.008)
    margin_y = max(2.0, h * 0.008)

    near_left = np.sum(q[:, 0] <= margin_x)
    near_right = np.sum(q[:, 0] >= w - margin_x)
    near_top = np.sum(q[:, 1] <= margin_y)
    near_bottom = np.sum(q[:, 1] >= h - margin_y)

    return (near_left + near_right + near_top + near_bottom) >= 4


def _is_valid_quad(
    quad: np.ndarray,
    frame_w: int,
    frame_h: int,
    min_area_ratio: float,
    max_area_ratio: float,
) -> bool:
    if quad is None or len(quad) != 4:
        return False

    q = order_points(quad)
    contour = q.reshape(-1, 1, 2).astype(np.float32)

    if not cv2.isContourConvex(contour.astype(np.int32)):
        return False

    frame_area = float(frame_w * frame_h)
    area = _polygon_area(q)
    ratio = area / max(frame_area, 1.0)

    if ratio < min_area_ratio or ratio > max_area_ratio:
        return False

    lengths = _side_lengths(q)
    min_side = min(frame_w, frame_h) * 0.08
    if float(np.min(lengths)) < min_side:
        return False

    # Perspective documents can have non-90-degree corners, but very
    # acute/obtuse shapes are usually furniture, shadows or screen edges.
    angles = _quad_angles(q)
    if any(angle < 35.0 or angle > 145.0 for angle in angles):
        return False

    # Reject degenerate long/thin quadrilaterals.
    bbox = cv2.boundingRect(contour.astype(np.int32))
    _, _, bw, bh = bbox
    if bw <= 0 or bh <= 0:
        return False
    aspect = max(bw, bh) / float(max(1, min(bw, bh)))
    if aspect > 3.8:
        return False

    if _touches_frame_too_much(q, frame_w, frame_h):
        return False

    return True


def _quad_score(quad: np.ndarray, frame_w: int, frame_h: int) -> float:
    """
    Higher is better.

    Area is the strongest signal, then we prefer a contour that fills
    its bounding box well and has document-like (not extreme) angles.
    """
    q = order_points(quad)
    frame_area = float(frame_w * frame_h)
    area_ratio = _polygon_area(q) / max(frame_area, 1.0)

    x, y, bw, bh = cv2.boundingRect(q.reshape(-1, 1, 2).astype(np.int32))
    rect_fill = _polygon_area(q) / float(max(1, bw * bh))

    angles = _quad_angles(q)
    angle_penalty = sum(abs(a - 90.0) for a in angles) / 360.0
    angle_score = max(0.0, 1.0 - angle_penalty)

    # Slight preference for documents near the middle of the frame.
    center = q.mean(axis=0)
    frame_center = np.array([frame_w / 2.0, frame_h / 2.0], dtype=np.float32)
    center_dist = np.linalg.norm(center - frame_center)
    max_dist = (frame_w ** 2 + frame_h ** 2) ** 0.5 / 2.0
    center_score = max(0.0, 1.0 - center_dist / max(max_dist, 1.0))

    return (
        area_ratio * 0.62
        + min(rect_fill, 1.0) * 0.18
        + angle_score * 0.12
        + center_score * 0.08
    )


class DocumentDetector:
    def __init__(
        self,
        detection_long_edge: int = DETECTION_LONG_EDGE,
        min_area_ratio: float = MIN_AREA_RATIO,
        max_area_ratio: float = MAX_AREA_RATIO,
    ):
        self.detection_long_edge = int(max(320, detection_long_edge))
        self.min_area_ratio = float(min_area_ratio)
        self.max_area_ratio = float(max_area_ratio)

    def _resize_for_detection(self, image: np.ndarray) -> Tuple[np.ndarray, float]:
        h, w = image.shape[:2]
        long_edge = max(w, h)

        if long_edge <= self.detection_long_edge:
            return image.copy(), 1.0

        scale = self.detection_long_edge / float(long_edge)
        resized = cv2.resize(
            image,
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, scale

    @staticmethod
    def _edge_maps(image_bgr: np.ndarray) -> Iterable[np.ndarray]:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

        # Local contrast helps with white paper on light backgrounds.
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)

        # Bilateral keeps page borders sharper than a heavy Gaussian blur.
        smooth = cv2.bilateralFilter(contrast, 7, 45, 45)

        median = float(np.median(smooth))
        lower = int(max(20, 0.66 * median))
        upper = int(min(220, max(lower + 30, 1.33 * median)))

        canny = cv2.Canny(smooth, lower, upper)
        canny = cv2.morphologyEx(
            canny,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            iterations=2,
        )
        canny = cv2.dilate(canny, np.ones((3, 3), np.uint8), iterations=1)
        yield canny

        # Adaptive threshold catches low-contrast paper boundaries that
        # Canny can miss under uneven room lighting.
        adaptive = cv2.adaptiveThreshold(
            smooth,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            9,
        )
        adaptive = cv2.morphologyEx(
            adaptive,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            iterations=2,
        )
        yield adaptive

        adaptive_inv = cv2.bitwise_not(adaptive)
        adaptive_inv = cv2.morphologyEx(
            adaptive_inv,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
            iterations=1,
        )
        yield adaptive_inv

    def _collect_quads(self, edge_map: np.ndarray) -> List[np.ndarray]:
        h, w = edge_map.shape[:2]
        contours, _ = cv2.findContours(
            edge_map, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return []

        frame_area = float(w * h)
        min_area = frame_area * self.min_area_ratio

        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:30]
        candidates: List[np.ndarray] = []

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < min_area:
                continue

            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 0:
                continue

            # Try several approximation strengths because document edges
            # may be broken/noisy depending on lighting and background.
            for epsilon_ratio in (0.012, 0.016, 0.020, 0.025, 0.032, 0.040):
                approx = cv2.approxPolyDP(
                    contour, epsilon_ratio * perimeter, True
                )

                if len(approx) != 4:
                    continue

                quad = order_points(approx.reshape(4, 2))
                if _is_valid_quad(
                    quad,
                    w,
                    h,
                    self.min_area_ratio,
                    self.max_area_ratio,
                ):
                    candidates.append(quad)
                    break

            # Fallback: for a strong almost-rectangular contour, use its
            # minimum-area rectangle. Keep this strict to avoid false boxes.
            if area >= frame_area * 0.25:
                rect = cv2.minAreaRect(contour)
                box = cv2.boxPoints(rect)
                hull_area = _polygon_area(order_points(box))
                fill = area / max(hull_area, 1.0)

                if fill >= 0.76:
                    quad = order_points(box)
                    if _is_valid_quad(
                        quad,
                        w,
                        h,
                        self.min_area_ratio,
                        self.max_area_ratio,
                    ):
                        candidates.append(quad)

        return candidates

    def detect(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Detect the most likely document and return its four corners."""
        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray):
            return None
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] < 3:
            return None

        original_h, original_w = frame_bgr.shape[:2]
        if original_w < 20 or original_h < 20:
            return None

        small, scale = self._resize_for_detection(frame_bgr)
        h, w = small.shape[:2]

        best_quad = None
        best_score = -1.0

        for edge_map in self._edge_maps(small):
            for quad in self._collect_quads(edge_map):
                score = _quad_score(quad, w, h)
                if score > best_score:
                    best_score = score
                    best_quad = quad

        if best_quad is None:
            return None

        result = best_quad / max(scale, 1e-6)

        # Clamp to original image bounds; this prevents tiny approximation
        # overshoots from creating invalid perspective-transform points.
        result[:, 0] = np.clip(result[:, 0], 0, original_w - 1)
        result[:, 1] = np.clip(result[:, 1], 0, original_h - 1)

        return order_points(result).astype(np.float32)
