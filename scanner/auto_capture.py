"""
Reliable document auto-capture controller.

Public compatibility is preserved:
    AutoCaptureController.update(quad, frame_diagonal, now)

The new `quality` argument is optional, so existing callers remain valid.

Auto capture now requires BOTH:
1. geometric stability of all four document corners; and
2. acceptable live-frame quality (sharpness, lighting, page size/visibility).

The controller itself stays independent from OpenCV/Kivy. Camera-side quality
measurements are passed in as a lightweight FrameQuality object.
"""

from collections import namedtuple
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np


AutoCaptureStatus = namedtuple(
    "AutoCaptureStatus",
    ["progress", "should_capture"],
)


@dataclass(frozen=True)
class FrameQuality:
    """
    Quality measurements produced by scanner.camera.DocumentCamera.

    Values are intentionally simple/scalar so this object is cheap to pass
    between the Camera4Kivy analysis callback and the UI thread.
    """

    sharpness: float = 0.0
    brightness: float = 0.0
    dark_ratio: float = 0.0
    bright_ratio: float = 0.0
    document_area_ratio: float = 0.0
    fully_visible: bool = False
    acceptable: bool = False
    reason: str = "Find document"


def _as_quad(
    quad: Optional[Sequence[Tuple[float, float]]]
) -> Optional[np.ndarray]:
    if quad is None:
        return None

    try:
        array = np.asarray(
            quad,
            dtype=np.float32,
        ).reshape(4, 2)
    except (TypeError, ValueError):
        return None

    if not np.all(np.isfinite(array)):
        return None

    return array


def _centroid(quad: np.ndarray) -> np.ndarray:
    return quad.mean(axis=0)


def _area(quad: np.ndarray) -> float:
    x = quad[:, 0]
    y = quad[:, 1]

    return float(
        0.5
        * abs(
            np.dot(x, np.roll(y, -1))
            - np.dot(y, np.roll(x, -1))
        )
    )


class AutoCaptureController:
    def __init__(
        self,
        stability_duration: float = 1.05,
        corner_movement_ratio: float = 0.014,
        centroid_movement_ratio: float = 0.010,
        max_area_change_ratio: float = 0.060,
        minimum_stable_updates: int = 5,
    ):
        self.stability_duration = float(
            max(0.25, stability_duration)
        )
        self.corner_movement_ratio = float(
            max(0.001, corner_movement_ratio)
        )
        self.centroid_movement_ratio = float(
            max(0.001, centroid_movement_ratio)
        )
        self.max_area_change_ratio = float(
            max(0.005, max_area_change_ratio)
        )
        self.minimum_stable_updates = int(
            max(2, minimum_stable_updates)
        )

        self._last_quad: Optional[np.ndarray] = None
        self._stable_since: Optional[float] = None
        self._stable_updates = 0

        self.feedback = "Find document"
        self.quality_ok = False

    def reset(self):
        self._last_quad = None
        self._stable_since = None
        self._stable_updates = 0
        self.feedback = "Find document"
        self.quality_ok = False

    def _reset_stability_only(self, now: float):
        """
        Reset the hold timer without forgetting the current document entirely.

        Useful when the document remains visible but is temporarily blurry or
        poorly lit. This avoids a jarring full detection reset.
        """
        self._stable_since = now
        self._stable_updates = 0

    def _is_stable(
        self,
        previous: np.ndarray,
        current: np.ndarray,
        frame_diagonal: float,
    ) -> bool:
        corner_threshold = (
            frame_diagonal
            * self.corner_movement_ratio
        )
        centroid_threshold = (
            frame_diagonal
            * self.centroid_movement_ratio
        )

        corner_distances = np.linalg.norm(
            current - previous,
            axis=1,
        )

        mean_corner_move = float(
            np.mean(corner_distances)
        )
        max_corner_move = float(
            np.max(corner_distances)
        )

        centroid_move = float(
            np.linalg.norm(
                _centroid(current)
                - _centroid(previous)
            )
        )

        old_area = _area(previous)
        new_area = _area(current)
        area_change = abs(
            new_area - old_area
        ) / max(old_area, 1.0)

        return (
            mean_corner_move
            <= corner_threshold
            and max_corner_move
            <= corner_threshold * 1.65
            and centroid_move
            <= centroid_threshold
            and area_change
            <= self.max_area_change_ratio
        )

    def update(
        self,
        quad: Optional[
            Sequence[Tuple[float, float]]
        ],
        frame_diagonal: float,
        now: float,
        quality: Optional[FrameQuality] = None,
    ) -> AutoCaptureStatus:
        """
        Update auto-capture state.

        `quality` is optional for backward compatibility. If omitted, geometry
        alone is used, matching the historical API.
        """
        current = _as_quad(quad)

        if current is None or frame_diagonal <= 0:
            self.reset()
            return AutoCaptureStatus(
                progress=0.0,
                should_capture=False,
            )

        # -------------------------------------------------------------
        # Quality gate
        # -------------------------------------------------------------
        if quality is not None:
            self.feedback = (
                quality.reason
                if quality.reason
                else "Hold steady"
            )
            self.quality_ok = bool(
                quality.acceptable
            )

            if not self.quality_ok:
                self._last_quad = current.copy()
                self._reset_stability_only(
                    float(now)
                )
                return AutoCaptureStatus(
                    progress=0.0,
                    should_capture=False,
                )
        else:
            self.quality_ok = True

        # -------------------------------------------------------------
        # Geometric stability
        # -------------------------------------------------------------
        if self._last_quad is None:
            self._last_quad = current.copy()
            self._stable_since = float(now)
            self._stable_updates = 1
            self.feedback = "Hold steady"

            return AutoCaptureStatus(
                progress=0.0,
                should_capture=False,
            )

        stable = self._is_stable(
            self._last_quad,
            current,
            frame_diagonal,
        )

        if stable:
            self._stable_updates += 1
        else:
            self._stable_since = float(now)
            self._stable_updates = 1

        self._last_quad = current.copy()

        if self._stable_since is None:
            self._stable_since = float(now)

        elapsed = max(
            0.0,
            float(now) - self._stable_since,
        )

        time_progress = min(
            elapsed
            / max(
                self.stability_duration,
                0.01,
            ),
            1.0,
        )

        update_progress = min(
            self._stable_updates
            / float(
                self.minimum_stable_updates
            ),
            1.0,
        )

        progress = min(
            time_progress,
            update_progress,
        )

        if stable:
            if progress >= 0.82:
                self.feedback = "Ready"
            else:
                self.feedback = "Hold steady"
        else:
            self.feedback = "Hold steady"

        if (
            time_progress >= 1.0
            and self._stable_updates
            >= self.minimum_stable_updates
        ):
            # Preserve the Ready feedback for the UI while clearing only the
            # geometric counters. ScannerScreen sets capture_busy immediately.
            self._last_quad = None
            self._stable_since = None
            self._stable_updates = 0
            self.feedback = "Ready"

            return AutoCaptureStatus(
                progress=1.0,
                should_capture=True,
            )

        return AutoCaptureStatus(
            progress=progress,
            should_capture=False,
        )
