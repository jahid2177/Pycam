"""
Scanner screen - live camera preview and page capture.

Owns: permission flow, connecting/disconnecting DocumentCamera, and
turning a shutter press into a saved file added to the current
scanning session (`app.active_session_pages`). Shows live
document-edge detection status (green outline drawn by DocumentCamera,
reflected here in the hint label) and drives auto-capture: once a
detected document has held still long enough, the shutter fires on its
own - the manual shutter button still works at any time. After every
capture, hands the raw photo to `image_processing.perspective` for
perspective correction (step 6) before continuing to the preview
screen - the actual warp math lives there, not here.

Does NOT own: the perspective-correction math itself (image_processing
module) or the multi-page editor (step 9).
"""

import os
import threading
import time

from kivy.clock import Clock
from kivy.properties import StringProperty, ObjectProperty, BooleanProperty, NumericProperty
from kivymd.uix.screen import MDScreen
from kivymd.app import MDApp

from scanner.camera import (
    DocumentCamera,
    CAMERA_AVAILABLE,
    camera_permission_granted,
    request_camera_permission,
)
from scanner.auto_capture import AutoCaptureController
from image_processing.perspective import correct_document_file


class ScannerScreen(MDScreen):
    camera_container = ObjectProperty(None)
    permission_box = ObjectProperty(None)
    shutter_button = ObjectProperty(None)
    flash_button = ObjectProperty(None)
    hint_label = ObjectProperty(None)
    top_bar = ObjectProperty(None)
    auto_ring = ObjectProperty(None)
    page_count_text = StringProperty("0 pages")
    document_detected = BooleanProperty(False)
    ring_progress = NumericProperty(0.0)
    auto_capture_enabled = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.camera_widget = None
        self._flash_on = False
        self._auto_capture = AutoCaptureController(stability_duration=0.9)

    # ---- Lifecycle -----------------------------------------------------

    def on_pre_enter(self, *args):
        self._update_page_count()
        if self.hint_label:
            self.hint_label.text = "Point the camera at a document"
        # Only apply the saved default when starting a fresh session -
        # once the user has toggled it mid-session, further pages keep
        # whatever they chose rather than resetting on every re-entry.
        app = MDApp.get_running_app()
        if not app.active_session_pages:
            self.auto_capture_enabled = bool(app.prefs.get("auto_capture"))

    def on_enter(self, *args):
        if not camera_permission_granted():
            self._show_permission_prompt()
            return
        self._ensure_camera_widget()
        # Connect one frame later so the widget has a size before
        # Camera4Kivy tries to bind a preview surface to it.
        Clock.schedule_once(lambda dt: self.camera_widget.start(analyze=True), 0)

    def on_leave(self, *args):
        if self.camera_widget:
            self.camera_widget.stop()
        self.document_detected = False
        self._auto_capture.reset()
        self.ring_progress = 0.0

    # ---- Permission -----------------------------------------------------

    def request_permission(self):
        request_camera_permission(self._on_permission_result)

    def _on_permission_result(self, granted: bool):
        if granted:
            self._hide_permission_prompt()
            self._ensure_camera_widget()
            Clock.schedule_once(lambda dt: self.camera_widget.start(analyze=True), 0)
        else:
            self._show_permission_prompt()

    def _show_permission_prompt(self):
        self.permission_box.opacity = 1
        self.permission_box.disabled = False
        self.shutter_button.disabled = True

    def _hide_permission_prompt(self):
        self.permission_box.opacity = 0
        self.permission_box.disabled = True
        self.shutter_button.disabled = False

    # ---- Camera setup -----------------------------------------------------

    def _ensure_camera_widget(self):
        if self.camera_widget is not None:
            return
        if not CAMERA_AVAILABLE:
            # Desktop dev environment without camera4kivy installed -
            # surface this clearly instead of silently showing nothing.
            self.permission_box.opacity = 1
            self.permission_box.disabled = False
            return
        self.camera_widget = DocumentCamera(
            size_hint=(1, 1), on_detection=self._on_detection
        )
        self.camera_container.add_widget(self.camera_widget, index=1)

    def _on_detection(self, quad, frame_size):
        # Runs on the main thread (DocumentCamera schedules it there).
        self.document_detected = quad is not None
        if self.hint_label:
            if self.document_detected:
                self.hint_label.text = (
                    "Hold still..." if self.auto_capture_enabled else "Document detected - tap to capture"
                )
            else:
                self.hint_label.text = "Point the camera at a document"

        if not self.auto_capture_enabled:
            self._auto_capture.reset()
            self.ring_progress = 0.0
            return

        frame_w, frame_h = frame_size
        diagonal = (frame_w ** 2 + frame_h ** 2) ** 0.5
        status = self._auto_capture.update(quad, diagonal, now=time.monotonic())
        self.ring_progress = status.progress
        if status.should_capture:
            self.capture()

    # ---- Capture -----------------------------------------------------

    def capture(self):
        if not self.camera_widget or self.shutter_button.disabled:
            return
        self.shutter_button.disabled = True
        self._auto_capture.reset()
        self.ring_progress = 0.0
        app = MDApp.get_running_app()
        session_id = id(app.active_session_pages)
        self.camera_widget.capture(
            subdir=f"session_{session_id}",
            on_saved=self._on_page_captured,
        )

    def _on_page_captured(self, path: str):
        app = MDApp.get_running_app()
        app.latest_raw_path = path  # kept for the manual crop editor (step 7)
        # Perspective correction (step 6) runs off the main thread -
        # warpPerspective on a full-resolution photo is fast but not
        # free, and this must never stutter the UI.
        if self.hint_label:
            self.hint_label.text = "Processing..."
        threading.Thread(
            target=self._process_capture, args=(path,), daemon=True
        ).start()

    def _process_capture(self, raw_path: str):
        base, ext = os.path.splitext(raw_path)
        corrected_path = f"{base}_corrected.jpg"
        try:
            was_corrected = correct_document_file(raw_path, corrected_path)
            final_path = corrected_path if was_corrected else raw_path
        except Exception:
            # Detection/warp failed on this particular photo (e.g. very
            # different lighting than the live preview) - fall back to
            # the raw capture rather than losing the page entirely.
            final_path = raw_path
        Clock.schedule_once(lambda dt: self._on_capture_processed(final_path), 0)

    def _on_capture_processed(self, path: str):
        app = MDApp.get_running_app()
        app.active_session_pages.append(path)
        self.shutter_button.disabled = False
        self._update_page_count()
        app.latest_capture_path = path
        app.go_to("preview")

    def _update_page_count(self):
        app = MDApp.get_running_app()
        count = len(app.active_session_pages)
        self.page_count_text = "1 page" if count == 1 else f"{count} pages"

    # ---- Auto-capture toggle -----------------------------------------

    def toggle_auto_capture(self):
        self.auto_capture_enabled = not self.auto_capture_enabled
        self._auto_capture.reset()
        self.ring_progress = 0.0
        MDApp.get_running_app().prefs.set("auto_capture", self.auto_capture_enabled)
        icon = "timer-outline" if self.auto_capture_enabled else "timer-off-outline"
        if self.top_bar:
            self.top_bar.right_action_items = [
                ["flash-off", lambda x: self.toggle_flash()],
                [icon, lambda x: self.toggle_auto_capture()],
            ]

    # ---- Navigation -----------------------------------------------------

    def toggle_flash(self):
        # Camera4Kivy exposes flash as a connect_camera()/reconnect option
        # rather than a live property, so a real toggle needs a
        # disconnect+reconnect cycle - deferred alongside remaining
        # capture-quality controls (focus, exposure).
        self._flash_on = not self._flash_on

    def go_to_pages(self):
        MDApp.get_running_app().go_to("editor")

    def close_scanner(self):
        MDApp.get_running_app().go_to("home")
