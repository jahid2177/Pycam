"""
Multi-page editor - manages the pages of an in-progress scanning
session (`app.active_session_pages`): reorder (move left/right, no
drag-and-drop yet), rotate, delete, and add more pages. "Save Document"
either creates a new document, or - as of step 10 - updates a saved
one that was reopened via HomeScreen.open_document (tracked by
`app.editing_document_id`).

Known limitation worth being upfront about: rotate writes to the page
file immediately (see image_processing.filters.rotate_image_file),
while reorder/delete only change the in-memory page list until "Save"
is pressed. So leaving this screen without saving discards a delete or
reorder, but NOT a rotate - the rotated file is already on disk either
way. Building a full copy-on-write staging system to make rotate
undoable too would mean duplicating image files during every edit
session; not worth the complexity at this stage, but worth documenting
rather than leaving as a silent surprise.

Built entirely in Python (like ui/crop.py) rather than a .kv file,
since the thumbnail row's contents are dynamic and rebuilt on every
change - there's no static layout for a .kv rule to describe.
"""

import threading
from datetime import datetime

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.scrollview import ScrollView
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton, MDFlatButton
from kivymd.uix.label import MDLabel
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.textfield import MDTextField
from kivymd.uix.dialog import MDDialog
from kivymd.app import MDApp

from image_processing.filters import rotate_image_file

THUMB_SIZE = dp(140)


class PageCard(MDBoxLayout):
    """One page's thumbnail plus its per-page controls. Index-based -
    `editor.move_left(self.index)` etc. rather than holding a reference
    to the page path, so it stays correct even after the list is
    reordered and this card gets rebuilt with new content."""

    def __init__(self, index, path, page_count, editor, **kwargs):
        super().__init__(orientation="vertical", size_hint=(None, None),
                          size=(THUMB_SIZE, THUMB_SIZE + dp(56)), spacing=dp(4), **kwargs)
        self.index = index
        self.editor = editor

        self.image_widget = Image(
            source=path, allow_stretch=True, keep_ratio=True,
            size_hint=(None, None), size=(THUMB_SIZE, THUMB_SIZE),
        )
        self.add_widget(self.image_widget)

        label = MDLabel(
            text=f"Page {index + 1}",
            halign="center",
            theme_text_color="Secondary",
            font_style="Caption",
            size_hint=(1, None),
            height=dp(18),
        )
        self.add_widget(label)

        controls = MDBoxLayout(orientation="horizontal", size_hint=(1, None), height=dp(36))
        controls.add_widget(MDIconButton(
            icon="chevron-left", disabled=index == 0,
            on_release=lambda x: editor.move_left(self.index),
        ))
        controls.add_widget(MDIconButton(
            icon="rotate-right-variant",
            on_release=lambda x: editor.rotate_page(self.index),
        ))
        controls.add_widget(MDIconButton(
            icon="delete-outline",
            on_release=lambda x: editor.delete_page(self.index),
        ))
        controls.add_widget(MDIconButton(
            icon="chevron-right", disabled=index == page_count - 1,
            on_release=lambda x: editor.move_right(self.index),
        ))
        self.add_widget(controls)

    def reload_image(self):
        self.image_widget.reload()


class AddPageCard(MDBoxLayout):
    def __init__(self, editor, **kwargs):
        super().__init__(
            orientation="vertical", size_hint=(None, None),
            size=(THUMB_SIZE, THUMB_SIZE + dp(56)), **kwargs
        )
        button = MDIconButton(
            icon="plus",
            size_hint=(None, None),
            size=(THUMB_SIZE, THUMB_SIZE),
            on_release=lambda x: editor.add_page(),
        )
        self.add_widget(button)
        self.add_widget(MDLabel(text="Add page", halign="center", font_style="Caption"))


class EditorScreen(MDScreen):
    """Owns the toolbar/empty-state/save-flow; page cards are rebuilt
    from `app.active_session_pages` on every structural change (add,
    delete, reorder) rather than diffed in place - with a handful of
    pages this is simpler and plenty fast."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._busy = False

        root = MDBoxLayout(orientation="vertical")

        self.toolbar = MDTopAppBar(title="Pages", elevation=2)
        self.toolbar.left_action_items = [["arrow-left", lambda x: self.go_home()]]
        root.add_widget(self.toolbar)

        scroll = ScrollView(do_scroll_y=False, size_hint=(1, 1))
        self.page_row = MDBoxLayout(
            orientation="horizontal", spacing=dp(12), padding=dp(16),
            size_hint=(None, 1), adaptive_width=True,
        )
        scroll.add_widget(self.page_row)
        root.add_widget(scroll)

        self.empty_label = MDLabel(
            text="No pages yet - scan your first page to start a document",
            halign="center", theme_text_color="Hint", opacity=0,
        )
        root.add_widget(self.empty_label)

        bottom_bar = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(72),
            padding=(dp(16), dp(8)), spacing=dp(12),
        )
        self.page_count_label = MDLabel(text="0 pages", theme_text_color="Secondary")
        bottom_bar.add_widget(self.page_count_label)
        bottom_bar.add_widget(Widget())
        self.save_button = MDRaisedButton(text="SAVE DOCUMENT", on_release=lambda x: self.save_document())
        bottom_bar.add_widget(self.save_button)
        root.add_widget(bottom_bar)

        self.add_widget(root)

    # ---- Lifecycle -----------------------------------------------------

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        if app.editing_document_id is not None:
            doc = app.db.get_document(app.editing_document_id)
            self.toolbar.title = doc["name"] if doc else "Edit Document"
        else:
            self.toolbar.title = "New Document"
        self.refresh_pages()

    def refresh_pages(self):
        app = MDApp.get_running_app()
        pages = app.active_session_pages
        self.page_row.clear_widgets()

        for i, path in enumerate(pages):
            self.page_row.add_widget(PageCard(i, path, len(pages), self))
        self.page_row.add_widget(AddPageCard(self))

        self.page_count_label.text = "1 page" if len(pages) == 1 else f"{len(pages)} pages"
        self.empty_label.opacity = 1 if not pages else 0
        self.save_button.disabled = not pages or self._busy

    # ---- Page actions -----------------------------------------------------

    def move_left(self, index):
        app = MDApp.get_running_app()
        pages = app.active_session_pages
        if index <= 0 or index >= len(pages):
            return
        pages[index - 1], pages[index] = pages[index], pages[index - 1]
        self.refresh_pages()

    def move_right(self, index):
        app = MDApp.get_running_app()
        pages = app.active_session_pages
        if index < 0 or index >= len(pages) - 1:
            return
        pages[index + 1], pages[index] = pages[index], pages[index + 1]
        self.refresh_pages()

    def delete_page(self, index):
        app = MDApp.get_running_app()
        pages = app.active_session_pages

        def do_delete(*a):
            if 0 <= index < len(pages):
                pages.pop(index)
            self.refresh_pages()
            dialog.dismiss()

        dialog = MDDialog(
            title="Delete this page?",
            text="This page will be removed from the document.",
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="DELETE", on_release=do_delete),
            ],
        )
        dialog.open()

    def rotate_page(self, index):
        app = MDApp.get_running_app()
        pages = app.active_session_pages
        if not (0 <= index < len(pages)):
            return
        path = pages[index]
        self._set_busy(True)
        threading.Thread(target=self._run_rotate, args=(path, index), daemon=True).start()

    def _run_rotate(self, path, index):
        try:
            rotate_image_file(path, clockwise=True)
        except Exception:
            pass  # leave the page as-is rather than crash the editor over one bad rotate
        Clock.schedule_once(lambda dt: self._on_rotate_done(index), 0)

    def _on_rotate_done(self, index):
        self._set_busy(False)
        # Re-render just the affected card's texture rather than a full
        # rebuild, so the row doesn't jump/re-scroll after a rotate.
        for card in self.page_row.children:
            if isinstance(card, PageCard) and card.index == index:
                card.reload_image()
                break

    def add_page(self):
        MDApp.get_running_app().go_to("scanner")

    def go_home(self):
        MDApp.get_running_app().go_to("home")

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.save_button.disabled = busy or not MDApp.get_running_app().active_session_pages

    # ---- Save -----------------------------------------------------

    def save_document(self):
        app = MDApp.get_running_app()
        if not app.active_session_pages or self._busy:
            return

        if app.editing_document_id is not None:
            existing = app.db.get_document(app.editing_document_id)
            default_name = existing["name"] if existing else "Untitled"
        else:
            default_name = f"Scan {datetime.now().strftime('%b %d, %Y %H:%M')}"

        field = MDTextField(text=default_name, hint_text="Document name")

        def do_save(*a):
            name = field.text.strip() or default_name
            dialog.dismiss()
            self._save_with_name(name)

        dialog = MDDialog(
            title="Save document",
            type="custom",
            content_cls=field,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dialog.dismiss()),
                MDFlatButton(text="SAVE", on_release=do_save),
            ],
        )
        dialog.open()

    def _save_with_name(self, name: str):
        app = MDApp.get_running_app()
        pages = list(app.active_session_pages)

        if app.editing_document_id is not None:
            app.db.update_pages(app.editing_document_id, pages)
            app.db.rename_document(app.editing_document_id, name)
        else:
            app.db.create_document(
                name=name,
                file_path=pages[0],
                page_count=len(pages),
                thumbnail_path=pages[0],
                pages=pages,
            )

        app.active_session_pages = []
        app.editing_document_id = None
        app.latest_capture_path = None
        app.latest_raw_path = None
        app.go_to("home")
