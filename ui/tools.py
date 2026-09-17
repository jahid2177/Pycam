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
    (
        "Scan",
        [
            ("card-account-details-outline", "ID Cards", "id_cards"),
            ("text-recognition", "Extract Text", "extract_text"),
            ("account-box-outline", "Passport\nPhoto Maker", "passport_photo"),
            ("translate", "Photo\nTranslation", "photo_translation"),
            ("qrcode-scan", "Scan Code", "scan_code"),
        ],
    ),
    (
        "Convert",
        [
            ("merge", "Merge PDF", "merge_pdf"),
            ("image-outline", "Image to PDF", "image_to_pdf"),
            ("file-document-edit-outline", "Text to PDF", "text_to_pdf"),
            ("file-word-outline", "To Word", "to_word"),
            ("microsoft-excel", "To Excel", "to_excel"),
            ("image-multiple-outline", "PDF to\nImages", "pdf_to_images"),
            ("image-size-select-large", "PDF to Long\nImage", "pdf_long_image"),
        ],
    ),
    (
        "Edit",
        [
            ("crop-free", "OpenCV Crop", "opencv_crop"),
            ("auto-fix", "BG Remover", "bg_remover"),
            ("crop", "Image Resizer", "image_resizer"),
            ("call-split", "Split PDF", "split_pdf"),
            ("draw-pen", "Sign", "sign"),
            ("watermark", "Add\nWatermark", "watermark"),
            ("file-export-outline", "Extract PDF\nPages", "extract_pages"),
            ("swap-vertical", "Reorder\nPages", "reorder_pages"),
            ("rotate-right", "Rotate PDF", "rotate_pdf"),
            ("lock-outline", "Lock", "lock_pdf"),
            ("arrow-collapse-vertical", "Compress", "compress_pdf"),
        ],
    ),
    (
        "Utilities",
        [
            ("head-cog-outline", "AI Chat", "ai_chat"),
            ("printer-outline", "Print", "print"),
            ("qrcode", "Create QR\nCode", "create_qr"),
        ],
    ),
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

        root = MDBoxLayout(
            orientation="vertical",
            md_bg_color=(0.97, 0.98, 1, 1),
        )

        toolbar = MDTopAppBar(
            title="Tools",
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
        for index, (title, _) in enumerate(TOOL_SECTIONS):
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
        for section_title, tools in TOOL_SECTIONS:
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

            for icon, title, key in tools:
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

        if key == "id_cards":
            app.active_session_pages = []
            app.editing_document_id = None
            scanner = app.screen_manager.get_screen("scanner")
            scanner.scan_type = "id_card"
            scanner.capture_mode = "batch"
            app.go_to("scanner")
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

        if key == "extract_text":
            if app.active_session_pages:
                app.go_to("editor")
            else:
                self._info(
                    "Extract Text",
                    "Scan or import a document first. OCR is available from the document workflow.",
                )
            return

        self._info(
            title,
            f"{title} is now available in the Tools dashboard. "
            "Its processing workflow is not implemented in the current Pycam codebase yet.",
        )

    def _show_search_message(self):
        self._info("Search tools", "Tool search can be added after the tool workflows are connected.")

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
