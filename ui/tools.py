from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.textfield import MDTextField

from storage.localization import tr
from storage.accessibility import label_widget, ensure_touch_target

from ui.navigation import BottomNavigationBar


ACCENTS = [
    (0.12, 0.76, 0.66, 1),
    (0.10, 0.62, 0.46, 1),
    (0.23, 0.52, 0.95, 1),
    (0.38, 0.34, 0.88, 1),
    (0.10, 0.67, 0.60, 1),
    (0.04, 0.58, 0.80, 1),
    (0.95, 0.25, 0.55, 1),
]

TOOL_SECTIONS = [
    ("scan", [
        ("card-account-details-outline", "tool_id_cards", "id_cards"),
        ("card-text-outline", "tool_nid_ocr", "nid_intelligence"),
        ("passport", "tool_passport_mrz", "passport_mrz"),
        ("text-recognition", "tool_extract_text", "extract_text"),
        ("account-box-outline", "tool_passport_photo", "passport_photo"),
        ("translate", "tool_photo_translation", "photo_translation"),
        ("qrcode-scan", "tool_scan_code", "scan_code"),
        ("book-open-page-variant", "tool_book_mode", "book_mode"),
    ]),
    ("convert", [
        ("merge", "tool_merge_pdf", "merge_pdf"),
        ("image-outline", "tool_image_to_pdf", "image_to_pdf"),
        ("file-document-edit-outline", "tool_text_to_pdf", "text_to_pdf"),
        ("file-word-outline", "tool_to_word", "to_word"),
        ("file-word-box-outline", "tool_pdf_to_word", "pdf_to_word"),
        ("microsoft-excel", "tool_to_excel", "to_excel"),
        ("image-multiple-outline", "tool_pdf_images", "pdf_to_images"),
        ("image-size-select-large", "tool_pdf_long", "pdf_long_image"),
    ]),
    ("edit", [
        ("crop-free", "tool_opencv_crop", "opencv_crop"), ("auto-fix", "tool_bg_remove", "bg_remover"),
        ("crop", "tool_resize", "image_resizer"), ("eraser", "tool_smart_erase", "smart_erase"),
        ("call-split", "tool_split_pdf", "split_pdf"), ("draw-pen", "tool_sign", "sign"),
        ("watermark", "tool_watermark", "watermark"), ("file-export-outline", "tool_extract_pages", "extract_pages"),
        ("swap-vertical", "tool_reorder_pages", "reorder_pages"), ("rotate-right", "tool_rotate_pdf", "rotate_pdf"),
        ("lock-outline", "tool_lock", "lock_pdf"), ("lock-open-variant-outline", "tool_unlock", "unlock_pdf"),
        ("file-remove-outline", "tool_remove_pages", "remove_pages"), ("file-plus-outline", "tool_insert_pages", "insert_pages"),
        ("format-list-numbered", "tool_page_numbers", "page_numbers"), ("page-layout-header-footer", "tool_header_footer", "header_footer"),
        ("file-cog-outline", "tool_metadata", "pdf_metadata"), ("layers-triple-outline", "tool_flatten", "flatten_pdf"),
        ("arrow-collapse-vertical", "tool_compress", "compress_pdf"),
    ]),
    ("utilities", [
        ("head-cog-outline", "tool_ai_chat", "ai_chat"), ("printer-outline", "tool_print", "print"),
        ("qrcode", "tool_create_qr", "create_qr"),
    ]),
]



class ToolTile(MDBoxLayout):
    def __init__(self, icon, title, key, controller, accent, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(126),
            padding=(dp(3), dp(4)),
            spacing=dp(3),
            **kwargs,
        )

        icon_wrap = MDCard(
            orientation="vertical",
            size_hint=(None, None),
            size=(dp(62), dp(62)),
            radius=[dp(31)],
            elevation=0,
            md_bg_color=(accent[0], accent[1], accent[2], 0.10),
            line_color=(accent[0], accent[1], accent[2], 0.20),
            pos_hint={"center_x": 0.5},
        )
        button = MDIconButton(
            icon=icon,
            theme_text_color="Custom",
            text_color=accent,
            user_font_size="29sp",
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            on_release=lambda *_: controller.open_tool(key, title.replace("\n", " ")),
        )
        label_widget(button, title.replace("\n", " "), "button")
        ensure_touch_target(button)
        icon_wrap.add_widget(button)
        self.add_widget(icon_wrap)

        self.add_widget(
            MDLabel(
                text=title,
                halign="center",
                valign="top",
                theme_text_color="Custom",
                text_color=(0.22, 0.27, 0.34, 1),
                font_style="Caption",
            )
        )


class ToolsScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        app = MDApp.get_running_app()
        self.language = app.prefs.get("app_language") if getattr(app, "prefs", None) else "en"

        root = MDBoxLayout(
            orientation="vertical",
            md_bg_color=(0.97, 0.98, 1, 1),
        )

        toolbar = MDTopAppBar(
            title=tr("tools", self.language, "Tools"),
            elevation=0,
            md_bg_color=(0.97, 0.98, 1, 1),
            specific_text_color=(0.05, 0.09, 0.17, 1),
        )
        toolbar.right_action_items = [
            ["magnify", lambda *_: self._show_search_message()]
        ]
        root.add_widget(toolbar)

        tab_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            padding=(dp(8), 0),
        )
        for index, (section_key, _) in enumerate(TOOL_SECTIONS):
            title = tr(section_key, self.language, section_key.title())
            tab_row.add_widget(
                MDFlatButton(
                    text=title,
                    theme_text_color="Custom",
                    text_color=(0.05, 0.12, 0.20, 1)
                    if index == 0
                    else (0.42, 0.47, 0.55, 1),
                )
            )
        root.add_widget(tab_row)

        scroll = ScrollView(do_scroll_x=False)
        content = MDBoxLayout(
            orientation="vertical",
            adaptive_height=True,
            padding=(dp(16), dp(8), dp(16), dp(18)),
            spacing=dp(10),
        )

        accent_index = 0
        for section_key, tools in TOOL_SECTIONS:
            section_title = tr(section_key, self.language, section_key.title())
            content.add_widget(
                MDLabel(
                    text=section_title,
                    font_style="H6",
                    bold=True,
                    size_hint_y=None,
                    height=dp(42),
                    theme_text_color="Custom",
                    text_color=(0.05, 0.09, 0.17, 1),
                )
            )

            grid = GridLayout(
                cols=4,
                size_hint_y=None,
                spacing=(dp(5), dp(5)),
            )
            rows = (len(tools) + 3) // 4
            grid.height = rows * dp(126)

            for icon, title_key, key in tools:
                title = tr(title_key, self.language, title_key)
                accent = ACCENTS[accent_index % len(ACCENTS)]
                accent_index += 1
                grid.add_widget(
                    ToolTile(
                        icon=icon,
                        title=title,
                        key=key,
                        controller=self,
                        accent=accent,
                    )
                )

            # Fill the last row so every tile keeps the same width.
            for _ in range((4 - (len(tools) % 4)) % 4):
                grid.add_widget(MDBoxLayout())

            content.add_widget(grid)

        scroll.add_widget(content)
        root.add_widget(scroll)
        root.add_widget(BottomNavigationBar(selected="tools"))
        self.add_widget(root)

    def open_tool(self, key, title):
        app = MDApp.get_running_app()

        if key in ("id_cards", "book_mode"):
            app.active_session_pages = []
            app.latest_capture_path = None
            app.latest_raw_path = None
            app.editing_document_id = None

            scanner = app.screen_manager.get_screen("scanner")
            if key == "id_cards":
                scanner.scan_type = "id_card"
                scanner.capture_mode = "batch"
            else:
                scanner.scan_type = "book"
                scanner.capture_mode = "single"
            app.go_to("scanner")
            return

        workflow_screens = {
            "nid_intelligence": "nid_intelligence_tool",
            "passport_mrz": "passport_mrz_tool",
            "extract_text": "extract_text_tool",
            "passport_photo": "passport_photo_tool",
            "photo_translation": "photo_translation_tool",
            "scan_code": "scan_code_tool",
            "merge_pdf": "merge_pdf_tool",
            "image_to_pdf": "image_to_pdf_tool",
            "text_to_pdf": "text_to_pdf_tool",
            "to_word": "to_word_tool",
            "pdf_to_word": "pdf_to_word_tool",
            "to_excel": "to_excel_tool",
            "pdf_to_images": "pdf_to_images_tool",
            "pdf_long_image": "pdf_long_image_tool",
            "bg_remover": "bg_remover_tool",
            "image_resizer": "image_resizer_tool",
            "smart_erase": "smart_erase_tool",
            "split_pdf": "split_pdf_tool",
            "sign": "sign_tool",
            "watermark": "watermark_tool",
            "extract_pages": "extract_pages_tool",
            "reorder_pages": "reorder_pages_tool",
            "rotate_pdf": "rotate_pdf_tool",
            "lock_pdf": "lock_pdf_tool",
            "unlock_pdf": "unlock_pdf_tool",
            "remove_pages": "remove_pages_tool",
            "insert_pages": "insert_pages_tool",
            "page_numbers": "page_numbers_tool",
            "header_footer": "header_footer_tool",
            "pdf_metadata": "pdf_metadata_tool",
            "flatten_pdf": "flatten_pdf_tool",
            "compress_pdf": "compress_pdf_tool",
            "create_qr": "create_qr_tool",
        }

        if key in workflow_screens:
            app.go_to(workflow_screens[key])
            return

        if key == "opencv_crop":
            if app.active_session_pages:
                app.crop_source_path = app.active_session_pages[-1]
                app.go_to("crop")
            else:
                self._info(
                    "OpenCV Crop",
                    "Scan or import an image first, then use OpenCV Crop.",
                )
            return

        if key == "ai_chat":
            app.go_to("ai_chat")
            return
        if key == "print":
            app.go_to("print_tool")
            return
        self._info(title, f"{title} is not available in this build yet.")

    def _show_search_message(self):
        field = MDTextField(hint_text=tr("tool_search_hint", self.language, "Type a tool name"), mode="rectangle")
        results = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(2))
        wrapper = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(8))
        wrapper.add_widget(field)
        wrapper.add_widget(results)

        def rebuild(*_):
            results.clear_widgets()
            query = field.text.strip().lower()
            matches = []
            for section_key, tools in TOOL_SECTIONS:
                section = tr(section_key, self.language, section_key.title())
                for icon, title_key, key in tools:
                    title = tr(title_key, self.language, title_key)
                    plain = title.replace("\n", " ")
                    if not query or query in plain.lower() or query in section.lower():
                        matches.append((plain, key))
            for title, key in matches[:12]:
                results.add_widget(MDFlatButton(
                    text=title,
                    size_hint_y=None,
                    height=dp(42),
                    on_release=lambda _, k=key, t=title: (dialog.dismiss(), self.open_tool(k, t)),
                ))
            if not matches:
                results.add_widget(MDLabel(text="কোনো মিল পাওয়া যায়নি" if self.language == "bn" else "No matching tools", halign="center", size_hint_y=None, height=dp(42)))

        dialog = MDDialog(
            title=tr("search_tools", self.language, "Search tools"),
            type="custom",
            content_cls=wrapper,
            buttons=[MDFlatButton(text=tr("close", self.language, "CLOSE"), on_release=lambda *_: dialog.dismiss())],
        )
        field.bind(text=rebuild)
        rebuild()
        dialog.open()

    @staticmethod
    def _info(title, text):
        dialog = MDDialog(
            title=title,
            text=text,
            buttons=[
                MDFlatButton(
                    text="OK",
                    on_release=lambda *_: dialog.dismiss(),
                )
            ],
        )
        dialog.open()
