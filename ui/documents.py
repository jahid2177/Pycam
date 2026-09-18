"""
Documents screen - the "Files" tab: the full document library.

Unlike HomeScreen (which shows only the most recent documents on the
dashboard), this screen lists *every* saved document, with the same
search-as-you-type and per-row actions (rename / export / OCR / delete).

The row widget (DocumentListItem) and the small helpers around it
(menu bookkeeping, relative-time formatting, the type-icon map) are owned by
ui.home and imported here rather than duplicated, so both screens stay in
sync automatically.
"""

from kivy.properties import ObjectProperty
from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
from kivymd.uix.textfield import MDTextField
from kivymd.app import MDApp

from ui.navigation import BottomNavigationBar
from ui.home import (
    DocumentListItem,
    dismiss_open_menu,
)


class DocumentsScreen(MDScreen):
    doc_list = ObjectProperty(None)
    empty_state = ObjectProperty(None)
    doc_count_label = ObjectProperty(None)
    bottom_nav_container = ObjectProperty(None)

    def on_kv_post(self, base_widget):
        if self.bottom_nav_container and not self.bottom_nav_container.children:
            self.bottom_nav_container.add_widget(BottomNavigationBar(selected="documents"))

    def on_pre_enter(self, *args):
        self.refresh_documents()

    def refresh_documents(self, search_query: str = None):
        app = MDApp.get_running_app()
        documents = app.db.list_documents(search=search_query)
        total = app.db.count_documents()

        self.doc_count_label.text = "1 document" if total == 1 else f"{total} documents"

        self.doc_list.clear_widgets()
        self.empty_state.opacity = 1 if not documents else 0
        self.empty_state.disabled = bool(documents)
        from kivy.metrics import dp
        self.empty_state.height = dp(240) if not documents else 0

        for document in documents:
            item = DocumentListItem(document=document, controller=self)
            self.doc_list.add_widget(item)

    # ---- Navigation --------------------------------------------------

    def go_home(self):
        MDApp.get_running_app().go_to("home")

    def go_settings(self):
        MDApp.get_running_app().go_to("settings")

    def go_tools(self):
        MDApp.get_running_app().go_to("tools")

    def open_document(self, document: dict):
        dismiss_open_menu()
        app = MDApp.get_running_app()
        if app.active_session_pages:
            from kivymd.uix.button import MDFlatButton

            def do_open(*a):
                dialog.dismiss()
                self._load_document_into_editor(document)

            dialog = MDDialog(
                title="Discard unsaved pages?",
                text="You have an unsaved scan in progress. Opening this "
                     "document will discard it.",
                buttons=[
                    MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                    MDFlatButton(text="DISCARD & OPEN", on_release=do_open),
                ],
            )
            dialog.open()
        else:
            self._load_document_into_editor(document)

    def _load_document_into_editor(self, document: dict):
        app = MDApp.get_running_app()
        pages = app.db.get_pages(document["id"])
        app.active_session_pages = list(pages)
        app.editing_document_id = document["id"]
        app.latest_capture_path = pages[-1] if pages else None
        app.latest_raw_path = None
        app.go_to("editor")

    # ---- Item actions --------------------------------------------------

    def prompt_rename(self, document: dict):
        dismiss_open_menu()
        field = MDTextField(text=document["name"], hint_text="Document name")

        def do_rename(*args):
            new_name = field.text.strip()
            if new_name:
                MDApp.get_running_app().db.rename_document(document["id"], new_name)
                self.refresh_documents()
            dialog.dismiss()

        from kivymd.uix.button import MDFlatButton

        dialog = MDDialog(
            title="Rename document",
            type="custom",
            content_cls=field,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="SAVE", on_release=do_rename),
            ],
        )
        dialog.open()

    def confirm_delete(self, document: dict):
        dismiss_open_menu()
        from kivymd.uix.button import MDFlatButton

        def do_delete(*args):
            MDApp.get_running_app().db.delete_document(document["id"])
            self.refresh_documents()
            dialog.dismiss()

        dialog = MDDialog(
            title="Delete document?",
            text=f'"{document["name"]}" will be permanently deleted.',
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="DELETE", on_release=do_delete),
            ],
        )
        dialog.open()

    def export_document(self, document: dict):
        dismiss_open_menu()
        app = MDApp.get_running_app()
        pages = app.db.get_pages(document["id"])
        if not pages:
            return

        from ui.export_options import show_export_dialog

        show_export_dialog(
            title=f'Export "{document["name"]}"',
            preferred_format=app.prefs.get("export_format"),
            callback=lambda fmt, options: self._run_export(document, pages, fmt, options),
        )

    def _run_export(self, document, pages, fmt, options):
        import threading

        threading.Thread(
            target=self._do_export,
            args=(document, pages, fmt, options),
            daemon=True,
        ).start()

    def _do_export(self, document, pages, fmt, options):
        from pdf.export import (
            export_to_pdf,
            export_to_image,
            export_to_images_zip,
        )

        app = MDApp.get_running_app()

        safe_name = "".join(
            c for c in document["name"] if c.isalnum() or c in " _-"
        ).strip() or "document"

        quality = options.get("quality", "balanced")

        try:
            if fmt == "pdf":
                output_path = app.storage.get_export_path(f"{safe_name}.pdf")
                export_to_pdf(
                    pages,
                    output_path,
                    page_size=options.get("page_size", "a4"),
                    orientation=options.get("orientation", "auto"),
                    margin_pt=float(options.get("margin_pt", 24.0)),
                    quality=quality,
                )
            elif len(pages) == 1:
                output_path = app.storage.get_export_path(f"{safe_name}.{fmt}")
                export_to_image(pages, output_path, fmt=fmt, quality=quality)
            else:
                output_path = app.storage.get_export_path(f"{safe_name}_{fmt}.zip")
                export_to_images_zip(pages, output_path, fmt=fmt, quality=quality)

            result = (True, output_path)

        except Exception as exc:
            result = (False, str(exc))

        from kivy.clock import Clock

        Clock.schedule_once(lambda dt: self._on_export_done(*result), 0)

    def run_ocr(self, document: dict):
        dismiss_open_menu()
        app = MDApp.get_running_app()
        pages = app.db.get_pages(document["id"])
        if not pages:
            return

        from kivy.utils import platform
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDFlatButton

        if platform != "android":
            dialog = MDDialog(
                title="OCR requires a real device",
                text="Both OCR backends (ML Kit and Tesseract) are Android-native "
                     "bridges and can't run in this desktop dev environment.",
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: dialog.dismiss())],
            )
            dialog.open()
            return

        def choose(language):
            dialog.dismiss()
            self._run_ocr_language(document, pages, language)

        preferred = app.prefs.get("ocr_language")
        content = MDBoxLayout(orientation="horizontal", spacing="12dp",
                               size_hint_y=None, height="48dp")
        for label, lang in [("ENGLISH", "english"), ("BENGALI", "bengali")]:
            content.add_widget(MDFlatButton(
                text=label,
                theme_text_color="Custom",
                text_color=(0.20, 0.85, 0.35, 1) if lang == preferred else (0, 0, 0, 0.87),
                on_release=lambda x, l=lang: choose(l),
            ))

        dialog = MDDialog(
            title="Run OCR - choose language",
            type="custom",
            content_cls=content,
            buttons=[],
        )
        dialog.open()

    def _run_ocr_language(self, document, pages, language):
        import threading
        threading.Thread(
            target=self._do_ocr, args=(document, pages, language), daemon=True
        ).start()

    def _do_ocr(self, document, pages, language):
        from ocr.ocr_manager import run_ocr_for_pages

        app = MDApp.get_running_app()
        try:
            text = run_ocr_for_pages(pages, language)
            result = (True, text)
        except Exception as e:
            result = (False, str(e))

        from kivy.clock import Clock

        def finish(dt):
            success, payload = result
            if success:
                app.db.update_ocr_text(document["id"], payload)
                self.refresh_documents()
            self._on_ocr_done(document, success, payload)

        Clock.schedule_once(finish, 0)

    def _on_ocr_done(self, document, success: bool, text_or_error: str):
        from kivymd.uix.button import MDFlatButton

        if success:
            preview = text_or_error[:300] + ("..." if len(text_or_error) > 300 else "")
            dialog = MDDialog(
                title="OCR complete",
                text=preview or "No text was recognized on this document.",
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: dialog.dismiss())],
            )
        else:
            dialog = MDDialog(
                title="OCR failed",
                text=text_or_error,
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: dialog.dismiss())],
            )
        dialog.open()

    def _on_export_done(self, success: bool, path_or_error: str):
        from kivy.utils import platform
        from kivymd.uix.button import MDFlatButton
        if success:
            from storage.notifications import notify_export_saved
            notify_export_saved(path_or_error)

            buttons = [MDFlatButton(text="OK", on_release=lambda *a: dialog.dismiss())]
            if platform == "android":
                buttons.insert(0, MDFlatButton(
                    text="SHARE",
                    on_release=lambda *a: self._share_exported(dialog, path_or_error),
                ))
            dialog = MDDialog(
                title="Export complete",
                text=f"Saved to:\n{path_or_error}",
                buttons=buttons,
            )
        else:
            dialog = MDDialog(
                title="Export failed",
                text=path_or_error,
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: dialog.dismiss())],
            )
        dialog.open()

    def _share_exported(self, dialog, file_path: str):
        dialog.dismiss()
        from storage.share import share_file
        from kivymd.uix.button import MDFlatButton
        try:
            share_file(file_path)
        except Exception as e:
            error_dialog = MDDialog(
                title="Share failed",
                text=str(e),
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: error_dialog.dismiss())],
            )
            error_dialog.open()
