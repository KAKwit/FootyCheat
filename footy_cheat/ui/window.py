from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import APP_ID
from ..controller import AppController
from ..engine.cutoff import FIRST_SEASON_YEAR
from ..engine.types import AppPage, Settings
from ..format import grouped, synced_label
from ..theme import accent_css
from .about import present_about, present_shortcuts
from .ladder_page import LadderPage
from .models_page import ModelsPage
from .preferences import PreferencesDialog
from .round_page import RoundPage
from .widgets import Crests, label

_TEXT = {"sm": "text-sm", "lg": "text-lg", "xl": "text-xl"}

_NAV = (
    (AppPage.ROUND, "Round", "x-office-calendar-symbolic"),
    (AppPage.LADDER, "Ladder", "view-list-symbolic"),
    (AppPage.MODELS, "Models", "applications-science-symbolic"),
)


class FootyWindow(Adw.ApplicationWindow):
    def __init__(self, application, controller: AppController, logo_dir: Path, icon_dir: Path, css_path: Path):
        super().__init__(application=application)
        self.controller = controller
        self._guard = False
        self._theming = False
        self._text_class = None
        self.set_title("Footy Cheat")
        width, height = _saved_size(controller.store)
        self.set_default_size(width, height)
        self._install_style(icon_dir, css_path)
        crests = Crests(logo_dir)

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self.refresh_button.add_css_class("flat")
        self.refresh_button.set_tooltip_text("Update now")
        self.refresh_button.connect("clicked", lambda *_: controller.refresh_now())
        self._refresh_busy = False
        self.synced = label("Not synced yet", "dim-label", "caption", ellipsize=True)
        self.synced.set_max_width_chars(28)
        self.synced.set_valign(Gtk.Align.CENTER)
        self.synced.set_visible(False)
        update = Gtk.Box(spacing=8)
        update.append(self.refresh_button)
        update.append(self.synced)
        self.menu_button = Gtk.MenuButton()
        self.menu_button.add_css_class("flat")
        self.menu_button.set_icon_name("open-menu-symbolic")
        self.menu_button.set_tooltip_text("Main Menu")
        self.menu_button.set_primary(True)
        self.menu_button.set_menu_model(_main_menu())
        self._install_actions(application)

        self.view = Adw.ViewStack()
        self.view.set_vexpand(True)
        self.view.set_hhomogeneous(False)
        self.view.set_vhomogeneous(False)
        self.preferences = PreferencesDialog(controller, crests)
        self.pages = {
            AppPage.ROUND: RoundPage(controller, crests),
            AppPage.LADDER: LadderPage(controller, crests),
            AppPage.MODELS: ModelsPage(controller),
        }
        for page, title, icon in _NAV:
            self.view.add_titled_with_icon(self.pages[page], page.value, title, icon)
        self.view.connect("notify::visible-child-name", self._view_changed)

        self.switcher = Adw.ViewSwitcher(policy=Adw.ViewSwitcherPolicy.WIDE)
        self.switcher.set_stack(self.view)
        self.header = Adw.HeaderBar()
        self.header.set_centering_policy(Adw.CenteringPolicy.STRICT)
        self.header.pack_start(update)
        self.header.set_title_widget(self.switcher)
        self.header.pack_end(self.menu_button)
        self.switcher_bar = Adw.ViewSwitcherBar()
        self.switcher_bar.set_stack(self.view)

        self.import_page = ImportPage(controller)
        self.opening = Adw.StatusPage(
            title="Opening the library",
            description="Reading the games stored on this computer.",
        )
        self.opening_spinner = Adw.Spinner()
        self.opening_spinner.set_size_request(48, 48)
        self.opening.set_child(self.opening_spinner)
        self.outer = Gtk.Stack()
        self.outer.add_css_class("main-content")
        self.outer.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.outer.set_transition_duration(200)
        self.outer.set_vexpand(True)
        self.outer.add_named(self.opening, "opening")
        self.outer.add_named(self.import_page, "import")
        self.outer.add_named(self.view, "pages")

        self.error_banner = Adw.Banner(title="")
        self.error_banner.add_css_class("error")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_vexpand(True)
        content.append(self.error_banner)
        content.append(self.outer)
        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(content)
        self.toolbar = Adw.ToolbarView()
        self.toolbar.add_top_bar(self.header)
        self.toolbar.add_bottom_bar(self.switcher_bar)
        self.toolbar.set_content(self.toasts)
        self.set_content(self.toolbar)

        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 550px"))
        narrow.add_setter(self.switcher_bar, "reveal", True)
        narrow.add_setter(self.switcher, "visible", False)
        narrow.add_setter(self.synced, "visible", True)
        self.add_breakpoint(narrow)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.connect("close-request", self._close)
        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", lambda *_: self.apply_theme())
        style.connect("notify::accent-color", lambda *_: self.apply_theme())
        controller.add_listener(self.refresh)
        self.refresh()


    def _install_style(self, icon_dir: Path, css_path: Path) -> None:
        display = Gdk.Display.get_default()
        provider = Gtk.CssProvider()
        provider.load_from_path(str(css_path))
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._accent = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            display, self._accent, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
        icons = Gtk.IconTheme.get_for_display(display)
        icons.add_search_path(str(icon_dir))
        self.set_icon_name(APP_ID)

    def _install_actions(self, application) -> None:
        preferences = Gio.SimpleAction.new("preferences", None)
        preferences.connect("activate", self._show_preferences)
        self.add_action(preferences)
        shortcuts = Gio.SimpleAction.new("shortcuts", None)
        shortcuts.connect("activate", self._show_shortcuts)
        self.add_action(shortcuts)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._show_about)
        self.add_action(about)
        application.set_accels_for_action("win.preferences", ["<primary>comma"])
        # ? is Shift+/ on this keyboard, and Control keeps the key as slash,
        # so the question-mark binding never sees the press.
        application.set_accels_for_action(
            "win.shortcuts",
            ["<primary>question", "<primary><shift>slash"],
        )

    def _show_preferences(self, *_args) -> None:
        self.preferences.update()
        self.preferences.present(self)

    def _show_shortcuts(self, *_args) -> None:
        present_shortcuts(self)

    def _show_about(self, *_args) -> None:
        present_about(self)

    def _ready(self) -> bool:
        controller = self.controller
        return (
            not controller.importing
            and controller.boot is not None
            and controller.year is not None
            and controller.round is not None
        )

    def _view_changed(self, *_args) -> None:
        if self._guard or not self._ready():
            return
        name = self.view.get_visible_child_name()
        try:
            page = AppPage(name)
        except ValueError:
            return
        if page != self.controller.page:
            self.controller.set_page(page)

    def refresh(self) -> None:
        self.apply_theme()
        controller = self.controller
        ready = self._ready()
        self.refresh_button.set_sensitive(not controller.importing)
        status = None if controller.boot is None else controller.boot.status
        synced = synced_label(None if status is None else status.last_sync)
        self.synced.set_label(controller.busy or synced)
        self.synced.set_tooltip_text(synced)
        busy = bool(controller.busy)
        if controller.busy:
            self.refresh_button.set_tooltip_text(f"{controller.busy}. {synced}")
        else:
            self.refresh_button.set_tooltip_text(f"Update now. {synced}")
        self._set_refresh_busy(busy and not controller.importing)
        notice = controller.notice
        if notice:
            controller.notice = None
            self.toasts.add_toast(Adw.Toast(title=notice, timeout=4))
        self.switcher.set_sensitive(ready)
        self.switcher_bar.set_sensitive(ready)
        self._guard = True
        if ready and self.view.get_visible_child_name() != controller.page.value:
            self.view.set_visible_child_name(controller.page.value)
        self._guard = False
        self.view.set_sensitive(ready)
        if controller.importing:
            self.outer.set_visible_child_name("import")
            self.import_page.update()
            self.error_banner.set_revealed(False)
        elif not ready:
            self.outer.set_visible_child_name("opening")
            failed = controller.error is not None
            self.opening.set_title("Couldn't open the library" if failed else "Opening the library")
            self.opening.set_description(
                controller.error or "Reading the games stored on this computer."
            )
            if failed:
                if self.opening.get_child() is not None:
                    self.opening.set_child(None)
                self.opening.set_icon_name("dialog-error-symbolic")
            else:
                self.opening.set_icon_name("")
                if self.opening.get_child() is not self.opening_spinner:
                    self.opening.set_child(self.opening_spinner)
            self.error_banner.set_revealed(False)
        else:
            self.outer.set_visible_child_name("pages")
            self.pages[controller.page].update()
            show_error = controller.error is not None
            self.error_banner.set_title(controller.error or "")
            self.error_banner.set_revealed(show_error)
        if self.preferences.get_mapped():
            self.preferences.update()

    def _set_refresh_busy(self, busy: bool) -> None:
        if busy == self._refresh_busy:
            return
        self._refresh_busy = busy
        if busy:
            image = Gtk.Image()
            image.set_pixel_size(16)
            image.set_from_paintable(Adw.SpinnerPaintable.new(image))
            self.refresh_button.set_child(image)
        else:
            self.refresh_button.set_icon_name("view-refresh-symbolic")

    def apply_theme(self) -> None:
        if self._theming:
            return
        self._theming = True
        try:
            settings = Settings() if self.controller.boot is None else self.controller.boot.settings
            manager = Adw.StyleManager.get_default()
            scheme = {
                "light": Adw.ColorScheme.FORCE_LIGHT,
                "dark": Adw.ColorScheme.FORCE_DARK,
            }.get(settings.theme, Adw.ColorScheme.DEFAULT)
            if manager.get_color_scheme() != scheme:
                manager.set_color_scheme(scheme)
            self._accent.load_from_string(accent_css(settings.team_theme, manager.get_dark()))
            wanted = _TEXT.get(settings.font_size)
            if wanted != self._text_class:
                if self._text_class is not None:
                    self.remove_css_class(self._text_class)
                if wanted is not None:
                    self.add_css_class(wanted)
                self._text_class = wanted
        finally:
            self._theming = False

    def _typing(self) -> bool:
        focus = self.get_focus()
        return isinstance(focus, (Gtk.Entry, Gtk.Text, Gtk.SearchEntry))

    def _key(self, _controller, keyval, _keycode, state) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and (keyval == Gdk.KEY_question or (shift and keyval == Gdk.KEY_slash)):
            self._show_shortcuts()
            return True
        pages = {
            Gdk.KEY_1: AppPage.ROUND,
            Gdk.KEY_2: AppPage.LADDER,
            Gdk.KEY_3: AppPage.MODELS,
        }
        if ctrl and keyval in pages and self._ready():
            self.controller.set_page(pages[keyval])
            return True
        if self._typing() or self.controller.page is not AppPage.ROUND or not self._ready():
            return False
        if keyval == Gdk.KEY_Left:
            self.controller.move_round(-1)
            return True
        if keyval == Gdk.KEY_Right:
            self.controller.move_round(1)
            return True
        if keyval == Gdk.KEY_Up:
            self.controller.move_game(-1)
            return True
        if keyval == Gdk.KEY_Down:
            self.controller.move_game(1)
            return True
        return False

    def _close(self, _window) -> bool:
        width = self.get_width()
        height = self.get_height()
        if width > 0 and height > 0:
            self.controller.store.meta_set("window_width", str(width))
            self.controller.store.meta_set("window_height", str(height))
        self.controller.remove_listener(self.refresh)
        self.controller.dispose()
        return False


class ImportPage(Gtk.Box):
    def __init__(self, controller: AppController):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_vexpand(True)
        explanation = (
            f"Fixtures, results, ladders and computer tips from the {FIRST_SEASON_YEAR} season "
            "onward are saved on this computer. Earlier seasons are not imported. "
            "Requests go out one at a time."
        )
        self.page = Adw.StatusPage(
            icon_name="folder-download-symbolic",
            title="Copying the Squiggle history",
            description=explanation,
        )
        self.page.set_vexpand(True)
        self.append(self.page)
        self.controller = controller
        self._explanation = explanation
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        extra.set_size_request(360, -1)
        extra.set_margin_top(6)
        progress_row = Gtk.Box(spacing=16)
        self.percent = label("…", "title-1", "figures")
        self.bar = Gtk.ProgressBar()
        self.bar.set_hexpand(True)
        self.bar.set_valign(Gtk.Align.CENTER)
        self.bar.add_css_class("thin")
        progress_row.append(self.percent)
        progress_row.append(self.bar)
        self.detail = label("", wrap=True)
        self.detail.set_justify(Gtk.Justification.CENTER)
        self.detail.set_halign(Gtk.Align.CENTER)
        counts = Gtk.Box(spacing=8)
        counts.set_halign(Gtk.Align.CENTER)
        self.seasons = _count(counts, "Seasons")
        self.games = _count(counts, "Games")
        self.tips = _count(counts, "Tips")
        self.action = Gtk.Button(label="Stop")
        self.action.set_halign(Gtk.Align.CENTER)
        self.action.connect("clicked", self._click)
        extra.append(progress_row)
        extra.append(self.detail)
        extra.append(counts)
        extra.append(self.action)
        self.page.set_child(extra)

    def update(self) -> None:
        controller = self.controller
        status = controller.status
        total = 0 if status is None else status.total
        done = 0 if status is None else status.done
        ratio = 0 if total <= 0 else max(0, min(1, done / total))
        failed = controller.error is not None and (status is None or not status.running)
        self.page.set_title("The copy stopped" if failed else "Copying the Squiggle history")
        self.page.set_description(controller.error if failed and controller.error else self._explanation)
        self.percent.set_label(f"{round(ratio * 100)}%" if total else "…")
        self.bar.set_fraction(ratio)
        message = "Starting" if status is None else status.message
        years = "" if status is None else f" · {status.years_done} seasons stored"
        games = "" if status is None or status.games <= 0 else f" · {grouped(status.games)} games"
        self.detail.set_label(f"{message}{years}{games}")
        if status is not None:
            self.seasons.set_label(str(status.years_done))
            self.games.set_label(grouped(status.games))
            self.tips.set_label(grouped(status.tips))
        if failed:
            self.action.set_label("Try again")
            self.action.add_css_class("suggested-action")
        else:
            self.action.set_label("Stop")
            self.action.remove_css_class("suggested-action")

    def _click(self, _button) -> None:
        status = self.controller.status
        failed = self.controller.error is not None and (status is None or not status.running)
        if failed:
            self.controller.start_import()
        else:
            self.controller.cancel_sync()


def _main_menu() -> Gio.Menu:
    menu = Gio.Menu()
    preferences = Gio.Menu()
    preferences.append("_Preferences", "win.preferences")
    menu.append_section(None, preferences)
    about = Gio.Menu()
    about.append("_Keyboard Shortcuts", "win.shortcuts")
    about.append("_About Footy Cheat", "win.about")
    menu.append_section(None, about)
    return menu


def _count(parent: Gtk.Box, title: str) -> Gtk.Label:
    box = Gtk.Box(spacing=6)
    box.add_css_class("count-pill")
    box.append(label(title, "dim-label", "caption"))
    value = label("0", "figures")
    box.append(value)
    parent.append(box)
    return value


def _saved_size(store) -> tuple[int, int]:
    try:
        width = int(store.meta_get("window_width") or 1120)
        height = int(store.meta_get("window_height") or 760)
    except (TypeError, ValueError):
        width, height = 1120, 760
    return max(width, 360), max(height, 480)

