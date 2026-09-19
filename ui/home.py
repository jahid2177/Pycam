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

from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivymd.uix.screen import MDScreen
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.dialog import MDDialog
from kivymd.uix.textfield import MDTextField
from kivymd.app import MDApp

from ui.navigation import BottomNavigationBar
from storage.localization import tr


DOCUMENT_TYPE_ICONS = {
    "document": "file-document-outline",
    "id_card": "card-account-details-outline",
    "receipt": "receipt",
    "certificate": "certificate-outline",
    "business_card": "card-account-mail-outline",
    "passport": "passport",
}


# --- Dropdown menu plumbing -------------------------------------------
# KivyMD's MDDropdownMenu anchors itself to the caller widget, so an overflow
# button sitting on the right edge of a row pushed the card past the screen
# edge. The most recently opened menu is tracked here so it can be clamped back
# inside the window, and so it can be closed before a dialog is shown - an open
# menu used to stay visible underneath the dialog's dim layer.
_open_menu = None


def register_open_menu(menu):
    global _open_menu
    _open_menu = menu


def dismiss_open_menu():
    """Close the tracked dropdown, if any, before showing a modal dialog."""
    global _open_menu
    menu, _open_menu = _open_menu, None
    if menu is not None:
        try:
            menu.dismiss()
        except Exception:
            pass


def keep_menu_on_screen(menu, margin=dp(8)):
    """Clamp an opened MDDropdownMenu surface inside the visible Window."""
    card = getattr(menu, "menu", None) or menu

    try:
        width = float(card.width)
        x = float(card.x)
    except Exception:
        return

    available = max(dp(80), Window.width - (margin * 2))
    if width > available:
        try:
            card.width = available
            width = available
        except Exception:
            pass

    limit = Window.width - margin
    try:
        if x + width > limit:
            card.x = max(margin, limit - width)
        if card.x < margin:
            card.x = margin
    except Exception:
        pass


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

    def __init__(self, document: dict, controller, search_query: str = None, **kwargs):
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
        if document.get("protected"):
            self.doc_meta = "🔒 " + self.doc_meta
        query = (search_query or "").strip()
        if query:
            haystack = document.get("ocr_text") or ""
            lower = haystack.lower()
            pos = lower.find(query.lower())
            if pos >= 0:
                start = max(0, pos - 28)
                end = min(len(haystack), pos + len(query) + 42)
                snippet = " ".join(haystack[start:end].split())
                if start > 0:
                    snippet = "…" + snippet
                if end < len(haystack):
                    snippet += "…"
                self.doc_meta = f"Match: {snippet}"
            elif query.lower() in (document.get("name") or "").lower():
                self.doc_meta = f"Name match • {self.doc_meta}"
        self._menu = None

    def open_menu(self, caller):
        items = [
            {"text": "Remove favorite" if self.document.get("favorite") else "Add favorite", "on_release": self._favorite},
            {"text": "Move to folder", "on_release": self._folder},
            {"text": "Edit tags", "on_release": self._tags},
            {"text": "Unprotect document" if self.document.get("protected") else "Protect document", "on_release": self._protect},
            {"text": "Rename", "on_release": self._rename},
        ]
        if hasattr(self.controller, "duplicate_document"):
            items.append({"text": "Duplicate", "on_release": self._duplicate})
        items.extend([
            {"text": "Export", "on_release": self._export},
            {"text": "Run OCR", "on_release": self._run_ocr},
            {"text": "Move to Trash", "on_release": self._delete},
        ])
        # The caller is the right-edge 3-dot button.  Make the menu grow to
        # the LEFT of that caller and give it an explicit phone-safe width so
        # it can never render beyond the right edge of the display.
        safe_width = min(dp(196), max(dp(150), Window.width - dp(24)))
        menu = MDDropdownMenu(
            caller=caller,
            items=items,
            width=safe_width,
            position="bottom",
            border_margin=dp(12),
            hor_growth="left",
        )
        self._menu = menu
        register_open_menu(menu)
        menu.open()

        # KivyMD finalises dropdown geometry asynchronously.  Clamp more than
        # once so both the first layout pass and Android's next frame are safe.
        keep_menu_on_screen(menu, margin=dp(12))
        from kivy.clock import Clock

        Clock.schedule_once(lambda dt: keep_menu_on_screen(menu, margin=dp(12)), 0)
        Clock.schedule_once(lambda dt: keep_menu_on_screen(menu, margin=dp(12)), 0.05)

    def _dismiss_menu(self):
        if self._menu:
            self._menu.dismiss()
            self._menu = None

    def _favorite(self, *args):
        self._dismiss_menu()
        self.controller.toggle_favorite(self.document)

    def _folder(self, *args):
        self._dismiss_menu()
        self.controller.prompt_folder(self.document)

    def _tags(self, *args):
        self._dismiss_menu()
        self.controller.prompt_tags(self.document)

    def _protect(self, *args):
        self._dismiss_menu()
        self.controller.toggle_protected(self.document)

    def _rename(self, *args):
        self._dismiss_menu()
        self.controller.prompt_rename(self.document)

    def _duplicate(self, *args):
        self._dismiss_menu()
        if hasattr(self.controller, "duplicate_document"):
            self.controller.duplicate_document(self.document)

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
        # Let children (the overflow menu button) handle their own tap first
        result = super().on_touch_up(touch)
        
        # Check if the touch is on the 3-dot menu button to stop propagation
        for child in self.children:
            if getattr(child, 'icon', '') == 'dots-vertical' and child.collide_point(*touch.pos):
                return True
                
        if result:
            return True
            
        # Treat as row click only if children didn't consume the touch
        if self.collide_point(*touch.pos):
            self.on_release_row()
            return True
        return False


class HomeScreen(MDScreen):
    recent_list = ObjectProperty(None)
    empty_state = ObjectProperty(None)
    doc_count_label = ObjectProperty(None)
    bottom_nav_container = ObjectProperty(None)

    storage_usage_text = StringProperty("Storage: 0 B")
    search_hint = StringProperty("Search")
    discard_text = StringProperty("DISCARD")
    resume_button_text = StringProperty("RESUME")
    empty_title = StringProperty("No documents yet")
    empty_subtitle = StringProperty("Tap the camera button to scan your first page")
    resume_text = StringProperty("")
    has_draft = BooleanProperty(False)

    RECENT_LIMIT = 8

    def on_kv_post(self, base_widget):
        if self.bottom_nav_container and not self.bottom_nav_container.children:
            self.bottom_nav_container.add_widget(BottomNavigationBar(selected="home"))

    def on_pre_enter(self, *args):
        self._apply_language()
        self.refresh_documents()
        self.refresh_home_stats()

    def _apply_language(self):
        app = MDApp.get_running_app()
        lang = app.prefs.get("app_language") if getattr(app, "prefs", None) else "en"
        self.search_hint = tr("search", lang, "Search")
        self.discard_text = tr("discard", lang, "DISCARD")
        self.resume_button_text = tr("resume", lang, "RESUME")
        self.empty_title = tr("no_documents", lang, "No documents yet")
        self.empty_subtitle = tr("scan_first_page", lang, "Tap the camera button to scan your first page")

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, value or 0))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024.0
        return "0 B"

    def refresh_home_stats(self):
        app = MDApp.get_running_app()
        try:
            lang = app.prefs.get("app_language") if getattr(app, "prefs", None) else "en"
            self.storage_usage_text = f"{tr("storage", lang, "Storage")}: {self._format_bytes(app.storage.get_storage_size_bytes())}"
        except Exception:
            self.storage_usage_text = tr("storage_unavailable", app.prefs.get("app_language"), "Storage unavailable")
        count = len(app.active_session_pages or [])
        self.has_draft = count > 0
        if count:
            lang = app.prefs.get("app_language")
            label = tr("page", lang, "page") if count == 1 else tr("pages", lang, "pages")
            self.resume_text = f"{tr("unfinished_scan", lang, "Unfinished scan")} • {count} {label}"
        else:
            self.resume_text = ""

    def refresh_documents(self, search_query: str = None):
        app = MDApp.get_running_app()
        documents = app.db.list_documents(search=search_query)
        total = app.db.count_documents()

        lang = app.prefs.get("app_language") if getattr(app, "prefs", None) else "en"
        unit = tr("document", lang, "document") if total == 1 else tr("documents", lang, "documents")
        self.doc_count_label.text = f"{total} {unit}"

        self.recent_list.clear_widgets()
        # Collapse the empty state to zero height, not just fade it out: an
        # invisible-but-present block still reserved ~240dp at the top of the
        # list, which pushed the first row down so it looked vertically centred
        # instead of top-aligned under the search bar.
        self.empty_state.opacity = 1 if not documents else 0
        self.empty_state.height = dp(240) if not documents else 0
        self.empty_state.disabled = bool(documents)

        for document in documents[: self.RECENT_LIMIT]:
            item = DocumentListItem(document=document, controller=self, search_query=search_query)
            self.recent_list.add_widget(item)

    # ---- Navigation --------------------------------------------------

    def _prepare_new_session(self, callback):
        app = MDApp.get_running_app()
        if not app.active_session_pages:
            callback()
            return

        from kivymd.uix.button import MDFlatButton

        def discard(*_):
            dialog.dismiss()
            app.active_session_pages = []
            app.editing_document_id = None
            app.latest_capture_path = None
            app.latest_raw_path = None
            try:
                app.clear_session_draft()
            except Exception:
                pass
            self.refresh_home_stats()
            callback()

        dialog = MDDialog(
            title="Start a new scan?",
            text="You have an unfinished scan. Starting a new one will discard that draft.",
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="DISCARD & START", on_release=discard),
            ],
        )
        dialog.open()

    def _launch_scan(self, capture_mode="single", scan_type="scan"):
        app = MDApp.get_running_app()
        app.active_session_pages = []
        app.editing_document_id = None
        app.pending_capture_mode = capture_mode
        app.pending_scan_type = scan_type
        app.go_to("scanner")

    def start_scan(self):
        self._prepare_new_session(lambda: self._launch_scan("single", "scan"))

    def start_batch_scan(self):
        self._prepare_new_session(lambda: self._launch_scan("batch", "scan"))

    def start_id_scan(self):
        self._prepare_new_session(lambda: self._launch_scan("batch", "id_card"))

    def import_images(self):
        def open_picker():
            app = MDApp.get_running_app()
            app.active_session_pages = []
            app.editing_document_id = None
            app.photo_picker_return_screen = "editor"
            app.go_to("photo_picker")
        self._prepare_new_session(open_picker)


    def import_pdf(self):
        def open_pdf_picker():
            app = MDApp.get_running_app()
            app.active_session_pages = []
            app.editing_document_id = None
            app.pending_scanner_action = "pdf"
            app.go_to("scanner")
        self._prepare_new_session(open_pdf_picker)

    def resume_scan(self):
        app = MDApp.get_running_app()
        if not app.active_session_pages:
            self.refresh_home_stats()
            return
        app.latest_capture_path = app.active_session_pages[-1]
        app.go_to("editor")

    def discard_draft(self):
        app = MDApp.get_running_app()
        app.active_session_pages = []
        app.editing_document_id = None
        app.latest_capture_path = None
        app.latest_raw_path = None
        try:
            app.clear_session_draft()
        except Exception:
            pass
        self.refresh_home_stats()

    def go_documents(self):
        MDApp.get_running_app().go_to("documents")

    def go_settings(self):
        MDApp.get_running_app().go_to("settings")

    def go_tools(self):
        MDApp.get_running_app().go_to("tools")

    def open_document(self, document: dict):
        dismiss_open_menu()
        if document.get("protected"):
            from ui.app_lock import request_pin
            request_pin("Protected document", lambda: self._open_document_unlocked(document))
            return
        self._open_document_unlocked(document)

    def _open_document_unlocked(self, document: dict):
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
        try:
            app.set_sensitive_content(bool(document.get("protected")))
        except Exception:
            pass
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

    def toggle_favorite(self, document: dict):
        app = MDApp.get_running_app()
        app.db.set_favorite(document["id"], not bool(document.get("favorite")))
        self.refresh_documents()

    def toggle_protected(self, document: dict):
        dismiss_open_menu()
        app = MDApp.get_running_app()
        from storage.security import has_pin
        from kivymd.uix.button import MDFlatButton
        if not has_pin(app.prefs):
            dialog = MDDialog(
                title="Set an app PIN first",
                text="Open Settings → App & Privacy and create a PIN before protecting documents.",
                buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())],
            )
            dialog.open()
            return
        from ui.app_lock import request_pin
        target = not bool(document.get("protected"))
        def apply():
            app.db.set_protected(document["id"], target)
            self.refresh_documents()
        request_pin("Protect document" if target else "Unprotect document", apply)

    def prompt_folder(self, document: dict):
        dismiss_open_menu()
        field = MDTextField(text=document.get("folder") or "", hint_text="Folder name (blank = no folder)")
        from kivymd.uix.button import MDFlatButton

        def save(*_):
            MDApp.get_running_app().db.set_folder(document["id"], field.text)
            dialog.dismiss()
            self.refresh_documents()

        dialog = MDDialog(
            title="Move to folder",
            type="custom",
            content_cls=field,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="SAVE", on_release=save),
            ],
        )
        dialog.open()

    def prompt_tags(self, document: dict):
        dismiss_open_menu()
        existing = document.get("tags") or []
        field = MDTextField(text=", ".join(existing), hint_text="Tags separated by commas")
        from kivymd.uix.button import MDFlatButton

        def save(*_):
            tags = [part.strip() for part in field.text.split(",") if part.strip()]
            MDApp.get_running_app().db.set_tags(document["id"], tags)
            dialog.dismiss()
            self.refresh_documents()

        dialog = MDDialog(
            title="Edit tags",
            type="custom",
            content_cls=field,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="SAVE", on_release=save),
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
            title="Move document to Trash?",
            text=f'"{document["name"]}" can be restored later from Trash.',
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="MOVE TO TRASH", on_release=do_delete),
            ],
        )
        dialog.open()

    def export_document(self, document: dict):
        dismiss_open_menu()
        if document.get("protected"):
            from ui.app_lock import request_pin
            request_pin("Protected document", lambda: self._export_document_unlocked(document))
            return
        self._export_document_unlocked(document)

    def _export_document_unlocked(self, document: dict):
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
                    searchable=bool(options.get("searchable", False)),
                    ocr_language=app.prefs.get("ocr_language") or "english",
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

            try:
                self._last_external_export = app.storage.publish_export(output_path, app.prefs)
                self._last_external_export_error = None
            except Exception as publish_exc:
                self._last_external_export = None
                self._last_external_export_error = str(publish_exc)

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
        dismiss_open_menu()
        if document.get("protected"):
            from ui.app_lock import request_pin
            request_pin("Protected document", lambda: self._run_ocr_unlocked(document))
            return
        self._run_ocr_unlocked(document)

    def _run_ocr_unlocked(self, document: dict):
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
        for label, lang in [("ENGLISH", "english"), ("BENGALI", "bengali"), ("EN+বাংলা", "mixed")]:
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
        if success:
            from ui.ocr_result import show_ocr_result_editor
            app = MDApp.get_running_app()

            def save_text(value):
                app.db.update_ocr_text(document["id"], value)
                self.refresh_documents()

            show_ocr_result_editor(
                f"{document.get('name', 'Document')} - OCR",
                text_or_error or "",
                on_save=save_text,
            )
            return

        from kivymd.uix.button import MDFlatButton
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
                buttons.insert(0, MDFlatButton(
                    text="OPEN",
                    on_release=lambda *a: self._open_exported(dialog, path_or_error),
                ))
            dialog = MDDialog(
                title="Export complete",
                text=(
                    f"Saved in app storage:\n{path_or_error}"
                    + (f"\n\nExternal copy:\n{getattr(self, '_last_external_export', '')}"
                       if getattr(self, '_last_external_export', None) and getattr(self, '_last_external_export', None) != path_or_error else "")
                    + (f"\n\nExternal save failed:\n{getattr(self, '_last_external_export_error', '')}"
                       if getattr(self, '_last_external_export_error', None) else "")
                ),
                buttons=buttons,
            )
        else:
            dialog = MDDialog(
                title="Export failed",
                text=path_or_error,
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: dialog.dismiss())],
            )
        dialog.open()

    def _open_exported(self, dialog, file_path: str):
        dialog.dismiss()
        from storage.share import open_file
        from kivymd.uix.button import MDFlatButton
        try:
            open_file(file_path)
        except Exception as e:
            error_dialog = MDDialog(
                title="Open failed",
                text=str(e),
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: error_dialog.dismiss())],
            )
            error_dialog.open()

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
