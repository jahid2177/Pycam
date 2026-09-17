from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.metrics import dp
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDIcon, MDLabel

ACTIVE = (0.05, 0.52, 0.46, 1)
INACTIVE = (0.38, 0.45, 0.54, 1)


class BottomNavItem(ButtonBehavior, MDBoxLayout):
    icon = StringProperty("home-outline")
    label = StringProperty("Home")
    target = StringProperty("home")
    selected = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(66),
            padding=(dp(4), dp(6)),
            spacing=0,
            **kwargs,
        )

        self._icon = MDIcon(
            icon=self.icon,
            halign="center",
            theme_text_color="Custom",
            font_size="25sp",
        )
        self._label = MDLabel(
            text=self.label,
            halign="center",
            theme_text_color="Custom",
            font_style="Caption",
            size_hint_y=None,
            height=dp(22),
        )
        self.add_widget(self._icon)
        self.add_widget(self._label)

        self.bind(
            icon=self._sync,
            label=self._sync,
            selected=self._sync,
        )
        self._sync()

    def _sync(self, *args):
        if not hasattr(self, "_icon"):
            return
        self._icon.icon = self.icon
        self._label.text = self.label
        color = ACTIVE if self.selected else INACTIVE
        self._icon.text_color = color
        self._label.text_color = color

    def on_release(self):
        app = MDApp.get_running_app()
        if self.target and app.screen_manager.current != self.target:
            app.go_to(self.target)


class BottomNavigationBar(MDBoxLayout):
    def __init__(self, selected="home", **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            padding=(dp(8), dp(2)),
            spacing=dp(2),
            md_bg_color=(0.985, 0.99, 1, 1),
            **kwargs,
        )

        items = [
            ("home-variant-outline", "Home", "home"),
            ("folder-outline", "Files", "documents"),
            ("view-grid-outline", "Tools", "tools"),
            ("cog-outline", "Settings", "settings"),
        ]

        for icon, label, target in items:
            self.add_widget(
                BottomNavItem(
                    icon=icon,
                    label=label,
                    target=target,
                    selected=(target == selected),
                )
            )
