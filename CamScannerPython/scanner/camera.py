"""
Camera bridge for the scanner screen, built on Camera4Kivy - a Kivy
Preview widget backed by Android CameraX (native side lives in the
`camerax_provider` hook referenced from buildozer.spec).

Camera4Kivy's own repo is archived (as of 2023-11-13) but the API is
stable and it remains the most direct maintained path from Kivy to
CameraX without hand-writing a full PyJNIus/Java bridge; if it ever
stops working with a newer Kivy/p4a we fall back to a hand-rolled
Camera2 PyJNIus bridge, which would only require rewriting this one
module - no other module in the app talks to the camera directly.

This module owns:
- connect/disconnect the physical camera
- take a full-resolution photo to disk
- real-time document-edge detection on preview frames (step 4) and
  drawing the detected outline over the live preview
- forwarding the detection result to `on_detection` so a later step
  (5 - auto capture) can react to a stable, well-framed quadrilateral
  without redoing any of this coordinate math
"""

import threading

import numpy as np
import cv2

from kivy.utils import platform
from kivy.clock import Clock
from kivy.graphics import Color, Line
from kivy.metrics import dp

from scanner.detector import DocumentDetector

CAMERA_AVAILABLE = True
try:
    from camera4kivy import Preview
except Exception:
    CAMERA_AVAILABLE = False
    Preview = object  # lets DocumentCamera be imported/inspected on any platform

# Analyze every Nth frame - Canny + contour search on every single
# preview frame is unnecessary work; skipping frames keeps the preview
# at full frame rate on low-end devices while the outline still tracks
# smoothly since document movement between 2-3 frames is tiny.
ANALYSIS_FRAME_SKIP = 2

OUTLINE_COLOR = (0.20, 0.85, 0.35, 0.95)  # green - "document detected"
OUTLINE_WIDTH = dp(3)


class DocumentCamera(Preview):
    """Subclass of camera4kivy.Preview.

    `on_detection(quad_or_none, frame_size)` fires on the main thread
    with either a (4, 2) array of corner points in ORIGINAL-frame pixel
    coordinates plus that frame's (width, height), or (None, size) when
    nothing is detected - this is what step 5's auto-capture stability
    check consumes (it needs frame_size to turn pixel movement into a
    resolution-independent ratio).
    """

    def __init__(self, on_detection=None, **kwargs):
        if not CAMERA_AVAILABLE:
            raise RuntimeError(
                "camera4kivy is not installed/available on this platform. "
                "Install it (`pip install camera4kivy`) and, for Android "
                "builds, add the camerax_provider hook described in "
                "buildozer.spec before using DocumentCamera."
            )
        super().__init__(**kwargs)
        self.on_detection = on_detection

        self._detector = DocumentDetector()
        self._capture_callback = None
        self._frame_counter = 0

        self._lock = threading.Lock()
        self._canvas_quad = None  # last detected quad, already in canvas coords

    # ---- Lifecycle -----------------------------------------------------

    def start(self, analyze=True):
        """Connect the physical camera. Call at least one frame after
        the hosting screen enters (on_enter uses Clock.schedule_once
        with timeout=0 to guarantee this)."""
        self.connect_camera(
            enable_analyze_pixels=analyze,
            camera_id="0",  # back camera - documents are scanned facing away
        )

    def stop(self):
        """Disconnect the camera. Must be called on_leave / on_pause so
        the app is a well-behaved camera citizen (spec requirement)."""
        try:
            self.disconnect_camera()
        except Exception:
            pass
        with self._lock:
            self._canvas_quad = None

    # ---- Capture -----------------------------------------------------

    def capture(self, subdir, on_saved):
        """Take a full-resolution photo.

        `on_saved(path)` is called with the absolute file path once the
        capture is written to disk - capture is async, this is the only
        reliable completion signal per Camera4Kivy's own docs.
        """
        self._capture_callback = on_saved
        self.capture_photo(
            location="internal",
            subdir=subdir,
            name_fmt="scan_{}.jpg",
            filepath_callback=self._on_captured,
        )

    def _on_captured(self, path):
        if self._capture_callback:
            Clock.schedule_once(lambda dt: self._capture_callback(path), 0)

    # ---- Camera4Kivy analysis hook -----------------------------------
    # Runs on Camera4Kivy's analysis thread. Per Camera4Kivy's own
    # guidance: do the analysis + coordinate transforms HERE, and only
    # display the (already-computed) result in canvas_instructions_callback.

    def analyze_pixels_callback(self, pixels, size, image_pos, image_scale, mirror):
        self._frame_counter += 1
        if self._frame_counter % ANALYSIS_FRAME_SKIP != 0:
            return

        frame_w, frame_h = size
        try:
            rgba = np.frombuffer(pixels, dtype=np.uint8).reshape(frame_h, frame_w, 4)
        except ValueError:
            return  # buffer size didn't match (e.g. mid-reconfigure) - skip this frame
        bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)

        quad = self._detector.detect(bgr)

        if quad is None:
            with self._lock:
                self._canvas_quad = None
        else:
            canvas_quad = self._to_canvas_coords(quad, frame_w, image_pos, image_scale, mirror)
            with self._lock:
                self._canvas_quad = canvas_quad

        if self.on_detection:
            Clock.schedule_once(
                lambda dt, q=quad, s=(frame_w, frame_h): self.on_detection(q, s), 0
            )

    @staticmethod
    def _to_canvas_coords(quad, frame_w, image_pos, image_scale, mirror):
        """Map detector output (original analysis-frame pixels) to
        widget/canvas coordinates, per Camera4Kivy's documented contract:
        annotation coordinates from analyze_pixels_callback are NEVER
        auto-mirrored, so a mirrored preview must be corrected here."""
        px, py = image_pos
        points = []
        for x, y in quad:
            if mirror:
                x = frame_w - x
            points.append(px + x * image_scale)
            points.append(py + y * image_scale)
        return points

    # ---- Camera4Kivy render hook ---------------------------------------
    # Runs on the GL/render thread - only draws the last computed result,
    # never recomputes anything (per Camera4Kivy's documented pattern).

    def canvas_instructions_callback(self, texture, tex_size, tex_pos):
        with self._lock:
            quad = self._canvas_quad
        if not quad:
            return
        Color(*OUTLINE_COLOR)
        Line(points=quad, width=OUTLINE_WIDTH, close=True)


def camera_permission_granted() -> bool:
    """Returns whether CAMERA permission is currently granted.
    Always True off-Android (desktop dev uses the OS camera directly)."""
    if platform != "android":
        return True
    try:
        from android.permissions import check_permission, Permission

        return check_permission(Permission.CAMERA)
    except Exception:
        return False


def request_camera_permission(on_result):
    """Request CAMERA permission. `on_result(granted: bool)` fires once
    the user answers the system dialog. No-op (immediate True) off-Android."""
    if platform != "android":
        on_result(True)
        return
    try:
        from android.permissions import request_permissions, Permission

        def _callback(permissions, grants):
            on_result(bool(grants) and all(grants))

        request_permissions([Permission.CAMERA], _callback)
    except Exception:
        on_result(False)
