"""
Bottom navigation bar, shared by every top-level screen.

Kept in one place (Home, Files, Tools and Settings all instantiate it) so the
bar - and the divider/elevation above it - stays identical on every screen.
"""

from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDIcon, MDLabel

ACTIVE = (0.05, 0.52, 0.46, 1)
INACTIVE = (0.38, 0.45, 0.54, 1)
BAR_BG = (1, 1, 1, 1)

# KivyMD's MDBoxLayout has no elevation/shadow of its own, and the bar's
# background was within a hair of the page colour, so bar and content merged
# into one flat white area with no visible boundary. Three stacked hairlines
# (light at the top, darkest against the bar) read as a soft top shadow; the
# darkest band doubles as the divider.
SHADOW_BANDS = (
    (0.935, 0.945, 0.965, 1),
    (0.895, 0.910, 0.930, 1),
    (0.835, 0.850, 0.875, 1),
)
BAND_HEIGHT = dp(2)
SHADOW_HEIGHT = BAND_HEIGHT * len(SHADOW_BANDS)
BAR_HEIGHT = dp(82)


class _ElevationShadow(MDBoxLayout):
    """Hairline bands drawn directly above the bar to signal elevation."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=SHADOW_HEIGHT,
            padding=(0, 0, 0, 0),
            spacing=0,
            **kwargs,
        )
        for color in SHADOW_BANDS:
            self.add_widget(
                MDBoxLayout(
                    size_hint_y=None,
                    height=BAND_HEIGHT,
                    md_bg_color=color,
                )
            )


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
    Four equal-width navigation cells, with a divider + soft top shadow so the
    bar is visually separated from the content behind it.

    Explicit 25% widths keep Home / Files / Tools / Settings perfectly centered
    even on phones with different screen widths.
    """

    def __init__(self, selected="home", **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=BAR_HEIGHT,
            padding=(0, 0, 0, 0),
            spacing=0,
            md_bg_color=BAR_BG,
            **kwargs,
        )

        self.add_widget(_ElevationShadow())

        row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=BAR_HEIGHT - SHADOW_HEIGHT,
            padding=(0, 0, 0, 0),
            spacing=0,
            md_bg_color=BAR_BG,
        )

        items = (
            ("home-variant-outline", "Home", "home"),
            ("folder-outline", "Files", "documents"),
            ("view-grid-outline", "Tools", "tools"),
            ("cog-outline", "Settings", "settings"),
        )

        for icon, label, target in items:
            row.add_widget(
                BottomNavItem(
                    icon=icon,
                    label=label,
                    target=target,
                    selected=(target == selected),
                )
            )

        self.add_widget(row)
