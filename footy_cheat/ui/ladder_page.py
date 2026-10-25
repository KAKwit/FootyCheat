import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from ..format import points_percent
from .widgets import Crests, PageHeader, YearMenu, empty_pane, label, scrolled


class LadderPage(Gtk.Box):
    def __init__(self, controller, crests: Crests):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.controller = controller
        self.crests = crests
        self._narrow = True
        self._form = False
        self._sig = None
        self._queued = False
        self.header = PageHeader()
        self.years = YearMenu(controller.choose_year)
        self.header.actions.append(self.years)
        self.bin = Adw.BreakpointBin()
        self.bin.set_vexpand(True)
        self.bin.set_size_request(1, 1)
        self.bin.set_child(Gtk.Box())
        for condition in ("min-width: 760px", "min-width: 980px"):
            point = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(condition))
            point.connect("apply", self._sync_layout)
            point.connect("unapply", self._sync_layout)
            self.bin.add_breakpoint(point)
        self.append(self.header)
        self.append(self.bin)

    def _sync_layout(self, *_args) -> None:
        width = self.bin.get_width()
        if width <= 0:
            return
        narrow = width < 760
        form = width >= 980
        if (self._narrow, self._form) == (narrow, form):
            return
        self._narrow = narrow
        self._form = form
        self._sig = None
        if self._queued:
            return
        self._queued = True

        def run():
            self._queued = False
            self.update()
            return False

        GLib.idle_add(run)

    def update(self) -> None:
        controller = self.controller
        seasons = [] if controller.boot is None else controller.boot.seasons
        self.years.set_years(seasons, controller.year)
        rows = [] if controller.ladder is None else controller.ladder.rows
        self.header.set_heading(
            "Ladder",
            "No table stored" if not rows else f"{len(rows)} clubs",
        )
        teams = [] if controller.boot is None else controller.boot.teams
        signature = (
            controller.year,
            self._narrow,
            self._form,
            tuple(
                (
                    row.team_id,
                    row.rank,
                    row.points,
                    row.percentage,
                    tuple(row.form),
                    row.next_abbrev,
                )
                for row in rows
            ),
            tuple((team.id, len(team.logo_bytes or b"")) for team in teams),
        )
        if signature == self._sig:
            return
        self._sig = signature
        if not rows:
            self.bin.set_child(
                empty_pane(
                    "view-list-symbolic",
                    "No ladder yet",
                    "No ladder is stored for this season yet.",
                )
            )
            return
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        body.add_css_class("ladder-list")
        if not self._narrow:
            body.append(self._head())
        for index, row in enumerate(rows):
            if index == 8:
                body.append(self._finals())
            if self._narrow:
                body.append(self._card(row, teams))
            else:
                body.append(self._line(row, teams))
        self.bin.set_child(scrolled(body))

    def _head(self) -> Gtk.Widget:
        row = Gtk.Box(spacing=8)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.append(_fixed("#", 36))
        row.append(_fixed("", 24))
        club = label("Club", "dim-label", "caption")
        club.set_hexpand(True)
        row.append(club)
        for text, width in (("P", 40), ("Pts", 52), ("%", 64), ("W–L–D", 88)):
            row.append(_fixed(text, width, end=True))
        if self._form:
            form_head = _fixed("Form", 120)
            form_head.add_css_class("form-column")
            row.append(form_head)
            row.append(_fixed("Next", 72, end=True))
        return row

    def _finals(self) -> Gtk.Widget:
        row = Gtk.Box(spacing=12)
        row.add_css_class("finals-line")
        row.append(label("Finals", "dim-label", "caption"))
        sep = Gtk.Separator()
        sep.set_hexpand(True)
        sep.set_valign(Gtk.Align.CENTER)
        row.append(sep)
        return row

    def _line(self, row, teams) -> Gtk.Widget:
        line = Gtk.Box(spacing=8)
        line.set_margin_start(8)
        line.set_margin_end(8)
        line.set_margin_top(4)
        line.set_margin_bottom(4)
        line.append(_fixed(str(row.rank), 36, figures=True))
        line.append(self.crests.widget(row.team_id, row.name, teams, 24))
        name = label(row.name, ellipsize=True)
        name.set_hexpand(True)
        line.append(name)
        line.append(_fixed(str(row.played), 40, end=True, figures=True))
        line.append(_fixed(str(row.points), 52, end=True, figures=True))
        line.append(_fixed(points_percent(row.percentage), 64, end=True, figures=True))
        record = f"{row.wins}–{row.losses}–{row.draws}"
        line.append(_fixed(record, 88, end=True, figures=True))
        if self._form:
            form = self._form_box(row)
            form.add_css_class("form-line")
            form.add_css_class("form-column")
            line.append(form)
            line.append(_fixed(row.next_abbrev or "–", 72, end=True))
        return line

    def _card(self, row, teams) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("ladder-card")
        top = Gtk.Box(spacing=8)
        top.append(label(str(row.rank), "dim-label", "figures"))
        top.append(self.crests.widget(row.team_id, row.name, teams, 24))
        name = label(row.name, "heading", ellipsize=True)
        name.set_hexpand(True)
        top.append(name)
        top.append(label(str(row.points), "title-2", "figures"))
        card.append(top)
        card.append(
            label(
                f"{row.played} played · {row.wins}–{row.losses}–{row.draws} · {points_percent(row.percentage)}%",
                "dim-label",
            )
        )
        form = self._form_box(row)
        form.set_halign(Gtk.Align.START)
        card.append(form)
        return card

    def _form_box(self, row) -> Gtk.Widget:
        box = Gtk.Box(spacing=4)
        box.set_size_request(120, -1)
        if not row.form:
            box.append(label("–", "dim-label"))
            return box
        for mark in row.form:
            mark_label = label(mark, "form", mark, "figures", xalign=0.5)
            mark_label.set_width_chars(1)
            box.append(mark_label)
        return box


def _fixed(text: str, width: int, end: bool = False, figures: bool = False) -> Gtk.Label:
    classes = ["figures"] if figures else ["dim-label", "caption"]
    widget = label(text, *classes, xalign=1 if end else 0)
    widget.set_size_request(width, -1)
    return widget
