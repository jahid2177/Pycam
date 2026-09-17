"""
High-resolution document re-detection and perspective correction.

This module is used AFTER a full-resolution camera capture, so it can spend
more work than the live preview detector. It intentionally keeps the existing
public API used by Pycam:

    four_point_transform(image, pts) -> warped image
    correct_document(image_bgr, detector=None) -> (image, corrected_bool)
    correct_document_file(input_path, output_path, detector=None) -> bool

Pipeline:
    full-resolution photo
        -> higher-resolution document re-detection
        -> conservative corner/edge refinement on the original pixels
        -> geometry validation
        -> four-point homography
        -> high-quality warp

The live detector is still the same scanner.detector.DocumentDetector.
No new Android/build dependency is introduced.
"""

from typing import Optional, Tuple

import cv2
import numpy as np

from scanner.detector import DocumentDetector, order_points


# Final-capture detection can use a larger analysis image than live preview
# because scanner.py already runs this function on a background thread.
FINAL_DETECTION_LONG_EDGE = 1500

# Corner refinement is conservative. A refined corner that moves too far away
# from the detector result is rejected.
MAX_REFINEMENT_SHIFT_RATIO = 0.035

# Search band around each detected document side, expressed relative to the
# full image diagonal.
EDGE_SEARCH_BAND_RATIO = 0.012

MIN_OUTPUT_SIDE = 32


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def _polygon_area(quad: np.ndarray) -> float:
    q = np.asarray(quad, dtype=np.float32).reshape(-1, 1, 2)
    return float(abs(cv2.contourArea(q)))


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
    ba = a - b
    bc = c - b
    denom = float(np.linalg.norm(ba) * np.linalg.norm(bc)) + 1e-6
    value = float(np.dot(ba, bc) / denom)
    value = float(np.clip(value, -1.0, 1.0))
    return float(np.degrees(np.arccos(value)))


def _is_valid_quad(
    quad: np.ndarray,
    image_width: int,
    image_height: int,
    min_area_ratio: float = 0.045,
) -> bool:
    try:
        q = order_points(quad)
    except (TypeError, ValueError):
        return False

    if not np.all(np.isfinite(q)):
        return False

    if image_width <= 0 or image_height <= 0:
        return False

    contour = np.round(q).astype(np.int32).reshape(-1, 1, 2)
    if not cv2.isContourConvex(contour):
        return False

    image_area = float(image_width * image_height)
    area_ratio = _polygon_area(q) / max(image_area, 1.0)

    if area_ratio < min_area_ratio or area_ratio > 0.995:
        return False

    sides = _side_lengths(q)
    if float(np.min(sides)) < min(image_width, image_height) * 0.055:
        return False

    angles = [
        _angle_deg(q[3], q[0], q[1]),
        _angle_deg(q[0], q[1], q[2]),
        _angle_deg(q[1], q[2], q[3]),
        _angle_deg(q[2], q[3], q[0]),
    ]

    # Full-resolution photos may be taken at perspective, so keep this broad.
    if any(angle < 20.0 or angle > 160.0 for angle in angles):
        return False

    # Reject almost-line polygons.
    longest = float(np.max(sides))
    shortest = float(np.min(sides))
    if shortest <= 1e-6 or longest / shortest > 7.0:
        return False

    return True


def _clamp_quad(
    quad: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    q = order_points(quad).astype(np.float32)
    q[:, 0] = np.clip(q[:, 0], 0, max(0, width - 1))
    q[:, 1] = np.clip(q[:, 1], 0, max(0, height - 1))
    return q


# ---------------------------------------------------------------------------
# Edge / line refinement
# ---------------------------------------------------------------------------

def _point_line_distance(
    points: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
) -> np.ndarray:
    """
    Vectorised perpendicular distance from N points to the infinite line AB.
    """
    ab = b - a
    denom = float(np.linalg.norm(ab))
    if denom <= 1e-6:
        return np.full((len(points),), 1e9, dtype=np.float32)

    cross = (
        ab[0] * (a[1] - points[:, 1])
        - (a[0] - points[:, 0]) * ab[1]
    )
    return np.abs(cross) / denom


def _projection_parameter(
    points: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
) -> np.ndarray:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom <= 1e-6:
        return np.zeros((len(points),), dtype=np.float32)
    return np.dot(points - a, ab) / denom


def _fit_line_for_side(
    edge_points: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    search_band: float,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Fit a robust line to edge pixels near one predicted document side.

    Returns (point_on_line, unit_direction) or None.
    """
    if edge_points.size == 0:
        return None

    distances = _point_line_distance(edge_points, a, b)
    t = _projection_parameter(edge_points, a, b)

    # Extend slightly past each corner so the fitted edges intersect cleanly.
    mask = (
        (distances <= search_band)
        & (t >= -0.10)
        & (t <= 1.10)
    )
    selected = edge_points[mask]

    # Require enough evidence across the side.
    if len(selected) < 24:
        return None

    # Reject points that only occupy a tiny portion of the edge.
    selected_t = _projection_parameter(selected, a, b)
    if (
        float(np.percentile(selected_t, 90))
        - float(np.percentile(selected_t, 10))
        < 0.45
    ):
        return None

    points_for_fit = selected.reshape(-1, 1, 2).astype(np.float32)

    try:
        vx, vy, x0, y0 = cv2.fitLine(
            points_for_fit,
            cv2.DIST_HUBER,
            0,
            0.01,
            0.01,
        ).reshape(-1)
    except cv2.error:
        return None

    direction = np.array([vx, vy], dtype=np.float32)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-6:
        return None

    direction /= norm
    point = np.array([x0, y0], dtype=np.float32)

    # Ensure the fitted direction is not wildly different from the expected
    # detector side. This prevents nearby text lines from hijacking refinement.
    expected = b - a
    expected_norm = float(np.linalg.norm(expected))
    if expected_norm <= 1e-6:
        return None
    expected /= expected_norm

    alignment = abs(float(np.dot(direction, expected)))
    if alignment < 0.90:
        return None

    return point, direction


def _line_intersection(
    line_a: Tuple[np.ndarray, np.ndarray],
    line_b: Tuple[np.ndarray, np.ndarray],
) -> Optional[np.ndarray]:
    """
    Intersection between p + t*d and q + u*e.
    """
    p, d = line_a
    q, e = line_b

    matrix = np.array(
        [
            [d[0], -e[0]],
            [d[1], -e[1]],
        ],
        dtype=np.float32,
    )
    rhs = q - p

    det = float(np.linalg.det(matrix))
    if abs(det) < 1e-5:
        return None

    try:
        t, _ = np.linalg.solve(matrix, rhs)
    except np.linalg.LinAlgError:
        return None

    return (p + d * float(t)).astype(np.float32)


def _make_refinement_edges(image_bgr: np.ndarray) -> np.ndarray:
    """
    Build a high-resolution edge map specifically for final corner refinement.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # CLAHE helps with shadows while keeping the page boundary visible.
    clahe = cv2.createCLAHE(
        clipLimit=1.8,
        tileGridSize=(8, 8),
    )
    enhanced = clahe.apply(gray)

    # Small Gaussian blur removes isolated camera noise before Canny.
    smooth = cv2.GaussianBlur(
        enhanced,
        (5, 5),
        0,
    )

    median = float(np.median(smooth))
    low = int(np.clip(median * 0.55, 18, 115))
    high = int(np.clip(median * 1.45, low + 32, 240))

    edges = cv2.Canny(
        smooth,
        low,
        high,
        L2gradient=True,
    )

    # Join tiny edge gaps but do not thicken the map aggressively.
    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (3, 3),
        ),
        iterations=1,
    )

    return edges


def refine_document_quad(
    image_bgr: np.ndarray,
    initial_quad: np.ndarray,
) -> np.ndarray:
    """
    Refine the detector's four sides against original-resolution edge pixels.

    The detector result is always the fallback. Refinement is accepted only
    when all four fitted lines are plausible and every refined corner remains
    close to its original detector corner.
    """
    if image_bgr is None:
        return order_points(initial_quad)

    height, width = image_bgr.shape[:2]
    initial = _clamp_quad(
        initial_quad,
        width,
        height,
    )

    if not _is_valid_quad(
        initial,
        width,
        height,
    ):
        return initial

    edges = _make_refinement_edges(image_bgr)

    # Extract edge coordinates as (x, y).
    ys, xs = np.nonzero(edges)
    if len(xs) < 100:
        return initial

    edge_points = np.column_stack(
        (xs, ys)
    ).astype(np.float32)

    diagonal = max(
        float((width * width + height * height) ** 0.5),
        1.0,
    )
    search_band = max(
        3.0,
        diagonal * EDGE_SEARCH_BAND_RATIO,
    )

    # TL->TR, TR->BR, BR->BL, BL->TL
    fitted_lines = []
    for index in range(4):
        a = initial[index]
        b = initial[(index + 1) % 4]

        line = _fit_line_for_side(
            edge_points,
            a,
            b,
            search_band,
        )
        if line is None:
            return initial

        fitted_lines.append(line)

    # Each corner is the intersection of its previous and next side.
    refined = []
    for index in range(4):
        previous_line = fitted_lines[(index - 1) % 4]
        current_line = fitted_lines[index]

        point = _line_intersection(
            previous_line,
            current_line,
        )
        if point is None:
            return initial

        refined.append(point)

    refined = order_points(
        np.asarray(refined, dtype=np.float32)
    )
    refined = _clamp_quad(
        refined,
        width,
        height,
    )

    # Do not accept a line-fit result that moved the polygon too far.
    shifts = np.linalg.norm(
        refined - initial,
        axis=1,
    )
    if float(np.max(shifts)) > diagonal * MAX_REFINEMENT_SHIFT_RATIO:
        return initial

    if not _is_valid_quad(
        refined,
        width,
        height,
    ):
        return initial

    # Prevent refinement from radically changing detected area.
    initial_area = max(_polygon_area(initial), 1.0)
    refined_area = _polygon_area(refined)
    area_change = abs(
        refined_area - initial_area
    ) / initial_area

    if area_change > 0.18:
        return initial

    return refined.astype(np.float32)


# ---------------------------------------------------------------------------
# Perspective warp
# ---------------------------------------------------------------------------

def _output_dimensions(
    rect: np.ndarray,
) -> Tuple[int, int]:
    """
    Estimate rectified dimensions from actual opposite edge lengths.

    We use the larger of the two opposite edges, which preserves useful
    resolution when perspective makes the far edge shorter.
    """
    tl, tr, br, bl = order_points(rect)

    top = float(np.linalg.norm(tr - tl))
    bottom = float(np.linalg.norm(br - bl))
    left = float(np.linalg.norm(bl - tl))
    right = float(np.linalg.norm(br - tr))

    width = int(round(max(top, bottom)))
    height = int(round(max(left, right)))

    return (
        max(width, MIN_OUTPUT_SIDE),
        max(height, MIN_OUTPUT_SIDE),
    )


def four_point_transform(
    image: np.ndarray,
    pts: np.ndarray,
) -> np.ndarray:
    """
    Warp `image` so quadrilateral `pts` becomes a flat rectangle.

    This function remains compatible with the manual Crop screen.
    """
    if image is None or not isinstance(image, np.ndarray):
        raise ValueError("A valid image array is required.")

    if image.ndim < 2:
        raise ValueError("Invalid image dimensions.")

    height, width = image.shape[:2]
    rect = _clamp_quad(
        np.asarray(pts, dtype=np.float32),
        width,
        height,
    )

    if not _is_valid_quad(
        rect,
        width,
        height,
        min_area_ratio=0.0001,
    ):
        raise ValueError(
            "The crop points do not form a valid quadrilateral."
        )

    output_width, output_height = _output_dimensions(rect)

    destination = np.array(
        [
            [0.0, 0.0],
            [output_width - 1.0, 0.0],
            [output_width - 1.0, output_height - 1.0],
            [0.0, output_height - 1.0],
        ],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(
        rect.astype(np.float32),
        destination,
    )

    # INTER_CUBIC is useful for captured documents/text. BORDER_REPLICATE
    # avoids thin black triangles caused by sub-pixel sampling at the edge.
    warped = cv2.warpPerspective(
        image,
        matrix,
        (output_width, output_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

    return warped


# ---------------------------------------------------------------------------
# Final-capture correction
# ---------------------------------------------------------------------------

def _make_final_detector() -> DocumentDetector:
    """
    A higher-resolution instance than the live Camera4Kivy detector.

    Constructor arguments are already supported by scanner.detector, so this
    introduces no new public dependency or API.
    """
    return DocumentDetector(
        detection_long_edge=FINAL_DETECTION_LONG_EDGE,
        min_area_ratio=0.055,
        max_area_ratio=0.99,
    )


def correct_document(
    image_bgr: np.ndarray,
    detector: Optional[DocumentDetector] = None,
) -> Tuple[np.ndarray, bool]:
    """
    Re-detect and perspective-correct a full-resolution captured document.

    Returns:
        (warped_image, True)  when a valid document was found
        (original_image, False) when final detection fails

    The original image is deliberately preserved on failure so one difficult
    frame never breaks the scan session.
    """
    if image_bgr is None or not isinstance(image_bgr, np.ndarray):
        raise ValueError("A valid BGR image is required.")

    if image_bgr.ndim != 3 or image_bgr.shape[2] < 3:
        raise ValueError("Expected a BGR color image.")

    height, width = image_bgr.shape[:2]

    final_detector = detector or _make_final_detector()
    quad = final_detector.detect(image_bgr)

    if quad is None:
        return image_bgr, False

    quad = _clamp_quad(
        quad,
        width,
        height,
    )

    if not _is_valid_quad(
        quad,
        width,
        height,
    ):
        return image_bgr, False

    refined_quad = refine_document_quad(
        image_bgr,
        quad,
    )

    try:
        warped = four_point_transform(
            image_bgr,
            refined_quad,
        )
    except (ValueError, cv2.error):
        # Conservative fallback to the original detector quad.
        try:
            warped = four_point_transform(
                image_bgr,
                quad,
            )
        except (ValueError, cv2.error):
            return image_bgr, False

    return warped, True


def correct_document_file(
    input_path: str,
    output_path: str,
    detector: Optional[DocumentDetector] = None,
) -> bool:
    """
    File wrapper used by ScannerScreen after a camera capture.

    Returns True if high-resolution perspective correction was applied,
    False if no reliable document was found and the original image was written
    unchanged.
    """
    image = cv2.imread(
        input_path,
        cv2.IMREAD_COLOR,
    )
    if image is None:
        raise ValueError(
            f"Could not read image: {input_path}"
        )

    corrected, was_corrected = correct_document(
        image,
        detector=detector,
    )

    # Preserve high JPEG quality for the editor/filter pipeline. PNG output
    # remains lossless if the caller requests a .png path.
    extension = PathLikeSuffix(output_path)

    if extension in (".jpg", ".jpeg"):
        success = cv2.imwrite(
            output_path,
            corrected,
            [int(cv2.IMWRITE_JPEG_QUALITY), 96],
        )
    elif extension == ".png":
        success = cv2.imwrite(
            output_path,
            corrected,
            [int(cv2.IMWRITE_PNG_COMPRESSION), 3],
        )
    else:
        success = cv2.imwrite(
            output_path,
            corrected,
        )

    if not success:
        raise IOError(
            f"Could not write corrected image: {output_path}"
        )

    return was_corrected


def PathLikeSuffix(path: str) -> str:
    """
    Tiny local helper to avoid adding pathlib work inside repeated calls.
    """
    if not path:
        return ""

    dot = path.rfind(".")
    if dot < 0:
        return ""

    return path[dot:].lower()
