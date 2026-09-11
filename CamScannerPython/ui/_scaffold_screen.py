"""
Shared base for screens whose real implementation lands in a later step
(camera/detection = step 3-4, crop editor = step 7, multi-page editor =
step 9, documents browser = step 10, settings = ongoing).

Per the build rules, we never fake a feature as "working" - each of
these screens is a genuine, navigable MDScreen with a real top bar and
back action; the body honestly says what step will fill it in, instead
of showing mocked buttons that do nothing.
"""

from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.button import MDIconButton
from kivymd.app import MDApp


class ScaffoldScreen(MDScreen):
    title_text = "Screen"
    pending_step = ""
    back_target = "home"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = MDBoxLayout(orientation="vertical")

        toolbar = MDTopAppBar(title=self.title_text, elevation=2)
        toolbar.left_action_items = [["arrow-left", lambda x: self.go_back()]]
        root.add_widget(toolbar)

        body = MDBoxLayout(
            orientation="vertical",
            padding="32dp",
            spacing="12dp",
        )
        body.add_widget(
            MDLabel(
                text=self.pending_step,
                halign="center",
                theme_text_color="Hint",
            )
        )
        root.add_widget(body)

        self.add_widget(root)

    def go_back(self):
        MDApp.get_running_app().go_to(self.back_target)
