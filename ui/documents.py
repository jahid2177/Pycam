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

from kivy.properties import ObjectProperty, StringProperty
from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
from kivymd.uix.textfield import MDTextField
from kivymd.app import MDApp

from ui.navigation import BottomNavigationBar
from storage.localization import tr
from ui.home import (
    DocumentListItem,
    dismiss_open_menu,
)


class DocumentsScreen(MDScreen):
    showing_trash = False
    favorites_only = False
    active_folder = None
    active_tag = None
    active_type = None
    sort_by = "modified_desc"
    doc_list = ObjectProperty(None)
    empty_state = ObjectProperty(None)
    doc_count_label = ObjectProperty(None)
    bottom_nav_container = ObjectProperty(None)
    search_hint = StringProperty("Search documents")
    all_text = StringProperty("ALL")
    favorites_text = StringProperty("FAVORITES")
    folders_text = StringProperty("FOLDERS")
    trash_text = StringProperty("TRASH")
    filter_text = StringProperty("FILTER")
    bulk_text = StringProperty("BULK")
    empty_title = StringProperty("No documents yet")
    empty_subtitle = StringProperty("Scanned documents will show up here")

    def on_kv_post(self, base_widget):
        if self.bottom_nav_container and not self.bottom_nav_container.children:
            self.bottom_nav_container.add_widget(BottomNavigationBar(selected="documents"))

    def on_pre_enter(self, *args):
        self._apply_language()
        self.refresh_documents()

    def _apply_language(self):
        app = MDApp.get_running_app()
        lang = app.prefs.get("app_language") if getattr(app, "prefs", None) else "en"
        self.search_hint = tr("search_documents", lang, "Search documents")
        self.all_text = tr("all", lang, "ALL")
        self.favorites_text = tr("favorites", lang, "FAVORITES")
        self.folders_text = tr("folders", lang, "FOLDERS")
        self.trash_text = tr("trash", lang, "TRASH")
        self.filter_text = tr("filter", lang, "FILTER")
        self.bulk_text = tr("bulk", lang, "BULK")
        self.empty_title = tr("no_documents", lang, "No documents yet")
        self.empty_subtitle = tr("scans_show_here", lang, "Scanned documents will show up here")

    def refresh_documents(self, search_query: str = None):
        app = MDApp.get_running_app()
        documents = app.db.list_documents(
            search=search_query,
            include_deleted=self.showing_trash,
            favorites_only=self.favorites_only and not self.showing_trash,
            folder=self.active_folder if not self.showing_trash else None,
            tag=self.active_tag if not self.showing_trash else None,
            document_type=self.active_type if not self.showing_trash else None,
            sort_by=self.sort_by,
        )
        if self.showing_trash:
            documents = [d for d in documents if d.get("deleted_at")]
        total = len(documents) if (self.showing_trash or self.favorites_only or self.active_folder is not None) else app.db.count_documents()

        lang = app.prefs.get("app_language") if getattr(app, "prefs", None) else "en"
        unit = tr("document", lang, "document") if total == 1 else tr("documents", lang, "documents")
        self.doc_count_label.text = f"{total} {unit}"

        self.doc_list.clear_widgets()
        self.empty_state.opacity = 1 if not documents else 0
        self.empty_state.disabled = bool(documents)
        from kivy.metrics import dp
        self.empty_state.height = dp(240) if not documents else 0

        for document in documents:
            item = DocumentListItem(document=document, controller=self, search_query=search_query)
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
        if document.get("protected"):
            from ui.app_lock import request_pin
            request_pin("Protected document", lambda: self._open_document_unlocked(document))
            return
        self._open_document_unlocked(document)

    def _open_document_unlocked(self, document: dict):
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
        if document.get("protected"):
            from storage.private_vault import materialize_document_pages
            pages, temp_root = materialize_document_pages(app, document["id"])
            app.private_unlock_temp = temp_root
        else:
            pages = app.db.get_pages(document["id"])
            app.private_unlock_temp = None
        app.active_session_pages = list(pages)
        app.editing_document_id = document["id"]
        app.latest_capture_path = pages[-1] if pages else None
        app.latest_raw_path = None
        try:
            app.set_sensitive_content(bool(document.get("protected")))
        except Exception:
            pass
        app.go_to("editor")

    # ---- Item actions --------------------------------------------------

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
            try:
                from storage.private_vault import protect_document, unprotect_document
                if target:
                    protect_document(app, document["id"])
                else:
                    unprotect_document(app, document["id"])
                self.refresh_documents()
            except Exception as exc:
                from kivymd.uix.button import MDFlatButton
                dialog = MDDialog(
                    title="Private folder error",
                    text=str(exc),
                    buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())],
                )
                dialog.open()
        request_pin("Protect document" if target else "Unprotect document", apply)

    def prompt_folder(self, document: dict):
        dismiss_open_menu()
        field = MDTextField(text=document.get("folder") or "", hint_text="Folder name (blank = no folder)")
        from kivymd.uix.button import MDFlatButton
        def save(*_):
            MDApp.get_running_app().db.set_folder(document["id"], field.text)
            dialog.dismiss(); self.refresh_documents()
        dialog = MDDialog(title="Move to folder", type="custom", content_cls=field,
            buttons=[MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()), MDFlatButton(text="SAVE", on_release=save)])
        dialog.open()

    def prompt_tags(self, document: dict):
        dismiss_open_menu()
        field = MDTextField(text=", ".join(document.get("tags") or []), hint_text="Tags separated by commas")
        from kivymd.uix.button import MDFlatButton
        def save(*_):
            tags=[x.strip() for x in field.text.split(",") if x.strip()]
            MDApp.get_running_app().db.set_tags(document["id"], tags)
            dialog.dismiss(); self.refresh_documents()
        dialog = MDDialog(title="Edit tags", type="custom", content_cls=field,
            buttons=[MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()), MDFlatButton(text="SAVE", on_release=save)])
        dialog.open()

    def show_all(self):
        self.showing_trash=False; self.favorites_only=False; self.active_folder=None; self.active_tag=None; self.active_type=None; self.refresh_documents()

    def show_favorites(self):
        self.showing_trash=False; self.favorites_only=True; self.active_folder=None; self.active_tag=None; self.active_type=None; self.refresh_documents()

    def show_trash(self):
        self.showing_trash=True; self.favorites_only=False; self.active_folder=None; self.active_tag=None; self.active_type=None; self.refresh_documents()

    def show_folder_dialog(self):
        app=MDApp.get_running_app(); folders=app.db.list_folders()
        from kivymd.uix.button import MDFlatButton
        from kivymd.uix.boxlayout import MDBoxLayout
        box=MDBoxLayout(orientation="vertical", adaptive_height=True, spacing="4dp")
        if not folders:
            from kivymd.uix.label import MDLabel
            box.add_widget(MDLabel(text="No folders yet", size_hint_y=None, height="36dp"))
        for name in folders:
            box.add_widget(MDFlatButton(text=name, on_release=lambda _, n=name: self._select_folder(dialog, n)))
        dialog=MDDialog(title="Folders", type="custom", content_cls=box,
            buttons=[MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss())])
        dialog.open()

    def _select_folder(self, dialog, name):
        dialog.dismiss(); self.showing_trash=False; self.favorites_only=False; self.active_folder=name; self.active_tag=None; self.active_type=None; self.refresh_documents()

    def restore_document(self, document):
        MDApp.get_running_app().db.restore_document(document["id"]); self.refresh_documents()

    def permanent_delete(self, document):
        MDApp.get_running_app().db.permanent_delete_document(document["id"]); self.refresh_documents()

    def show_filter_dialog(self):
        app = MDApp.get_running_app()
        from kivymd.uix.button import MDFlatButton
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel

        box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing="4dp")
        box.add_widget(MDLabel(text="Sort", bold=True, size_hint_y=None, height="34dp"))
        sort_options = [
            ("Newest modified", "modified_desc"),
            ("Oldest modified", "modified_asc"),
            ("Name A–Z", "name_asc"),
            ("Name Z–A", "name_desc"),
            ("Most pages", "pages_desc"),
            ("Largest size", "size_desc"),
            ("Smallest size", "size_asc"),
            ("Newest created", "created_desc"),
        ]
        for label, key in sort_options:
            box.add_widget(MDFlatButton(text=label, on_release=lambda _, k=key: self._apply_sort(dialog, k)))

        tags = app.db.list_tags()
        if tags:
            box.add_widget(MDLabel(text="Tags", bold=True, size_hint_y=None, height="34dp"))
            for tag in tags[:10]:
                box.add_widget(MDFlatButton(text=f"#{tag}", on_release=lambda _, t=tag: self._apply_tag(dialog, t)))

        types = app.db.list_document_types()
        if types:
            box.add_widget(MDLabel(text="Document type", bold=True, size_hint_y=None, height="34dp"))
            for dtype in types[:10]:
                box.add_widget(MDFlatButton(text=dtype, on_release=lambda _, t=dtype: self._apply_type(dialog, t)))

        box.add_widget(MDFlatButton(text="CLEAR FILTERS", on_release=lambda *_: self._clear_filters(dialog)))
        dialog = MDDialog(
            title="Sort & Filter",
            type="custom",
            content_cls=box,
            buttons=[MDFlatButton(text="CLOSE", on_release=lambda *_: dialog.dismiss())],
        )
        dialog.open()

    def _apply_sort(self, dialog, key):
        self.sort_by = key
        dialog.dismiss()
        self.refresh_documents()

    def _apply_tag(self, dialog, tag):
        self.showing_trash = False
        self.active_tag = tag
        dialog.dismiss()
        self.refresh_documents()

    def _apply_type(self, dialog, document_type):
        self.showing_trash = False
        self.active_type = document_type
        dialog.dismiss()
        self.refresh_documents()

    def _clear_filters(self, dialog=None):
        self.showing_trash = False
        self.favorites_only = False
        self.active_folder = None
        self.active_tag = None
        self.active_type = None
        self.sort_by = "modified_desc"
        if dialog:
            dialog.dismiss()
        self.refresh_documents()

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

    def duplicate_document(self, document: dict):
        """Create an independent copy of a saved document and its page files."""
        dismiss_open_menu()
        import os
        import shutil
        app = MDApp.get_running_app()
        pages = app.db.get_pages(document["id"])
        if not pages:
            return

        base_name = (document.get("name") or "Document").strip()
        new_name = f"{base_name} Copy"
        first = pages[0]
        new_id = app.db.create_document(
            name=new_name,
            file_path=first,
            page_count=len(pages),
            thumbnail_path=None,
            ocr_text=document.get("ocr_text"),
            document_type=document.get("document_type") or "document",
            pages=pages,
        )
        try:
            target_dir = app.storage.get_document_dir(new_id)
            copied = []
            for idx, src in enumerate(pages, start=1):
                ext = os.path.splitext(src)[1].lower() or ".jpg"
                dst = os.path.join(target_dir, f"page_{idx:03d}{ext}")
                shutil.copy2(src, dst)
                copied.append(dst)
            app.db.update_pages(new_id, copied)
            app.db.copy_metadata(document["id"], new_id)
            thumb_src = document.get("thumbnail_path")
            if thumb_src and os.path.isfile(thumb_src):
                thumb_dst = app.storage.get_thumbnail_path(new_id)
                shutil.copy2(thumb_src, thumb_dst)
            self.refresh_documents()
            from kivymd.uix.button import MDFlatButton
            dialog = MDDialog(
                title="Document duplicated",
                text=f'Created "{new_name}".',
                buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())],
            )
            dialog.open()
        except Exception as exc:
            try:
                app.db.permanent_delete_document(new_id)
            except Exception:
                pass
            from kivymd.uix.button import MDFlatButton
            dialog = MDDialog(
                title="Duplicate failed",
                text=str(exc),
                buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())],
            )
            dialog.open()

    def show_bulk_actions(self):
        """Select multiple documents for favorite, trash, or ZIP export."""
        app = MDApp.get_running_app()
        documents = app.db.list_documents(
            favorites_only=self.favorites_only,
            folder=self.active_folder,
            tag=self.active_tag,
            document_type=self.active_type,
            sort_by=self.sort_by,
        )
        if not documents:
            from kivymd.uix.button import MDFlatButton
            dialog = MDDialog(
                title="Bulk actions",
                text="No active documents are available to select.",
                buttons=[MDFlatButton(text="OK", on_release=lambda *_: dialog.dismiss())],
            )
            dialog.open()
            return

        from kivy.metrics import dp
        from kivy.uix.scrollview import ScrollView
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDFlatButton
        from kivymd.uix.selectioncontrol import MDCheckbox
        from kivymd.uix.label import MDLabel

        selected = set()
        root = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(360), spacing=dp(4))
        count_label = MDLabel(text="0 selected", size_hint_y=None, height=dp(34), theme_text_color="Secondary")
        root.add_widget(count_label)
        scroll = ScrollView(do_scroll_x=False)
        rows = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(2))
        scroll.add_widget(rows)
        root.add_widget(scroll)

        def toggle(doc_id, checkbox, active):
            if active:
                selected.add(doc_id)
            else:
                selected.discard(doc_id)
            count_label.text = f"{len(selected)} selected"

        for doc in documents:
            row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(6))
            cb = MDCheckbox(size_hint=(None, None), size=(dp(40), dp(40)))
            cb.bind(active=lambda checkbox, active, did=doc["id"]: toggle(did, checkbox, active))
            label = MDLabel(text=doc["name"], shorten=True, shorten_from="right")
            row.add_widget(cb)
            row.add_widget(label)
            rows.add_widget(row)

        def chosen_docs():
            return [d for d in documents if d["id"] in selected]

        def require_selection(action):
            docs = chosen_docs()
            if not docs:
                count_label.text = "Select at least one document"
                return
            dialog.dismiss()
            action(docs)

        dialog = MDDialog(
            title="Bulk actions",
            type="custom",
            content_cls=root,
            buttons=[
                MDFlatButton(text="FAVORITE", on_release=lambda *_: require_selection(self._bulk_favorite)),
                MDFlatButton(text="TRASH", on_release=lambda *_: require_selection(self._bulk_trash)),
                MDFlatButton(text="EXPORT ZIP", on_release=lambda *_: require_selection(self._bulk_export_zip)),
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
            ],
        )
        dialog.open()

    def _bulk_favorite(self, documents):
        app = MDApp.get_running_app()
        for doc in documents:
            app.db.set_favorite(doc["id"], True)
        self.refresh_documents()

    def _bulk_trash(self, documents):
        def apply():
            app = MDApp.get_running_app()
            for doc in documents:
                app.db.move_to_trash(doc["id"])
            self.refresh_documents()

        if any(doc.get("protected") for doc in documents):
            from ui.app_lock import request_pin
            request_pin("Protected documents", apply)
        else:
            apply()

    def _bulk_export_zip(self, documents):
        def start_export():
            import threading
            threading.Thread(target=self._do_bulk_export_zip, args=(documents,), daemon=True).start()

        if any(doc.get("protected") for doc in documents):
            from ui.app_lock import request_pin
            request_pin("Protected documents", start_export)
        else:
            start_export()

    def _do_bulk_export_zip(self, documents):
        import os
        import re
        import zipfile
        from datetime import datetime
        app = MDApp.get_running_app()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = app.storage.get_export_path(f"Documents_{stamp}.zip")
        used_folders = set()
        try:
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for doc in documents:
                    base = re.sub(r"[^A-Za-z0-9 _.-]+", "_", doc.get("name") or "Document").strip() or "Document"
                    folder = base
                    counter = 2
                    while folder.lower() in used_folders:
                        folder = f"{base}_{counter}"
                        counter += 1
                    used_folders.add(folder.lower())
                    cleanup_root = None
                    if doc.get("protected"):
                        from storage.private_vault import materialize_document_pages
                        pages, cleanup_root = materialize_document_pages(app, doc["id"])
                    else:
                        pages = app.db.get_pages(doc["id"])
                    try:
                        for idx, src in enumerate(pages, start=1):
                            if not src or not os.path.isfile(src):
                                continue
                            ext = os.path.splitext(src)[1].lower() or ".jpg"
                            zf.write(src, arcname=f"{folder}/page_{idx:03d}{ext}")
                    finally:
                        if cleanup_root:
                            from storage.private_vault import cleanup_materialized
                            cleanup_materialized(cleanup_root)
                    metadata = (
                        f"Name: {doc.get('name','')}\n"
                        f"Pages: {len(pages)}\n"
                        f"Type: {doc.get('document_type','document')}\n"
                        f"Folder: {doc.get('folder','')}\n"
                        f"Tags: {', '.join(doc.get('tags') or [])}\n"
                    )
                    zf.writestr(f"{folder}/document-info.txt", metadata)
            result = (True, output_path)
        except Exception as exc:
            result = (False, str(exc))
        from kivy.clock import Clock
        Clock.schedule_once(lambda _dt: self._on_export_done(*result), 0)

    def confirm_delete(self, document: dict):
        dismiss_open_menu()
        if self.showing_trash:
            self._show_trash_actions(document)
            return
        from kivymd.uix.button import MDFlatButton

        def do_delete(*args):
            MDApp.get_running_app().db.delete_document(document["id"])
            self.refresh_documents()
            dialog.dismiss()

        dialog = MDDialog(
            title="Move document to Trash?",
            text=f'"{document["name"]}" can be restored later.',
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="MOVE TO TRASH", on_release=do_delete),
            ],
        )
        dialog.open()

    def _show_trash_actions(self, document):
        from kivymd.uix.button import MDFlatButton
        dialog = MDDialog(
            title="Trash",
            text=f'Choose what to do with "{document["name"]}".',
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="RESTORE", on_release=lambda *_: (dialog.dismiss(), self.restore_document(document))),
                MDFlatButton(text="DELETE FOREVER", on_release=lambda *_: (dialog.dismiss(), self.permanent_delete(document))),
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
        cleanup_root = None
        if document.get("protected"):
            from storage.private_vault import materialize_document_pages
            pages, cleanup_root = materialize_document_pages(app, document["id"])
        else:
            pages = app.db.get_pages(document["id"])
        if not pages:
            return

        from ui.export_options import show_export_dialog

        show_export_dialog(
            title=f'Export "{document["name"]}"',
            preferred_format=app.prefs.get("export_format"),
            callback=lambda fmt, options: self._run_export(document, pages, fmt, options, cleanup_root),
        )

    def _run_export(self, document, pages, fmt, options, cleanup_root=None):
        import threading

        threading.Thread(
            target=self._do_export,
            args=(document, pages, fmt, options, cleanup_root),
            daemon=True,
        ).start()

    def _do_export(self, document, pages, fmt, options, cleanup_root=None):
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
                    searchable=bool(options.get("searchable", False)),
                    ocr_language=app.prefs.get("ocr_language") or "english",
                )
            elif len(pages) == 1:
                output_path = app.storage.get_export_path(f"{safe_name}.{fmt}")
                export_to_image(pages, output_path, fmt=fmt, quality=quality)
            else:
                output_path = app.storage.get_export_path(f"{safe_name}_{fmt}.zip")
                export_to_images_zip(pages, output_path, fmt=fmt, quality=quality)

            try:
                self._last_external_export = app.storage.publish_export(output_path, app.prefs)
                self._last_external_export_error = None
            except Exception as publish_exc:
                self._last_external_export = None
                self._last_external_export_error = str(publish_exc)

            result = (True, output_path)

        except Exception as exc:
            result = (False, str(exc))

        if cleanup_root:
            try:
                from storage.private_vault import cleanup_materialized
                cleanup_materialized(cleanup_root)
            except Exception:
                pass

        from kivy.clock import Clock

        Clock.schedule_once(lambda dt: self._on_export_done(*result), 0)

    def run_ocr(self, document: dict):
        dismiss_open_menu()
        if document.get("protected"):
            from ui.app_lock import request_pin
            request_pin("Protected document", lambda: self._run_ocr_unlocked(document))
            return
        self._run_ocr_unlocked(document)

    def _run_ocr_unlocked(self, document: dict):
        app = MDApp.get_running_app()
        cleanup_root = None
        if document.get("protected"):
            from storage.private_vault import materialize_document_pages
            pages, cleanup_root = materialize_document_pages(app, document["id"])
        else:
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
            self._run_ocr_language(document, pages, language, cleanup_root)

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

    def _run_ocr_language(self, document, pages, language, cleanup_root=None):
        import threading
        threading.Thread(
            target=self._do_ocr, args=(document, pages, language, cleanup_root), daemon=True
        ).start()

    def _do_ocr(self, document, pages, language, cleanup_root=None):
        from ocr.ocr_manager import run_ocr_for_pages

        app = MDApp.get_running_app()
        try:
            text = run_ocr_for_pages(pages, language)
            result = (True, text)
        except Exception as e:
            result = (False, str(e))

        if cleanup_root:
            try:
                from storage.private_vault import cleanup_materialized
                cleanup_materialized(cleanup_root)
            except Exception:
                pass

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
