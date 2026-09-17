"""
Stable auto-capture controller.

Auto capture only fires after the whole document quadrilateral remains
stable for long enough. It compares each corner, center and area so a
rotating or changing page cannot be considered stable merely because its
centroid has not moved much.
"""

from collections import namedtuple
from typing import Optional, Sequence, Tuple

import numpy as np

AutoCaptureStatus = namedtuple(
    "AutoCaptureStatus",
    ["progress", "should_capture"],
)


def _as_quad(
    quad: Optional[Sequence[Tuple[float, float]]]
) -> Optional[np.ndarray]:
    if quad is None:
        return None

    try:
        return np.asarray(
            quad,
            dtype=np.float32,
        ).reshape(4, 2)
    except (TypeError, ValueError):
        return None


def _centroid(quad: np.ndarray) -> np.ndarray:
    return quad.mean(axis=0)


def _area(quad: np.ndarray) -> float:
    x = quad[:, 0]
    y = quad[:, 1]
    return float(
        0.5
        * abs(
            np.dot(x, np.roll(y, 1))
            - np.dot(y, np.roll(x, 1))
        )
    )


class AutoCaptureController:
    def __init__(
        self,
        stability_duration: float = 1.35,
        corner_movement_ratio: float = 0.014,
        centroid_movement_ratio: float = 0.010,
        max_area_change_ratio: float = 0.065,
        minimum_stable_updates: int = 5,
    ):
        self.stability_duration = float(stability_duration)
        self.corner_movement_ratio = float(corner_movement_ratio)
        self.centroid_movement_ratio = float(
            centroid_movement_ratio
        )
        self.max_area_change_ratio = float(
            max_area_change_ratio
        )
        self.minimum_stable_updates = int(
            max(2, minimum_stable_updates)
        )

        self._last_quad: Optional[np.ndarray] = None
        self._stable_since: Optional[float] = None
        self._stable_updates = 0

    def reset(self):
        self._last_quad = None
        self._stable_since = None
        self._stable_updates = 0

    def _is_stable(
        self,
        previous: np.ndarray,
        current: np.ndarray,
        frame_diagonal: float,
    ) -> bool:
        corner_threshold = (
            frame_diagonal * self.corner_movement_ratio
        )
        centroid_threshold = (
            frame_diagonal * self.centroid_movement_ratio
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
            mean_corner_move <= corner_threshold
            and max_corner_move <= corner_threshold * 1.65
            and centroid_move <= centroid_threshold
            and area_change <= self.max_area_change_ratio
        )

    def update(
        self,
        quad: Optional[Sequence[Tuple[float, float]]],
        frame_diagonal: float,
        now: float,
    ) -> AutoCaptureStatus:
        current = _as_quad(quad)

        if current is None or frame_diagonal <= 0:
            self.reset()
            return AutoCaptureStatus(
                progress=0.0,
                should_capture=False,
            )

        if self._last_quad is None:
            self._last_quad = current.copy()
            self._stable_since = now
            self._stable_updates = 1
            return AutoCaptureStatus(
                progress=0.0,
                should_capture=False,
            )

        if self._is_stable(
            self._last_quad,
            current,
            frame_diagonal,
        ):
            self._stable_updates += 1
        else:
            self._stable_since = now
            self._stable_updates = 1

        self._last_quad = current.copy()

        if self._stable_since is None:
            self._stable_since = now

        elapsed = max(
            0.0,
            now - self._stable_since,
        )
        time_progress = min(
            elapsed / max(
                self.stability_duration,
                0.01,
            ),
            1.0,
        )
        update_progress = min(
            self._stable_updates
            / float(self.minimum_stable_updates),
            1.0,
        )
        progress = min(
            time_progress,
            update_progress,
        )

        if (
            time_progress >= 1.0
            and self._stable_updates
            >= self.minimum_stable_updates
        ):
            self.reset()
            return AutoCaptureStatus(
                progress=1.0,
                should_capture=True,
            )

        return AutoCaptureStatus(
            progress=progress,
            should_capture=False,
        )
