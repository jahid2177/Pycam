"""Connected workflows for Pycam's formerly-placeholder utility tools."""

import os
import re
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar

from ocr.ocr_manager import run_ocr_for_pages, run_ocr_for_individual_images
from pdf.export import export_to_pdf
from storage.file_picker import FilePicker, copy_to_app_temp, render_pdf_to_images
from storage.share import open_file, share_file
from tools.table_ocr import ocr_table_cells, parse_text_table, table_to_tsv, tsv_to_rows
from tools.document_tools import (
    add_header_footer,
    add_page_numbers,
    combine_images_vertically,
    compress_pdf,
    create_docx_from_text,
    create_docx_from_pages,
    extract_pdf_text,
    create_qr,
    create_xlsx_from_text,
    create_xlsx_from_rows,
    create_csv_from_rows,
    extract_pdf_pages,
    insert_pdf_pages,
    lock_pdf,
    merge_pdfs,
    remove_pdf_pages,
    remove_background,
    reorder_pdf_pages,
    resize_image,
    rotate_pdf,
    sign_pdf,
    smart_erase_image,
    split_pdf,
    text_to_pdf,
    unlock_pdf,
    watermark_pdf,
)


TOOL_INFO = {
    "merge_pdf": ("Merge PDF", "Add two or more PDFs, then merge them in the selected order."),
    "image_to_pdf": ("Image to PDF", "Add one or more images and export one PDF."),
    "text_to_pdf": ("Text to PDF", "Type or paste text and create a PDF."),
    "to_word": ("To Word", "Select a document image, run OCR, and create a DOCX file."),
    "pdf_to_word": ("PDF to Word", "Extract text from a PDF into DOCX. Scanned PDFs use OCR fallback on Android."),
    "to_excel": ("To Excel", "Select a table/document image, run OCR, and create an XLSX file."),
    "pdf_to_images": ("PDF to Images", "Render every PDF page to a high-quality JPEG image."),
    "pdf_long_image": ("PDF to Long Image", "Render the PDF and join all pages vertically."),
    "bg_remover": ("BG Remover", "Remove the main photo background using GrabCut."),
    "image_resizer": ("Image Resizer", "Resize an image to an exact width and height."),
    "smart_erase": ("Smart Erase", "Automatically remove small stains, colored pen specks and isolated marks from a scanned page."),
    "split_pdf": ("Split PDF", "Split every page of a PDF into a separate PDF file."),
    "sign": ("Sign PDF", "Select a PDF and a signature image. The signature is placed on page 1."),
    "watermark": ("Add Watermark", "Add text watermark to every PDF page."),
    "extract_pages": ("Extract PDF Pages", "Extract pages such as 1,3-5 into a new PDF."),
    "reorder_pages": ("Reorder Pages", "Enter a complete page order such as 3,1,2."),
    "rotate_pdf": ("Rotate PDF", "Rotate all PDF pages by 90, 180, or 270 degrees."),
    "lock_pdf": ("Lock PDF", "Encrypt a PDF with a password."),
    "compress_pdf": ("Compress PDF", "Compress PDF content streams and remove duplicate objects."),
    "unlock_pdf": ("Unlock PDF", "Remove PDF password protection when you know the password."),
    "remove_pages": ("Remove PDF Pages", "Remove selected pages such as 2,4-6 from a PDF."),
    "insert_pages": ("Insert PDF Pages", "Insert all pages from a second PDF into a base PDF."),
    "page_numbers": ("Page Numbers", "Add sequential page numbers at the bottom of every page."),
    "header_footer": ("Header / Footer", "Add a simple header and/or footer to every PDF page."),
    "pdf_metadata": ("PDF Metadata", "Edit Title, Author, Subject, Keywords, Creator or Producer metadata."),
    "flatten_pdf": ("Flatten PDF", "Flatten AcroForm field values into page content where supported."),
    "create_qr": ("Create QR Code", "Create a QR code from text, a URL, Wi-Fi text, or contact data."),
}

IMAGE_MODES = {"image_to_pdf", "to_word", "to_excel", "bg_remover", "image_resizer", "smart_erase"}
PDF_MODES = {"merge_pdf", "pdf_to_word", "pdf_to_images", "pdf_long_image", "split_pdf", "sign", "watermark",
             "extract_pages", "reorder_pages", "rotate_pdf", "lock_pdf", "compress_pdf",
             "unlock_pdf", "remove_pages", "insert_pages", "page_numbers", "header_footer",
             "pdf_metadata", "flatten_pdf"}


class AdvancedToolScreen(MDScreen):
    def __init__(self, mode, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode
        self._picker = FilePicker()
        self._selected = []
        self._signature = None
        self._last_output = None
        self._last_published = None
        self._running = False
        self._job_id = 0
        self._table_preview = None
        self._table_format = None
        self._build_ui()

    def _build_ui(self):
        title, subtitle = TOOL_INFO[self.mode]
        root = MDBoxLayout(orientation="vertical", md_bg_color=(0.97, 0.98, 1, 1))
        toolbar = MDTopAppBar(title=title, elevation=0)
        toolbar.left_action_items = [["arrow-left", lambda *_: MDApp.get_running_app().go_to("tools")]]
        root.add_widget(toolbar)

        scroll = ScrollView(do_scroll_x=False)
        body = MDBoxLayout(orientation="vertical", adaptive_height=True,
                           padding=(dp(18), dp(16), dp(18), dp(28)), spacing=dp(12))
        body.add_widget(MDLabel(text=subtitle, theme_text_color="Secondary",
                                size_hint_y=None, height=dp(56)))

        self.selection_label = MDLabel(text="No file selected", theme_text_color="Secondary",
                                       size_hint_y=None, height=dp(48), halign="center")

        if self.mode in PDF_MODES:
            label = "ADD PDF" if self.mode in {"merge_pdf", "insert_pages"} else "SELECT PDF"
            body.add_widget(MDRaisedButton(text=label, pos_hint={"center_x": 0.5},
                                           on_release=lambda *_: self._pick_pdf()))
        elif self.mode in IMAGE_MODES:
            label = "ADD IMAGE" if self.mode == "image_to_pdf" else "SELECT IMAGE"
            body.add_widget(MDRaisedButton(text=label, pos_hint={"center_x": 0.5},
                                           on_release=lambda *_: self._pick_image()))

        if self.mode == "sign":
            body.add_widget(MDFlatButton(text="SELECT SIGNATURE IMAGE", pos_hint={"center_x": 0.5},
                                         on_release=lambda *_: self._pick_signature()))

        body.add_widget(self.selection_label)

        self.input_field = None
        if self.mode in {"text_to_pdf", "watermark", "extract_pages", "reorder_pages",
                         "rotate_pdf", "lock_pdf", "create_qr", "unlock_pdf", "remove_pages",
                         "insert_pages", "page_numbers", "header_footer", "pdf_metadata"}:
            hints = {
                "text_to_pdf": "Text",
                "watermark": "Watermark text",
                "extract_pages": "Pages, e.g. 1,3-5",
                "reorder_pages": "Order, e.g. 3,1,2",
                "rotate_pdf": "Angle: 90 / 180 / 270",
                "lock_pdf": "Password",
                "create_qr": "Text or URL",
                "unlock_pdf": "Current PDF password",
                "remove_pages": "Pages to remove, e.g. 2,4-6",
                "insert_pages": "Insert after page: 0 = beginning",
                "page_numbers": "Starting page number (default 1)",
                "header_footer": "Header | Footer (either side may be blank)",
                "pdf_metadata": "Title=...\nAuthor=...\nSubject=...\nKeywords=...",
            }
            self.input_field = MDTextField(hint_text=hints[self.mode], mode="rectangle",
                                           multiline=self.mode in {"text_to_pdf", "create_qr", "pdf_metadata"},
                                           size_hint_y=None,
                                           height=dp(200) if self.mode in {"text_to_pdf", "create_qr", "pdf_metadata"} else dp(64))
            if self.mode in {"lock_pdf", "unlock_pdf"}:
                self.input_field.password = True
            body.add_widget(self.input_field)

        self.width_field = self.height_field = None
        self.keep_aspect = True
        self.bg_field = None
        if self.mode == "image_resizer":
            row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(70), spacing=dp(8))
            self.width_field = MDTextField(hint_text="Width px", text="1080", input_filter="int")
            self.height_field = MDTextField(hint_text="Height px", text="1440", input_filter="int")
            row.add_widget(self.width_field); row.add_widget(self.height_field)
            body.add_widget(row)
            presets = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(4))
            for label, w, h in [("DOC", 1080, 1440), ("SQUARE", 1080, 1080),
                                ("A4 300DPI", 2480, 3508), ("HD", 1920, 1080)]:
                presets.add_widget(MDFlatButton(text=label, on_release=lambda _b, W=w, H=h: self._set_resize_preset(W, H)))
            body.add_widget(presets)
        elif self.mode == "bg_remover":
            self.bg_field = MDTextField(
                hint_text="Background: transparent / white / blue / gray",
                text="transparent", mode="rectangle", size_hint_y=None, height=dp(64))
            body.add_widget(self.bg_field)

        if self.mode == "to_excel":
            body.add_widget(MDFlatButton(
                text="DETECT TABLE", pos_hint={"center_x": 0.5},
                on_release=lambda *_: self.detect_table_preview()))
            self._table_preview = MDTextField(
                hint_text="Detected table preview (TAB separated). You can edit cells before export.",
                mode="rectangle", multiline=True, size_hint_y=None, height=dp(260))
            self._table_format = MDTextField(
                hint_text="Export format: xlsx or csv", text="xlsx", mode="rectangle",
                size_hint_y=None, height=dp(64))
            body.add_widget(self._table_preview)
            body.add_widget(self._table_format)

        actions = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(56), spacing=dp(8),
                              padding=(dp(24), 0, dp(24), 0))
        self.run_button = MDRaisedButton(text="RUN", on_release=lambda *_: self.run_tool())
        self.cancel_button = MDFlatButton(text="CANCEL", disabled=True, on_release=lambda *_: self.cancel_tool())
        actions.add_widget(self.run_button)
        actions.add_widget(self.cancel_button)
        body.add_widget(actions)
        self.status = MDLabel(text="", halign="center", theme_text_color="Secondary",
                              size_hint_y=None, height=dp(80))
        body.add_widget(self.status)
        result_actions = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52),
                                     spacing=dp(8), padding=(dp(20), 0, dp(20), 0))
        self.open_button = MDFlatButton(text="OPEN RESULT", disabled=True,
                                        on_release=lambda *_: self.open_result())
        self.share_button = MDFlatButton(text="SHARE RESULT", disabled=True,
                                         on_release=lambda *_: self.share_result())
        result_actions.add_widget(self.open_button)
        result_actions.add_widget(self.share_button)
        body.add_widget(result_actions)
        scroll.add_widget(body)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        self.status.text = ""

    def _pick_pdf(self):
        self._picker.choose_pdf(self._on_pdf, self._picker_error)

    def _pick_image(self):
        self._picker.choose_image(self._on_image, self._picker_error)

    def _pick_signature(self):
        self._picker.choose_image(self._on_signature, self._picker_error)

    def _on_pdf(self, path):
        app = MDApp.get_running_app()
        local = copy_to_app_temp(path, app.storage, prefix=self.mode)
        if self.mode in {"merge_pdf", "insert_pages"}:
            if self.mode == "insert_pages" and len(self._selected) >= 2:
                self._selected = []
            self._selected.append(local)
        else:
            self._selected = [local]
        self._sync_selection()

    def _on_image(self, path):
        app = MDApp.get_running_app()
        local = copy_to_app_temp(path, app.storage, prefix=self.mode)
        if self.mode == "image_to_pdf":
            self._selected.append(local)
        else:
            self._selected = [local]
        self._sync_selection()

    def _on_signature(self, path):
        app = MDApp.get_running_app()
        self._signature = copy_to_app_temp(path, app.storage, prefix="signature")
        self._sync_selection()

    def _sync_selection(self):
        if self.mode == "merge_pdf":
            self.selection_label.text = f"{len(self._selected)} PDF(s) selected"
        elif self.mode == "insert_pages":
            if len(self._selected) == 0:
                self.selection_label.text = "Select base PDF, then PDF to insert"
            elif len(self._selected) == 1:
                self.selection_label.text = f"Base: {os.path.basename(self._selected[0])} • now add insert PDF"
            else:
                self.selection_label.text = (f"Base: {os.path.basename(self._selected[0])} • "
                                             f"Insert: {os.path.basename(self._selected[1])}")
        elif self.mode == "image_to_pdf":
            self.selection_label.text = f"{len(self._selected)} image(s) selected"
        elif self.mode == "sign":
            self.selection_label.text = (
                ("PDF selected" if self._selected else "Select a PDF") +
                (" • Signature selected" if self._signature else " • Select signature")
            )
        else:
            self.selection_label.text = os.path.basename(self._selected[0]) if self._selected else "No file selected"

    def _picker_error(self, message):
        self._show_error("File selection", message)

    def _set_resize_preset(self, width, height):
        if self.width_field and self.height_field:
            self.width_field.text = str(width)
            self.height_field.text = str(height)

    def detect_table_preview(self):
        if self._running:
            return
        if not self._selected:
            self._show_error("Table OCR", "Select a table/document image first.")
            return
        self._running = True
        self._job_id += 1
        job_id = self._job_id
        self.status.text = "Detecting table and reading cells..."
        self.run_button.disabled = True
        self.cancel_button.disabled = False
        threading.Thread(target=self._table_preview_worker, args=(job_id,), daemon=True).start()

    def _table_preview_worker(self, job_id):
        try:
            app = MDApp.get_running_app()
            source = self._need_one()
            language = app.prefs.get("ocr_language") or "english"
            rows = ocr_table_cells(source, language, run_ocr_for_individual_images)
            if not rows:
                text = run_ocr_for_pages([source], language)
                rows = parse_text_table(text)
            preview = table_to_tsv(rows)
            if not preview.strip():
                raise RuntimeError("No table structure or readable text was detected.")
            Clock.schedule_once(lambda dt, value=preview, jid=job_id: self._table_preview_done(jid, value), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, msg=str(exc), jid=job_id: self._worker_error(jid, msg), 0)

    def _table_preview_done(self, job_id, preview):
        if job_id != self._job_id:
            return
        self._running = False
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        if self._table_preview is not None:
            self._table_preview.text = preview
            rows = tsv_to_rows(preview)
            cols = max((len(r) for r in rows), default=0)
            self.status.text = f"Table detected: {len(rows)} row(s) × {cols} column(s). Edit if needed, then RUN."

    def run_tool(self):
        if self._running:
            self.status.text = "A task is already running."
            return
        self._running = True
        self._job_id += 1
        job_id = self._job_id
        self.status.text = "Processing..."
        self.share_button.disabled = True
        self.open_button.disabled = True
        self.run_button.disabled = True
        self.cancel_button.disabled = False
        threading.Thread(target=self._worker, args=(job_id,), daemon=True).start()

    def cancel_tool(self):
        if not self._running:
            return
        self._job_id += 1  # invalidate the in-flight worker result
        self._running = False
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self.status.text = "Cancelled. The current background operation will be ignored when it finishes."

    def _worker(self, job_id):
        try:
            output = self._execute()
            published = None
            publish_error = None
            if isinstance(output, str) and os.path.isfile(output):
                try:
                    app = MDApp.get_running_app()
                    published = app.storage.publish_export(output, app.prefs)
                except Exception as exc:
                    publish_error = str(exc)
            Clock.schedule_once(
                lambda dt, result=output, pub=published, perr=publish_error, jid=job_id:
                    self._done(result, jid, pub, perr), 0
            )
        except Exception as exc:
            Clock.schedule_once(lambda dt, msg=str(exc), jid=job_id: self._worker_error(jid, msg), 0)

    def _worker_error(self, job_id, message):
        if job_id != self._job_id:
            return
        self._running = False
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self._show_error("Tool failed", message)

    def _output(self, name):
        return MDApp.get_running_app().storage.get_export_path(name)

    def _need_one(self):
        if not self._selected:
            raise ValueError("Select a file first.")
        return self._selected[0]

    def _execute(self):
        app = MDApp.get_running_app()
        stamp = int(time.time())
        value = self.input_field.text.strip() if self.input_field else ""

        if self.mode == "merge_pdf":
            return merge_pdfs(self._selected, self._output(f"Merged_{stamp}.pdf"))
        if self.mode == "image_to_pdf":
            if not self._selected:
                raise ValueError("Add at least one image.")
            page_size = (app.prefs.get("pdf_page_size") or "a4").lower()
            if page_size not in {"auto", "a4", "letter", "legal"}:
                page_size = "a4"
            margin_name = (app.prefs.get("pdf_margin") or "normal").lower()
            margin_pt = {"none": 0.0, "small": 12.0, "normal": 24.0, "large": 36.0}.get(margin_name, 24.0)
            quality = (app.prefs.get("export_quality") or "balanced").lower()
            if quality not in {"high", "balanced", "small"}:
                quality = "balanced"
            return export_to_pdf(
                self._selected,
                self._output(f"Images_{stamp}.pdf"),
                page_size=page_size,
                orientation="auto",
                margin_pt=margin_pt,
                quality=quality,
            )
        if self.mode == "text_to_pdf":
            return text_to_pdf(value, self._output(f"Text_{stamp}.pdf"))
        if self.mode == "pdf_to_word":
            pdf = self._need_one()
            pages = extract_pdf_text(pdf)
            readable_chars = sum(len(re.sub(r"\s+", "", page or "")) for page in pages)
            # Text PDFs convert directly. Image-only/scanned PDFs fall back to
            # Android PdfRenderer + the app's configured OCR pipeline.
            if readable_chars < max(40, len(pages) * 12):
                out_dir = app.storage.get_temp_path(f"pdf_word_ocr_{stamp}")
                images = render_pdf_to_images(pdf, out_dir)
                if not images:
                    raise RuntimeError("This PDF has no extractable text and its pages could not be rendered for OCR.")
                language = app.prefs.get("ocr_language") or "english"
                ocr_text = run_ocr_for_pages(images, language)
                if not (ocr_text or "").strip():
                    raise RuntimeError("This appears to be a scanned PDF, but OCR could not read any text.")
                # Keep a page boundary when renderer returns page images.
                pages = []
                for image in images:
                    page_text = run_ocr_for_pages([image], language)
                    pages.append(page_text or "")
            title = os.path.splitext(os.path.basename(pdf))[0]
            return create_docx_from_pages(pages, self._output(f"PDF_Word_{stamp}.docx"), title=title)
        if self.mode in {"to_word", "to_excel"}:
            source = self._need_one()
            language = app.prefs.get("ocr_language") or "english"
            if self.mode == "to_word":
                text = run_ocr_for_pages([source], language)
                if not text.strip():
                    raise RuntimeError("No readable text was detected.")
                return create_docx_from_text(text, self._output(f"OCR_{stamp}.docx"))

            preview = (self._table_preview.text if self._table_preview is not None else "").strip()
            if preview:
                rows = tsv_to_rows(preview)
            else:
                rows = ocr_table_cells(source, language, run_ocr_for_individual_images)
                if not rows:
                    text = run_ocr_for_pages([source], language)
                    rows = parse_text_table(text)
            if not rows:
                raise RuntimeError("No readable table was detected.")
            fmt = ((self._table_format.text if self._table_format is not None else "xlsx") or "xlsx").strip().lower()
            if fmt == "csv":
                return create_csv_from_rows(rows, self._output(f"Table_{stamp}.csv"))
            if fmt not in {"xlsx", "excel"}:
                raise ValueError("Export format must be xlsx or csv.")
            return create_xlsx_from_rows(rows, self._output(f"Table_{stamp}.xlsx"), sheet_name="Table OCR")
        if self.mode == "pdf_to_images":
            pdf = self._need_one()
            out_dir = app.storage.get_temp_path(f"pdf_images_{stamp}")
            paths = render_pdf_to_images(pdf, out_dir)
            if not paths:
                raise RuntimeError("No PDF pages were rendered.")
            # Place rendered pages in a ZIP so one result can be shared.
            import zipfile
            out = self._output(f"PDF_Images_{stamp}.zip")
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                for p in paths: z.write(p, os.path.basename(p))
            return out
        if self.mode == "pdf_long_image":
            pdf = self._need_one()
            out_dir = app.storage.get_temp_path(f"pdf_long_{stamp}")
            paths = render_pdf_to_images(pdf, out_dir)
            if not paths:
                raise RuntimeError("No PDF pages were rendered.")
            # The combiner automatically returns a ZIP of numbered long-image
            # segments when one giant bitmap would exceed a safe Android height.
            return combine_images_vertically(
                paths,
                self._output(f"Long_Image_{stamp}.jpg"),
                max_width=1600,
                max_segment_height=28000,
                gap_px=8,
            )
        if self.mode == "bg_remover":
            background = (self.bg_field.text.strip().lower() if self.bg_field else "transparent") or "transparent"
            suffix = "transparent" if background in {"transparent", "clear", "png"} else background
            return remove_background(self._need_one(), self._output(f"No_BG_{suffix}_{stamp}.png"), background)
        if self.mode == "smart_erase":
            return smart_erase_image(self._need_one(), self._output(f"Smart_Erase_{stamp}.jpg"))
        if self.mode == "image_resizer":
            w = int(self.width_field.text or 0); h = int(self.height_field.text or 0)
            return resize_image(self._need_one(), self._output(f"Resized_{w}x{h}_{stamp}.jpg"), w, h, keep_aspect=True)
        if self.mode == "split_pdf":
            out_dir = app.storage.get_temp_path(f"split_{stamp}")
            paths = split_pdf(self._need_one(), out_dir)
            import zipfile
            out = self._output(f"Split_PDF_{stamp}.zip")
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                for p in paths: z.write(p, os.path.basename(p))
            return out
        if self.mode == "sign":
            if not self._signature:
                raise ValueError("Select a signature image.")
            return sign_pdf(self._need_one(), self._signature, self._output(f"Signed_{stamp}.pdf"))
        if self.mode == "watermark":
            return watermark_pdf(self._need_one(), self._output(f"Watermarked_{stamp}.pdf"), value)
        if self.mode == "extract_pages":
            return extract_pdf_pages(self._need_one(), self._output(f"Extracted_{stamp}.pdf"), value)
        if self.mode == "reorder_pages":
            return reorder_pdf_pages(self._need_one(), self._output(f"Reordered_{stamp}.pdf"), value)
        if self.mode == "rotate_pdf":
            return rotate_pdf(self._need_one(), self._output(f"Rotated_{stamp}.pdf"), int(value or 90))
        if self.mode == "lock_pdf":
            return lock_pdf(self._need_one(), self._output(f"Locked_{stamp}.pdf"), value)
        if self.mode == "compress_pdf":
            return compress_pdf(self._need_one(), self._output(f"Compressed_{stamp}.pdf"))
        if self.mode == "unlock_pdf":
            return unlock_pdf(self._need_one(), self._output(f"Unlocked_{stamp}.pdf"), value)
        if self.mode == "remove_pages":
            return remove_pdf_pages(self._need_one(), self._output(f"Pages_Removed_{stamp}.pdf"), value)
        if self.mode == "insert_pages":
            if len(self._selected) != 2:
                raise ValueError("Select the base PDF, then the PDF whose pages should be inserted.")
            try:
                after_page = int(value or 0)
            except ValueError:
                raise ValueError("Insert position must be a whole page number, or 0 for the beginning.")
            return insert_pdf_pages(self._selected[0], self._selected[1],
                                    self._output(f"Pages_Inserted_{stamp}.pdf"), after_page)
        if self.mode == "page_numbers":
            try:
                start = int(value or 1)
            except ValueError:
                raise ValueError("Starting page number must be a whole number.")
            return add_page_numbers(self._need_one(), self._output(f"Numbered_{stamp}.pdf"), start)
        if self.mode == "header_footer":
            header, footer = (value.split("|", 1) + [""])[:2] if "|" in value else (value, "")
            return add_header_footer(self._need_one(), self._output(f"Header_Footer_{stamp}.pdf"),
                                     header.strip(), footer.strip())
        if self.mode == "pdf_metadata":
            return edit_pdf_metadata(self._need_one(), self._output(f"Metadata_{stamp}.pdf"), value)
        if self.mode == "flatten_pdf":
            return flatten_pdf(self._need_one(), self._output(f"Flattened_{stamp}.pdf"))
        if self.mode == "create_qr":
            return create_qr(value, self._output(f"QR_{stamp}.png"))
        raise RuntimeError("Unknown tool mode.")

    def _done(self, result, job_id=None, published=None, publish_error=None):
        if job_id is not None and job_id != self._job_id:
            return
        self._running = False
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self._last_output = result if isinstance(result, str) else None
        self._last_published = published
        if isinstance(result, str):
            text = f"Done\n{os.path.basename(result)}"
            if published and published != result:
                text += f"\nSaved externally: {published}"
            elif publish_error:
                text += f"\nExternal save failed: {publish_error}"
            self.status.text = text
            self.share_button.disabled = False
            self.open_button.disabled = False
        else:
            self.status.text = "Done"

    def open_result(self):
        if not self._last_output:
            return
        try:
            open_file(self._last_output)
        except Exception as exc:
            self._show_error("Open", str(exc))

    def share_result(self):
        if not self._last_output:
            return
        try:
            share_file(self._last_output)
        except Exception as exc:
            self._show_error("Share", str(exc))

    def _show_error(self, title, message):
        self.status.text = ""
        dialog = MDDialog(title=title, text=str(message), buttons=[
            MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())
        ])
        dialog.open()
