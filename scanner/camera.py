"""
Camera4Kivy bridge for Pycam document scanning.

Step 4 adds lightweight frame-quality analysis for reliable auto capture:
- blur/sharpness via variance of Laplacian;
- dark/overexposed checks;
- document size and edge-visibility checks.

Existing Camera4Kivy callback signature is preserved:
    on_detection(quad, frame_size)

The latest quality result is exposed as:
    camera.last_quality

This avoids breaking ScannerScreen or any other existing callback user.
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

from scanner.auto_capture import FrameQuality
from scanner.detector import (
    DocumentDetector,
    order_points,
)
from scanner.tracker import DocumentTracker


CAMERA_AVAILABLE = True
try:
    from camera4kivy import Preview
except Exception:
    CAMERA_AVAILABLE = False
    Preview = object


ANALYSIS_RESOLUTION = 720

# Adaptive analysis throttle. Excess callbacks are dropped instead of
# queued, so live preview remains responsive under CPU load.
MIN_ANALYSIS_INTERVAL = 0.045
MAX_ANALYSIS_INTERVAL = 0.115
INITIAL_ANALYSIS_INTERVAL = 0.055
PROCESSING_EMA_ALPHA = 0.18

OUTLINE_COLOR = (
    0.12,
    0.88,
    0.67,
    0.98,
)
OUTLINE_WIDTH = dp(3)

# Existing temporal smoothing parameters.
SMOOTH_ALPHA_STABLE = 0.20
SMOOTH_ALPHA_MOVING = 0.36
MAX_SINGLE_FRAME_JUMP_RATIO = 0.095
JUMP_CONFIRM_FRAMES = 2
MAX_MISSED_DETECTION_FRAMES = 5

# Auto-capture quality thresholds tuned for ~720 px analysis frames.
MIN_DOCUMENT_AREA_RATIO = 0.125
GOOD_DOCUMENT_AREA_RATIO = 0.18

MIN_MEAN_BRIGHTNESS = 42.0
MAX_MEAN_BRIGHTNESS = 220.0
MAX_DARK_PIXEL_RATIO = 0.46
MAX_BRIGHT_PIXEL_RATIO = 0.42

# Variance of Laplacian is content/resolution dependent. This intentionally
# uses a conservative low threshold for a 720px preview frame; final captured
# quality still comes from the full-resolution camera photo.
MIN_SHARPNESS = 52.0

VISIBLE_MARGIN_RATIO = 0.007


class DocumentCamera(Preview):
    def __init__(
        self,
        on_detection=None,
        on_camera_error=None,
        **kwargs,
    ):
        if not CAMERA_AVAILABLE:
            raise RuntimeError(
                "camera4kivy is not available. "
                "Install camera4kivy and use the "
                "CameraX provider hook on Android."
            )

        kwargs.setdefault(
            "aspect_ratio",
            "full",
        )
        kwargs.setdefault(
            "orientation",
            "same",
        )
        kwargs.setdefault(
            "letterbox_color",
            (0, 0, 0, 1),
        )

        super().__init__(**kwargs)

        self.on_detection = on_detection
        self.on_camera_error = (
            on_camera_error
        )

        self._detector = DocumentDetector(
            detection_long_edge=720,
            min_area_ratio=0.10,
            max_area_ratio=0.97,
        )

        # One temporal tracker owns association/smoothing for all live frames.
        self._tracker = DocumentTracker(
            max_missed_frames=6,
            switch_confirmation_frames=3,
            stable_motion_ratio=0.010,
            normal_motion_ratio=0.040,
            switch_motion_ratio=0.105,
            max_same_document_area_change=0.34,
        )

        self._capture_callback = None
        self._capture_error_callback = None
        self._capture_in_progress = False
        self._frame_counter = 0

        self._session_running = False
        self._last_analysis_started = 0.0
        self._analysis_interval = INITIAL_ANALYSIS_INTERVAL
        self._processing_time_ema = 0.0

        self._lock = threading.Lock()
        self._canvas_quad = None
        self._smoothed_quad: Optional[
            np.ndarray
        ] = None
        self._last_frame_size = (
            0,
            0,
        )

        self._missed_frames = 0
        self._pending_jump_quad: Optional[
            np.ndarray
        ] = None
        self._pending_jump_count = 0

        self._torch_on = False

        self.last_quality = FrameQuality()

    # ------------------------------------------------------------------
    # Camera lifecycle
    # ------------------------------------------------------------------

    def start(self, analyze=True):
        """
        Start at most one CameraX session.

        Android/Kivy lifecycle callbacks can repeat; this guard prevents
        duplicate camera binding/opening.
        """
        if self._session_running:
            return

        if getattr(self, "camera_connected", False):
            self._session_running = True
            return

        self._tracker.reset()
        self.last_quality = FrameQuality()
        self._frame_counter = 0
        self._last_analysis_started = 0.0
        self._analysis_interval = INITIAL_ANALYSIS_INTERVAL
        self._processing_time_ema = 0.0

        try:
            self.connect_camera(
                camera_id=(
                    "back"
                    if platform == "android"
                    else "0"
                ),
                filepath_callback=self._on_captured,
                enable_analyze_pixels=bool(analyze),
                analyze_pixels_resolution=ANALYSIS_RESOLUTION,
                enable_video=False,
                enable_zoom_gesture=True,
                enable_focus_gesture=True,
            )
            self._session_running = True
        except Exception as exc:
            self._session_running = False
            self._notify_camera_error(
                f"Could not start camera: {exc}"
            )

    def stop(self):
        """
        Release torch, CameraX, tracking and analysis state.
        """
        if self._torch_on:
            try:
                self.set_torch(False)
            except Exception:
                pass

        self._session_running = False

        try:
            self.disconnect_camera()
        except Exception:
            pass

        self._tracker.reset()

        with self._lock:
            self._canvas_quad = None
            self._smoothed_quad = None

        self._missed_frames = 0
        self._pending_jump_quad = None
        self._pending_jump_count = 0
        self._capture_in_progress = False
        self._capture_callback = None
        self._capture_error_callback = None
        self.last_quality = FrameQuality()

        self._last_analysis_started = 0.0
        self._analysis_interval = INITIAL_ANALYSIS_INTERVAL
        self._processing_time_ema = 0.0

    def reset_detection_state(self):
        """Forget the previous page without reconnecting CameraX.

        A multi-page scan keeps the same camera session alive.  Resetting only
        ScannerScreen's UI state is not enough because DocumentTracker and the
        smoothed overlay still remember the page that was just captured.  This
        method clears that temporal history so the next physical page is
        evaluated as a fresh document immediately.
        """
        self._tracker.reset()
        self.last_quality = FrameQuality()
        self._frame_counter = 0
        self._last_analysis_started = 0.0

        with self._lock:
            self._canvas_quad = None
            self._smoothed_quad = None

        self._missed_frames = 0
        self._pending_jump_quad = None
        self._pending_jump_count = 0

        # Remove the old green outline on the UI thread.  The next analysed
        # frame will draw a new outline if a document is present.
        try:
            Clock.schedule_once(lambda dt: self.canvas.ask_update(), 0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Flash / torch
    # ------------------------------------------------------------------

    @property
    def torch_on(self) -> bool:
        return self._torch_on

    def set_torch(
        self,
        enabled: bool,
    ) -> bool:
        enabled = bool(enabled)

        if platform != "android":
            self._torch_on = enabled
            return True

        if not getattr(
            self,
            "camera_connected",
            False,
        ):
            return False

        try:
            self.flash(
                "on"
                if enabled
                else "off"
            )
            self._torch_on = enabled
            return True
        except Exception as exc:
            self._notify_camera_error(
                "Flash/torch is not available "
                f"on this camera: {exc}"
            )
            return False

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    @property
    def capture_in_progress(self) -> bool:
        return self._capture_in_progress

    def capture(
        self,
        subdir,
        on_saved,
        on_error=None,
    ):
        if self._capture_in_progress:
            return False

        self._capture_callback = on_saved
        self._capture_error_callback = (
            on_error
        )
        self._capture_in_progress = True

        unique_name = (
            f"scan_{int(time.time() * 1000)}"
        )

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

            callback = (
                self._capture_error_callback
            )
            self._capture_error_callback = (
                None
            )

            if callback:
                Clock.schedule_once(
                    lambda dt, message=str(exc):
                        callback(message),
                    0,
                )
            else:
                self._notify_camera_error(
                    f"Capture failed: {exc}"
                )

            return False

    def _on_captured(self, path):
        self._capture_in_progress = False

        saved_callback = (
            self._capture_callback
        )
        error_callback = (
            self._capture_error_callback
        )

        self._capture_callback = None
        self._capture_error_callback = None

        if (
            isinstance(path, str)
            and path.strip()
        ):
            clean_path = path.strip()

            if saved_callback:
                Clock.schedule_once(
                    lambda dt, p=clean_path:
                        saved_callback(p),
                    0,
                )
            return

        message = (
            "Camera did not return a "
            "saved photo path."
        )

        if error_callback:
            Clock.schedule_once(
                lambda dt, m=message:
                    error_callback(m),
                0,
            )
        else:
            self._notify_camera_error(
                message
            )

    def _notify_camera_error(
        self,
        message: str,
    ):
        if self.on_camera_error:
            Clock.schedule_once(
                lambda dt, m=str(message):
                    self.on_camera_error(m),
                0,
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
        """
        Analyze the newest useful frame only.

        Adaptive throttling targets roughly 9-20 useful detection updates per
        second depending on actual detector cost, avoiding an obsolete-frame
        processing queue.
        """
        if not self._session_running:
            return

        now = time.monotonic()

        if (
            self._last_analysis_started > 0.0
            and now - self._last_analysis_started
            < self._analysis_interval
        ):
            return

        self._last_analysis_started = now
        processing_started = now
        self._frame_counter += 1

        try:
            frame_w = int(size[0])
            frame_h = int(size[1])
        except Exception:
            return

        if frame_w <= 0 or frame_h <= 0:
            return

        try:
            rgba = np.frombuffer(
                pixels,
                dtype=np.uint8,
            ).reshape(
                frame_h,
                frame_w,
                4,
            )
        except (ValueError, TypeError):
            return

        bgr = None
        detected = None

        try:
            # frombuffer is zero-copy; BGR is the only full analysis-frame
            # conversion required by the existing detector.
            bgr = cv2.cvtColor(
                rgba,
                cv2.COLOR_RGBA2BGR,
            )
            detected = self._detector.detect(
                bgr
            )
        except Exception:
            detected = None

        self._last_frame_size = (
            frame_w,
            frame_h,
        )

        stable_quad = self._tracker.update(
            detected,
            (frame_w, frame_h),
            now,
        )

        if bgr is not None:
            try:
                self.last_quality = (
                    self._measure_frame_quality(
                        bgr,
                        stable_quad,
                    )
                )
            except Exception:
                self.last_quality = FrameQuality(
                    reason="Hold steady"
                )
        else:
            self.last_quality = FrameQuality()

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
            payload = (
                None
                if stable_quad is None
                else stable_quad.copy()
            )

            # Keep the existing callback contract unchanged.
            Clock.schedule_once(
                lambda dt, q=payload, s=(frame_w, frame_h):
                    self.on_detection(q, s),
                0,
            )

        elapsed = max(
            0.0,
            time.monotonic()
            - processing_started,
        )

        if self._processing_time_ema <= 0.0:
            self._processing_time_ema = elapsed
        else:
            self._processing_time_ema = (
                (
                    1.0
                    - PROCESSING_EMA_ALPHA
                )
                * self._processing_time_ema
                + PROCESSING_EMA_ALPHA
                * elapsed
            )

        desired_interval = max(
            MIN_ANALYSIS_INTERVAL,
            self._processing_time_ema
            * 1.18,
        )

        self._analysis_interval = float(
            np.clip(
                desired_interval,
                MIN_ANALYSIS_INTERVAL,
                MAX_ANALYSIS_INTERVAL,
            )
        )

    def _measure_frame_quality(
        self,
        frame_bgr: np.ndarray,
        quad: Optional[np.ndarray],
    ) -> FrameQuality:
        """
        Lightweight quality gate for auto capture.

        Only the document region is evaluated where possible, so a dark desk
        around a white page does not incorrectly trigger "More light needed".
        """
        frame_h, frame_w = (
            frame_bgr.shape[:2]
        )

        if quad is None:
            return FrameQuality(
                reason="Find document"
            )

        q = order_points(
            np.asarray(
                quad,
                dtype=np.float32,
            ).reshape(4, 2)
        )

        frame_area = float(
            frame_w * frame_h
        )
        document_area = float(
            abs(
                cv2.contourArea(
                    q.reshape(
                        -1,
                        1,
                        2,
                    )
                )
            )
        )
        document_area_ratio = (
            document_area
            / max(
                frame_area,
                1.0,
            )
        )

        margin_x = (
            frame_w
            * VISIBLE_MARGIN_RATIO
        )
        margin_y = (
            frame_h
            * VISIBLE_MARGIN_RATIO
        )

        fully_visible = bool(
            np.all(
                q[:, 0] >= margin_x
            )
            and np.all(
                q[:, 0]
                <= frame_w - 1 - margin_x
            )
            and np.all(
                q[:, 1] >= margin_y
            )
            and np.all(
                q[:, 1]
                <= frame_h - 1 - margin_y
            )
        )

        # Work on a padded bounding box and a polygon mask. This avoids a
        # full-frame Laplacian allocation every analyzed frame.
        x, y, w, h = cv2.boundingRect(
            np.round(q)
            .astype(np.int32)
            .reshape(-1, 1, 2)
        )

        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(
            frame_w,
            x + w,
        )
        y1 = min(
            frame_h,
            y + h,
        )

        if (
            x1 - x0 < 20
            or y1 - y0 < 20
        ):
            return FrameQuality(
                document_area_ratio=(
                    document_area_ratio
                ),
                fully_visible=(
                    fully_visible
                ),
                reason="Move closer",
            )

        roi = frame_bgr[
            y0:y1,
            x0:x1,
        ]

        local_quad = q.copy()
        local_quad[:, 0] -= x0
        local_quad[:, 1] -= y0

        mask = np.zeros(
            roi.shape[:2],
            dtype=np.uint8,
        )
        cv2.fillConvexPoly(
            mask,
            np.round(
                local_quad
            ).astype(np.int32),
            255,
        )

        gray = cv2.cvtColor(
            roi,
            cv2.COLOR_BGR2GRAY,
        )

        pixels = gray[
            mask > 0
        ]

        if pixels.size < 128:
            return FrameQuality(
                document_area_ratio=(
                    document_area_ratio
                ),
                fully_visible=(
                    fully_visible
                ),
                reason="Hold steady",
            )

        brightness = float(
            np.mean(pixels)
        )
        dark_ratio = float(
            np.mean(
                pixels < 35
            )
        )
        bright_ratio = float(
            np.mean(
                pixels > 245
            )
        )

        # Downsample only very large ROI before Laplacian. The analysis frame
        # is already ~720px long edge, so this normally keeps original size.
        quality_gray = gray

        long_edge = max(
            quality_gray.shape[:2]
        )
        if long_edge > 720:
            scale = (
                720.0
                / float(long_edge)
            )
            quality_gray = (
                cv2.resize(
                    quality_gray,
                    (
                        max(
                            1,
                            int(
                                quality_gray.shape[1]
                                * scale
                            ),
                        ),
                        max(
                            1,
                            int(
                                quality_gray.shape[0]
                                * scale
                            ),
                        ),
                    ),
                    interpolation=(
                        cv2.INTER_AREA
                    ),
                )
            )

        laplacian = cv2.Laplacian(
            quality_gray,
            cv2.CV_64F,
        )
        sharpness = float(
            laplacian.var()
        )

        # -------------------------------------------------------------
        # Ordered feedback priority
        # -------------------------------------------------------------
        if (
            document_area_ratio
            < MIN_DOCUMENT_AREA_RATIO
        ):
            reason = "Move closer"
            acceptable = False

        elif not fully_visible:
            reason = (
                "Document not fully visible"
            )
            acceptable = False

        elif (
            brightness
            < MIN_MEAN_BRIGHTNESS
            or dark_ratio
            > MAX_DARK_PIXEL_RATIO
        ):
            reason = "More light needed"
            acceptable = False

        elif (
            brightness
            > MAX_MEAN_BRIGHTNESS
            or bright_ratio
            > MAX_BRIGHT_PIXEL_RATIO
        ):
            reason = "Too bright"
            acceptable = False

        elif sharpness < MIN_SHARPNESS:
            reason = "Hold steady"
            acceptable = False

        else:
            reason = "Hold steady"
            acceptable = True

        return FrameQuality(
            sharpness=sharpness,
            brightness=brightness,
            dark_ratio=dark_ratio,
            bright_ratio=bright_ratio,
            document_area_ratio=(
                document_area_ratio
            ),
            fully_visible=fully_visible,
            acceptable=acceptable,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Existing temporal stabilization
    # ------------------------------------------------------------------

    def _stabilize_detection(
        self,
        quad: Optional[np.ndarray],
        frame_w: int,
        frame_h: int,
    ) -> Optional[np.ndarray]:
        """
        Compatibility wrapper. DocumentTracker is the only smoothing state.
        """
        return self._tracker.update(
            quad,
            (frame_w, frame_h),
            time.monotonic(),
        )

    @staticmethod
    def _to_canvas_coords(
        quad,
        frame_w,
        frame_h,
        image_pos,
        image_scale,
        mirror,
    ):
        """
        Map detector coordinates to the visible Camera4Kivy preview.

        Detector space uses top-left origin. Kivy uses bottom-left origin.
        Camera4Kivy-provided image_pos/image_scale are used directly, avoiding
        device-specific magic offsets.
        """
        try:
            px = float(image_pos[0])
            py = float(image_pos[1])
        except Exception:
            px = 0.0
            py = 0.0

        if isinstance(
            image_scale,
            (tuple, list, np.ndarray),
        ):
            if len(image_scale) >= 2:
                sx = float(image_scale[0])
                sy = float(image_scale[1])
            elif len(image_scale) == 1:
                sx = sy = float(image_scale[0])
            else:
                sx = sy = 1.0
        else:
            try:
                sx = sy = float(image_scale)
            except Exception:
                sx = sy = 1.0

        if not np.isfinite(sx) or abs(sx) < 1e-8:
            sx = 1.0
        if not np.isfinite(sy) or abs(sy) < 1e-8:
            sy = 1.0

        points = []

        for x, y in np.asarray(
            quad,
            dtype=np.float32,
        ).reshape(4, 2):
            x = float(x)
            y = float(y)

            if mirror:
                x = frame_w - x

            points.extend(
                (
                    px + x * sx,
                    py + (frame_h - y) * sy,
                )
            )

        return points

    # ------------------------------------------------------------------
    # Render hook
    # ------------------------------------------------------------------

    def canvas_instructions_callback(
        self,
        texture,
        tex_size,
        tex_pos,
    ):
        with self._lock:
            quad = (
                None
                if self._canvas_quad
                is None
                else list(
                    self._canvas_quad
                )
            )

        if not quad:
            return

        Color(
            *OUTLINE_COLOR
        )
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
        from android.permissions import (
            Permission,
            check_permission,
        )

        return bool(
            check_permission(
                Permission.CAMERA
            )
        )
    except Exception:
        return False


def request_camera_permission(
    on_result,
):
    if platform != "android":
        on_result(True)
        return

    try:
        from android.permissions import (
            Permission,
            request_permissions,
        )

        def _callback(
            permissions,
            grants,
        ):
            granted = (
                bool(grants)
                and all(
                    bool(value)
                    for value
                    in grants
                )
            )

            Clock.schedule_once(
                lambda dt:
                    on_result(
                        granted
                    ),
                0,
            )

        request_permissions(
            [
                Permission.CAMERA
            ],
            _callback,
        )
    except Exception:
        Clock.schedule_once(
            lambda dt:
                on_result(False),
            0,
        )
