import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from ..engine.cutoff import FIRST_SEASON_YEAR
from ..engine.types import Settings
from ..format import grouped, synced_label
from ..theme import CLUBS
from .widgets import Crests, pin_viewports

_THEME_KEYS = ("system", "light", "dark")
_SIZE_KEYS = ("sm", "md", "lg", "xl")


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, controller, crests: Crests):
        super().__init__(title="Preferences", content_width=680, content_height=640)
        self.controller = controller
        self.crests = crests
        self._guard = False
        self._club_key = None
        self._club_rows: list[tuple[Gtk.Widget, int | None, Gtk.Widget]] = []
        self.connect("map", lambda *_args: self._pin_scroll())
        self.connect("notify::visible-page", lambda *_args: self._pin_scroll())
        self.add(self._appearance_page())
        self.add(self._squiggle_page())
        self.add(self._library_page())

    def _pin_scroll(self, tries: int = 0) -> bool:
        pin_viewports(self)
        if tries < 8:
            GLib.timeout_add(50, self._pin_scroll, tries + 1)
        return False

    def _appearance_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title="Appearance",
            icon_name="display-brightness-symbolic",
            name="appearance",
        )
        appearance = Adw.PreferencesGroup()
        self.theme_row = Adw.ComboRow(
            title="Theme",
            subtitle="Follows this computer unless you pick light or dark.",
        )
        self.theme_row.set_model(Gtk.StringList.new(["System", "Light", "Dark"]))
        self.theme_row.connect("notify::selected", self._theme)
        appearance.add(self.theme_row)
        self.size_row = Adw.ComboRow(
            title="Text size",
            subtitle="Scales this window. The system text size still applies.",
        )
        self.size_row.set_model(Gtk.StringList.new(["Small", "Medium", "Large", "Extra large"]))
        self.size_row.connect("notify::selected", self._size)
        appearance.add(self.size_row)
        self.club_group = Adw.PreferencesGroup(
            title="Club colours",
            description="The accent follows the club you support. Scores and text stay easy to read.",
        )
        page.add(appearance)
        page.add(self.club_group)
        return page

    def _squiggle_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title="Squiggle",
            icon_name="mail-unread-symbolic",
            name="squiggle",
        )
        group = Adw.PreferencesGroup(
            description=(
                "Squiggle asks apps to send a contact email in the User-Agent. "
                "It stays on this computer and is only sent to Squiggle."
            ),
        )
        self.email = Adw.EntryRow(title="Contact email")
        self.email.set_input_purpose(Gtk.InputPurpose.EMAIL)
        self.email.connect("changed", self._email)
        group.add(self.email)
        page.add(group)
        return page

    def _library_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title="Library",
            icon_name="folder-symbolic",
            name="library",
            description=f"Seasons before {FIRST_SEASON_YEAR} are not downloaded.",
        )
        self.error_banner = Adw.Banner(title="")
        self.error_banner.add_css_class("error")
        page.set_banner(self.error_banner)
        stats = Adw.PreferencesGroup(title="On this computer")
        self.games_value = _count(stats, "Games")
        self.tips_value = _count(stats, "Tips")
        self.seasons_value = _count(stats, "Seasons")
        self.synced_row = Adw.ActionRow(title="Not synced yet")
        self.busy_row = Adw.ActionRow(title="")
        self.busy_row.set_visible(False)
        stats.add(self.synced_row)
        stats.add(self.busy_row)
        actions = Adw.PreferencesGroup(title="Update")
        update = Adw.ActionRow(
            title="Update now",
            subtitle="Check Squiggle and save the latest games and tips.",
        )
        update.set_activatable(True)
        update.connect("activated", lambda *_args: self.controller.refresh_now())
        again = Adw.ActionRow(
            title="Download again",
            subtitle=(
                f"Replace the local copy from the {FIRST_SEASON_YEAR} season onward. "
                "You'll be asked before it starts."
            ),
        )
        again.add_css_class("danger-row")
        again.set_activatable(True)
        again.connect("activated", self._confirm_rebuild)
        actions.add(update)
        actions.add(again)
        page.add(stats)
        page.add(actions)
        return page

    def update(self) -> None:
        settings = self._settings()
        self._guard = True
        theme = settings.theme if settings.theme in _THEME_KEYS else "system"
        size = settings.font_size if settings.font_size in _SIZE_KEYS else "md"
        theme_index = _THEME_KEYS.index(theme)
        size_index = _SIZE_KEYS.index(size)
        if self.theme_row.get_selected() != theme_index:
            self.theme_row.set_selected(theme_index)
        if self.size_row.get_selected() != size_index:
            self.size_row.set_selected(size_index)
        if not _editing(self.email) and self.email.get_text() != settings.contact_email:
            self.email.set_text(settings.contact_email)
        self._guard = False
        self._fill_clubs(settings)
        if self.get_mapped():
            pin_viewports(self)
        status = None if self.controller.boot is None else self.controller.boot.status
        games = 0 if status is None else status.games
        tips = 0 if status is None else status.tips
        done = 0 if status is None else status.years_done
        total = 0 if status is None else status.years_total
        self.games_value.set_label(grouped(games))
        self.tips_value.set_label(grouped(tips))
        self.seasons_value.set_label(f"{done} / {total}")
        self.synced_row.set_title(synced_label(None if status is None else status.last_sync))
        error = "" if status is None or not status.last_error else status.last_error
        self.error_banner.set_title(error)
        self.error_banner.set_revealed(bool(error))
        self.busy_row.set_title(self.controller.busy)
        self.busy_row.set_visible(bool(self.controller.busy))

    def _fill_clubs(self, settings: Settings) -> None:
        teams = [] if self.controller.boot is None else self.controller.boot.teams
        key = tuple((team.id, team.name, len(team.logo_bytes or b"")) for team in teams)
        if key != self._club_key:
            self._club_key = key
            for row, _team_id, _check in self._club_rows:
                self.club_group.remove(row)
            self._club_rows.clear()
            self._add_club("Default", None, teams)
            for team_id, (name, _wash, _gold) in CLUBS.items():
                label_name = name
                for team in teams:
                    if team.id == team_id and team.name:
                        label_name = team.name
                        break
                self._add_club(label_name, team_id, teams)
        self._show_club(settings.team_theme)

    def _add_club(self, name: str, team_id: int | None, teams) -> None:
        row = Adw.ActionRow(title=name)
        row.set_activatable(True)
        row.set_focus_on_click(False)
        if team_id is None:
            mark = Gtk.Image.new_from_icon_name("preferences-color-symbolic")
            mark.set_pixel_size(24)
        else:
            mark = self.crests.widget(team_id, name, teams, 24)
            if isinstance(mark, Gtk.Picture):
                mark.set_can_shrink(True)
            mark.set_size_request(24, 24)
        row.add_prefix(mark)
        check = Gtk.Image.new_from_icon_name("object-select-symbolic")
        check.add_css_class("confidence")
        check.set_visible(False)
        row.add_suffix(check)
        row.connect("activated", lambda *_args, chosen=team_id: self._choose_club(chosen))
        self.club_group.add(row)
        self._club_rows.append((row, team_id, check))

    def _show_club(self, team_id: int | None) -> None:
        for _row, row_id, check in self._club_rows:
            check.set_visible(row_id == team_id)

    def _settings(self) -> Settings:
        if self.controller.boot is None:
            return self.controller.store.load_settings()
        return self.controller.boot.settings.copy()

    def _theme(self, *_args) -> None:
        self._choose(_THEME_KEYS, self.theme_row, "theme")

    def _size(self, *_args) -> None:
        self._choose(_SIZE_KEYS, self.size_row, "font_size")

    def _choose(self, keys: tuple[str, ...], row: Adw.ComboRow, field: str) -> None:
        if self._guard:
            return
        index = row.get_selected()
        if index >= len(keys):
            return
        settings = self._settings()
        if getattr(settings, field) == keys[index]:
            return
        setattr(settings, field, keys[index])
        self.controller.save(settings)

    def _email(self, *_args) -> None:
        if self._guard:
            return
        settings = self._settings()
        text = self.email.get_text()
        if settings.contact_email == text:
            return
        settings.contact_email = text
        self.controller.save(settings)

    def _choose_club(self, team_id: int | None) -> None:
        settings = self._settings()
        if settings.team_theme == team_id:
            return
        settings.team_theme = team_id
        self._show_club(team_id)
        self.controller.save(settings)

    def _confirm_rebuild(self, _row) -> None:
        dialog = Adw.AlertDialog(
            heading="Download again?",
            body=(
                f"This replaces the local copy from the {FIRST_SEASON_YEAR} season onward, "
                "one season at a time."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("download", "Download")
        dialog.set_response_appearance("download", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._rebuild_response)
        dialog.present(self)

    def _rebuild_response(self, _dialog, response: str) -> None:
        if response == "download":
            self.controller.rebuild_all()


def _count(group: Adw.PreferencesGroup, title: str) -> Gtk.Label:
    row = Adw.ActionRow(title=title)
    value = Gtk.Label(label="0", xalign=1)
    value.add_css_class("figures")
    row.add_suffix(value)
    group.add(row)
    return value


def _editing(widget: Gtk.Widget) -> bool:
    root = widget.get_root()
    focus = None if root is None else root.get_focus()
    current = focus
    while current is not None:
        if current is widget:
            return True
        current = current.get_parent()
    return False
