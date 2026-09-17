from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDIcon, MDLabel

ACTIVE = (0.05, 0.52, 0.46, 1)
INACTIVE = (0.38, 0.45, 0.54, 1)
BAR_BG = (0.985, 0.99, 1, 1)


class BottomNavItem(ButtonBehavior, MDBoxLayout):
    icon = StringProperty("home-outline")
    label = StringProperty("Home")
    target = StringProperty("home")
    selected = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint=(0.25, 1),
            padding=(0, dp(7), 0, dp(4)),
            spacing=0,
            **kwargs,
        )

        self._icon = MDIcon(
            icon=self.icon,
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            font_size="27sp",
            size_hint_y=0.62,
        )
        self._label = MDLabel(
            text=self.label,
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            font_style="Caption",
            size_hint_y=0.38,
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

        color = ACTIVE if self.selected else INACTIVE
        self._icon.icon = self.icon
        self._icon.text_color = color
        self._label.text = self.label
        self._label.text_color = color

    def on_release(self):
        app = MDApp.get_running_app()
        if not self.target:
            return
        if app.screen_manager.current != self.target:
            app.go_to(self.target)


class BottomNavigationBar(MDBoxLayout):
    """
    Four equal-width navigation cells.

    Explicit 25% widths keep Home / Files / Tools / Settings perfectly
    centered even on phones with different screen widths.
    """

    def __init__(self, selected="home", **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(82),
            padding=(0, 0, 0, 0),
            spacing=0,
            md_bg_color=BAR_BG,
            **kwargs,
        )

        items = (
            ("home-variant-outline", "Home", "home"),
            ("folder-outline", "Files", "documents"),
            ("view-grid-outline", "Tools", "tools"),
            ("cog-outline", "Settings", "settings"),
        )

        for icon, label, target in items:
            self.add_widget(
                BottomNavItem(
                    icon=icon,
                    label=label,
                    target=target,
                    selected=(target == selected),
                )
            )
