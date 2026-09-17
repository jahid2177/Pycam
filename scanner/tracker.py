"""
Temporal document quadrilateral tracker for Pycam.

This module deliberately depends only on NumPy plus scanner.detector's
point-order helper, so it remains safe for Android/python-for-android.

The live detector may produce slightly different corners on every frame.
DocumentTracker associates each new quadrilateral with the currently
tracked document, rejects one-frame contour switches, predicts small
motion, and applies adaptive exponential smoothing.

Public API:
    tracker = DocumentTracker()
    tracked = tracker.update(quad_or_none, frame_size, timestamp)
    tracker.reset()

`tracked` is either None or a float32 (4, 2) array ordered:
    top-left, top-right, bottom-right, bottom-left
"""

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

from scanner.detector import order_points


SEARCHING = "SEARCHING"
DOCUMENT_FOUND = "DOCUMENT_FOUND"
TRACKING = "TRACKING"
STABILIZING = "STABILIZING"


def _quad(
    points: Optional[Sequence[Sequence[float]]],
) -> Optional[np.ndarray]:
    if points is None:
        return None

    try:
        q = np.asarray(points, dtype=np.float32).reshape(4, 2)
    except (TypeError, ValueError):
        return None

    if not np.all(np.isfinite(q)):
        return None

    return order_points(q).astype(np.float32)


def _centroid(q: np.ndarray) -> np.ndarray:
    return q.mean(axis=0)


def _area(q: np.ndarray) -> float:
    x = q[:, 0]
    y = q[:, 1]
    return float(
        0.5
        * abs(
            np.dot(x, np.roll(y, -1))
            - np.dot(y, np.roll(x, -1))
        )
    )


def _perimeter(q: np.ndarray) -> float:
    rolled = np.roll(q, -1, axis=0)
    return float(np.sum(np.linalg.norm(rolled - q, axis=1)))


def _mean_corner_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.linalg.norm(a - b, axis=1)))


@dataclass
class TrackingMetrics:
    state: str = SEARCHING
    confidence: float = 0.0
    motion_ratio: float = 1.0
    area_change_ratio: float = 1.0
    missed_frames: int = 0
    stable_frames: int = 0


class DocumentTracker:
    """
    Lightweight temporal tracker for a detected document quadrilateral.

    The detector remains the source of truth. This class only decides whether
    a detection belongs to the same document and how quickly the overlay
    should move toward it.
    """

    def __init__(
        self,
        max_missed_frames: int = 6,
        switch_confirmation_frames: int = 3,
        stable_motion_ratio: float = 0.010,
        normal_motion_ratio: float = 0.040,
        switch_motion_ratio: float = 0.105,
        max_same_document_area_change: float = 0.34,
    ):
        self.max_missed_frames = int(max(1, max_missed_frames))
        self.switch_confirmation_frames = int(
            max(2, switch_confirmation_frames)
        )
        self.stable_motion_ratio = float(stable_motion_ratio)
        self.normal_motion_ratio = float(normal_motion_ratio)
        self.switch_motion_ratio = float(switch_motion_ratio)
        self.max_same_document_area_change = float(
            max_same_document_area_change
        )

        self.metrics = TrackingMetrics()

        self._tracked: Optional[np.ndarray] = None
        self._last_observation: Optional[np.ndarray] = None
        self._velocity = np.zeros((4, 2), dtype=np.float32)
        self._last_timestamp: Optional[float] = None

        self._pending_switch: Optional[np.ndarray] = None
        self._pending_switch_count = 0

    @property
    def state(self) -> str:
        return self.metrics.state

    @property
    def confidence(self) -> float:
        return self.metrics.confidence

    @property
    def tracked_quad(self) -> Optional[np.ndarray]:
        if self._tracked is None:
            return None
        return self._tracked.copy()

    def reset(self):
        self.metrics = TrackingMetrics()
        self._tracked = None
        self._last_observation = None
        self._velocity.fill(0.0)
        self._last_timestamp = None
        self._pending_switch = None
        self._pending_switch_count = 0

    @staticmethod
    def _frame_diagonal(frame_size: Tuple[int, int]) -> float:
        width, height = frame_size
        return max(
            float((width * width + height * height) ** 0.5),
            1.0,
        )

    def _predict(self, dt: float) -> np.ndarray:
        if self._tracked is None:
            raise RuntimeError("Tracker has no active quadrilateral.")

        # Prediction is intentionally capped. This is not an optical-flow
        # tracker; prediction only removes a small amount of visual lag.
        bounded_dt = float(np.clip(dt, 0.0, 0.12))
        return (
            self._tracked
            + self._velocity * bounded_dt * 0.55
        ).astype(np.float32)

    def _association_metrics(
        self,
        observation: np.ndarray,
        predicted: np.ndarray,
        frame_diag: float,
    ) -> Tuple[float, float, float]:
        corner_distance = (
            _mean_corner_distance(observation, predicted)
            / frame_diag
        )

        center_distance = float(
            np.linalg.norm(
                _centroid(observation) - _centroid(predicted)
            )
        ) / frame_diag

        old_area = max(_area(predicted), 1.0)
        new_area = _area(observation)
        area_change = abs(new_area - old_area) / old_area

        return corner_distance, center_distance, area_change

    def _looks_like_same_document(
        self,
        corner_distance: float,
        center_distance: float,
        area_change: float,
    ) -> bool:
        # Normal handheld movement is accepted. A very large jump or sudden
        # scale change is treated as a possible contour switch.
        return (
            corner_distance <= self.switch_motion_ratio
            and center_distance <= self.switch_motion_ratio * 0.80
            and area_change <= self.max_same_document_area_change
        )

    def _confirm_switch(
        self,
        observation: np.ndarray,
        frame_diag: float,
    ) -> bool:
        if self._pending_switch is None:
            self._pending_switch = observation.copy()
            self._pending_switch_count = 1
            return False

        repeat_distance = (
            _mean_corner_distance(
                observation,
                self._pending_switch,
            )
            / frame_diag
        )

        old_area = max(_area(self._pending_switch), 1.0)
        area_change = abs(
            _area(observation) - old_area
        ) / old_area

        if repeat_distance <= 0.050 and area_change <= 0.20:
            # Blend switch candidates so one noisy confirmation frame does
            # not become the initial new track position.
            self._pending_switch = (
                0.55 * self._pending_switch
                + 0.45 * observation
            ).astype(np.float32)
            self._pending_switch_count += 1
        else:
            self._pending_switch = observation.copy()
            self._pending_switch_count = 1

        return (
            self._pending_switch_count
            >= self.switch_confirmation_frames
        )

    def _accept_new_track(
        self,
        observation: np.ndarray,
        timestamp: float,
    ) -> np.ndarray:
        self._tracked = observation.copy()
        self._last_observation = observation.copy()
        self._velocity.fill(0.0)
        self._last_timestamp = timestamp

        self._pending_switch = None
        self._pending_switch_count = 0

        self.metrics.state = DOCUMENT_FOUND
        self.metrics.confidence = max(
            0.42,
            self.metrics.confidence * 0.65,
        )
        self.metrics.motion_ratio = 0.0
        self.metrics.area_change_ratio = 0.0
        self.metrics.missed_frames = 0
        self.metrics.stable_frames = 1

        return self._tracked.copy()

    def _adaptive_alpha(
        self,
        motion_ratio: float,
        area_change: float,
    ) -> float:
        """
        Small jitter gets strong smoothing; real motion is followed faster.
        """
        if (
            motion_ratio <= self.stable_motion_ratio
            and area_change <= 0.025
        ):
            return 0.16

        if (
            motion_ratio <= self.normal_motion_ratio
            and area_change <= 0.10
        ):
            # Smooth transition between 0.22 and 0.38.
            t = (
                motion_ratio - self.stable_motion_ratio
            ) / max(
                self.normal_motion_ratio
                - self.stable_motion_ratio,
                1e-6,
            )
            return float(
                np.clip(0.22 + 0.16 * t, 0.22, 0.38)
            )

        return 0.52

    def update(
        self,
        detected_quad: Optional[Sequence[Sequence[float]]],
        frame_size: Tuple[int, int],
        timestamp: float,
    ) -> Optional[np.ndarray]:
        observation = _quad(detected_quad)
        frame_diag = self._frame_diagonal(frame_size)

        if self._tracked is None:
            if observation is None:
                self.metrics.state = SEARCHING
                self.metrics.confidence = 0.0
                return None
            return self._accept_new_track(
                observation,
                float(timestamp),
            )

        now = float(timestamp)
        if self._last_timestamp is None:
            dt = 0.0
        else:
            dt = max(0.0, now - self._last_timestamp)

        predicted = self._predict(dt)

        # -------------------------------------------------------------
        # Temporary detection miss
        # -------------------------------------------------------------
        if observation is None:
            self.metrics.missed_frames += 1
            self.metrics.stable_frames = 0
            self.metrics.confidence *= 0.86

            self._pending_switch = None
            self._pending_switch_count = 0

            if self.metrics.missed_frames <= self.max_missed_frames:
                # Hold/predict a few frames instead of blinking.
                self._tracked = predicted
                self._velocity *= 0.72
                self._last_timestamp = now
                self.metrics.state = TRACKING
                return self._tracked.copy()

            self.reset()
            return None

        # -------------------------------------------------------------
        # Associate the detection with current track
        # -------------------------------------------------------------
        (
            motion_ratio,
            center_ratio,
            area_change,
        ) = self._association_metrics(
            observation,
            predicted,
            frame_diag,
        )

        if not self._looks_like_same_document(
            motion_ratio,
            center_ratio,
            area_change,
        ):
            # Do not jump to another contour immediately.
            if self._confirm_switch(
                observation,
                frame_diag,
            ):
                confirmed = (
                    observation
                    if self._pending_switch is None
                    else self._pending_switch
                )
                return self._accept_new_track(
                    order_points(confirmed),
                    now,
                )

            self.metrics.confidence *= 0.94
            self.metrics.stable_frames = 0
            self.metrics.missed_frames = 0
            self.metrics.motion_ratio = motion_ratio
            self.metrics.area_change_ratio = area_change
            self.metrics.state = TRACKING

            self._tracked = predicted
            self._velocity *= 0.82
            self._last_timestamp = now
            return self._tracked.copy()

        # Same document: clear any pending contour switch.
        self._pending_switch = None
        self._pending_switch_count = 0
        self.metrics.missed_frames = 0

        alpha = self._adaptive_alpha(
            motion_ratio,
            area_change,
        )

        previous = self._tracked.copy()
        updated = (
            (1.0 - alpha) * predicted
            + alpha * observation
        ).astype(np.float32)

        # Velocity is measured in pixels/second and itself low-pass filtered.
        if dt > 1e-3:
            measured_velocity = (
                observation
                - (
                    self._last_observation
                    if self._last_observation is not None
                    else previous
                )
            ) / dt

            # Protect against one strange detector frame producing huge
            # predicted motion on subsequent frames.
            max_velocity = frame_diag * 1.7
            magnitudes = np.linalg.norm(
                measured_velocity,
                axis=1,
            )
            scale = np.ones_like(magnitudes)
            too_fast = magnitudes > max_velocity
            scale[too_fast] = (
                max_velocity
                / np.maximum(
                    magnitudes[too_fast],
                    1e-6,
                )
            )
            measured_velocity = (
                measured_velocity * scale[:, None]
            )

            self._velocity = (
                0.72 * self._velocity
                + 0.28 * measured_velocity
            ).astype(np.float32)

        self._tracked = order_points(updated)
        self._last_observation = observation.copy()
        self._last_timestamp = now

        self.metrics.motion_ratio = motion_ratio
        self.metrics.area_change_ratio = area_change

        if (
            motion_ratio <= self.stable_motion_ratio
            and area_change <= 0.035
        ):
            self.metrics.stable_frames += 1
            self.metrics.state = (
                STABILIZING
                if self.metrics.stable_frames >= 3
                else TRACKING
            )
            self.metrics.confidence = min(
                1.0,
                self.metrics.confidence + 0.075,
            )
        else:
            self.metrics.stable_frames = 0
            self.metrics.state = TRACKING
            self.metrics.confidence = min(
                0.88,
                self.metrics.confidence + 0.025,
            )

        return self._tracked.copy()
