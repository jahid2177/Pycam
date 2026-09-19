"""Reusable editable OCR result dialog for Home/Documents/Preview flows."""

from pathlib import Path

from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField

from ocr.ocr_manager import (
    find_text_matches,
    normalize_ocr_paragraphs,
    replace_ocr_text,
)


def _safe_base_name(value: str) -> str:
    cleaned = "".join(c for c in (value or "OCR Result") if c.isalnum() or c in " _-").strip()
    return cleaned or "OCR_Result"


class OCRResultEditor:
    def __init__(self, title: str, text: str, on_save=None):
        self.title = title or "OCR Result"
        self.on_save = on_save
        self._last_export = None
        self._build(text or "")

    def _build(self, text: str):
        root = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        root.height = dp(548)

        self.status = MDLabel(text="Editable OCR text", size_hint_y=None, height=dp(28), theme_text_color="Secondary")
        root.add_widget(self.status)

        self.editor = MDTextField(
            text=text,
            multiline=True,
            mode="rectangle",
            hint_text="Recognized text",
            size_hint_y=None,
            height=dp(300),
        )
        root.add_widget(self.editor)

        find_row = MDBoxLayout(spacing=dp(6), size_hint_y=None, height=dp(54))
        self.find_field = MDTextField(hint_text="Find", mode="rectangle")
        self.replace_field = MDTextField(hint_text="Replace", mode="rectangle")
        find_row.add_widget(self.find_field)
        find_row.add_widget(self.replace_field)
        root.add_widget(find_row)

        action_row = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(44))
        for label, callback in (
            ("FIND", self.find),
            ("REPLACE ALL", self.replace_all),
            ("CLEAN", self.clean),
            ("COPY", self.copy),
        ):
            action_row.add_widget(MDFlatButton(text=label, on_release=callback))
        root.add_widget(action_row)

        export_row = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(44))
        for label, ext in (("TXT", "txt"), ("WORD", "docx"), ("PDF", "pdf")):
            export_row.add_widget(MDFlatButton(text=label, on_release=lambda *_a, e=ext: self.export(e)))
        root.add_widget(export_row)

        file_row = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(44))
        self.open_export_button = MDFlatButton(text="OPEN EXPORT", disabled=True, on_release=self.open_export)
        self.share_export_button = MDFlatButton(text="SHARE EXPORT", disabled=True, on_release=self.share_export)
        file_row.add_widget(self.open_export_button)
        file_row.add_widget(self.share_export_button)
        root.add_widget(file_row)

        buttons = [MDFlatButton(text="CLOSE", on_release=lambda *_: self.dialog.dismiss())]
        if self.on_save is not None:
            buttons.append(MDFlatButton(text="SAVE OCR", on_release=self.save))

        self.dialog = MDDialog(
            title=self.title,
            type="custom",
            content_cls=root,
            buttons=buttons,
        )

    def open(self):
        self.dialog.open()
        return self

    def find(self, *_):
        matches = find_text_matches(self.editor.text, self.find_field.text)
        if not self.find_field.text:
            self.status.text = "Enter text to find."
        elif not matches:
            self.status.text = "No matches found."
        else:
            self.status.text = f"Found {len(matches)} match(es). First at character {matches[0][0] + 1}."

    def replace_all(self, *_):
        new_text, count = replace_ocr_text(
            self.editor.text,
            self.find_field.text,
            self.replace_field.text,
        )
        self.editor.text = new_text
        self.status.text = f"Replaced {count} occurrence(s)." if count else "No matches replaced."

    def clean(self, *_):
        self.editor.text = normalize_ocr_paragraphs(self.editor.text)
        self.status.text = "Paragraph spacing cleaned."

    def copy(self, *_):
        Clipboard.copy(self.editor.text or "")
        self.status.text = "Copied to clipboard."

    def save(self, *_):
        if self.on_save is not None:
            try:
                self.on_save(self.editor.text)
                self.status.text = "OCR text saved to document."
            except Exception as exc:
                self.status.text = f"Save failed: {exc}"

    def export(self, ext: str):
        app = MDApp.get_running_app()
        base = _safe_base_name(self.title)
        try:
            output = app.storage.get_export_path(f"{base}_OCR.{ext}")
            if ext == "txt":
                Path(output).write_text(self.editor.text or "", encoding="utf-8")
            elif ext == "docx":
                from tools.document_tools import create_docx_from_text
                create_docx_from_text(self.editor.text, output)
            elif ext == "pdf":
                from tools.document_tools import text_to_pdf
                text_to_pdf(self.editor.text, output)
            else:
                raise ValueError("Unsupported export type")
            try:
                external = app.storage.publish_export(output, app.prefs)
            except Exception as publish_exc:
                external = None
                publish_error = str(publish_exc)
            else:
                publish_error = None
            self._last_export = output
            self.open_export_button.disabled = False
            self.share_export_button.disabled = False
            self.status.text = f"Saved: {output}"
            if external and external != output:
                self.status.text += f"\nExternal copy: {external}"
            elif publish_error:
                self.status.text += f"\nExternal save failed: {publish_error}"
        except Exception as exc:
            self.status.text = f"Export failed: {exc}"

    def open_export(self, *_):
        if not self._last_export:
            return
        try:
            from storage.share import open_file
            open_file(self._last_export)
        except Exception as exc:
            self.status.text = f"Open failed: {exc}"

    def share_export(self, *_):
        if not self._last_export:
            return
        try:
            from storage.share import share_file
            share_file(self._last_export)
        except Exception as exc:
            self.status.text = f"Share failed: {exc}"


def show_ocr_result_editor(title: str, text: str, on_save=None):
    return OCRResultEditor(title, text, on_save=on_save).open()
