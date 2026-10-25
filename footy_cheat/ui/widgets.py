from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, GLib, Gtk, Pango

from ..format import format_afl_day, format_kickoff


def clear(widget: Gtk.Widget) -> None:
    child = widget.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        widget.remove(child)
        child = nxt


def label(
    text: str,
    *classes: str,
    xalign: float = 0,
    ellipsize: bool = False,
    wrap: bool = False,
    markup: bool = False,
) -> Gtk.Label:
    widget = Gtk.Label(xalign=xalign)
    if markup:
        widget.set_markup(text)
    else:
        widget.set_label(text)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_xalign(xalign)
    for css in classes:
        widget.add_css_class(css)
    return widget


def pin_viewports(widget: Gtk.Widget) -> None:
    """Keep click-to-focus from moving a scrolled window."""
    if isinstance(widget, Gtk.Viewport):
        widget.set_scroll_to_focus(False)
    child = widget.get_first_child()
    while child is not None:
        pin_viewports(child)
        child = child.get_next_sibling()


def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    window = Gtk.ScrolledWindow()
    window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    window.set_vexpand(True)
    window.set_propagate_natural_height(True)
    window.set_child(child)
    pin_viewports(window)
    return window


def pill(text: str, tone: str) -> Gtk.Label:
    widget = label(text, "pill", tone)
    widget.set_halign(Gtk.Align.START)
    return widget


def empty_pane(icon: str, title: str, body: str):
    from gi.repository import Adw

    page = Adw.StatusPage(icon_name=icon, title=title, description=body)
    page.set_vexpand(True)
    return page


class _FixedPicture(Gtk.Picture):
    """Picture whose size request is the crest size, not the file's pixel size."""

    def __init__(self, paintable: Gdk.Paintable, size: int):
        super().__init__()
        self._size = size
        self.set_paintable(paintable)
        self.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.set_can_shrink(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(False)
        self.set_vexpand(False)

    def do_measure(self, _orientation, _for_size):
        return self._size, self._size, -1, -1


class Crests:
    def __init__(self, logo_dir: Path):
        self.logo_dir = logo_dir
        self._cache: dict[tuple[int, int], Gdk.Texture | None] = {}

    def widget(self, team_id: int, name: str, teams, size: int) -> Gtk.Widget:
        texture = self.texture(team_id, teams)
        if texture is not None:
            return _FixedPicture(texture, size)
        fallback = label((name[:1] or "?").upper(), "crest-fallback")
        if size >= 40:
            fallback.add_css_class("large")
        fallback.set_size_request(size, size)
        fallback.set_halign(Gtk.Align.CENTER)
        fallback.set_valign(Gtk.Align.CENTER)
        fallback.set_hexpand(False)
        return fallback

    def texture(self, team_id: int, teams) -> Gdk.Texture | None:
        data = b""
        for team in teams:
            if team.id == team_id and team.logo_bytes:
                data = team.logo_bytes
                break
        key = (team_id, len(data))
        if key in self._cache:
            return self._cache[key]
        texture = None
        if data:
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            except Exception:
                texture = None
        if texture is None:
            path = self.logo_dir / f"{team_id}.png"
            if path.is_file():
                try:
                    texture = Gdk.Texture.new_from_filename(str(path))
                except Exception:
                    texture = None
        self._cache[key] = texture
        return texture


class PageHeader(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.add_css_class("page-header")
        row = Gtk.Box(spacing=12)
        self.title = label("", "title-1")
        self.title.set_hexpand(True)
        self.title.set_valign(Gtk.Align.CENTER)
        self.actions = Gtk.Box(spacing=6)
        self.actions.set_valign(Gtk.Align.CENTER)
        row.append(self.title)
        row.append(self.actions)
        self.subtitle = label("", "dim-label")
        self.append(row)
        self.append(self.subtitle)

    def set_heading(self, title: str, subtitle: str) -> None:
        self.title.set_label(title)
        self.subtitle.set_label(subtitle)


class YearMenu(Gtk.DropDown):
    def __init__(self, on_year):
        self._strings = Gtk.StringList()
        super().__init__(model=self._strings)
        self._on_year = on_year
        self._ids: list[int] = []
        self._guard = False
        self.connect("notify::selected", self._changed)

    def set_years(self, seasons, year: int | None) -> None:
        ids = [season.year for season in seasons]
        self._guard = True
        if ids != self._ids:
            while self._strings.get_n_items():
                self._strings.remove(0)
            for season in seasons:
                self._strings.append(str(season.year))
            self._ids = ids
        if year in self._ids:
            self.set_selected(self._ids.index(year))
        self._guard = False

    def _changed(self, *_args) -> None:
        if self._guard:
            return
        index = self.get_selected()
        if index is None or index < 0 or index >= len(self._ids):
            return
        self._on_year(self._ids[index])


def grouped_days(games) -> list[tuple[str, list]]:
    groups: list[tuple[str, list]] = []
    for game in games:
        day = "Date to be confirmed" if not game.date else format_afl_day(game.date)
        if groups and groups[-1][0] == day:
            groups[-1][1].append(game)
        else:
            groups.append((day, [game]))
    return groups


def ribbon(game) -> tuple[str, str]:
    if game.complete >= 100:
        return "Full time", "muted"
    if game.complete > 0:
        return (game.timestr or "Live"), "live"
    if not game.date:
        return "Upcoming", "gold"
    return format_kickoff(game.date), "gold"


def outcome(game) -> tuple[str, str]:
    call = game.call
    finished = game.complete >= 100
    live = 0 < game.complete < 100
    if call is None or call.pick_team_id is None:
        return "No tip", "muted"
    if live:
        return "Live", "live"
    if finished and game.winner_id is None:
        return "Draw", "muted"
    if not finished:
        return ("With crowd" if call.followed_consensus else "Level vote"), "muted"
    hit = call.pick_team_id == game.winner_id
    upset = call.consensus_team_id is not None and game.winner_id != call.consensus_team_id
    if hit and upset:
        return "Called upset", "good"
    if hit:
        return "Called", "good"
    if upset:
        return "Missed upset", "bad"
    return "Missed", "bad"


def centre_line(game) -> str:
    if (
        game.complete >= 100
        and game.home_score is not None
        and game.away_score is not None
    ):
        if game.winner_id is None or game.home_score == game.away_score:
            return "Draw"
        margin = abs(game.home_score - game.away_score)
        winner = game.home_name if game.winner_id == game.home_id else game.away_name
        return f"{winner} won by {margin}"
    if game.complete > 0:
        return "In progress"
    return ""

