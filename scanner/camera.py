"""
Camera4Kivy bridge for Pycam document scanning.

This version focuses on:
- real Android torch control (not UI-only flash state);
- stable document outline with temporal hysteresis;
- missed-frame hold so the outline does not blink;
- rejection of single-frame false jumps;
- CameraX-safe photo + image-analysis configuration.
"""

import threading
import time
from typing import Optional

import cv2
import numpy as np

from kivy.clock import Clock
from kivy.graphics import Color, Line
from kivy.metrics import dp
from kivy.utils import platform

from scanner.detector import DocumentDetector, order_points


CAMERA_AVAILABLE = True
try:
    from camera4kivy import Preview
except Exception:
    CAMERA_AVAILABLE = False
    Preview = object


ANALYSIS_FRAME_SKIP = 2
ANALYSIS_RESOLUTION = 720

OUTLINE_COLOR = (0.12, 0.88, 0.67, 0.98)
OUTLINE_WIDTH = dp(3)

# Stability tuning
SMOOTH_ALPHA_STABLE = 0.20
SMOOTH_ALPHA_MOVING = 0.36
MAX_SINGLE_FRAME_JUMP_RATIO = 0.095
JUMP_CONFIRM_FRAMES = 2
MAX_MISSED_DETECTION_FRAMES = 5


class DocumentCamera(Preview):
    def __init__(self, on_detection=None, on_camera_error=None, **kwargs):
        if not CAMERA_AVAILABLE:
            raise RuntimeError(
                "camera4kivy is not available. Install camera4kivy and "
                "use the CameraX provider hook on Android."
            )

        # 16:9 matches the full-screen scanner reference more closely.
        kwargs.setdefault("aspect_ratio", "16:9")
        kwargs.setdefault("orientation", "same")
        kwargs.setdefault("letterbox_color", (0, 0, 0, 1))

        super().__init__(**kwargs)

        self.on_detection = on_detection
        self.on_camera_error = on_camera_error

        self._detector = DocumentDetector(
            detection_long_edge=720,
            min_area_ratio=0.10,
            max_area_ratio=0.97,
        )

        self._capture_callback = None
        self._capture_error_callback = None
        self._capture_in_progress = False
        self._frame_counter = 0

        self._lock = threading.Lock()
        self._canvas_quad = None
        self._smoothed_quad: Optional[np.ndarray] = None
        self._last_frame_size = (0, 0)

        self._missed_frames = 0
        self._pending_jump_quad: Optional[np.ndarray] = None
        self._pending_jump_count = 0

        self._torch_on = False

    # ------------------------------------------------------------------
    # Camera lifecycle
    # ------------------------------------------------------------------

    def start(self, analyze=True):
        try:
            self.connect_camera(
                camera_id="back" if platform == "android" else "0",
                filepath_callback=self._on_captured,
                enable_analyze_pixels=bool(analyze),
                analyze_pixels_resolution=ANALYSIS_RESOLUTION,
                enable_video=False,
                enable_zoom_gesture=True,
                enable_focus_gesture=True,
            )
        except Exception as exc:
            self._notify_camera_error(
                f"Could not start camera: {exc}"
            )

    def stop(self):
        # Never leave the LED on when leaving the scanner.
        if self._torch_on:
            try:
                self.set_torch(False)
            except Exception:
                pass

        try:
            self.disconnect_camera()
        except Exception:
            pass

        with self._lock:
            self._canvas_quad = None
            self._smoothed_quad = None

        self._missed_frames = 0
        self._pending_jump_quad = None
        self._pending_jump_count = 0
        self._capture_in_progress = False
        self._capture_callback = None
        self._capture_error_callback = None

    # ------------------------------------------------------------------
    # Flash / torch
    # ------------------------------------------------------------------

    @property
    def torch_on(self) -> bool:
        return self._torch_on

    def set_torch(self, enabled: bool) -> bool:
        """
        Turn the Android torch on/off immediately.

        Camera4Kivy exposes Android flash/torch control through flash().
        For preview illumination we use explicit 'on'/'off' states.
        """
        enabled = bool(enabled)

        if platform != "android":
            self._torch_on = enabled
            return True

        if not getattr(self, "camera_connected", False):
            return False

        try:
            self.flash("on" if enabled else "off")
            self._torch_on = enabled
            return True
        except Exception as exc:
            self._notify_camera_error(
                f"Flash/torch is not available on this camera: {exc}"
            )
            return False

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    @property
    def capture_in_progress(self) -> bool:
        return self._capture_in_progress

    def capture(self, subdir, on_saved, on_error=None):
        if self._capture_in_progress:
            return False

        self._capture_callback = on_saved
        self._capture_error_callback = on_error
        self._capture_in_progress = True

        unique_name = f"scan_{int(time.time() * 1000)}"

        try:
            self.capture_photo(
                location="private",
                subdir=str(subdir),
                name=unique_name,
            )
            return True
        except Exception as exc:
            self._capture_in_progress = False
            self._capture_callback = None

            callback = self._capture_error_callback
            self._capture_error_callback = None

            if callback:
                Clock.schedule_once(
                    lambda dt, message=str(exc): callback(message), 0
                )
            else:
                self._notify_camera_error(f"Capture failed: {exc}")

            return False

    def _on_captured(self, path):
        self._capture_in_progress = False

        saved_callback = self._capture_callback
        error_callback = self._capture_error_callback

        self._capture_callback = None
        self._capture_error_callback = None

        if isinstance(path, str) and path.strip():
            clean_path = path.strip()
            if saved_callback:
                Clock.schedule_once(
                    lambda dt, p=clean_path: saved_callback(p), 0
                )
            return

        message = "Camera did not return a saved photo path."
        if error_callback:
            Clock.schedule_once(
                lambda dt, m=message: error_callback(m), 0
            )
        else:
            self._notify_camera_error(message)

    def _notify_camera_error(self, message: str):
        if self.on_camera_error:
            Clock.schedule_once(
                lambda dt, m=str(message): self.on_camera_error(m), 0
            )

    # ------------------------------------------------------------------
    # Live analysis
    # ------------------------------------------------------------------

    def analyze_pixels_callback(
        self,
        pixels,
        size,
        image_pos,
        image_scale,
        mirror,
    ):
        self._frame_counter += 1
        if self._frame_counter % ANALYSIS_FRAME_SKIP:
            return

        try:
            frame_w, frame_h = int(size[0]), int(size[1])
        except Exception:
            return

        if frame_w <= 0 or frame_h <= 0:
            return

        try:
            rgba = np.frombuffer(
                pixels, dtype=np.uint8
            ).reshape(frame_h, frame_w, 4)
        except (ValueError, TypeError):
            return

        try:
            bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
            detected = self._detector.detect(bgr)
        except Exception:
            detected = None

        self._last_frame_size = (frame_w, frame_h)

        stable_quad = self._stabilize_detection(
            detected,
            frame_w,
            frame_h,
        )

        if stable_quad is None:
            with self._lock:
                self._canvas_quad = None
        else:
            canvas_quad = self._to_canvas_coords(
                stable_quad,
                frame_w,
                frame_h,
                image_pos,
                image_scale,
                mirror,
            )
            with self._lock:
                self._canvas_quad = canvas_quad

        if self.on_detection:
            payload = None if stable_quad is None else stable_quad.copy()
            Clock.schedule_once(
                lambda dt, q=payload, s=(frame_w, frame_h):
                    self.on_detection(q, s),
                0,
            )

    def _stabilize_detection(
        self,
        quad: Optional[np.ndarray],
        frame_w: int,
        frame_h: int,
    ) -> Optional[np.ndarray]:
        """
        Stable tracking without an expensive full tracker.

        1. Hold the last good quad for a few missed frames.
        2. Ignore a one-frame large jump.
        3. Accept a large jump only after it repeats.
        4. Use stronger EMA smoothing when movement is small.
        """
        diagonal = max(
            (frame_w ** 2 + frame_h ** 2) ** 0.5,
            1.0,
        )

        if quad is None:
            self._missed_frames += 1

            if (
                self._smoothed_quad is not None
                and self._missed_frames <= MAX_MISSED_DETECTION_FRAMES
            ):
                return self._smoothed_quad.copy()

            self._smoothed_quad = None
            self._pending_jump_quad = None
            self._pending_jump_count = 0
            return None

        self._missed_frames = 0
        current = order_points(
            np.asarray(quad, dtype=np.float32).reshape(4, 2)
        )

        if self._smoothed_quad is None:
            self._smoothed_quad = current.copy()
            self._pending_jump_quad = None
            self._pending_jump_count = 0
            return self._smoothed_quad.copy()

        distances = np.linalg.norm(
            current - self._smoothed_quad,
            axis=1,
        )
        mean_move = float(np.mean(distances))
        move_ratio = mean_move / diagonal

        # A large sudden jump is usually a false contour. Require the
        # new position to appear in two consecutive analyzed frames.
        if move_ratio > MAX_SINGLE_FRAME_JUMP_RATIO:
            if self._pending_jump_quad is None:
                self._pending_jump_quad = current.copy()
                self._pending_jump_count = 1
                return self._smoothed_quad.copy()

            jump_repeat = float(
                np.mean(
                    np.linalg.norm(
                        current - self._pending_jump_quad,
                        axis=1,
                    )
                )
            ) / diagonal

            if jump_repeat <= 0.045:
                self._pending_jump_count += 1
            else:
                self._pending_jump_quad = current.copy()
                self._pending_jump_count = 1

            if self._pending_jump_count < JUMP_CONFIRM_FRAMES:
                return self._smoothed_quad.copy()

            self._smoothed_quad = current.copy()
            self._pending_jump_quad = None
            self._pending_jump_count = 0
            return self._smoothed_quad.copy()

        self._pending_jump_quad = None
        self._pending_jump_count = 0

        # Strong smoothing while the device/page is nearly still.
        alpha = (
            SMOOTH_ALPHA_STABLE
            if move_ratio < 0.025
            else SMOOTH_ALPHA_MOVING
        )

        self._smoothed_quad = (
            alpha * current
            + (1.0 - alpha) * self._smoothed_quad
        ).astype(np.float32)

        return self._smoothed_quad.copy()

    @staticmethod
    def _to_canvas_coords(
        quad,
        frame_w,
        frame_h,
        image_pos,
        image_scale,
        mirror,
    ):
        px, py = float(image_pos[0]), float(image_pos[1])

        if isinstance(image_scale, (tuple, list, np.ndarray)):
            if len(image_scale) >= 2:
                sx = float(image_scale[0])
                sy = float(image_scale[1])
            else:
                sx = sy = float(image_scale[0])
        else:
            sx = sy = float(image_scale)

        points = []
        for x, y in quad:
            x = float(x)
            y = float(y)

            if mirror:
                x = frame_w - x

            canvas_x = px + x * sx
            canvas_y = py + (frame_h - y) * sy
            points.extend((canvas_x, canvas_y))

        return points

    # ------------------------------------------------------------------
    # Render hook
    # ------------------------------------------------------------------

    def canvas_instructions_callback(self, texture, tex_size, tex_pos):
        with self._lock:
            quad = (
                None
                if self._canvas_quad is None
                else list(self._canvas_quad)
            )

        if not quad:
            return

        Color(*OUTLINE_COLOR)
        Line(
            points=quad,
            width=OUTLINE_WIDTH,
            close=True,
            joint="round",
        )


def camera_permission_granted() -> bool:
    if platform != "android":
        return True

    try:
        from android.permissions import Permission, check_permission
        return bool(check_permission(Permission.CAMERA))
    except Exception:
        return False


def request_camera_permission(on_result):
    if platform != "android":
        on_result(True)
        return

    try:
        from android.permissions import Permission, request_permissions

        def _callback(permissions, grants):
            granted = bool(grants) and all(bool(v) for v in grants)
            Clock.schedule_once(
                lambda dt: on_result(granted), 0
            )

        request_permissions(
            [Permission.CAMERA],
            _callback,
        )
    except Exception:
        Clock.schedule_once(
            lambda dt: on_result(False), 0
        )
