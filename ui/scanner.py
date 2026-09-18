"""
Scanner screen controller.

Changes in this version:
- Capture is guarded against double taps / auto+manual races.
- Camera errors are shown in the UI instead of crashing the app.
- Single / Batch capture modes.
- Scan / ID Cards modes matching the provided scanner UI.
- ID Cards mode guides the user through front/back captures.
- Stable auto-capture uses full quadrilateral movement, not only centroid.
"""

import os
import shutil
import threading
import time

from kivy.clock import Clock
from kivy.properties import (
    BooleanProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.screen import MDScreen

from image_processing.perspective import correct_document_file
from image_processing.id_card import combine_id_card_front_back
from scanner.auto_capture import AutoCaptureController
from storage.file_picker import FilePicker, copy_to_app_temp, render_pdf_to_images
from scanner.camera import (
    CAMERA_AVAILABLE,
    DocumentCamera,
    camera_permission_granted,
    request_camera_permission,
)


class ScannerScreen(MDScreen):
    camera_container = ObjectProperty(None)
    permission_box = ObjectProperty(None)
    shutter_button = ObjectProperty(None)
    hint_label = ObjectProperty(None)
    top_bar = ObjectProperty(None)
    auto_ring = ObjectProperty(None)

    page_count_text = StringProperty("0 pages")
    document_detected = BooleanProperty(False)
    ring_progress = NumericProperty(0.0)
    auto_capture_enabled = BooleanProperty(True)

    capture_mode = StringProperty("single")   # single | batch
    scan_type = StringProperty("scan")        # scan | id_card
    capture_busy = BooleanProperty(False)
    flash_on = BooleanProperty(False)
    enhance_on = BooleanProperty(True)
    hd_mode = BooleanProperty(True)
    scan_feedback = StringProperty("Find document")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.camera_widget = None
        self._file_picker = FilePicker()
        self._auto_capture = AutoCaptureController(
            stability_duration=1.05,
            corner_movement_ratio=0.014,
            centroid_movement_ratio=0.010,
            max_area_change_ratio=0.060,
            minimum_stable_updates=5,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_pre_enter(self, *args):
        self.capture_busy = False
        self._update_page_count()
        self._auto_capture.reset()
        self.ring_progress = 0.0
        self.scan_feedback = "Find document"

        app = MDApp.get_running_app()
        if not app.active_session_pages:
            self.auto_capture_enabled = bool(
                app.prefs.get("auto_capture")
            )
            self.capture_mode = "single"
            self.scan_type = "scan"

        self._update_hint()

    def on_enter(self, *args):
        if not camera_permission_granted():
            self._show_permission_prompt()
            return

        self._hide_permission_prompt()
        self._ensure_camera_widget()

        if self.camera_widget is not None:
            # The camera widget is reused between pages/screens.  Clear any
            # previous page's tracker/smoothing history before analysis starts.
            try:
                self.camera_widget.reset_detection_state()
            except Exception:
                pass
            Clock.schedule_once(
                lambda dt: self.camera_widget.start(analyze=True),
                0.10,
            )

    def on_leave(self, *args):
        if self.camera_widget:
            self.camera_widget.stop()

        self.capture_busy = False
        self.document_detected = False
        self.flash_on = False
        self._auto_capture.reset()
        self.ring_progress = 0.0
        self.scan_feedback = "Find document"

    # ------------------------------------------------------------------
    # Permission
    # ------------------------------------------------------------------

    def request_permission(self):
        request_camera_permission(self._on_permission_result)

    def _on_permission_result(self, granted: bool):
        if not granted:
            self._show_permission_prompt()
            return

        self._hide_permission_prompt()
        self._ensure_camera_widget()

        if self.camera_widget is not None:
            Clock.schedule_once(
                lambda dt: self.camera_widget.start(analyze=True),
                0.10,
            )

    def _show_permission_prompt(self):
        if self.permission_box:
            self.permission_box.opacity = 1
            self.permission_box.disabled = False

        if self.shutter_button:
            self.shutter_button.disabled = True

    def _hide_permission_prompt(self):
        if self.permission_box:
            self.permission_box.opacity = 0
            self.permission_box.disabled = True

        if self.shutter_button:
            self.shutter_button.disabled = self.capture_busy

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def _ensure_camera_widget(self):
        if self.camera_widget is not None:
            return

        if not CAMERA_AVAILABLE:
            self._show_camera_error(
                "Camera4Kivy is not available in this build."
            )
            return

        try:
            self.camera_widget = DocumentCamera(
                size_hint=(1, 1),
                on_detection=self._on_detection,
                on_camera_error=self._show_camera_error,
            )
            # Camera goes behind labels/overlays.
            self.camera_container.add_widget(
                self.camera_widget,
                index=len(self.camera_container.children),
            )
        except Exception as exc:
            self.camera_widget = None
            self._show_camera_error(
                f"Could not create camera preview: {exc}"
            )

    def _show_camera_error(self, message: str):
        self.capture_busy = False

        if self.shutter_button:
            self.shutter_button.disabled = False

        if self.hint_label:
            self.hint_label.text = "Camera error"

        dialog = MDDialog(
            title="Camera error",
            text=str(message),
            buttons=[
                MDFlatButton(
                    text="OK",
                    on_release=lambda *a: dialog.dismiss(),
                )
            ],
        )
        dialog.open()

    # ------------------------------------------------------------------
    # Detection / auto capture
    # ------------------------------------------------------------------

    def _on_detection(self, quad, frame_size):
        if self.capture_busy:
            return

        self.document_detected = (
            quad is not None
        )

        quality = None
        if self.camera_widget is not None:
            quality = getattr(
                self.camera_widget,
                "last_quality",
                None,
            )

        if not self.auto_capture_enabled:
            self._auto_capture.reset()
            self.ring_progress = 0.0

            if (
                quality is not None
                and quad is not None
            ):
                self.scan_feedback = (
                    quality.reason
                    if not quality.acceptable
                    else (
                        "Document detected - "
                        "tap capture"
                    )
                )
            else:
                self.scan_feedback = (
                    "Find document"
                )

            self._update_hint()
            return

        if quad is None:
            self._auto_capture.reset()
            self.ring_progress = 0.0
            self.scan_feedback = (
                "Find document"
            )
            self._update_hint()
            return

        frame_w, frame_h = frame_size
        diagonal = (
            frame_w ** 2
            + frame_h ** 2
        ) ** 0.5

        status = self._auto_capture.update(
            quad,
            diagonal,
            now=time.monotonic(),
            quality=quality,
        )

        self.ring_progress = (
            status.progress
        )
        self.scan_feedback = (
            self._auto_capture.feedback
        )
        self._update_hint()

        if (
            status.should_capture
            and not self.capture_busy
        ):
            self.capture()

    def _update_hint(self):
        if not self.hint_label:
            return

        if self.capture_busy:
            self.hint_label.text = (
                "Processing..."
            )
            return

        if self.scan_type == "id_card":
            count = len(
                MDApp.get_running_app()
                .active_session_pages
            )

            if count == 0:
                base = (
                    "Place the FRONT "
                    "of the ID card"
                )
            elif count == 1:
                base = (
                    "Place the BACK "
                    "of the ID card"
                )
            else:
                base = (
                    "ID card captured"
                )
        else:
            base = (
                "Point at document "
                "& hold steady"
            )

        if not self.document_detected:
            self.hint_label.text = base
            return

        feedback = (
            self.scan_feedback
            or "Hold steady"
        )

        # In ID-card mode preserve front/back instruction until a quality
        # problem or Ready/Hold-steady state actually matters.
        if (
            self.scan_type == "id_card"
            and feedback
            == "Find document"
        ):
            self.hint_label.text = base
            return

        self.hint_label.text = feedback

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture(self):
        if self.capture_busy:
            return

        if self.camera_widget is None:
            self._show_camera_error(
                "Camera is not ready yet."
            )
            return

        if getattr(self.camera_widget, "capture_in_progress", False):
            return

        # ID Cards mode intentionally accepts only front + back.
        app = MDApp.get_running_app()
        if self.scan_type == "id_card" and len(app.active_session_pages) >= 2:
            self._show_info(
                "ID Cards",
                "Front and back have already been captured.",
            )
            return

        self.capture_busy = True
        self.shutter_button.disabled = True
        self._auto_capture.reset()
        self.ring_progress = 0.0
        self._update_hint()

        session_id = id(app.active_session_pages)

        started = self.camera_widget.capture(
            subdir=f"session_{session_id}",
            on_saved=self._on_page_captured,
            on_error=self._on_capture_error,
        )

        if not started:
            self._on_capture_error(
                "The camera did not start the capture."
            )

    def _on_capture_error(self, message: str):
        self.capture_busy = False
        self.ring_progress = 0.0

        if self.shutter_button:
            self.shutter_button.disabled = False

        self._update_hint()

        self._show_info(
            "Capture failed",
            str(message),
        )

    def _on_page_captured(self, path: str):
        if not path or not isinstance(path, str):
            self._on_capture_error(
                "The camera returned an invalid photo path."
            )
            return

        app = MDApp.get_running_app()
        app.latest_raw_path = path

        if self.hint_label:
            self.hint_label.text = "Detecting document..."

        threading.Thread(
            target=self._process_capture,
            args=(path,),
            daemon=True,
        ).start()

    def _process_capture(self, raw_path: str):
        base, _ = os.path.splitext(raw_path)
        corrected_path = f"{base}_corrected.jpg"

        try:
            was_corrected = correct_document_file(
                raw_path,
                corrected_path,
            )
            final_path = (
                corrected_path if was_corrected else raw_path
            )
        except Exception:
            final_path = raw_path

        Clock.schedule_once(
            lambda dt, p=final_path:
                self._on_capture_processed(p),
            0,
        )

    def _on_capture_processed(self, path: str):
        app = MDApp.get_running_app()

        app.active_session_pages.append(path)
        app.latest_capture_path = path

        self.capture_busy = False
        self.document_detected = False
        self.ring_progress = 0.0
        self.scan_feedback = "Find document"
        self._auto_capture.reset()

        # In Batch mode the CameraX session stays alive.  Explicitly forget
        # the page that was just captured so the next page gets a brand-new
        # edge detection/tracking cycle instead of inheriting a stale quad.
        if self.camera_widget is not None:
            try:
                self.camera_widget.reset_detection_state()
            except Exception:
                pass

        if self.shutter_button:
            self.shutter_button.disabled = False

        self._update_page_count()
        self._update_hint()

        # ID / NID workflow:
        # 1) first side stays in the camera session;
        # 2) after the back side is captured, combine both corrected card
        #    images onto one A4 page without stretching either card;
        # 3) replace the two temporary session pages with the combined page;
        # 4) open the normal Editor, so existing save/export code works
        #    unchanged.
        if self.scan_type == "id_card":
            if len(app.active_session_pages) >= 2:
                self.capture_busy = True
                if self.shutter_button:
                    self.shutter_button.disabled = True
                if self.hint_label:
                    self.hint_label.text = "Combining front & back..."

                front_path = app.active_session_pages[0]
                back_path = app.active_session_pages[1]

                threading.Thread(
                    target=self._combine_id_card_worker,
                    args=(front_path, back_path),
                    daemon=True,
                ).start()
            return

        # Batch mode keeps the camera open. Single mode preserves the
        # existing review/crop/filter flow.
        if self.capture_mode == "batch":
            return

        app.go_to("preview")

    def _combine_id_card_worker(
        self,
        front_path: str,
        back_path: str,
    ):
        """Build one A4 page from front/back off the Kivy UI thread."""
        app = MDApp.get_running_app()
        output_path = app.storage.get_temp_path(
            f"id_card_combined_{int(time.time() * 1000)}.jpg"
        )

        try:
            combine_id_card_front_back(
                front_path,
                back_path,
                output_path,
            )
        except Exception as exc:
            Clock.schedule_once(
                lambda dt, message=str(exc):
                    self._on_id_card_combine_failed(message),
                0,
            )
            return

        Clock.schedule_once(
            lambda dt, path=output_path:
                self._on_id_card_combined(path),
            0,
        )

    def _on_id_card_combined(
        self,
        combined_path: str,
    ):
        app = MDApp.get_running_app()

        app.active_session_pages = [
            combined_path
        ]
        app.latest_capture_path = combined_path
        app.latest_raw_path = None

        self.capture_busy = False
        self.document_detected = False
        self.ring_progress = 0.0
        self.scan_feedback = "Find document"

        if self.shutter_button:
            self.shutter_button.disabled = False

        self._update_page_count()

        self.scan_type = "scan"
        self.capture_mode = "single"

        app.go_to("editor")

    def _on_id_card_combine_failed(
        self,
        message: str,
    ):
        """Fail safely and keep front/back as separate pages."""
        app = MDApp.get_running_app()

        self.capture_busy = False
        if self.shutter_button:
            self.shutter_button.disabled = False

        self._show_info(
            "ID card combine failed",
            (
                f"{message}\n\n"
                "The front and back images were kept as separate pages."
            ),
        )

        app.go_to("editor")

    # ------------------------------------------------------------------
    # Capture mode controls
    # ------------------------------------------------------------------

    def select_capture_mode(self, mode: str):
        if mode not in ("single", "batch"):
            return

        self.capture_mode = mode
        self._auto_capture.reset()
        self.ring_progress = 0.0
        self._update_hint()

    def select_scan_type(self, scan_type: str):
        if scan_type not in ("scan", "id_card"):
            return

        app = MDApp.get_running_app()

        # Avoid mixing regular document pages and ID-card sides in one
        # session. Ask before discarding already captured unsaved pages.
        if app.active_session_pages and scan_type != self.scan_type:
            def switch_after_discard(*args):
                dialog.dismiss()
                app.active_session_pages = []
                app.latest_capture_path = None
                app.latest_raw_path = None
                self.scan_type = scan_type
                if scan_type == "id_card":
                    self.capture_mode = "batch"
                self._update_page_count()
                self._update_hint()

            dialog = MDDialog(
                title="Change scan mode?",
                text=(
                    "Changing between Document Scan and ID Cards will "
                    "discard the unsaved pages in the current scan."
                ),
                buttons=[
                    MDFlatButton(
                        text="CANCEL",
                        on_release=lambda *a: dialog.dismiss(),
                    ),
                    MDFlatButton(
                        text="DISCARD",
                        on_release=switch_after_discard,
                    ),
                ],
            )
            dialog.open()
            return

        self.scan_type = scan_type

        # Front/back ID capture behaves like a tiny batch.
        if scan_type == "id_card":
            self.capture_mode = "batch"

        self._auto_capture.reset()
        self.ring_progress = 0.0
        self._update_hint()

    # ------------------------------------------------------------------
    # Import from Gallery / Files
    # ------------------------------------------------------------------

    def pick_image(self):
        if self.capture_busy:
            return
        self._file_picker.choose_image(
            self._on_image_picked,
            self._on_picker_error,
        )

    def pick_pdf(self):
        if self.capture_busy:
            return
        self._file_picker.choose_pdf(
            self._on_pdf_picked,
            self._on_picker_error,
        )

    def _on_picker_error(self, message):
        self._show_info("Import", str(message))

    def _on_image_picked(self, selected_path):
        app = MDApp.get_running_app()

        try:
            private_path = copy_to_app_temp(
                selected_path,
                app.storage,
                prefix="gallery",
            )
        except Exception as exc:
            self._show_info(
                "Image import failed",
                str(exc),
            )
            return

        self.capture_busy = True
        if self.shutter_button:
            self.shutter_button.disabled = True
        if self.hint_label:
            self.hint_label.text = "Importing image..."

        app.latest_raw_path = private_path

        threading.Thread(
            target=self._process_capture,
            args=(private_path,),
            daemon=True,
        ).start()

    def _on_pdf_picked(self, selected_path):
        app = MDApp.get_running_app()

        try:
            private_pdf = copy_to_app_temp(
                selected_path,
                app.storage,
                prefix="pdf",
            )
        except Exception as exc:
            self._show_info(
                "PDF import failed",
                str(exc),
            )
            return

        self.capture_busy = True
        if self.shutter_button:
            self.shutter_button.disabled = True
        if self.hint_label:
            self.hint_label.text = "Importing PDF..."

        threading.Thread(
            target=self._import_pdf_worker,
            args=(private_pdf,),
            daemon=True,
        ).start()

    def _import_pdf_worker(self, pdf_path):
        app = MDApp.get_running_app()
        output_dir = app.storage.get_temp_path(
            f"pdf_pages_{int(time.time() * 1000)}"
        )

        try:
            pages = render_pdf_to_images(
                pdf_path,
                output_dir,
            )
            Clock.schedule_once(
                lambda dt, items=pages:
                    self._on_pdf_imported(items),
                0,
            )
        except Exception as exc:
            Clock.schedule_once(
                lambda dt, message=str(exc):
                    self._on_pdf_import_failed(message),
                0,
            )

    def _on_pdf_imported(self, pages):
        self.capture_busy = False

        if self.shutter_button:
            self.shutter_button.disabled = False

        if not pages:
            self._show_info(
                "PDF import failed",
                "The selected PDF contains no readable pages.",
            )
            self._update_hint()
            return

        app = MDApp.get_running_app()
        app.active_session_pages = list(pages)
        app.latest_capture_path = pages[-1]
        app.latest_raw_path = None
        self._update_page_count()
        app.go_to("editor")

    def _on_pdf_import_failed(self, message):
        self.capture_busy = False

        if self.shutter_button:
            self.shutter_button.disabled = False

        self._update_hint()
        self._show_info(
            "PDF import failed",
            message,
        )

    # ------------------------------------------------------------------
    # Auto capture / flash
    # ------------------------------------------------------------------

    def toggle_auto_capture(self):
        self.auto_capture_enabled = not self.auto_capture_enabled
        self._auto_capture.reset()
        self.ring_progress = 0.0

        MDApp.get_running_app().prefs.set(
            "auto_capture",
            self.auto_capture_enabled,
        )

        icon = (
            "timer-outline"
            if self.auto_capture_enabled
            else "timer-off-outline"
        )

        if self.top_bar:
            self.top_bar.right_action_items = [
                [
                    "flash-off",
                    lambda x: self.toggle_flash(),
                ],
                [
                    icon,
                    lambda x: self.toggle_auto_capture(),
                ],
            ]

        self._update_hint()

    def toggle_flash(self):
        if self.camera_widget is None:
            self._show_info(
                "Flash",
                "Camera is not ready yet.",
            )
            return

        requested = not self.flash_on
        success = self.camera_widget.set_torch(requested)

        if success:
            self.flash_on = requested
        else:
            self.flash_on = False

    def toggle_enhance(self):
        """
        UI control matching the reference scanner.

        Perspective correction and document enhancement already happen
        after capture; this switch controls the visual state and leaves
        the stable live detector enabled.
        """
        self.enhance_on = not self.enhance_on

    def toggle_hd(self):
        # Camera4Kivy uses the highest available sensor resolution by
        # default. Keep HD enabled by default; this button mirrors the
        # reference scanner control without reconnecting CameraX.
        self.hd_mode = not self.hd_mode

    def open_more(self):
        self._show_info(
            "Scanner options",
            "Use Single/Batch for page capture and Scan/ID Cards for "
            "document type. Pinch to zoom and tap the preview to focus.",
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def go_to_pages(self):
        app = MDApp.get_running_app()
        if app.active_session_pages:
            app.go_to("editor")

    def close_scanner(self):
        MDApp.get_running_app().go_to("home")

    def _update_page_count(self):
        count = len(
            MDApp.get_running_app().active_session_pages
        )
        self.page_count_text = (
            "1 page" if count == 1 else f"{count} pages"
        )

    @staticmethod
    def _show_info(title: str, text: str):
        dialog = MDDialog(
            title=title,
            text=text,
            buttons=[
                MDFlatButton(
                    text="OK",
                    on_release=lambda *a: dialog.dismiss(),
                )
            ],
        )
        dialog.open()
