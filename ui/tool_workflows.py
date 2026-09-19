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

from ocr.ocr_manager import run_ocr_for_pages, ocr_language_status, run_ocr_with_fallback
from tools.code_reader import decode_codes, classify_payload
from image_processing.passport_photo import create_passport_photo, create_print_sheet, analyze_passport_alignment
from tools.id_passport_intelligence import (
    parse_bangladesh_nid_text, format_nid_result,
    parse_passport_mrz, format_mrz_result,
)
from storage.file_picker import FilePicker, copy_to_app_temp


MODE_INFO = {
    "nid_intelligence": {
        "title": "NID OCR",
        "subtitle": "Extract structured fields from a Bangladesh NID image.",
        "button": "SELECT NID IMAGE",
    },
    "passport_mrz": {
        "title": "Passport MRZ",
        "subtitle": "Read and validate the 2-line passport MRZ (TD3).",
        "button": "SELECT PASSPORT IMAGE",
    },
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
        "subtitle": "Extract text from a photo and translate between supported languages.",
        "button": "SELECT IMAGE",
    },
    "scan_code": {
        "title": "Scan Code",
        "subtitle": "Select an image containing QR, EAN/UPC, Code 128/39 or another supported barcode.",
        "button": "SELECT CODE IMAGE",
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
        self._passport_sheet_output = None
        self._preview = None
        self._last_qr_value = None
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

        self.passport_preset_field = None
        self.passport_background_field = None
        self.translation_source_field = None
        self.translation_target_field = None
        if self.mode == "passport_photo":
            self.passport_preset_field = MDTextField(
                text="bangladesh",
                hint_text="Preset: bangladesh / india / usa / uk / schengen",
                helper_text="USA uses 51×51 mm; others default to 35×45 mm.",
                helper_text_mode="persistent",
                mode="rectangle",
                size_hint_y=None,
                height=dp(78),
            )
            body.add_widget(self.passport_preset_field)
            self.passport_background_field = MDTextField(
                text="white",
                hint_text="Background: white / blue / light_gray",
                mode="rectangle",
                size_hint_y=None,
                height=dp(62),
            )
            body.add_widget(self.passport_background_field)
        elif self.mode == "photo_translation":
            self.translation_source_field = MDTextField(
                text="auto",
                hint_text="Source: auto / english / bengali / mixed",
                helper_text="Auto tries the configured OCR language, then English fallback.",
                helper_text_mode="persistent",
                mode="rectangle",
                size_hint_y=None,
                height=dp(78),
            )
            body.add_widget(self.translation_source_field)
            self.translation_target_field = MDTextField(
                text="bn",
                hint_text="Target: bn / en / hi / ar / zh / ja",
                helper_text="Translation requires an internet connection.",
                helper_text_mode="persistent",
                mode="rectangle",
                size_hint_y=None,
                height=dp(78),
            )
            body.add_widget(self.translation_target_field)

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
            actions.add_widget(
                MDFlatButton(
                    text="4x6 SHEET",
                    on_release=lambda *_: self.create_passport_sheet("4x6"),
                )
            )
            actions.add_widget(
                MDFlatButton(
                    text="A4 SHEET",
                    on_release=lambda *_: self.create_passport_sheet("a4"),
                )
            )
        elif self.mode == "scan_code":
            actions.add_widget(
                MDFlatButton(
                    text="HISTORY",
                    on_release=lambda *_: self.show_qr_history(),
                )
            )
            actions.add_widget(
                MDFlatButton(
                    text="CLEAR HISTORY",
                    on_release=lambda *_: self.clear_qr_history(),
                )
            )
            actions.add_widget(
                MDRaisedButton(
                    text="OPEN ACTION",
                    on_release=lambda *_: self.open_qr_action(),
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
            "nid_intelligence": self._worker_nid_intelligence,
            "passport_mrz": self._worker_passport_mrz,
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
    # NID / Passport intelligence
    # ------------------------------------------------------------------

    def _worker_nid_intelligence(self, path):
        try:
            text, used_language = run_ocr_with_fallback([path], "mixed")
            if not (text or "").strip():
                raise RuntimeError("No readable NID text was detected.")
            data = parse_bangladesh_nid_text(text)
            result = format_nid_result(data)
            result = f"OCR LANGUAGE: {used_language.upper()}\n\n" + result
            self._post_result(result)
        except Exception as exc:
            self._post_error("NID OCR failed", str(exc))

    def _worker_passport_mrz(self, path):
        try:
            # MRZ uses Latin A-Z/0-9/<, so English is the most reliable first pass.
            text, used_language = run_ocr_with_fallback([path], "english")
            if not (text or "").strip():
                raise RuntimeError("No readable passport text was detected.")
            data = parse_passport_mrz(text)
            result = format_mrz_result(data)
            result = f"OCR LANGUAGE: {used_language.upper()}\n\n" + result
            if data.get("error"):
                result += "\n\nTip: crop closer to the two MRZ lines at the bottom of the passport data page."
            self._post_result(result)
        except Exception as exc:
            self._post_error("Passport MRZ failed", str(exc))

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
            app = MDApp.get_running_app()
            source = (
                self.translation_source_field.text.strip().lower()
                if self.translation_source_field else "auto"
            ) or "auto"
            target = (
                self.translation_target_field.text.strip().lower()
                if self.translation_target_field else "bn"
            ) or "bn"

            ocr_language = source
            if source == "auto":
                preferred = str(app.prefs.get("ocr_language") or "english").strip().lower()
                if preferred not in {"english", "bengali", "mixed"}:
                    preferred = "english"
                available, _message = ocr_language_status(preferred)
                ocr_language = preferred if available else "english"
            elif source not in {"english", "bengali", "mixed"}:
                raise ValueError("OCR source must be auto, english, bengali, or mixed.")

            if ocr_language in {"bengali", "mixed"}:
                available, message = ocr_language_status(ocr_language)
                if not available:
                    if source == "auto":
                        ocr_language = "english"
                    else:
                        raise RuntimeError(message)

            if source == "auto":
                original, ocr_language = run_ocr_with_fallback([path], ocr_language)
            else:
                original = run_ocr_for_pages([path], ocr_language).strip()
            if not original:
                raise RuntimeError("No readable text was detected in the selected image.")

            translated = self._translate_text(
                original,
                source_code="auto",
                target_code=target,
            )

            result = (
                f"OCR LANGUAGE: {ocr_language.upper()}\n"
                "ORIGINAL TEXT\n"
                "--------------------\n"
                f"{original}\n\n"
                f"TRANSLATION ({target.upper()})\n"
                "--------------------\n"
                f"{translated}"
            )
            self._post_result(result)
        except Exception as exc:
            self._post_error("Photo translation failed", str(exc))

    @staticmethod
    def _translate_text(text, source_code="auto", target_code="bn"):
        """Translate text with bounded chunks and retry/backoff.

        This keeps the existing zero-key public Google endpoint, but makes
        failure explicit and avoids one oversized request for long OCR pages.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("Nothing to translate.")

        source_code = (source_code or "auto").strip().lower()
        target_code = (target_code or "bn").strip().lower()
        if not target_code or len(target_code) > 12:
            raise ValueError("Invalid target language code.")

        chunks = []
        current = []
        current_len = 0
        for paragraph in text.splitlines():
            part = paragraph.strip()
            if not part:
                continue
            if current and current_len + len(part) + 1 > 2500:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(part)
            current_len += len(part) + 1
        if current:
            chunks.append("\n".join(current))
        if not chunks:
            chunks = [text[:2500]]

        output = []
        for chunk in chunks:
            query = urllib.parse.urlencode(
                {
                    "client": "gtx",
                    "sl": source_code,
                    "tl": target_code,
                    "dt": "t",
                    "q": chunk,
                }
            )
            url = "https://translate.googleapis.com/translate_a/single?" + query
            last_error = None
            for attempt in range(3):
                try:
                    request = urllib.request.Request(
                        url,
                        headers={"User-Agent": "Pycam/1.0 Android"},
                    )
                    with urllib.request.urlopen(request, timeout=15) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    parts = [
                        part[0]
                        for part in (payload[0] or [])
                        if part and part[0]
                    ]
                    translated = "".join(parts).strip()
                    if not translated:
                        raise RuntimeError("Translation service returned no text.")
                    output.append(translated)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(0.8 * (attempt + 1))
            if last_error is not None:
                raise RuntimeError(
                    "Translation service is unavailable. Check internet connection and retry. "
                    f"({last_error})"
                )

        return "\n".join(output).strip()

    # ------------------------------------------------------------------
    # QR / Scan Code
    # ------------------------------------------------------------------

    def _worker_scan_code(self, path):
        try:
            image = cv2.imread(path)
            if image is None:
                raise RuntimeError("Could not decode the selected image.")

            decoded = decode_codes(image)
            if not decoded:
                self._post_result(
                    "No supported QR/barcode could be decoded from this image. "
                    "Try a sharper, closer image with the whole code visible."
                )
                return

            app = MDApp.get_running_app()
            history = list(app.prefs.get("qr_history") or [])
            from datetime import datetime
            for item in decoded:
                history.insert(
                    0,
                    {
                        "value": item.value,
                        "type": item.symbology,
                        "scanned_at": datetime.utcnow().isoformat(),
                    },
                )

            seen = set()
            clean = []
            for item in history:
                value = str(item.get("value", "")).strip()
                if value and value not in seen:
                    seen.add(value)
                    clean.append(item)
                if len(clean) >= 50:
                    break
            app.prefs.set("qr_history", clean)

            self._last_qr_value = decoded[0].value
            blocks = []
            for index, item in enumerate(decoded, start=1):
                semantic = classify_payload(item.value, fallback=item.symbology)
                label = item.symbology
                if semantic != item.symbology:
                    label = f"{item.symbology} / {semantic}"
                blocks.append(f"Code {index} [{label}]:\n{item.value}")
            self._post_result("\n\n".join(blocks))
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

            preset = (
                self.passport_preset_field.text.strip().lower()
                if self.passport_preset_field else "bangladesh"
            ) or "bangladesh"
            background = (
                self.passport_background_field.text.strip().lower()
                if self.passport_background_field else "white"
            ) or "white"

            alignment = analyze_passport_alignment(image)
            output, size_mm = create_passport_photo(
                image,
                preset=preset,
                background=background,
                dpi=300,
            )

            app = MDApp.get_running_app()
            output_path = app.storage.get_temp_path(
                f"passport_{preset}_{int(time.time() * 1000)}.jpg"
            )

            if not cv2.imwrite(
                output_path,
                output,
                [int(cv2.IMWRITE_JPEG_QUALITY), 96],
            ):
                raise RuntimeError("Could not save the passport photo.")

            self._passport_output = output_path
            self._passport_size_mm = size_mm
            self._passport_preset = preset
            self._passport_background = background
            self._passport_alignment = alignment

            Clock.schedule_once(
                lambda dt, p=output_path:
                    self._show_passport_preview(p),
                0,
            )
        except Exception as exc:
            self._post_error("Passport Photo Maker failed", str(exc))

    def _show_passport_preview(self, path):
        width_mm, height_mm = getattr(self, "_passport_size_mm", (35.0, 45.0))
        image = cv2.imread(path)
        px = "unknown" if image is None else f"{image.shape[1]} × {image.shape[0]} px"
        self.status_label.text = f"{width_mm:g} × {height_mm:g} mm photo created."
        align = getattr(self, "_passport_alignment", {}) or {}
        face_state = "Detected" if align.get("face_detected") else "Not detected"
        eye_state = "Detected" if align.get("eyes_detected") else "Fallback"
        roll = float(align.get("roll_degrees") or 0.0)
        guidance = str(align.get("guidance") or "Automatic framing completed.")
        self.result_field.text = (
            "Passport photo created successfully.\n"
            f"Preset: {getattr(self, '_passport_preset', 'bangladesh').title()}\n"
            f"Background: {getattr(self, '_passport_background', 'white')}\n"
            f"Size: {px} at 300 DPI target.\n"
            f"Face: {face_state} | Eyes: {eye_state} | Head tilt: {roll:+.1f}°\n"
            f"Alignment: {guidance}\n"
            "Use 4x6 SHEET or A4 SHEET for print-ready multiple copies.\n"
            "Note: automatic framing is a visual aid; verify official photo rules before submission."
        )

        self.preview_box.clear_widgets()
        self.preview_box.height = dp(360)

        preview = Image(
            source=path,
            fit_mode="contain",
        )
        self.preview_box.add_widget(preview)

    def create_passport_sheet(self, sheet):
        if not self._passport_output:
            self._show_error("Passport Photo Maker", "Create a passport photo first.")
            return
        try:
            photo = cv2.imread(self._passport_output)
            if photo is None:
                raise RuntimeError("Could not reopen the passport photo.")
            page = create_print_sheet(photo, sheet=sheet, dpi=300)
            app = MDApp.get_running_app()
            out = app.storage.get_temp_path(
                f"passport_{sheet}_sheet_{int(time.time() * 1000)}.jpg"
            )
            if not cv2.imwrite(out, page, [int(cv2.IMWRITE_JPEG_QUALITY), 96]):
                raise RuntimeError("Could not save print sheet.")
            self._passport_sheet_output = out
            self.status_label.text = f"{sheet.upper()} print sheet created."
            self.preview_box.clear_widgets()
            self.preview_box.height = dp(420)
            self.preview_box.add_widget(Image(source=out, fit_mode="contain"))
        except Exception as exc:
            self._show_error("Passport print sheet", str(exc))

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

    def open_qr_action(self):
        value = (self._last_qr_value or "").strip()
        if not value:
            self._show_error("QR action", "Scan a QR code with a URL, phone, email, or SMS action first.")
            return
        try:
            from storage.android_actions import action_uri_from_qr, open_uri
            uri = action_uri_from_qr(value)
            if not uri:
                self._show_error("QR action", "This QR result has no safe external action. Use COPY RESULT instead.")
                return
            open_uri(uri)
            self.status_label.text = "Opened in the appropriate Android app"
        except Exception as exc:
            self._show_error("QR action", str(exc))

    def show_qr_history(self):
        app = MDApp.get_running_app()
        history = list(app.prefs.get("qr_history") or [])
        if not history:
            self.result_field.text = "Code scan history is empty."
            return
        lines = []
        for index, item in enumerate(history[:50], 1):
            value = str(item.get("value", "")).strip()
            scanned = str(item.get("scanned_at", "")).replace("T", " ")[:19]
            code_type = str(item.get("type", "QR") or "QR")
            lines.append(f"{index}. [{code_type}] {value}\n   {scanned}")
        self.result_field.text = "CODE HISTORY\n\n" + "\n\n".join(lines)
        self.status_label.text = f"{len(history[:50])} saved code result(s)"

    def clear_qr_history(self):
        app = MDApp.get_running_app()
        app.prefs.set("qr_history", [])
        self.result_field.text = "Code scan history cleared."
        self.status_label.text = "History cleared"

    def copy_result(self):
        text = self.result_field.text.strip()
        if not text:
            self._show_error("Copy", "There is no result to copy yet.")
            return
        Clipboard.copy(text)
        self.status_label.text = "Copied to clipboard"
