import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gtk, PangoCairo

from ..engine.cutoff import FIRST_SEASON_YEAR
from ..engine.model import sort_models
from ..engine.numbers import to_fixed
from ..format import format_clear, format_percent
from ..theme import accent_for
from .widgets import PageHeader, YearMenu, clear, empty_pane, label, pill, scrolled

_LEADER_EXTRAS = (
    (0.22, 0.48, 0.75, 1.0),
    (0.82, 0.45, 0.12, 1.0),
    (0.45, 0.38, 0.62, 1.0),
)


class ModelsPage(Gtk.Box):
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.controller = controller
        self.sort = "record"
        self.header = PageHeader()
        self.years = YearMenu(controller.choose_year)
        self.header.actions.append(self.years)
        self.group = Adw.ToggleGroup()
        self.group.set_halign(Gtk.Align.START)
        self.group.set_margin_start(20)
        self.group.set_margin_top(12)
        for name, title in (("record", "Record"), ("upset", "Upsets"), ("margin", "Margin")):
            toggle = Adw.Toggle()
            toggle.set_name(name)
            toggle.set_label(title)
            self.group.add(toggle)
        self.group.set_active_name("record")
        self.group.connect("notify::active-name", self._sorted)
        note = label(
            "Footy Cheat follows the majority of the models. "
            "A level vote goes to the side whose models state more confidence. "
            "The bar is games clear of the median model. "
            f"Seasons before {FIRST_SEASON_YEAR} are not part of the record.",
            "dim-label",
            wrap=True,
        )
        note.set_margin_start(20)
        note.set_margin_end(20)
        note.set_margin_top(12)
        note.set_margin_bottom(12)
        self.host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.host.add_css_class("record-list")
        self.append(self.header)
        self.append(self.group)
        self.append(note)
        self.append(scrolled(self.host))
        self._guard = False

    def _sorted(self, *_args) -> None:
        if self._guard:
            return
        name = self.group.get_active_name()
        if name:
            self.sort = name
            self.update()

    def update(self) -> None:
        controller = self.controller
        seasons = [] if controller.boot is None else controller.boot.seasons
        self.years.set_years(seasons, controller.year)
        board = controller.models
        rows = [] if board is None else sort_models(board.rows, self.sort)
        if board is None:
            subtitle = "No model record"
        elif not rows:
            subtitle = "No settled tips"
        else:
            subtitle = f"{len(rows)} models"
        self.header.set_heading("Model record", subtitle)
        clear(self.host)
        if board is None or not rows:
            if board is None:
                self.host.append(
                    empty_pane(
                        "applications-science-symbolic",
                        "No model record",
                        "Computer tips appear here after the library has been copied.",
                    )
                )
            else:
                self.host.append(
                    empty_pane(
                        "applications-science-symbolic",
                        "No settled tips",
                        "No model has a result in this season yet.",
                    )
                )
            return
        team_id = _team_theme(controller)
        scale = _clear_scale(rows, board.footy)
        if len(board.rounds) >= 2 and any(len(line.points) >= 2 for line in board.lines):
            self.host.append(RaceChart(board, team_id))
        if board.footy is not None and board.footy.tips > 0:
            self.host.append(self._card(board.footy, None, scale, team_id, pinned=True))
        for index, row in enumerate(rows, start=1):
            self.host.append(self._card(row, index, scale, team_id))

    def _card(self, row, rank: int | None, scale: float, team_id: int | None, pinned: bool = False):
        card = Gtk.Box(spacing=12)
        card.add_css_class("model-card")
        if pinned:
            card.add_css_class("footy")
        if rank is not None:
            card.append(label(str(rank), "dim-label", "figures"))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        text.set_hexpand(True)
        title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title.append(self._title(row))
        career = _career(row)
        if career:
            title.append(label(career, "dim-label", "caption"))
        text.append(title)
        bar_row = Gtk.Box(spacing=8)
        bar = ClearBar(row.clear, scale, team_id)
        bar.set_valign(Gtk.Align.CENTER)
        bar_row.append(bar)
        ahead = label(format_clear(row.clear), "figures", "caption", xalign=1)
        ahead.set_width_chars(6)
        bar_row.append(ahead)
        text.append(bar_row)
        wrap = Gtk.FlowBox()
        wrap.set_selection_mode(Gtk.SelectionMode.NONE)
        wrap.set_max_children_per_line(5)
        wrap.set_column_spacing(14)
        wrap.set_row_spacing(4)
        for title_text, value in _stats(row):
            wrap.insert(_mini(title_text, value), -1)
        text.append(wrap)
        card.append(text)
        hero, caption = _hero(row, self.sort)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.set_valign(Gtk.Align.START)
        side.append(label(hero, "title-1", "figures", xalign=1))
        side.append(label(caption, "dim-label", "caption", xalign=1))
        card.append(side)
        return card

    def _title(self, row) -> Gtk.Widget:
        head = Gtk.Box(spacing=8)
        name = label(row.name, "heading", ellipsize=True)
        name.set_hexpand(True)
        name.set_valign(Gtk.Align.CENTER)
        head.append(name)
        if row.honour == "winner":
            head.append(_badge("Winner"))
        elif row.honour == "leader":
            head.append(_badge("Leader"))
        return head


class ClearBar(Gtk.DrawingArea):
    def __init__(self, ahead: float, scale: float, team_id: int | None):
        super().__init__()
        self.ahead = ahead
        self.scale = scale if scale > 0 else 1.0
        self.team_id = team_id
        self.set_content_height(10)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.set_tooltip_text("Games clear of the median model.")

    def _draw(self, _area, cr, width, height) -> None:
        if width <= 0 or height <= 0:
            return
        dark = _dark()
        track_h = 6
        y = (height - track_h) / 2
        if dark:
            cr.set_source_rgba(1, 1, 1, 0.14)
        else:
            cr.set_source_rgba(0, 0, 0, 0.12)
        _round_rect(cr, 0, y, width, track_h, 3)
        cr.fill()
        mid = width / 2
        frac = max(-1.0, min(1.0, self.ahead / self.scale))
        fill_w = (width / 2) * abs(frac)
        if fill_w >= 1:
            if frac > 0:
                cr.set_source_rgba(*series_color("leader", 0, self.team_id))
                _round_rect(cr, mid, y, fill_w, track_h, 3)
            else:
                behind = (1.0, 0.48, 0.44, 1.0) if dark else (0.77, 0.20, 0.17, 1.0)
                cr.set_source_rgba(*behind)
                _round_rect(cr, mid - fill_w, y, fill_w, track_h, 3)
            cr.fill()
        if dark:
            cr.set_source_rgba(0.9, 0.9, 0.92, 0.85)
        else:
            cr.set_source_rgba(0.25, 0.25, 0.28, 0.7)
        cr.rectangle(mid - 0.5, y - 1, 1, track_h + 2)
        cr.fill()


class RaceChart(Gtk.Box):
    def __init__(self, board, team_id: int | None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("race-card")
        self.set_hexpand(True)
        self.board = board
        self.team_id = team_id
        self.append(label("Games clear of the field", "heading"))
        caption = label(
            "Running games clear of the median model.",
            "dim-label",
            "caption",
            wrap=True,
        )
        self.append(caption)
        self.append(self._legend())
        area = Gtk.DrawingArea()
        area.add_css_class("race-plot")
        area.set_content_height(168)
        area.set_hexpand(True)
        area.set_draw_func(self._draw)
        summary = _race_summary(board)
        area.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Games clear of the field"],
        )
        if summary:
            area.set_tooltip_text(summary)
            area.update_property([Gtk.AccessibleProperty.DESCRIPTION], [summary])
        self.append(area)

    def _legend(self) -> Gtk.Widget:
        box = Gtk.FlowBox()
        box.set_selection_mode(Gtk.SelectionMode.NONE)
        box.set_max_children_per_line(4)
        box.set_column_spacing(14)
        box.set_row_spacing(4)
        box.set_halign(Gtk.Align.START)
        box.insert(self._chip("field", 0, "Field"), -1)
        named = [line for line in self.board.lines if line.points and line.role == "footy"]
        named.extend(line for line in self.board.lines if line.points and line.role != "footy")
        leader_index = 0
        for line in named:
            index = 0
            if line.role == "leader":
                index = leader_index
                leader_index += 1
            text = f"{line.name}  {format_clear(line.points[-1])}"
            box.insert(self._chip(line.role, index, text), -1)
        return box

    def _chip(self, kind: str, leader_index: int, text: str) -> Gtk.Widget:
        row = Gtk.Box(spacing=6)
        row.append(_Swatch(kind, leader_index, self.team_id))
        name = label(text, "caption", ellipsize=True)
        name.set_max_width_chars(28)
        name.set_valign(Gtk.Align.CENTER)
        row.append(name)
        return row

    def _draw(self, area, cr, width, height) -> None:
        if width < 48 or height < 48:
            return
        count = len(self.board.round_names)
        series = []
        colors = []
        leader_index = 0
        for line in self.board.lines:
            count = min(count, len(line.points))
        if count < 2:
            return
        for line in self.board.lines:
            if len(line.points) < 2:
                continue
            if line.role == "leader":
                colors.append(series_color("leader", leader_index, self.team_id))
                leader_index += 1
            else:
                colors.append(series_color("footy", 0, self.team_id))
            series.append(line.points[:count])
        paint_race(
            area,
            cr,
            width,
            height,
            self.board.rounds[:count],
            self.board.round_names[:count],
            series,
            colors,
            _ink(),
        )


class _Swatch(Gtk.DrawingArea):
    def __init__(self, kind: str, leader_index: int, team_id: int | None):
        super().__init__()
        self.kind = kind
        self.leader_index = leader_index
        self.team_id = team_id
        self.set_size_request(18, 10)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, width, height) -> None:
        if width <= 0 or height <= 0:
            return
        cr.set_line_width(2)
        cr.set_source_rgba(*series_color(self.kind, self.leader_index, self.team_id))
        if self.kind == "field":
            cr.set_dash([3, 2], 0)
        cr.move_to(1, height / 2)
        cr.line_to(max(1, width - 1), height / 2)
        cr.stroke()


def paint_race(area, cr, width, height, rounds, names, series, colors, ink) -> None:
    left, right, top, bottom = 36, 10, 12, 32
    plot_w = width - left - right
    plot_h = height - top - bottom
    if plot_w < 20 or plot_h < 20 or not series:
        return
    peak = max(abs(point) for points in series for point in points)
    limit, step = _axis_limit(peak)
    xs = [left + plot_w * index / (len(rounds) - 1) for index in range(len(rounds))]

    def y_of(value: float) -> float:
        return top + plot_h / 2 - (value / limit) * (plot_h / 2)

    faint = (ink[0], ink[1], ink[2], 0.16)
    tick = -limit
    while tick <= limit + step * 0.01:
        y = y_of(tick)
        cr.set_source_rgba(*faint)
        cr.set_line_width(1)
        cr.move_to(left, y)
        cr.line_to(left + plot_w, y)
        cr.stroke()
        cr.set_source_rgba(*ink)
        _show(area, cr, _tick_label(tick), left - 6, y, "end", center_y=True)
        tick += step

    zero = y_of(0)
    cr.set_source_rgba(*series_color("field", 0, None))
    cr.set_dash([4, 3], 0)
    cr.set_line_width(1.5)
    cr.move_to(left, zero)
    cr.line_to(left + plot_w, zero)
    cr.stroke()
    cr.set_dash([], 0)

    cr.save()
    cr.rectangle(left, top, plot_w, plot_h)
    cr.clip()
    for points, color in zip(series, colors):
        cr.set_source_rgba(*color)
        cr.set_line_width(2)
        cr.move_to(xs[0], y_of(points[0]))
        for x, point in zip(xs[1:], points[1:]):
            cr.line_to(x, y_of(point))
        cr.stroke()
        if len(points) <= 12:
            for x, point in zip(xs, points):
                cr.arc(x, y_of(point), 2.4, 0, math.tau)
                cr.fill()
    cr.restore()

    cr.set_source_rgba(*ink)
    placed = []
    last = len(rounds) - 1
    label_y = top + plot_h + 14
    for index, number, name in _label_plan(rounds, names):
        layout = area.create_pango_layout(short_round(number, name))
        _ink_rect, logical = layout.get_pixel_extents()
        edge = xs[index] - logical.width / 2
        far = edge + logical.width
        if placed and edge < placed[-1][1] + 6:
            if index != last:
                continue
            while placed and edge < placed[-1][1] + 6:
                placed.pop()
        placed.append((edge, far, layout))
    for edge, _far, layout in placed:
        cr.move_to(edge, label_y)
        PangoCairo.show_layout(cr, layout)


def _label_plan(rounds, names):
    count = len(rounds)
    chosen = []
    for index, (number, name) in enumerate(zip(rounds, names)):
        folded = name.casefold()
        notable = any(word in folded for word in ("final", "semi", "grand", "preliminary"))
        if index in (0, count - 1) or notable or number % 5 == 0:
            chosen.append((index, number, name))
    return chosen


def _show(area, cr, text, x, y, align, center_y: bool = False) -> None:
    layout = area.create_pango_layout(text)
    _ink_rect, logical = layout.get_pixel_extents()
    origin_x = x - logical.width if align == "end" else x
    origin_y = y - logical.height / 2 if center_y else y
    cr.move_to(origin_x, origin_y)
    PangoCairo.show_layout(cr, layout)


def _axis_limit(peak: float) -> tuple[float, float]:
    peak = max(peak, 1.0) * 1.1
    raw_step = peak / 2
    if raw_step <= 1:
        step = 1.0
    else:
        magnitude = 10 ** math.floor(math.log10(raw_step))
        step = 10 * magnitude
        for multiplier in (1, 2, 5, 10):
            if multiplier * magnitude >= raw_step - 1e-9:
                step = multiplier * magnitude
                break
    limit = math.ceil((peak / step) - 1e-9) * step
    return float(limit), float(step)


def _tick_label(tick: float) -> str:
    rounded = int(round(tick))
    return "0" if rounded == 0 else str(rounded)


def short_round(number: int, name: str) -> str:
    folded = name.casefold()
    if number == 0 or "opening" in folded:
        return "OR"
    if "wildcard" in folded:
        return "WF"
    if "grand" in folded:
        return "GF"
    if "preliminary" in folded:
        return "PF"
    if "semi" in folded:
        return "SF"
    if folded.startswith("finals"):
        tail = name.split()[-1]
        return f"FW{tail}" if tail.isdigit() else "FW"
    if "final" in folded:
        return "FW"
    if folded.startswith("round "):
        return name.split(" ", 1)[1]
    return str(number)


def series_color(kind: str, leader_index: int, team_id: int | None) -> tuple[float, float, float, float]:
    dark = _dark()
    if kind == "field":
        return (0.55, 0.56, 0.6, 0.95) if dark else (0.35, 0.36, 0.4, 0.9)
    if kind == "footy":
        return (0.94, 0.95, 0.96, 1.0) if dark else (0.12, 0.13, 0.15, 1.0)
    if leader_index <= 0:
        red, green, blue = _rgb(accent_for(team_id)[0])
        return red, green, blue, 1.0
    return _LEADER_EXTRAS[min(leader_index - 1, len(_LEADER_EXTRAS) - 1)]


def _ink() -> tuple[float, float, float, float]:
    if _dark():
        return (0.82, 0.83, 0.86, 0.8)
    return (0.22, 0.23, 0.26, 0.8)


def _dark() -> bool:
    return bool(Adw.StyleManager.get_default().get_dark())


def _rgb(hex_color: str) -> tuple[float, float, float]:
    text = hex_color.removeprefix("#")
    return tuple(int(text[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _round_rect(cr, x, y, width, height, radius) -> None:
    if width <= 0 or height <= 0:
        return
    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _clear_scale(rows, footy) -> float:
    clears = [abs(row.clear) for row in rows]
    if footy is not None:
        clears.append(abs(footy.clear))
    scale = max(clears, default=0.0)
    return scale if scale > 0 else 1.0


def _team_theme(controller) -> int | None:
    if controller.boot is None:
        return None
    return controller.boot.settings.team_theme


def _career(row) -> str | None:
    if row.career_accuracy is None or row.career_from is None:
        return None
    return f"{format_percent(row.career_accuracy)} since {row.career_from}"


def _stats(row) -> list[tuple[str, str]]:
    upsets = "–" if row.upset_chances == 0 else f"{row.upset_hits}/{row.upset_chances}"
    dissent = "–" if row.dissent_tips == 0 else format_percent(row.dissent_accuracy)
    return [
        ("Tips", str(row.tips)),
        ("Right", f"{row.correct}/{row.tips}"),
        ("Field", format_clear(row.clear)),
        ("Upsets", upsets),
        ("Dissent", dissent),
    ]


def _race_summary(board) -> str:
    parts = []
    for line in board.lines:
        if line.points:
            parts.append(f"{line.name} {format_clear(line.points[-1])}")
    if not parts:
        return ""
    parts.append("The dashed line is the median model.")
    return ". ".join(parts)


def _badge(text: str) -> Gtk.Widget:
    badge = pill(text, "gold")
    badge.set_valign(Gtk.Align.CENTER)
    return badge


def _mini(title: str, value: str) -> Gtk.Widget:
    box = Gtk.Box(spacing=6)
    box.append(label(title, "dim-label", "caption"))
    box.append(label(value, "figures"))
    return box


def _hero(row, sort: str) -> tuple[str, str]:
    if sort == "upset":
        value = "–" if row.upset_chances == 0 else format_percent(row.upset_accuracy, 1)
        return value, "upsets"
    if sort == "margin":
        if row.margin_error is None:
            return "–", "points"
        return to_fixed(row.margin_error, 1), "points"
    return format_percent(row.accuracy, 1), "right"
