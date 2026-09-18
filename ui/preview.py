"""
Review screen for Pycam.

Matches the reference "Scan review" design: editable title, an "Add" page
button, a page navigator (< 1/1 >) with a Compare toggle, a scrollable
filter row, and a bottom toolbar (Retake / Left / Crop / Extract Text /
confirm checkmark).
"""

import threading
import time
from datetime import datetime

import cv2

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivymd.app import MDApp
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.snackbar import Snackbar

from image_processing.filters import FILTER_LABELS, apply_filter, rotate_image_file

CHIP_SELECTED_COLOR = (0.07, 0.60, 0.50, 0.30)
CHIP_IDLE_COLOR = (1, 1, 1, 0.06)


class PreviewScreen(MDScreen):
    document_title = StringProperty("")
    page_counter_text = StringProperty("1/1")
    current_filter = StringProperty("original")
    compare_mode = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_index = 0
        self._busy = False

        # Per-page filter selection, keyed by page path so a choice
        # survives navigating away and back to a page.
        self._page_filters = {}
        self._filter_chips = {}

    # ---- Lifecycle -----------------------------------------------------

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()

        if not self.document_title:
            self.document_title = f"Scan {datetime.now().strftime('%d-%m-%Y')}"
            self.title_field.text = self.document_title

        pages = self._pages()
        if not pages and getattr(app, "latest_capture_path", None):
            pages.append(app.latest_capture_path)

        self._current_index = (
            max(0, min(self._current_index, len(pages) - 1)) if pages else 0
        )

        self._build_filter_row()
        self.refresh_page()

    # ---- Page helpers -----------------------------------------------------

    def _pages(self):
        return MDApp.get_running_app().active_session_pages

    def _current_path(self):
        pages = self._pages()
        if not pages or not (0 <= self._current_index < len(pages)):
            return None
        return pages[self._current_index]

    def refresh_page(self):
        pages = self._pages()
        has_pages = bool(pages)

        self.empty_state.opacity = 0 if has_pages else 1
        self.empty_state.disabled = has_pages
        self.preview_image.opacity = 1 if has_pages else 0
        self.delete_page_btn.opacity = 1 if has_pages else 0
        self.delete_page_btn.disabled = not has_pages

        self.page_counter_text = f"{self._current_index + 1}/{max(1, len(pages))}"
        self.prev_page_btn.disabled = self._current_index <= 0
        self.next_page_btn.disabled = not pages or self._current_index >= len(pages) - 1

        self.compare_mode = False

        if has_pages:
            path = pages[self._current_index]
            self.current_filter = self._page_filters.get(path, "original")
            self.preview_image.source = path
            self.preview_image.reload()
            self._highlight_selected_chip()
        else:
            self.preview_image.source = ""

    def go_to_previous_page(self):
        if self._current_index > 0:
            self._current_index -= 1
            self.refresh_page()

    def go_to_next_page(self):
        pages = self._pages()
        if self._current_index < len(pages) - 1:
            self._current_index += 1
            self.refresh_page()

    # ---- Title -----------------------------------------------------

    def rename_document(self, new_title):
        new_title = (new_title or "").strip()
        if new_title:
            self.document_title = new_title
        else:
            # Don't allow an empty title to stick; restore the field.
            self.title_field.text = self.document_title

    # ---- Add / delete page -----------------------------------------------------

    def add_page(self):
        MDApp.get_running_app().go_to("scanner")

    def delete_current_page(self):
        pages = self._pages()
        if not pages or not (0 <= self._current_index < len(pages)):
            return

        removed_path = pages.pop(self._current_index)
        self._page_filters.pop(removed_path, None)

        if self._current_index >= len(pages):
            self._current_index = max(0, len(pages) - 1)

        self.refresh_page()

    # ---- Filters -----------------------------------------------------

    def _build_filter_row(self):
        self.filter_row.clear_widgets()
        self._filter_chips = {}

        for key, label in FILTER_LABELS.items():
            chip = Factory.FilterChip()
            chip.selected = key == self.current_filter
            chip.md_bg_color = CHIP_SELECTED_COLOR if chip.selected else CHIP_IDLE_COLOR

            chip.add_widget(
                MDLabel(
                    text=label[:1],
                    halign="center",
                    bold=True,
                    theme_text_color="Custom",
                    text_color=(1, 1, 1, 1),
                )
            )
            chip.add_widget(
                MDLabel(
                    text=label,
                    halign="center",
                    font_style="Caption",
                    theme_text_color="Custom",
                    text_color=(0.85, 0.85, 0.85, 1),
                    size_hint_y=None,
                    height=dp(16),
                    shorten=True,
                )
            )

            chip.bind(on_release=self._chip_release_handler(key))
            self.filter_row.add_widget(chip)
            self._filter_chips[key] = chip

    def _chip_release_handler(self, filter_key):
        def _handler(*_args):
            self.select_filter(filter_key)
        return _handler

    def _highlight_selected_chip(self):
        for key, chip in self._filter_chips.items():
            chip.selected = key == self.current_filter
            chip.md_bg_color = CHIP_SELECTED_COLOR if chip.selected else CHIP_IDLE_COLOR

    def select_filter(self, filter_key):
        path = self._current_path()
        if path is None or self._busy or filter_key not in FILTER_LABELS:
            return

        self.current_filter = filter_key
        self._highlight_selected_chip()
        self._set_busy(True)

        threading.Thread(
            target=self._run_filter, args=(path, filter_key), daemon=True
        ).start()

    def _run_filter(self, path, filter_key):
        try:
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"Could not read image: {path}")

            filtered = apply_filter(image, filter_key)

            app = MDApp.get_running_app()
            preview_path = app.storage.get_temp_path(
                f"filter_preview_{int(time.time() * 1000)}.jpg"
            )
            success = cv2.imwrite(
                preview_path, filtered, [int(cv2.IMWRITE_JPEG_QUALITY), 92]
            )
            if not success:
                preview_path = path
        except Exception:
            preview_path = path

        Clock.schedule_once(
            lambda dt: self._on_filter_applied(path, filter_key, preview_path), 0
        )

    def _on_filter_applied(self, source_path, filter_key, preview_path):
        self._set_busy(False)

        if self._current_path() != source_path:
            # User navigated to a different page while this was running;
            # drop the stale result rather than showing it on the wrong page.
            return

        self._page_filters[source_path] = filter_key
        self.preview_image.source = preview_path
        self.preview_image.reload()

    def toggle_compare(self):
        path = self._current_path()
        if path is None:
            return

        self.compare_mode = not self.compare_mode
        if self.compare_mode:
            # Show the untouched original while the button is held/toggled.
            self.preview_image.source = path
        else:
            self.refresh_page()
            return

        self.preview_image.reload()

    def _set_busy(self, busy):
        self._busy = busy
        self.processing_label.opacity = 1 if busy else 0

    # ---- Retake / rotate / crop / OCR -----------------------------------------------------

    def retake(self):
        pages = self._pages()
        if pages and 0 <= self._current_index < len(pages):
            removed_path = pages.pop(self._current_index)
            self._page_filters.pop(removed_path, None)
        MDApp.get_running_app().go_to("scanner")

    def rotate_left(self):
        path = self._current_path()
        if path is None or self._busy:
            return

        self._set_busy(True)
        threading.Thread(target=self._run_rotate, args=(path,), daemon=True).start()

    def _run_rotate(self, path):
        try:
            rotate_image_file(path, clockwise=False)
        except Exception:
            pass  # leave the page as-is rather than crash the review screen
        Clock.schedule_once(lambda dt: self._on_rotate_done(), 0)

    def _on_rotate_done(self):
        self._set_busy(False)
        self.preview_image.reload()

    def adjust_crop(self):
        path = self._current_path()
        if path is None:
            return

        app = MDApp.get_running_app()
        app.crop_source_path = path
        # [UPDATE] ক্রপ পেজের সঠিক ইনডেক্স সেভ করা হলো
        app.crop_source_index = self._current_index 
        app.go_to("crop")

    def extract_text(self):
        path = self._current_path()
        if path is None:
            return
            
        # [UPDATE] OCR ইন্টিগ্রেশনের প্রস্তুতি এবং ইউজার নোটিফিকেশন
        Snackbar(text="Extracting text...").open()
        
        # TODO: আপনার ocr_manager.py কানেক্ট করুন। উদাহরণস্বরূপ:
        # from ocr.ocr_manager import OCRManager
        # manager = OCRManager()
        # threading.Thread(target=self._run_ocr, args=(path, manager), daemon=True).start()

    # ---- Confirm / discard -----------------------------------------------------

    def confirm_page(self):
        if not self._pages():
            Snackbar(text="Add at least one page first.").open()
            return
        MDApp.get_running_app().go_to("editor")

    def discard(self):
        MDApp.get_running_app().go_to("home")

