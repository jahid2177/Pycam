"""
Documents library - the full, searchable/sortable list of every saved
document (Home only shows a short recent list). Also where bulk
delete lives, via an explicit "Select" mode rather than a long-press
gesture (simpler to get right without being able to test touch timing
by hand in this environment, and just as usable).

Tapping a row reopens that document in the editor - reuses the same
"discard unsaved pages?" guard as HomeScreen.open_document, since a
session can just as easily be in progress when browsing from here.

Built entirely in Python (like ui/editor.py and ui/crop.py) since the
row list and bulk-action bar are both dynamic.
"""

from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.uix.scrollview import ScrollView
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDFlatButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.textfield import MDTextField
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.dialog import MDDialog
from kivymd.app import MDApp

from ui.home import DOCUMENT_TYPE_ICONS, _format_relative_time

SORT_OPTIONS = {
    "updated_desc": "Newest first",
    "updated_asc": "Oldest first",
    "name_asc": "Name (A-Z)",
    "pages_desc": "Most pages",
}


def _sort_documents(documents, sort_key):
    if sort_key == "updated_asc":
        return sorted(documents, key=lambda d: d.get("updated_at", ""))
    if sort_key == "name_asc":
        return sorted(documents, key=lambda d: d.get("name", "").lower())
    if sort_key == "pages_desc":
        return sorted(documents, key=lambda d: d.get("page_count", 0), reverse=True)
    return sorted(documents, key=lambda d: d.get("updated_at", ""), reverse=True)


class DocumentRow(BoxLayout):
    """A document row for the library list. Separate from
    ui.home.DocumentListItem (which Home also uses) because this one
    needs a selection checkbox and Home's doesn't - keeping them
    separate avoids coupling the two screens through one shared
    widget's growing feature set."""

    doc_name = StringProperty("")
    doc_meta = StringProperty("")

    def __init__(self, document, controller, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(72),
                          padding=(dp(12), dp(4)), spacing=dp(12), **kwargs)
        self.document = document
        self.controller = controller

        self.checkbox = MDIconButton(
            icon="checkbox-blank-circle-outline",
            size_hint_x=None,
            width=dp(40) if controller.selection_mode else 0,
            opacity=1 if controller.selection_mode else 0,
            on_release=lambda x: controller.toggle_select(document["id"]),
        )
        self.add_widget(self.checkbox)
        self._update_checkbox()

        icon = MDIconButton(
            icon=DOCUMENT_TYPE_ICONS.get(document.get("document_type", "document"), "file-document-outline"),
            disabled=True, size_hint_x=None, width=dp(40),
        )
        self.add_widget(icon)

        text_col = MDBoxLayout(orientation="vertical")
        page_count = document.get("page_count", 0)
        page_label = "1 page" if page_count == 1 else f"{page_count} pages"
        when = _format_relative_time(document.get("updated_at", ""))
        text_col.add_widget(MDLabel(text=document["name"], font_style="Subtitle1", shorten=True))
        text_col.add_widget(MDLabel(
            text=f"{page_label} • {when}" if when else page_label,
            theme_text_color="Secondary", font_style="Caption",
        ))
        self.add_widget(text_col)

        self.menu_button = MDIconButton(
            icon="dots-vertical",
            size_hint_x=None,
            width=0 if controller.selection_mode else dp(40),
            opacity=0 if controller.selection_mode else 1,
            on_release=self._open_menu,
        )
        self.add_widget(self.menu_button)

    def _update_checkbox(self):
        selected = self.document["id"] in self.controller.selected_ids
        self.checkbox.icon = "checkbox-marked-circle" if selected else "checkbox-blank-circle-outline"

    def _open_menu(self, caller):
        items = [
            {"text": "Rename", "on_release": lambda: self.controller.prompt_rename(self.document)},
            {"text": "Export", "on_release": lambda: self.controller.export_document(self.document)},
            {"text": "Run OCR", "on_release": lambda: self.controller.run_ocr(self.document)},
            {"text": "Delete", "on_release": lambda: self.controller.confirm_delete(self.document)},
        ]
        menu = MDDropdownMenu(caller=caller, items=items, width_mult=3)
        for item in items:
            original = item["on_release"]
            item["on_release"] = (lambda o=original, m=menu: (m.dismiss(), o()))
        menu.items = items
        menu.open()

    def on_touch_up(self, touch):
        if super().on_touch_up(touch):
            return True
        if self.collide_point(*touch.pos):
            if self.controller.selection_mode:
                self.controller.toggle_select(self.document["id"])
            else:
                self.controller.open_document(self.document)
            return True
        return False


class DocumentsScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selection_mode = False
        self.selected_ids = set()
        self._search_query = None
        self._sort_key = "updated_desc"
        self._documents = []

        root = MDBoxLayout(orientation="vertical")

        self.toolbar = MDTopAppBar(title="My Documents", elevation=2)
        self.toolbar.left_action_items = [["arrow-left", lambda x: self.go_home()]]
        self._set_default_toolbar_actions()
        root.add_widget(self.toolbar)

        self.search_field = MDTextField(
            hint_text="Search documents", size_hint_y=None, height=dp(48),
            padding=(dp(16), dp(8)),
        )
        self.search_field.bind(text=lambda i, v: self._on_search_text(v))
        self.search_field.height = 0
        self.search_field.opacity = 0
        root.add_widget(self.search_field)

        scroll = ScrollView()
        self.list_box = MDBoxLayout(orientation="vertical", adaptive_height=True)
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

        self.empty_label = MDLabel(
            text="No documents saved yet", halign="center",
            theme_text_color="Hint", opacity=0,
        )
        root.add_widget(self.empty_label)

        self.bulk_bar = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=0, opacity=0,
            padding=(dp(16), dp(8)), spacing=dp(12),
        )
        self.selection_label = MDLabel(text="0 selected", theme_text_color="Secondary")
        self.bulk_bar.add_widget(self.selection_label)
        self.bulk_bar.add_widget(Widget())
        self.bulk_bar.add_widget(MDFlatButton(text="SELECT ALL", on_release=lambda x: self.select_all()))
        self.bulk_bar.add_widget(MDRaisedButton(text="DELETE", on_release=lambda x: self.delete_selected()))
        root.add_widget(self.bulk_bar)

        self.add_widget(root)

    def _set_default_toolbar_actions(self):
        self.toolbar.right_action_items = [
            ["magnify", lambda x: self.toggle_search()],
            ["sort", lambda x: self.open_sort_menu()],
            ["checkbox-multiple-marked-outline", lambda x: self.toggle_selection_mode()],
        ]

    # ---- Lifecycle -----------------------------------------------------

    def on_pre_enter(self, *args):
        self.refresh_documents()

    def refresh_documents(self):
        app = MDApp.get_running_app()
        documents = app.db.list_documents(search=self._search_query or None)
        documents = _sort_documents(documents, self._sort_key)
        self._documents = documents

        self.list_box.clear_widgets()
        for document in documents:
            self.list_box.add_widget(DocumentRow(document, controller=self))

        self.empty_label.opacity = 1 if not documents else 0
        self._update_bulk_bar()

    # ---- Search -----------------------------------------------------

    def toggle_search(self):
        showing = self.search_field.height > 0
        if showing:
            self.search_field.height = 0
            self.search_field.opacity = 0
            self.search_field.text = ""
            self._search_query = None
        else:
            self.search_field.height = dp(48)
            self.search_field.opacity = 1
        self.refresh_documents()

    def _on_search_text(self, value):
        self._search_query = value.strip() or None
        self.refresh_documents()

    # ---- Sort -----------------------------------------------------

    def open_sort_menu(self):
        items = [
            {"text": label, "on_release": lambda k=key: self._set_sort(k)}
            for key, label in SORT_OPTIONS.items()
        ]
        menu = MDDropdownMenu(caller=self.toolbar, items=items, width_mult=4)
        for item in items:
            original = item["on_release"]
            item["on_release"] = (lambda o=original, m=menu: (m.dismiss(), o()))
        menu.items = items
        menu.open()

    def _set_sort(self, key):
        self._sort_key = key
        self.refresh_documents()

    # ---- Selection mode -----------------------------------------------------

    def toggle_selection_mode(self):
        self.selection_mode = not self.selection_mode
        self.selected_ids = set()
        self.refresh_documents()

    def toggle_select(self, document_id):
        if document_id in self.selected_ids:
            self.selected_ids.discard(document_id)
        else:
            self.selected_ids.add(document_id)
        self.refresh_documents()

    def select_all(self):
        self.selected_ids = {d["id"] for d in self._documents}
        self.refresh_documents()

    def _update_bulk_bar(self):
        if self.selection_mode:
            self.bulk_bar.height = dp(56)
            self.bulk_bar.opacity = 1
            count = len(self.selected_ids)
            self.selection_label.text = "1 selected" if count == 1 else f"{count} selected"
        else:
            self.bulk_bar.height = 0
            self.bulk_bar.opacity = 0

    def delete_selected(self):
        if not self.selected_ids:
            return
        app = MDApp.get_running_app()
        count = len(self.selected_ids)

        def do_delete(*a):
            for doc_id in list(self.selected_ids):
                app.db.delete_document(doc_id)
            self.selected_ids = set()
            self.selection_mode = False
            dialog.dismiss()
            self.refresh_documents()

        dialog = MDDialog(
            title=f"Delete {count} document{'s' if count != 1 else ''}?",
            text="This cannot be undone.",
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="DELETE", on_release=do_delete),
            ],
        )
        dialog.open()

    # ---- Per-document actions (DocumentRow's overflow menu) -----------------------------------------------------

    def prompt_rename(self, document):
        app = MDApp.get_running_app()
        field = MDTextField(text=document["name"], hint_text="Document name")

        def do_rename(*a):
            new_name = field.text.strip()
            if new_name:
                app.db.rename_document(document["id"], new_name)
                self.refresh_documents()
            dialog.dismiss()

        dialog = MDDialog(
            title="Rename document", type="custom", content_cls=field,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="SAVE", on_release=do_rename),
            ],
        )
        dialog.open()

    def confirm_delete(self, document):
        app = MDApp.get_running_app()

        def do_delete(*a):
            app.db.delete_document(document["id"])
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

    def export_document(self, document):
        app = MDApp.get_running_app()
        pages = app.db.get_pages(document["id"])
        if not pages:
            return

        def choose(fmt):
            dialog.dismiss()
            self._run_export(document, pages, fmt)

        preferred = app.prefs.get("export_format")
        content = MDBoxLayout(orientation="horizontal", spacing="12dp",
                               size_hint_y=None, height="48dp")
        for label, fmt in [("PDF", "pdf"), ("JPG", "jpg"), ("PNG", "png")]:
            content.add_widget(MDFlatButton(
                text=label,
                theme_text_color="Custom",
                text_color=(0.20, 0.85, 0.35, 1) if fmt == preferred else (0, 0, 0, 0.87),
                on_release=lambda x, f=fmt: choose(f),
            ))

        dialog = MDDialog(
            title=f'Export "{document["name"]}"',
            type="custom",
            content_cls=content,
            buttons=[],
        )
        dialog.open()

    def _run_export(self, document, pages, fmt):
        import threading
        threading.Thread(target=self._do_export, args=(document, pages, fmt), daemon=True).start()

    def _do_export(self, document, pages, fmt):
        from pdf.export import export_to_pdf, export_to_image, export_to_images_zip

        app = MDApp.get_running_app()
        safe_name = "".join(c for c in document["name"] if c.isalnum() or c in " _-").strip() or "document"
        try:
            if fmt == "pdf":
                output_path = app.storage.get_export_path(f"{safe_name}.pdf")
                export_to_pdf(pages, output_path)
            elif len(pages) == 1:
                output_path = app.storage.get_export_path(f"{safe_name}.{fmt}")
                export_to_image(pages, output_path, fmt=fmt)
            else:
                output_path = app.storage.get_export_path(f"{safe_name}_{fmt}.zip")
                export_to_images_zip(pages, output_path, fmt=fmt)
            result = (True, output_path)
        except Exception as e:
            result = (False, str(e))

        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: self._on_export_done(*result), 0)

    def _on_export_done(self, success, path_or_error):
        from kivy.utils import platform
        if success:
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

    def _share_exported(self, dialog, file_path):
        dialog.dismiss()
        from storage.share import share_file
        try:
            share_file(file_path)
        except Exception as e:
            error_dialog = MDDialog(
                title="Share failed",
                text=str(e),
                buttons=[MDFlatButton(text="OK", on_release=lambda *a: error_dialog.dismiss())],
            )
            error_dialog.open()

    # ---- Open / navigation -----------------------------------------------------

    def run_ocr(self, document):
        app = MDApp.get_running_app()
        pages = app.db.get_pages(document["id"])
        if not pages:
            return

        from kivy.utils import platform

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
            self._on_ocr_done(success, payload)

        Clock.schedule_once(finish, 0)

    def _on_ocr_done(self, success, text_or_error):
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

    def open_document(self, document):
        app = MDApp.get_running_app()
        if app.active_session_pages:
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

    def _load_document_into_editor(self, document):
        app = MDApp.get_running_app()
        pages = app.db.get_pages(document["id"])
        app.active_session_pages = list(pages)
        app.editing_document_id = document["id"]
        app.latest_capture_path = pages[-1] if pages else None
        app.latest_raw_path = None
        app.go_to("editor")

    def go_home(self):
        MDApp.get_running_app().go_to("home")
