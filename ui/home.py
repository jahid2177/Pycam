"""
Home screen - the app's landing screen.

Responsibilities:
- Show a live count + list of recently updated documents from the DB
- Provide navigation into Scanner, Documents, and Settings
- Provide a lightweight search-as-you-type over document name/OCR text

This screen does NOT touch the camera or OpenCV directly; scanning is
owned entirely by ScannerScreen (kept per spec section 4's module
boundaries).
"""

from datetime import datetime

from kivy.properties import StringProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivymd.uix.screen import MDScreen
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.dialog import MDDialog
from kivymd.uix.textfield import MDTextField
from kivymd.app import MDApp

from ui.navigation import BottomNavigationBar


DOCUMENT_TYPE_ICONS = {
    "document": "file-document-outline",
    "id_card": "card-account-details-outline",
    "receipt": "receipt",
    "certificate": "certificate-outline",
    "business_card": "card-account-mail-outline",
    "passport": "passport",
}


def _format_relative_time(iso_timestamp: str) -> str:
    try:
        then = datetime.fromisoformat(iso_timestamp)
    except (TypeError, ValueError):
        return ""
    delta = datetime.utcnow() - then
    seconds = delta.total_seconds()
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hr ago"
    if seconds < 172800:
        return "Yesterday"
    return then.strftime("%d %b %Y")


class DocumentListItem(BoxLayout):
    """One row in a document list (used by both Home's recent list and
    Documents' full library). Kept as a plain BoxLayout (not MDList's
    built-in item) so we can show a type icon, two-line metadata, and a
    per-item overflow menu.

    `controller` is any object exposing prompt_rename/export_document/
    run_ocr/confirm_delete/open_document for this row's document dict -
    Home and Documents both implement that same small interface rather
    than this widget needing to know which screen it's on."""

    doc_id = ObjectProperty(None)
    doc_name = StringProperty("")
    doc_meta = StringProperty("")
    type_icon = StringProperty("file-document-outline")

    def __init__(self, document: dict, controller, **kwargs):
        super().__init__(**kwargs)
        self.document = document
        self.controller = controller
        self.doc_id = document["id"]
        self.doc_name = document["name"]
        self.type_icon = DOCUMENT_TYPE_ICONS.get(
            document.get("document_type", "document"), "file-document-outline"
        )
        page_count = document.get("page_count", 0)
        page_label = "1 page" if page_count == 1 else f"{page_count} pages"
        when = _format_relative_time(document.get("updated_at", ""))
        self.doc_meta = f"{page_label} • {when}" if when else page_label
        self._menu = None

    def open_menu(self, caller):
        items = [
            {"text": "Rename", "on_release": self._rename},
            {"text": "Export", "on_release": self._export},
            {"text": "Run OCR", "on_release": self._run_ocr},
            {"text": "Delete", "on_release": self._delete},
        ]
        self._menu = MDDropdownMenu(caller=caller, items=items, width_mult=3)
        self._menu.open()

    def _dismiss_menu(self):
        if self._menu:
            self._menu.dismiss()
            self._menu = None

    def _rename(self, *args):
        self._dismiss_menu()
        self.controller.prompt_rename(self.document)

    def _export(self, *args):
        self._dismiss_menu()
        self.controller.export_document(self.document)

    def _run_ocr(self, *args):
        self._dismiss_menu()
        self.controller.run_ocr(self.document)

    def _delete(self, *args):
        self._dismiss_menu()
        self.controller.confirm_delete(self.document)

    def on_release_row(self):
        self.controller.open_document(self.document)

    def on_touch_up(self, touch):
        # Let children (the overflow menu button) handle their own tap
        # first; only treat this as "open the document" if nothing
        # inside the row already consumed the touch. Without this
        # override, on_release_row was previously unreachable - a
        # BoxLayout has no built-in tap event of its own.
        if super().on_touch_up(touch):
            return True
        if self.collide_point(*touch.pos):
            self.on_release_row()
            return True
        return False


class HomeScreen(MDScreen):
    recent_list = ObjectProperty(None)
    empty_state = ObjectProperty(None)
    doc_count_label = ObjectProperty(None)
    bottom_nav_container = ObjectProperty(None)

    RECENT_LIMIT = 8

    def on_kv_post(self, base_widget):
        if self.bottom_nav_container and not self.bottom_nav_container.children:
            self.bottom_nav_container.add_widget(BottomNavigationBar(selected="home"))

    def on_pre_enter(self, *args):
        self.refresh_documents()

    def refresh_documents(self, search_query: str = None):
        app = MDApp.get_running_app()
        documents = app.db.list_documents(search=search_query)
        total = app.db.count_documents()

        self.doc_count_label.text = "1 document" if total == 1 else f"{total} documents"

        self.recent_list.clear_widgets()
        self.empty_state.opacity = 1 if not documents else 0
        self.empty_state.disabled = bool(documents)

        for document in documents[: self.RECENT_LIMIT]:
            item = DocumentListItem(document=document, controller=self)
            self.recent_list.add_widget(item)

    # ---- Navigation --------------------------------------------------

    def start_scan(self):
        app = MDApp.get_running_app()
        app.active_session_pages = []
        app.editing_document_id = None  # a brand-new scan, not continuing a saved one
        app.go_to("scanner")

    def go_documents(self):
        MDApp.get_running_app().go_to("documents")

    def go_settings(self):
        MDApp.get_running_app().go_to("settings")

    def go_tools(self):
        MDApp.get_running_app().go_to("tools")

    def open_document(self, document: dict):
        app = MDApp.get_running_app()
        if app.active_session_pages:
            # Opening a saved document replaces the in-progress session
            # in app.active_session_pages - warn rather than silently
            # discard whatever the user hasn't saved yet.
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

    # ---- Search --------------------------------------------------------

    def open_search(self):
        self._search_field = MDTextField(hint_text="Search documents")
        self._search_dialog = MDDialog(
            title="Search",
            type="custom",
            content_cls=self._search_field,
            buttons=[],
        )
        self._search_field.bind(text=self._on_search_text)
        self._search_dialog.open()

    def _on_search_text(self, instance, value):
        self.refresh_documents(search_query=value.strip() or None)

    # ---- Item actions --------------------------------------------------

    def prompt_rename(self, document: dict):
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
        app = MDApp.get_running_app()
        pages = app.db.get_pages(
            document["id"]
        )
        if not pages:
            return

        from ui.export_options import (
            show_export_dialog,
        )

        show_export_dialog(
            title=f'Export "{document["name"]}"',
            preferred_format=(
                app.prefs.get(
                    "export_format"
                )
            ),
            callback=lambda fmt, options:
                self._run_export(
                    document,
                    pages,
                    fmt,
                    options,
                ),
        )

    def _run_export(
        self,
        document,
        pages,
        fmt,
        options,
    ):
        import threading

        threading.Thread(
            target=self._do_export,
            args=(
                document,
                pages,
                fmt,
                options,
            ),
            daemon=True,
        ).start()

    def _do_export(
        self,
        document,
        pages,
        fmt,
        options,
    ):
        from pdf.export import (
            export_to_pdf,
            export_to_image,
            export_to_images_zip,
        )

        app = MDApp.get_running_app()

        safe_name = "".join(
            c
            for c in document["name"]
            if c.isalnum()
            or c in " _-"
        ).strip() or "document"

        quality = options.get(
            "quality",
            "balanced",
        )

        try:
            if fmt == "pdf":
                output_path = (
                    app.storage.get_export_path(
                        f"{safe_name}.pdf"
                    )
                )

                export_to_pdf(
                    pages,
                    output_path,
                    page_size=options.get(
                        "page_size",
                        "a4",
                    ),
                    orientation=options.get(
                        "orientation",
                        "auto",
                    ),
                    margin_pt=float(
                        options.get(
                            "margin_pt",
                            24.0,
                        )
                    ),
                    quality=quality,
                )

            elif len(pages) == 1:
                output_path = (
                    app.storage.get_export_path(
                        f"{safe_name}.{fmt}"
                    )
                )

                export_to_image(
                    pages,
                    output_path,
                    fmt=fmt,
                    quality=quality,
                )

            else:
                output_path = (
                    app.storage.get_export_path(
                        f"{safe_name}_{fmt}.zip"
                    )
                )

                export_to_images_zip(
                    pages,
                    output_path,
                    fmt=fmt,
                    quality=quality,
                )

            result = (
                True,
                output_path,
            )

        except Exception as exc:
            result = (
                False,
                str(exc),
            )

        from kivy.clock import Clock

        Clock.schedule_once(
            lambda dt:
                self._on_export_done(
                    *result
                ),
            0,
        )

    def run_ocr(self, document: dict):
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
            # Export is a genuine new output file, so it may notify. This is
            # deliberately NOT called from edit/done/crop/filter actions.
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
