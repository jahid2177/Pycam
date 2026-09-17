"""
Professional document boundary detector for Pycam.

Public API intentionally preserved:
    DocumentDetector(...).detect(frame_bgr) -> np.ndarray(4, 2) | None
    order_points(points) -> TL, TR, BR, BL

Design goals:
- Android / python-for-android friendly: OpenCV + NumPy only.
- Fast enough for live preview at ~640-960 px analysis resolution.
- Better tolerance for white-on-light, shadows, uneven illumination,
  textured backgrounds, rotated pages and moderate perspective.
- Multi-candidate scoring instead of "largest contour wins".
- A4 / Letter / Legal ratios are only SOFT hints, never hard filters.
- Same detector can still be used for full-resolution re-detection after
  capture because results are always returned in source-image coordinates.

No Kivy dependency is used here.
"""

from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

DETECTION_LONG_EDGE = 760
MIN_AREA_RATIO = 0.085
MAX_AREA_RATIO = 0.985

# Candidate generation is deliberately bounded for mobile performance.
MAX_CONTOURS_PER_MAP = 28
MAX_CANDIDATES_TOTAL = 48

# Common paper aspect ratios expressed as long_side / short_side.
# They are scoring hints only.
PAPER_RATIOS = (
    1.41421356,  # A4
    1.29411765,  # US Letter
    1.64705882,  # US Legal
)


# ---------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------

def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Return four points ordered TL, TR, BR, BL.

    Uses the usual sum/difference method first, then verifies orientation.
    The function keeps the historical public API used by perspective.py,
    camera.py and crop code.
    """
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)

    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(-1)

    ordered[0] = pts[np.argmin(sums)]   # top-left
    ordered[2] = pts[np.argmax(sums)]   # bottom-right
    ordered[1] = pts[np.argmin(diffs)] # top-right
    ordered[3] = pts[np.argmax(diffs)] # bottom-left

    # Degenerate/symmetric cases can occasionally assign one point twice.
    # Fall back to angle sorting around the centroid if that happens.
    unique = np.unique(np.round(ordered, 3), axis=0)
    if len(unique) != 4:
        center = pts.mean(axis=0)
        angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
        ring = pts[np.argsort(angles)]

        # Start with the visually top-left point.
        start = int(np.argmin(ring[:, 0] + ring[:, 1]))
        ring = np.roll(ring, -start, axis=0)

        # In image coordinates clockwise TL->TR->BR->BL has positive
        # signed shoelace area with this point convention.
        candidate = ring.astype(np.float32)
        if _signed_area(candidate) < 0:
            candidate = candidate[[0, 3, 2, 1]]
        ordered = candidate

    return ordered.astype(np.float32)


def _signed_area(quad: np.ndarray) -> float:
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    x = q[:, 0]
    y = q[:, 1]
    return float(
        0.5
        * (
            np.dot(x, np.roll(y, -1))
            - np.dot(y, np.roll(x, -1))
        )
    )


def _polygon_area(quad: np.ndarray) -> float:
    return float(
        abs(
            cv2.contourArea(
                np.asarray(quad, dtype=np.float32).reshape(-1, 1, 2)
            )
        )
    )


def _side_lengths(quad: np.ndarray) -> np.ndarray:
    q = order_points(quad)
    return np.array(
        [
            np.linalg.norm(q[1] - q[0]),  # top
            np.linalg.norm(q[2] - q[1]),  # right
            np.linalg.norm(q[3] - q[2]),  # bottom
            np.linalg.norm(q[0] - q[3]),  # left
        ],
        dtype=np.float32,
    )


def _angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle ABC in degrees."""
    ba = a - b
    bc = c - b
    denom = float(np.linalg.norm(ba) * np.linalg.norm(bc)) + 1e-6
    value = float(np.dot(ba, bc) / denom)
    value = float(np.clip(value, -1.0, 1.0))
    return float(np.degrees(np.arccos(value)))


def _quad_angles(quad: np.ndarray) -> List[float]:
    q = order_points(quad)
    return [
        _angle_deg(q[3], q[0], q[1]),
        _angle_deg(q[0], q[1], q[2]),
        _angle_deg(q[1], q[2], q[3]),
        _angle_deg(q[2], q[3], q[0]),
    ]


def _estimated_page_ratio(quad: np.ndarray) -> float:
    """
    Estimate long-side / short-side ratio after perspective effects are
    reduced by averaging opposite edge lengths.
    """
    top, right, bottom, left = _side_lengths(quad)
    width = max(1.0, float((top + bottom) * 0.5))
    height = max(1.0, float((left + right) * 0.5))
    return max(width, height) / min(width, height)


def _line_distance(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    denom = float(np.linalg.norm(ab))
    if denom <= 1e-6:
        return 1e9
    return float(abs(np.cross(ab, point - a)) / denom)


def _opposite_edge_consistency(quad: np.ndarray) -> float:
    """
    1.0 means opposite sides have similar length.
    Perspective is allowed, so this is a soft score only.
    """
    top, right, bottom, left = _side_lengths(quad)

    horizontal = min(top, bottom) / max(top, bottom, 1e-6)
    vertical = min(left, right) / max(left, right, 1e-6)
    return float(np.clip((horizontal + vertical) * 0.5, 0.0, 1.0))


def _rectangularity(quad: np.ndarray) -> float:
    q = order_points(quad)
    rect = cv2.minAreaRect(q.reshape(-1, 1, 2))
    rw, rh = rect[1]
    rect_area = float(rw * rh)
    if rect_area <= 1.0:
        return 0.0
    return float(np.clip(_polygon_area(q) / rect_area, 0.0, 1.0))


def _center_score(quad: np.ndarray, w: int, h: int) -> float:
    center = order_points(quad).mean(axis=0)
    frame_center = np.array([w * 0.5, h * 0.5], dtype=np.float32)
    distance = float(np.linalg.norm(center - frame_center))
    max_distance = ((w * 0.5) ** 2 + (h * 0.5) ** 2) ** 0.5
    return float(np.clip(1.0 - distance / max(max_distance, 1.0), 0.0, 1.0))


def _paper_ratio_score(quad: np.ndarray) -> float:
    ratio = _estimated_page_ratio(quad)

    # Receipts/cards/books must still work. A common paper ratio can add
    # confidence, but an unusual ratio is never rejected by this score.
    best_error = min(abs(np.log(ratio / target)) for target in PAPER_RATIOS)
    return float(np.exp(-best_error * 2.4))


def _angle_score(quad: np.ndarray) -> float:
    """
    Perspective documents do not always have 90 degree image-space corners.
    This therefore rewards plausible angles without over-penalising skew.
    """
    angles = np.asarray(_quad_angles(quad), dtype=np.float32)
    deviations = np.abs(angles - 90.0)
    mean_dev = float(np.mean(deviations))
    worst_dev = float(np.max(deviations))

    mean_score = np.clip(1.0 - mean_dev / 55.0, 0.0, 1.0)
    worst_score = np.clip(1.0 - max(0.0, worst_dev - 18.0) / 70.0, 0.0, 1.0)
    return float(0.65 * mean_score + 0.35 * worst_score)


def _perspective_plausibility(quad: np.ndarray) -> float:
    """
    Reject bizarre trapezoids softly rather than forcing parallel edges.
    """
    q = order_points(quad)
    lengths = _side_lengths(q)
    shortest = float(np.min(lengths))
    longest = float(np.max(lengths))
    if shortest <= 1e-6:
        return 0.0

    side_balance = shortest / longest

    # Diagonals of a normal perspective rectangle should not differ wildly.
    d1 = float(np.linalg.norm(q[2] - q[0]))
    d2 = float(np.linalg.norm(q[3] - q[1]))
    diag_balance = min(d1, d2) / max(d1, d2, 1e-6)

    return float(np.clip(0.45 * side_balance + 0.55 * diag_balance, 0.0, 1.0))


def _touches_frame_too_much(quad: np.ndarray, w: int, h: int) -> bool:
    """
    Reject a contour that is essentially the camera-frame rectangle.
    A real page is still allowed to approach one or two frame edges.
    """
    q = order_points(quad)
    mx = max(2.0, w * 0.006)
    my = max(2.0, h * 0.006)

    edge_hits = 0
    edge_hits += int(np.sum(q[:, 0] <= mx))
    edge_hits += int(np.sum(q[:, 0] >= w - 1 - mx))
    edge_hits += int(np.sum(q[:, 1] <= my))
    edge_hits += int(np.sum(q[:, 1] >= h - 1 - my))

    area_ratio = _polygon_area(q) / max(float(w * h), 1.0)

    # Require both many edge contacts and very high coverage.
    return edge_hits >= 4 and area_ratio > 0.90


def _is_valid_quad(
    quad: np.ndarray,
    frame_w: int,
    frame_h: int,
    min_area_ratio: float,
    max_area_ratio: float,
) -> bool:
    if quad is None:
        return False

    try:
        q = order_points(quad)
    except (ValueError, TypeError):
        return False

    if not np.all(np.isfinite(q)):
        return False

    contour_i = np.round(q).astype(np.int32).reshape(-1, 1, 2)
    if not cv2.isContourConvex(contour_i):
        return False

    frame_area = float(frame_w * frame_h)
    area = _polygon_area(q)
    area_ratio = area / max(frame_area, 1.0)

    if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
        return False

    lengths = _side_lengths(q)
    min_side = min(frame_w, frame_h) * 0.075
    if float(np.min(lengths)) < min_side:
        return False

    # Do not reject moderate perspective. Only very acute/obtuse corners are
    # treated as implausible.
    angles = _quad_angles(q)
    if any(angle < 24.0 or angle > 156.0 for angle in angles):
        return False

    ratio = _estimated_page_ratio(q)
    # Allows receipts/business cards but rejects near-line contours.
    if ratio > 6.5:
        return False

    if _perspective_plausibility(q) < 0.22:
        return False

    if _touches_frame_too_much(q, frame_w, frame_h):
        return False

    return True


# ---------------------------------------------------------------------
# Image / edge helpers
# ---------------------------------------------------------------------

def _normalize_u8(image: np.ndarray) -> np.ndarray:
    return cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def _adaptive_canny(gray: np.ndarray) -> np.ndarray:
    median = float(np.median(gray))
    lower = int(np.clip(0.62 * median, 18, 120))
    upper = int(np.clip(1.38 * median, lower + 28, 235))
    return cv2.Canny(gray, lower, upper, L2gradient=True)


def _border_support_score(edge_image: np.ndarray, quad: np.ndarray) -> float:
    """
    Measure how much real edge evidence exists close to the 4 proposed sides.

    A filled/closed quadrilateral mask is intentionally NOT used because that
    would reward threshold blobs even when their boundary is weak. Instead we
    rasterize each edge and dilate it slightly, then inspect the source edge
    map underneath.
    """
    if edge_image is None:
        return 0.0

    h, w = edge_image.shape[:2]
    q = np.round(order_points(quad)).astype(np.int32)

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.polylines(mask, [q.reshape(-1, 1, 2)], True, 255, 1, cv2.LINE_AA)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    locations = mask > 0
    count = int(np.count_nonzero(locations))
    if count <= 0:
        return 0.0

    supported = np.count_nonzero(edge_image[locations] > 0)
    return float(np.clip(supported / float(count), 0.0, 1.0))


def _local_contrast_score(gray: np.ndarray, quad: np.ndarray) -> float:
    """
    Compare a thin band just inside vs. just outside the candidate border.

    This helps distinguish a real paper boundary from large low-contrast
    furniture/wall rectangles. It remains a soft score for white-on-white
    documents.
    """
    h, w = gray.shape[:2]
    q = np.round(order_points(quad)).astype(np.int32).reshape(-1, 1, 2)

    filled = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(filled, q, 255)

    kernel = np.ones((7, 7), dtype=np.uint8)
    inner = cv2.subtract(filled, cv2.erode(filled, kernel, iterations=2))
    outer = cv2.subtract(cv2.dilate(filled, kernel, iterations=2), filled)

    inner_values = gray[inner > 0]
    outer_values = gray[outer > 0]
    if inner_values.size < 16 or outer_values.size < 16:
        return 0.0

    contrast = abs(float(np.mean(inner_values)) - float(np.mean(outer_values)))
    return float(np.clip(contrast / 42.0, 0.0, 1.0))


def _dedupe_quads(candidates: Sequence[np.ndarray], frame_diag: float) -> List[np.ndarray]:
    """
    Remove the same page generated by multiple preprocessing branches.
    """
    unique: List[np.ndarray] = []
    center_threshold = frame_diag * 0.025
    corner_threshold = frame_diag * 0.035

    for candidate in candidates:
        q = order_points(candidate)
        duplicate = False

        for existing in unique:
            center_distance = float(
                np.linalg.norm(q.mean(axis=0) - existing.mean(axis=0))
            )
            corner_distance = float(
                np.mean(np.linalg.norm(q - existing, axis=1))
            )
            if (
                center_distance <= center_threshold
                and corner_distance <= corner_threshold
            ):
                duplicate = True
                break

        if not duplicate:
            unique.append(q)
            if len(unique) >= MAX_CANDIDATES_TOTAL:
                break

    return unique


# ---------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------

class DocumentDetector:
    def __init__(
        self,
        detection_long_edge: int = DETECTION_LONG_EDGE,
        min_area_ratio: float = MIN_AREA_RATIO,
        max_area_ratio: float = MAX_AREA_RATIO,
    ):
        self.detection_long_edge = int(max(360, detection_long_edge))
        self.min_area_ratio = float(np.clip(min_area_ratio, 0.02, 0.80))
        self.max_area_ratio = float(np.clip(max_area_ratio, 0.20, 0.999))

        if self.max_area_ratio <= self.min_area_ratio:
            self.max_area_ratio = min(0.999, self.min_area_ratio + 0.10)

        # Reuse CLAHE instead of allocating it for every frame.
        self._clahe = cv2.createCLAHE(
            clipLimit=2.1,
            tileGridSize=(8, 8),
        )

    def _resize_for_detection(
        self,
        image: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        h, w = image.shape[:2]
        long_edge = max(w, h)

        if long_edge <= self.detection_long_edge:
            return image.copy(), 1.0

        scale = self.detection_long_edge / float(long_edge)
        resized = cv2.resize(
            image,
            (
                max(1, int(round(w * scale))),
                max(1, int(round(h * scale))),
            ),
            interpolation=cv2.INTER_AREA,
        )
        return resized, scale

    def _preprocess(
        self,
        image_bgr: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Return:
            gray_original-ish, contrast luminance, denoised luminance
        """
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

        lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
        luminance = lab[:, :, 0]

        # Blend grayscale and LAB luminance. LAB often handles coloured
        # backgrounds/shadows better while grayscale preserves neutral pages.
        mixed = cv2.addWeighted(gray, 0.45, luminance, 0.55, 0)
        contrast = self._clahe.apply(mixed)

        # Small bilateral filter preserves border edges and printed strokes.
        smooth = cv2.bilateralFilter(
            contrast,
            d=5,
            sigmaColor=36,
            sigmaSpace=36,
        )

        return gray, contrast, smooth

    def _edge_maps(
        self,
        contrast: np.ndarray,
        smooth: np.ndarray,
    ) -> Iterable[Tuple[str, np.ndarray]]:
        """
        Several inexpensive complementary maps.

        No branch alone needs to solve every lighting/background case.
        """
        close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (5, 5),
        )

        # 1) Adaptive Canny: sharp visible document borders.
        canny = _adaptive_canny(smooth)
        canny = cv2.morphologyEx(
            canny,
            cv2.MORPH_CLOSE,
            close_kernel,
            iterations=2,
        )
        canny = cv2.dilate(
            canny,
            np.ones((3, 3), dtype=np.uint8),
            iterations=1,
        )
        yield "canny", canny

        # 2) Scharr magnitude: catches faint edges that Canny can fragment.
        gx = cv2.Scharr(smooth, cv2.CV_16S, 1, 0)
        gy = cv2.Scharr(smooth, cv2.CV_16S, 0, 1)
        ax = cv2.convertScaleAbs(gx)
        ay = cv2.convertScaleAbs(gy)
        gradient = cv2.addWeighted(ax, 0.5, ay, 0.5, 0)

        # Otsu chooses a frame-specific gradient threshold.
        _, gradient_bw = cv2.threshold(
            gradient,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        gradient_bw = cv2.morphologyEx(
            gradient_bw,
            cv2.MORPH_CLOSE,
            close_kernel,
            iterations=2,
        )
        yield "gradient", gradient_bw

        # 3) Adaptive local threshold: useful for white paper on white/light
        # desks and uneven illumination.
        block = 31
        adaptive = cv2.adaptiveThreshold(
            smooth,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            8,
        )
        adaptive = cv2.morphologyEx(
            adaptive,
            cv2.MORPH_CLOSE,
            close_kernel,
            iterations=2,
        )
        yield "adaptive", adaptive

        # 4) Inverse local threshold: coloured/dark documents on bright
        # backgrounds.
        adaptive_inv = cv2.bitwise_not(adaptive)
        adaptive_inv = cv2.morphologyEx(
            adaptive_inv,
            cv2.MORPH_CLOSE,
            close_kernel,
            iterations=1,
        )
        yield "adaptive_inv", adaptive_inv

    def _contour_to_quad(
        self,
        contour: np.ndarray,
        frame_w: int,
        frame_h: int,
    ) -> Optional[np.ndarray]:
        area = float(cv2.contourArea(contour))
        if area <= 0:
            return None

        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            return None

        # Multiple epsilons improve robustness for rough/shadowed borders.
        for epsilon_ratio in (
            0.010,
            0.014,
            0.018,
            0.022,
            0.028,
            0.036,
            0.046,
        ):
            approx = cv2.approxPolyDP(
                contour,
                epsilon_ratio * perimeter,
                True,
            )

            if len(approx) == 4:
                quad = order_points(
                    approx.reshape(4, 2).astype(np.float32)
                )
                if _is_valid_quad(
                    quad,
                    frame_w,
                    frame_h,
                    self.min_area_ratio,
                    self.max_area_ratio,
                ):
                    return quad

            # If approximation produces 5-8 corners, use their convex hull
            # and try a tighter approximation once. This helps pages whose
            # edge is split by a shadow/clip.
            if 5 <= len(approx) <= 8:
                hull = cv2.convexHull(approx)
                hull_perim = float(cv2.arcLength(hull, True))
                if hull_perim > 0:
                    hull_approx = cv2.approxPolyDP(
                        hull,
                        0.028 * hull_perim,
                        True,
                    )
                    if len(hull_approx) == 4:
                        quad = order_points(
                            hull_approx.reshape(4, 2).astype(np.float32)
                        )
                        if _is_valid_quad(
                            quad,
                            frame_w,
                            frame_h,
                            self.min_area_ratio,
                            self.max_area_ratio,
                        ):
                            return quad

        return None

    def _collect_quads(
        self,
        edge_map: np.ndarray,
    ) -> List[np.ndarray]:
        h, w = edge_map.shape[:2]
        frame_area = float(w * h)
        min_area = frame_area * self.min_area_ratio * 0.82

        contours, _ = cv2.findContours(
            edge_map,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        if not contours:
            return []

        contours = sorted(
            contours,
            key=cv2.contourArea,
            reverse=True,
        )[:MAX_CONTOURS_PER_MAP]

        candidates: List[np.ndarray] = []

        for contour in contours:
            contour_area = float(cv2.contourArea(contour))
            if contour_area < min_area:
                continue

            quad = self._contour_to_quad(contour, w, h)
            if quad is not None:
                candidates.append(quad)
                continue

            # Strict fallback for contours that are almost rectangular but
            # whose edges are fragmented. minAreaRect is only accepted when
            # the original contour fills the rectangle well.
            if contour_area >= frame_area * max(self.min_area_ratio, 0.14):
                rect = cv2.minAreaRect(contour)
                rw, rh = rect[1]
                rect_area = float(rw * rh)

                if rect_area > 1.0:
                    fill = contour_area / rect_area
                    if fill >= 0.80:
                        box = order_points(
                            cv2.boxPoints(rect).astype(np.float32)
                        )
                        if _is_valid_quad(
                            box,
                            w,
                            h,
                            self.min_area_ratio,
                            self.max_area_ratio,
                        ):
                            candidates.append(box)

        return candidates

    def _score_candidate(
        self,
        quad: np.ndarray,
        gray: np.ndarray,
        master_edges: np.ndarray,
        frame_w: int,
        frame_h: int,
    ) -> float:
        q = order_points(quad)
        frame_area = float(frame_w * frame_h)
        area_ratio = _polygon_area(q) / max(frame_area, 1.0)

        # Area saturates instead of dominating. This avoids always selecting
        # the largest furniture/screen contour.
        area_score = float(
            np.clip(
                (area_ratio - self.min_area_ratio)
                / max(0.48 - self.min_area_ratio, 0.08),
                0.0,
                1.0,
            )
        )

        rectangle_score = _rectangularity(q)
        angle_score = _angle_score(q)
        opposite_score = _opposite_edge_consistency(q)
        perspective_score = _perspective_plausibility(q)
        center_score = _center_score(q, frame_w, frame_h)
        ratio_score = _paper_ratio_score(q)
        edge_score = _border_support_score(master_edges, q)
        contrast_score = _local_contrast_score(gray, q)

        # Weighted multi-signal score. Paper ratio is intentionally small,
        # because receipts/cards/books remain valid documents.
        score = (
            0.22 * area_score
            + 0.16 * rectangle_score
            + 0.12 * angle_score
            + 0.09 * opposite_score
            + 0.08 * perspective_score
            + 0.08 * center_score
            + 0.07 * ratio_score
            + 0.13 * edge_score
            + 0.05 * contrast_score
        )

        # Very weak borders are suspicious, but don't hard-reject them because
        # white-on-white pages can legitimately have low contrast.
        if edge_score < 0.10 and contrast_score < 0.10:
            score *= 0.78

        # A nearly full-frame candidate is often the preview border itself.
        if area_ratio > 0.92:
            score *= 0.82

        return float(score)

    def detect(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """
        Detect the most likely document and return 4 corners in ORIGINAL
        source-image coordinates ordered TL, TR, BR, BL.

        Returns None when no plausible document exists.
        """
        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray):
            return None

        if frame_bgr.ndim != 3 or frame_bgr.shape[2] < 3:
            return None

        original_h, original_w = frame_bgr.shape[:2]
        if original_w < 40 or original_h < 40:
            return None

        # Ignore alpha if a caller ever passes BGRA.
        source = frame_bgr[:, :, :3]

        small, scale = self._resize_for_detection(source)
        h, w = small.shape[:2]

        gray, contrast, smooth = self._preprocess(small)

        candidates: List[np.ndarray] = []
        edge_maps: List[np.ndarray] = []

        for _, edge_map in self._edge_maps(contrast, smooth):
            edge_maps.append(edge_map)
            candidates.extend(self._collect_quads(edge_map))

        if not candidates:
            return None

        frame_diag = float((w * w + h * h) ** 0.5)
        candidates = _dedupe_quads(candidates, frame_diag)

        # Master edge evidence combines Canny/gradient/threshold branches.
        master_edges = np.zeros((h, w), dtype=np.uint8)
        for edge_map in edge_maps:
            master_edges = cv2.bitwise_or(master_edges, edge_map)

        best_quad: Optional[np.ndarray] = None
        best_score = -1.0

        for quad in candidates:
            if not _is_valid_quad(
                quad,
                w,
                h,
                self.min_area_ratio,
                self.max_area_ratio,
            ):
                continue

            score = self._score_candidate(
                quad,
                gray,
                master_edges,
                w,
                h,
            )

            if score > best_score:
                best_score = score
                best_quad = quad

        if best_quad is None:
            return None

        # Conservative confidence floor. Keeps low-quality random polygons
        # out while retaining difficult low-contrast documents.
        if best_score < 0.30:
            return None

        result = order_points(best_quad) / max(scale, 1e-6)

        # Clamp tiny approximation overshoots.
        result[:, 0] = np.clip(
            result[:, 0],
            0,
            original_w - 1,
        )
        result[:, 1] = np.clip(
            result[:, 1],
            0,
            original_h - 1,
        )

        return order_points(result).astype(np.float32)
