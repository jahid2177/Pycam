"""
Auto-capture stability tracking.

Decides WHEN to fire the shutter automatically: once a detected
document quadrilateral has stayed roughly in the same place for a
short duration, `update()` reports that a capture should happen.

Deliberately takes no dependency on Kivy, the camera, or wall-clock
time (a `now` timestamp is passed in) so the whole state machine can
be driven by a unit test with fabricated timestamps and fabricated
quads - see the docstring example below.

    >>> ctrl = AutoCaptureController(stability_duration=1.0)
    >>> quad = [(0, 0), (100, 0), (100, 100), (0, 100)]
    >>> ctrl.update(quad, frame_diagonal=500, now=0.0).should_capture
    False
    >>> ctrl.update(quad, frame_diagonal=500, now=1.1).should_capture
    True
"""

from collections import namedtuple
from typing import Optional, Sequence, Tuple

AutoCaptureStatus = namedtuple("AutoCaptureStatus", ["progress", "should_capture"])


def _centroid(quad: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class AutoCaptureController:
    def __init__(
        self,
        stability_duration: float = 0.9,
        movement_threshold_ratio: float = 0.025,
    ):
        """
        stability_duration: seconds the document must hold still before
            a capture is triggered.
        movement_threshold_ratio: max allowed centroid movement between
            consecutive detections, as a fraction of the frame's
            diagonal length, to still count as "held still". Using a
            ratio (not raw pixels) keeps behavior consistent whether
            frames are 480px or 1080px wide.
        """
        self.stability_duration = stability_duration
        self.movement_threshold_ratio = movement_threshold_ratio
        self._last_centroid: Optional[Tuple[float, float]] = None
        self._stable_since: Optional[float] = None

    def reset(self):
        self._last_centroid = None
        self._stable_since = None

    def update(
        self,
        quad: Optional[Sequence[Tuple[float, float]]],
        frame_diagonal: float,
        now: float,
    ) -> AutoCaptureStatus:
        if quad is None or frame_diagonal <= 0:
            self.reset()
            return AutoCaptureStatus(progress=0.0, should_capture=False)

        centroid = _centroid(quad)
        threshold = frame_diagonal * self.movement_threshold_ratio

        if self._last_centroid is None:
            self._stable_since = now
        else:
            moved = _distance(centroid, self._last_centroid)
            if moved > threshold:
                self._stable_since = now  # motion detected - restart the hold timer

        self._last_centroid = centroid

        if self._stable_since is None:
            self._stable_since = now

        elapsed = now - self._stable_since
        progress = min(max(elapsed / self.stability_duration, 0.0), 1.0)

        if progress >= 1.0:
            self.reset()
            return AutoCaptureStatus(progress=1.0, should_capture=True)

        return AutoCaptureStatus(progress=progress, should_capture=False)
