"""
Working tool flows for the Tools dashboard:
- Extract Text
- Passport Photo Maker
- Photo Translation
- Scan Code

All image selection uses androidstorage4kivy through storage.file_picker.
Long-running OCR / translation / OpenCV work runs off the UI thread.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

import cv2

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import (
    MDFlatButton,
    MDRaisedButton,
)
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar

from ocr.ocr_manager import run_ocr_for_pages
from storage.file_picker import FilePicker, copy_to_app_temp


MODE_INFO = {
    "extract_text": {
        "title": "Extract Text",
        "subtitle": "Select an image and extract text with OCR.",
        "button": "SELECT IMAGE",
    },
    "passport_photo": {
        "title": "Passport Photo Maker",
        "subtitle": "Create a 35 × 45 mm passport-size photo from an image.",
        "button": "SELECT PHOTO",
    },
    "photo_translation": {
        "title": "Photo Translation",
        "subtitle": "Extract English text from a photo and translate it to Bengali.",
        "button": "SELECT IMAGE",
    },
    "scan_code": {
        "title": "Scan Code",
        "subtitle": "Select an image containing a QR code.",
        "button": "SELECT QR IMAGE",
    },
}


class ToolWorkflowScreen(MDScreen):
    status_text = StringProperty("")
    result_text = StringProperty("")

    def __init__(self, mode, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode
        self._picker = FilePicker()
        self._selected_image = None
        self._passport_output = None
        self._preview = None
        self._build_ui()

    def _build_ui(self):
        info = MODE_INFO[self.mode]

        root = MDBoxLayout(
            orientation="vertical",
            md_bg_color=(0.97, 0.98, 1, 1),
        )

        toolbar = MDTopAppBar(
            title=info["title"],
            elevation=0,
            md_bg_color=(0.97, 0.98, 1, 1),
            specific_text_color=(0.05, 0.09, 0.17, 1),
        )
        toolbar.left_action_items = [
            ["arrow-left", lambda *_: MDApp.get_running_app().go_to("tools")]
        ]
        root.add_widget(toolbar)

        scroll = ScrollView(do_scroll_x=False)
        body = MDBoxLayout(
            orientation="vertical",
            adaptive_height=True,
            padding=(dp(20), dp(18), dp(20), dp(24)),
            spacing=dp(14),
        )

        body.add_widget(
            MDLabel(
                text=info["subtitle"],
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(54),
            )
        )

        select_button = MDRaisedButton(
            text=info["button"],
            pos_hint={"center_x": 0.5},
            on_release=lambda *_: self.pick_image(),
        )
        body.add_widget(select_button)

        self.status_label = MDLabel(
            text="",
            halign="center",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(40),
        )
        body.add_widget(self.status_label)

        self.preview_box = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=0,
        )
        body.add_widget(self.preview_box)

        self.result_field = MDTextField(
            text="",
            hint_text="Result",
            mode="rectangle",
            multiline=True,
            readonly=True,
            size_hint_y=None,
            height=dp(280),
        )
        body.add_widget(self.result_field)

        actions = MDBoxLayout(
            orientation="horizontal",
            adaptive_width=True,
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
            pos_hint={"center_x": 0.5},
        )

        actions.add_widget(
            MDFlatButton(
                text="COPY RESULT",
                on_release=lambda *_: self.copy_result(),
            )
        )

        if self.mode == "passport_photo":
            actions.add_widget(
                MDRaisedButton(
                    text="OPEN IN EDITOR",
                    on_release=lambda *_: self.open_passport_in_editor(),
                )
            )

        body.add_widget(actions)

        scroll.add_widget(body)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        self.status_label.text = ""
        if self.mode != "passport_photo":
            self.result_field.text = ""

    # ------------------------------------------------------------------
    # Picker
    # ------------------------------------------------------------------

    def pick_image(self):
        self.status_label.text = "Opening gallery..."
        self._picker.choose_image(
            self._on_image_selected,
            self._on_picker_error,
        )

    def _on_picker_error(self, message):
        self.status_label.text = ""
        self._show_error("Image selection", str(message))

    def _on_image_selected(self, path):
        app = MDApp.get_running_app()

        try:
            local_path = copy_to_app_temp(
                path,
                app.storage,
                prefix=self.mode,
            )
        except Exception as exc:
            self._show_error("Import failed", str(exc))
            return

        self._selected_image = local_path
        self.status_label.text = "Processing..."

        worker = {
            "extract_text": self._worker_extract_text,
            "passport_photo": self._worker_passport_photo,
            "photo_translation": self._worker_photo_translation,
            "scan_code": self._worker_scan_code,
        }[self.mode]

        threading.Thread(
            target=worker,
            args=(local_path,),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # Extract Text
    # ------------------------------------------------------------------

    def _worker_extract_text(self, path):
        try:
            app = MDApp.get_running_app()
            language = app.prefs.get("ocr_language") or "english"
            text = run_ocr_for_pages([path], language)
            if not text.strip():
                text = "No readable text was detected."
            self._post_result(text)
        except Exception as exc:
            self._post_error("OCR failed", str(exc))

    # ------------------------------------------------------------------
    # Photo Translation
    # ------------------------------------------------------------------

    def _worker_photo_translation(self, path):
        try:
            original = run_ocr_for_pages([path], "english").strip()
            if not original:
                raise RuntimeError("No readable English text was detected.")

            translated = self._translate_to_bengali(original)

            result = (
                "ORIGINAL TEXT\n"
                "--------------------\n"
                f"{original}\n\n"
                "BENGALI TRANSLATION\n"
                "--------------------\n"
                f"{translated}"
            )
            self._post_result(result)
        except Exception as exc:
            self._post_error("Photo translation failed", str(exc))

    @staticmethod
    def _translate_to_bengali(text):
        """
        Lightweight online translation using Google's public web
        translation endpoint. INTERNET permission already exists in the app.
        """
        query = urllib.parse.urlencode(
            {
                "client": "gtx",
                "sl": "auto",
                "tl": "bn",
                "dt": "t",
                "q": text,
            }
        )
        url = (
            "https://translate.googleapis.com/translate_a/single?"
            + query
        )

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))

        translated_parts = []
        for part in payload[0]:
            if part and part[0]:
                translated_parts.append(part[0])

        translated = "".join(translated_parts).strip()
        if not translated:
            raise RuntimeError("Translation service returned no text.")
        return translated

    # ------------------------------------------------------------------
    # QR / Scan Code
    # ------------------------------------------------------------------

    def _worker_scan_code(self, path):
        try:
            image = cv2.imread(path)
            if image is None:
                raise RuntimeError("Could not decode the selected image.")

            detector = cv2.QRCodeDetector()
            results = []

            # Newer OpenCV builds can decode multiple QR codes.
            try:
                ok, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
                if ok:
                    results.extend(
                        item.strip()
                        for item in decoded_info
                        if item and item.strip()
                    )
            except Exception:
                pass

            if not results:
                data, points, _ = detector.detectAndDecode(image)
                if data and data.strip():
                    results.append(data.strip())

            if not results:
                self._post_result(
                    "No QR code could be decoded from this image."
                )
            else:
                text = "\n\n".join(
                    f"Code {index + 1}:\n{value}"
                    for index, value in enumerate(results)
                )
                self._post_result(text)
        except Exception as exc:
            self._post_error("Scan Code failed", str(exc))

    # ------------------------------------------------------------------
    # Passport photo
    # ------------------------------------------------------------------

    def _worker_passport_photo(self, path):
        try:
            image = cv2.imread(path)
            if image is None:
                raise RuntimeError("Could not decode the selected photo.")

            height, width = image.shape[:2]

            # Passport photo aspect: 35mm × 45mm => width/height = 7/9.
            target_ratio = 35.0 / 45.0
            current_ratio = width / float(height)

            if current_ratio > target_ratio:
                # Too wide: center-crop horizontally.
                crop_width = int(round(height * target_ratio))
                x1 = max(0, (width - crop_width) // 2)
                cropped = image[:, x1:x1 + crop_width]
            else:
                # Too tall/narrow: center-crop vertically.
                crop_height = int(round(width / target_ratio))
                y1 = max(0, (height - crop_height) // 2)
                cropped = image[y1:y1 + crop_height, :]

            # 35x45 mm at 300 DPI is approximately 413x531 pixels.
            output = cv2.resize(
                cropped,
                (413, 531),
                interpolation=cv2.INTER_CUBIC,
            )

            app = MDApp.get_running_app()
            output_path = app.storage.get_temp_path(
                f"passport_35x45_{int(time.time() * 1000)}.jpg"
            )

            if not cv2.imwrite(
                output_path,
                output,
                [int(cv2.IMWRITE_JPEG_QUALITY), 96],
            ):
                raise RuntimeError("Could not save the passport photo.")

            self._passport_output = output_path

            Clock.schedule_once(
                lambda dt, p=output_path:
                    self._show_passport_preview(p),
                0,
            )
        except Exception as exc:
            self._post_error("Passport Photo Maker failed", str(exc))

    def _show_passport_preview(self, path):
        self.status_label.text = "35 × 45 mm photo created."
        self.result_field.text = (
            "Passport photo created successfully.\n"
            "Size: 413 × 531 px (35 × 45 mm aspect at ~300 DPI).\n"
            "Tap OPEN IN EDITOR to continue."
        )

        self.preview_box.clear_widgets()
        self.preview_box.height = dp(360)

        preview = Image(
            source=path,
            fit_mode="contain",
        )
        self.preview_box.add_widget(preview)

    def open_passport_in_editor(self):
        if not self._passport_output:
            self._show_error(
                "Passport Photo Maker",
                "Create a passport photo first.",
            )
            return

        app = MDApp.get_running_app()
        app.active_session_pages = [self._passport_output]
        app.latest_capture_path = self._passport_output
        app.latest_raw_path = self._selected_image
        app.go_to("editor")

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    def _post_result(self, text):
        Clock.schedule_once(
            lambda dt, value=str(text):
                self._set_result(value),
            0,
        )

    def _set_result(self, text):
        self.status_label.text = "Done"
        self.result_field.text = text

    def _post_error(self, title, message):
        Clock.schedule_once(
            lambda dt, t=title, m=message:
                self._show_error(t, m),
            0,
        )

    def _show_error(self, title, message):
        self.status_label.text = ""
        dialog = MDDialog(
            title=title,
            text=str(message),
            buttons=[
                MDFlatButton(
                    text="OK",
                    on_release=lambda *_: dialog.dismiss(),
                )
            ],
        )
        dialog.open()

    def copy_result(self):
        text = self.result_field.text.strip()
        if not text:
            self._show_error("Copy", "There is no result to copy yet.")
            return
        Clipboard.copy(text)
        self.status_label.text = "Copied to clipboard"
