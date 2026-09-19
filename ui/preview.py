"""
Review screen for Pycam.

Matches the reference "Scan review" design: editable title, an "Add" page
button, a page navigator (< 1/1 >) with a Compare toggle, a scrollable
filter row, and a bottom toolbar (Retake / Left / Crop / Extract Text /
confirm checkmark).
"""

import os
import shutil
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
        self._undo_stacks = {}
        self._redo_stacks = {}

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
        self._undo_stacks = {}
        self._redo_stacks = {}

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


    # ---- Edit history -----------------------------------------------------

    def _schedule_autosave(self, reason):
        try:
            MDApp.get_running_app().schedule_session_autosave(reason)
        except Exception:
            pass

    def _snapshot_for_undo(self, path):
        if not path or not os.path.isfile(path):
            return
        app = MDApp.get_running_app()
        snap = app.storage.get_temp_path(f"undo_{int(time.time() * 1000)}_{os.path.basename(path)}")
        shutil.copy2(path, snap)
        stack = self._undo_stacks.setdefault(path, [])
        stack.append(snap)
        if len(stack) > 12:
            old = stack.pop(0)
            try:
                os.remove(old)
            except OSError:
                pass
        self._redo_stacks[path] = []

    def undo_edit(self):
        path = self._current_path()
        stack = self._undo_stacks.get(path, []) if path else []
        if not path or not stack or self._busy:
            Snackbar(text="Nothing to undo").open()
            return
        app = MDApp.get_running_app()
        current = app.storage.get_temp_path(f"redo_{int(time.time() * 1000)}_{os.path.basename(path)}")
        shutil.copy2(path, current)
        self._redo_stacks.setdefault(path, []).append(current)
        shutil.copy2(stack.pop(), path)
        self.preview_image.source = path
        self.preview_image.reload()
        self._schedule_autosave("preview_undo")
        Snackbar(text="Undo applied").open()

    def redo_edit(self):
        path = self._current_path()
        stack = self._redo_stacks.get(path, []) if path else []
        if not path or not stack or self._busy:
            Snackbar(text="Nothing to redo").open()
            return
        self._snapshot_for_undo(path)
        # _snapshot_for_undo clears redo, so preserve the target first.
        target = stack[-1]
        self._redo_stacks[path] = stack[:-1]
        shutil.copy2(target, path)
        self.preview_image.source = path
        self.preview_image.reload()
        self._schedule_autosave("preview_redo")
        Snackbar(text="Redo applied").open()

    def open_annotation(self):
        path = self._current_path()
        if path is None or self._busy:
            return
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDFlatButton
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.textfield import MDTextField

        box = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None, height=dp(180))
        text_field = MDTextField(hint_text="Text stamp (optional)", text="")
        shape_field = MDTextField(hint_text="Shape: rectangle / circle / arrow / highlight", text="rectangle")
        box.add_widget(text_field)
        box.add_widget(shape_field)

        def apply_annotation(*_):
            self._snapshot_for_undo(path)
            try:
                from image_processing.annotations import add_shape, add_text_stamp
                shape = (shape_field.text or "rectangle").strip().lower()
                if shape in ("rectangle", "circle", "arrow", "highlight"):
                    add_shape(path, shape)
                if (text_field.text or "").strip():
                    add_text_stamp(path, text_field.text.strip(), "bottom-right")
                dialog.dismiss()
                self.preview_image.source = path
                self.preview_image.reload()
                self._schedule_autosave("annotation")
                Snackbar(text="Annotation applied").open()
            except Exception as exc:
                Snackbar(text=f"Annotation failed: {exc}").open()

        def date_stamp(*_):
            self._snapshot_for_undo(path)
            try:
                from image_processing.annotations import add_date_stamp
                add_date_stamp(path)
                dialog.dismiss()
                self.preview_image.source = path
                self.preview_image.reload()
                self._schedule_autosave("annotation_date")
                Snackbar(text="Date stamp added").open()
            except Exception as exc:
                Snackbar(text=f"Stamp failed: {exc}").open()

        dialog = MDDialog(
            title="Annotate page", type="custom", content_cls=box,
            buttons=[
                MDFlatButton(text="DRAW", on_release=lambda *_: (dialog.dismiss(), self.open_freehand_annotation())),
                MDFlatButton(text="DATE", on_release=date_stamp),
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="APPLY", on_release=apply_annotation),
            ],
        )
        dialog.open()

    def open_freehand_annotation(self):
        path = self._current_path()
        if path is None or self._busy:
            return
        try:
            from ui.freehand_annotation import FreehandAnnotationView

            def _before_save():
                self._snapshot_for_undo(path)

            def _saved():
                self.current_filter = "original"
                self._page_filters[path] = "original"
                self.preview_image.source = path
                self.preview_image.reload()
                self._schedule_autosave("freehand_annotation")
                Snackbar(text="Freehand annotation saved").open()

            FreehandAnnotationView(
                image_path=path,
                before_save=_before_save,
                on_saved=_saved,
            ).open()
        except Exception as exc:
            Snackbar(text=f"Could not open drawing editor: {exc}").open()

    def _commit_filters_worker(self):
        try:
            pages = list(self._pages())
            for path in pages:
                key = self._page_filters.get(path, "original")
                if key == "original":
                    continue
                image = cv2.imread(path, cv2.IMREAD_COLOR)
                if image is None:
                    continue
                filtered = apply_filter(image, key)
                cv2.imwrite(path, filtered, [int(cv2.IMWRITE_JPEG_QUALITY), 96])
            result = (True, "")
        except Exception as exc:
            result = (False, str(exc))
        Clock.schedule_once(lambda dt: self._on_filters_committed(*result), 0)

    def _on_filters_committed(self, ok, message):
        self._set_busy(False)
        if not ok:
            Snackbar(text=f"Could not apply filter: {message}").open()
            return
        self._page_filters.clear()
        self._schedule_autosave("filter_commit")
        MDApp.get_running_app().go_to("editor")

    # ---- Retake / rotate / crop / OCR -----------------------------------------------------

    def retake(self):
        pages = self._pages()
        if pages and 0 <= self._current_index < len(pages):
            removed_path = pages.pop(self._current_index)
            self._page_filters.pop(removed_path, None)
            self._schedule_autosave("retake_remove")
        MDApp.get_running_app().go_to("scanner")

    def rotate_left(self):
        path = self._current_path()
        if path is None or self._busy:
            return

        self._snapshot_for_undo(path)
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
        self._schedule_autosave("preview_rotate")

    def adjust_crop(self):
        path = self._current_path()
        if path is None:
            return

        app = MDApp.get_running_app()
        app.crop_source_path = path
        # [UPDATE] ক্রপ পেজের সঠিক ইনডেক্স সেভ করা হলো
        app.crop_source_index = self._current_index 
        app.go_to("crop")

    def open_adjustments(self):
        path = self._current_path()
        if path is None or self._busy:
            return
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDFlatButton
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.textfield import MDTextField

        box = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None, height=dp(250))
        fields = {}
        for key, hint, default in (
            ("brightness", "Brightness (-100..100)", "0"),
            ("contrast", "Contrast (0.5..2.0)", "1.0"),
            ("saturation", "Saturation (0..2.0)", "1.0"),
            ("sharpness", "Sharpness (0..2.0)", "0.0"),
        ):
            field = MDTextField(text=default, hint_text=hint, input_filter="float")
            fields[key] = field
            box.add_widget(field)

        def apply_now(*_):
            try:
                values = {
                    "brightness": max(-100.0, min(100.0, float(fields["brightness"].text or 0))),
                    "contrast": max(0.5, min(2.0, float(fields["contrast"].text or 1))),
                    "saturation": max(0.0, min(2.0, float(fields["saturation"].text or 1))),
                    "sharpness": max(0.0, min(2.0, float(fields["sharpness"].text or 0))),
                }
            except ValueError:
                Snackbar(text="Enter valid adjustment values").open()
                return
            dialog.dismiss()
            self._snapshot_for_undo(path)
            self._set_busy(True)
            threading.Thread(target=self._apply_adjustments_worker, args=(path, values), daemon=True).start()

        dialog = MDDialog(
            title="Fine Adjustments", type="custom", content_cls=box,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="APPLY", on_release=apply_now),
            ],
        )
        dialog.open()

    def _apply_adjustments_worker(self, path, values):
        try:
            from image_processing.adjustments import adjust_image
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            adjusted = adjust_image(image, **values)
            ok = cv2.imwrite(path, adjusted, [int(cv2.IMWRITE_JPEG_QUALITY), 96])
            if not ok:
                raise IOError("Could not save adjusted page")
            result = (True, "")
        except Exception as exc:
            result = (False, str(exc))
        Clock.schedule_once(lambda dt: self._on_adjustments_done(*result), 0)

    def _on_adjustments_done(self, ok, message):
        self._set_busy(False)
        if ok:
            self.preview_image.reload()
            self._schedule_autosave("fine_adjustment")
            Snackbar(text="Adjustments applied").open()
        else:
            Snackbar(text=f"Adjust failed: {message}").open()

    def extract_text(self):
        path = self._current_path()
        if path is None:
            return

        Snackbar(text="Extracting text...").open()
        language = MDApp.get_running_app().prefs.get("ocr_language") or "english"
        threading.Thread(
            target=self._extract_text_worker,
            args=(path, language),
            daemon=True,
        ).start()

    def _extract_text_worker(self, path, language):
        try:
            from ocr.ocr_manager import run_ocr_for_pages
            text = run_ocr_for_pages([path], language).strip()
            if not text:
                text = "No readable text was detected."
            Clock.schedule_once(lambda dt, value=text: self._show_ocr_result(value), 0)
        except Exception as exc:
            Clock.schedule_once(
                lambda dt, msg=str(exc): Snackbar(text=f"OCR failed: {msg}").open(),
                0,
            )

    def _show_ocr_result(self, text):
        from kivy.core.clipboard import Clipboard
        from kivymd.uix.button import MDFlatButton
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.textfield import MDTextField
        from ocr.ocr_manager import clean_ocr_text

        field = MDTextField(
            text=text, hint_text="Extracted text", multiline=True, mode="rectangle",
            size_hint_y=None, height=dp(320),
        )

        def copy_text(*_):
            Clipboard.copy(field.text)
            Snackbar(text="OCR text copied").open()

        def clean_text(*_):
            field.text = clean_ocr_text(field.text)
            Snackbar(text="OCR text cleaned").open()

        def save_as(kind):
            try:
                app = MDApp.get_running_app()
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base = app.storage.get_export_path(f"OCR_{stamp}.{kind}")
                if kind == "txt":
                    with open(base, "w", encoding="utf-8") as fh:
                        fh.write(field.text)
                elif kind == "docx":
                    from tools.document_tools import text_to_docx
                    text_to_docx(field.text, base)
                else:
                    from tools.document_tools import text_to_pdf
                    text_to_pdf(field.text, base)
                try:
                    external = app.storage.publish_export(base, app.prefs)
                except Exception as publish_exc:
                    Snackbar(text=f"Saved in app storage; external save failed: {publish_exc}").open()
                else:
                    message = f"Saved: {base}" if external == base else f"Saved externally: {external}"
                    Snackbar(text=message).open()
            except Exception as exc:
                Snackbar(text=f"Save failed: {exc}").open()

        dialog = MDDialog(
            title="Extracted Text", type="custom", content_cls=field,
            buttons=[
                MDFlatButton(text="CLEAN", on_release=clean_text),
                MDFlatButton(text="COPY", on_release=copy_text),
                MDFlatButton(text="TXT", on_release=lambda *_: save_as("txt")),
                MDFlatButton(text="WORD", on_release=lambda *_: save_as("docx")),
                MDFlatButton(text="PDF", on_release=lambda *_: save_as("pdf")),
                MDFlatButton(text="CLOSE", on_release=lambda *_: dialog.dismiss()),
            ],
        )
        dialog.open()

    # ---- Confirm / discard -----------------------------------------------------

    def confirm_page(self):
        if not self._pages():
            Snackbar(text="Add at least one page first.").open()
            return
        if self._busy:
            return
        if any(value != "original" for value in self._page_filters.values()):
            self._set_busy(True)
            threading.Thread(target=self._commit_filters_worker, daemon=True).start()
            return
        MDApp.get_running_app().go_to("editor")

    def discard(self):
        MDApp.get_running_app().go_to("home")

