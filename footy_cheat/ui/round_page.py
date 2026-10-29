import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from ..controller import AppController
from ..format import (
    format_confidence,
    format_margin,
    ordinal,
    team_side_name,
)
from .widgets import (
    Crests,
    PageHeader,
    YearMenu,
    centre_line,
    clear,
    empty_pane,
    grouped_days,
    label,
    outcome,
    pill,
    pin_viewports,
    ribbon,
    scrolled,
)


class _GameRow(Gtk.ListBoxRow):
    def __init__(self, game_id: int, day: str):
        super().__init__()
        self.game_id = game_id
        self.day = day


class RoundPage(Gtk.Box):
    def __init__(self, controller: AppController, crests: Crests):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.controller = controller
        self.crests = crests
        self._stacked = True
        self._side = False
        self._inspector = False
        self._structure_sig = None
        self._selection_sig = None
        self._queued = False
        self._round_key = None
        self._cards: dict[int, Gtk.Box] = {}
        self._rows: dict[int, _GameRow] = {}
        self._list: Gtk.ListBox | None = None
        self._selecting = False
        self._inline_tip: Gtk.Widget | None = None
        self._inspector_host: Gtk.Box | None = None
        self._tips_inline = True
        self.header = PageHeader()
        self.prev = Gtk.Button(icon_name="go-previous-symbolic")
        self.prev.set_tooltip_text("Previous round")
        self.prev.connect("clicked", lambda *_: controller.move_round(-1))
        self.nxt = Gtk.Button(icon_name="go-next-symbolic")
        self.nxt.set_tooltip_text("Next round")
        self.nxt.connect("clicked", lambda *_: controller.move_round(1))
        self.years = YearMenu(controller.choose_year)
        self.header.actions.append(self.prev)
        self.header.actions.append(self.nxt)
        self.header.actions.append(self.years)
        self.header.subtitle.set_wrap(True)
        self.header.subtitle.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.bin = Adw.BreakpointBin()
        self.bin.set_vexpand(True)
        self.bin.set_size_request(1, 1)
        self.bin.set_child(Gtk.Box())
        for condition in ("min-width: 560px", "min-width: 860px", "min-width: 1120px"):
            point = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(condition))
            point.connect("apply", self._sync_layout)
            point.connect("unapply", self._sync_layout)
            self.bin.add_breakpoint(point)
        self.append(self.header)
        self.append(self.bin)
        self._scroll = None
        self._round_scroll = None

    def _sync_layout(self, *_args) -> None:
        width = self.bin.get_width()
        if width <= 0:
            return
        stacked = width < 560
        side = width >= 860
        inspector = width >= 1120
        if (self._stacked, self._side, self._inspector) == (stacked, side, inspector):
            return
        self._stacked = stacked
        self._side = side
        self._inspector = inspector
        self._structure_sig = None
        self._queue()

    def _queue(self) -> None:
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
        games = [] if controller.games is None else controller.games.games
        done = sum(1 for game in games if game.complete >= 100)
        subtitle = "No games fixtured" if not games else f"{done} of {len(games)} complete"
        note = self._season_note()
        if note:
            subtitle = f"{subtitle}. {note}"
        title = controller.games.round_name if controller.games is not None else "Games"
        if controller.year is not None:
            title = f"{controller.year} {title}"
        self.header.set_heading(title, subtitle)
        structure = self._structure()
        selection = self._selection()
        if structure == self._structure_sig and self._cards:
            if selection != self._selection_sig:
                self._selection_sig = selection
                self._retarget()
            return
        same_round = self._round_key == (controller.year, controller.round)
        same_year = self._round_key is not None and self._round_key[0] == controller.year
        self._round_key = (controller.year, controller.round)
        scroll_value = _scroll_value(self._scroll) if same_round else 0.0
        round_value = _scroll_value(self._round_scroll) if same_year else 0.0
        self._structure_sig = structure
        self._selection_sig = selection
        self._scroll = None
        self._round_scroll = None
        self._list = None
        self._cards = {}
        self._rows = {}
        self._inline_tip = None
        self._inspector_host = None
        self.bin.set_child(self._body())
        self._retarget()
        if self._scroll is not None and same_round:
            GLib.idle_add(self._restore, self._scroll, scroll_value, 0)
        if self._round_scroll is not None and same_year:
            GLib.idle_add(self._restore, self._round_scroll, round_value, 0)

    def _season_note(self) -> str:
        controller = self.controller
        focus = None if controller.boot is None else controller.boot.focus
        if (
            focus is not None
            and focus.out_of_season
            and focus.year == controller.year
            and focus.round == controller.round
            and focus.subtitle
        ):
            return focus.subtitle
        return ""

    def _restore(self, window: Gtk.ScrolledWindow, value: float, tries: int) -> bool:
        if window.get_parent() is None:
            return False
        adjustment = _adjustment(window)
        upper = max(0, adjustment.get_upper() - adjustment.get_page_size())
        if value > 0 and upper + 1 < value and tries < 8:
            GLib.timeout_add(16, self._restore, window, value, tries + 1)
            return False
        adjustment.set_value(min(value, upper))
        return False

    def _structure(self):
        controller = self.controller
        games = [] if controller.games is None else controller.games.games
        teams = [] if controller.boot is None else controller.boot.teams
        seasons = [] if controller.boot is None else controller.boot.seasons
        return (
            controller.year,
            controller.round,
            self._stacked,
            self._side,
            self._inspector,
            tuple(
                (
                    game.id,
                    game.complete,
                    game.home_score,
                    game.away_score,
                    game.winner_id,
                    game.timestr,
                    game.is_final,
                    game.is_grand_final,
                    None
                    if game.call is None
                    else (game.call.pick_team_id, game.call.confidence, game.call.summary),
                )
                for game in games
            ),
            tuple((team.id, len(team.logo_bytes or b"")) for team in teams),
            tuple((season.year, tuple(item.round for item in season.rounds)) for season in seasons),
        )

    def _selection(self):
        controller = self.controller
        tips = None if controller.selected_id is None else controller.tips.get(controller.selected_id)
        tip_sig = None if tips is None else tuple(
            (tip.source_id, tip.tip, tip.confidence, tip.margin, tip.year_rank) for tip in tips
        )
        return controller.selected_id, tip_sig

    def _selected_game(self):
        games = [] if self.controller.games is None else self.controller.games.games
        for game in games:
            if game.id == self.controller.selected_id:
                return game
        return None

    def _retarget(self) -> None:
        selected = self.controller.selected_id
        anchor = self._viewport_anchor()
        if self._inline_tip is not None:
            parent = self._inline_tip.get_parent()
            if parent is not None:
                parent.remove(self._inline_tip)
            self._inline_tip = None
        for game_id, card in self._cards.items():
            if game_id == selected:
                card.add_css_class("selected")
                card.set_name("selected-game")
            else:
                card.remove_css_class("selected")
                if card.get_name() == "selected-game":
                    card.set_name("")
        game = self._selected_game()
        if (
            self._tips_inline
            and game is not None
            and game.call is not None
            and selected in self._cards
        ):
            tip = self._tip_body(game)
            self._cards[selected].append(tip)
            self._inline_tip = tip
        row = None if selected is None else self._rows.get(selected)
        if self._list is not None:
            current = self._list.get_selected_row()
            if current is not row:
                self._selecting = True
                if row is None:
                    self._list.unselect_all()
                else:
                    self._list.select_row(row)
                self._selecting = False
        if self._inspector_host is not None:
            clear(self._inspector_host)
            if game is not None and game.call is not None:
                inspector = scrolled(self._tip_inspector(game))
                inspector.set_propagate_natural_width(False)
                self._inspector_host.append(inspector)
            else:
                note = label("No model tips for this game", "dim-label", wrap=True)
                note.set_margin_top(18)
                note.set_margin_start(16)
                note.set_margin_end(18)
                self._inspector_host.append(note)
        if anchor is not None:
            GLib.idle_add(self._restore_anchor, anchor[0], anchor[1], 0, None)

    def _viewport_anchor(self) -> tuple[int, float] | None:
        content = _content(self._scroll)
        if content is None or self._scroll is None:
            return None
        top = self._scroll.get_vadjustment().get_value()
        chosen: tuple[float, int, float] | None = None
        for game_id, card in self._cards.items():
            if card.get_height() <= 0:
                continue
            try:
                success, rect = card.compute_bounds(content)
            except Exception:
                continue
            if not success:
                continue
            y = rect.get_y()
            if y + card.get_height() <= top:
                continue
            if chosen is None or y < chosen[0]:
                chosen = (y, game_id, y - top)
        if chosen is None:
            return None
        return chosen[1], chosen[2]

    def _restore_anchor(
        self,
        game_id: int,
        offset: float,
        tries: int,
        previous: float | None,
    ) -> bool:
        content = _content(self._scroll)
        card = self._cards.get(game_id)
        if content is None or card is None or self._scroll is None or card.get_parent() is None:
            return False
        if card.get_height() <= 0 and tries < 8:
            GLib.timeout_add(16, self._restore_anchor, game_id, offset, tries + 1, previous)
            return False
        try:
            success, rect = card.compute_bounds(content)
        except Exception:
            return False
        if not success:
            return False
        adjustment = self._scroll.get_vadjustment()
        upper = max(0, adjustment.get_upper() - adjustment.get_page_size())
        target = min(max(0, rect.get_y() - offset), upper)
        adjustment.set_value(target)
        if tries < 6 and (previous is None or abs(target - previous) > 0.5):
            GLib.timeout_add(16, self._restore_anchor, game_id, offset, tries + 1, target)
        return False

    def _body(self) -> Gtk.Widget:
        controller = self.controller
        rounds = []
        if controller.boot is not None:
            for season in controller.boot.seasons:
                if season.year == controller.year:
                    rounds = season.rounds
                    break
        games = [] if controller.games is None else controller.games.games
        self._tips_inline = not (self._side and self._inspector)
        if not games and controller.games is None:
            return empty_pane(
                "x-office-calendar-symbolic",
                "Opening the round",
                "Reading the games stored on this computer.",
            )
        board = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        board.set_hexpand(True)
        if not self._side:
            board.append(self._strip(rounds))
        if not games:
            board.append(
                empty_pane(
                    "appointment-missed-symbolic",
                    "Nothing fixtured",
                    "Nothing is fixtured for this round.",
                )
            )
            return self._wrap(board, rounds)
        games_list = Gtk.ListBox()
        games_list.add_css_class("games")
        games_list.add_css_class("fixture-list")
        games_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        games_list.set_focusable(False)
        games_list.set_header_func(self._day_header)
        games_list.update_property([Gtk.AccessibleProperty.LABEL], ["Fixtures"])
        games_list.connect("row-selected", self._row_selected)
        self._list = games_list
        teams = [] if controller.boot is None else controller.boot.teams
        self._selecting = True
        for day, day_games in grouped_days(games):
            for game in day_games:
                games_list.append(self._row(game, teams, day))
        self._selecting = False
        self._scroll = scrolled(games_list)
        board.append(self._scroll)
        return self._wrap(board, rounds)

    def _day_header(self, row: _GameRow, before: _GameRow | None) -> None:
        if before is not None and before.day == row.day:
            row.set_header(None)
            return
        row.set_header(label(row.day, "day-heading"))

    def _row_selected(self, _box, row: _GameRow | None) -> None:
        if self._selecting or row is None:
            return
        if row.game_id != self.controller.selected_id:
            self.controller.select_game(row.game_id)

    def _wrap(self, board: Gtk.Widget, rounds) -> Gtk.Widget:
        if not self._side:
            return board
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.set_hexpand(False)
        side.add_css_class("round-column")
        side_scroll = scrolled(self._round_list(rounds))
        side_scroll.set_propagate_natural_width(True)
        self._round_scroll = side_scroll
        side.append(side_scroll)
        if self._inspector:
            pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            pane.set_vexpand(True)
            pane.set_size_request(_TIP_MIN, -1)
            pane.add_css_class("inspector-column")
            self._inspector_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self._inspector_host.set_vexpand(True)
            pane.append(self._inspector_host)
            return _TipSplit(side, board, pane)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.append(side)
        row.append(board)
        return row

    def _round_list(self, rounds) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("round-list")
        for item in rounds:
            button = Gtk.Button()
            button.set_focus_on_click(False)
            button.set_has_frame(item.round == self.controller.round)
            if item.round == self.controller.round:
                button.add_css_class("suggested-action")
            else:
                button.add_css_class("flat")
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.set_hexpand(True)
            name = label(item.name, xalign=0)
            name.set_hexpand(True)
            name.set_width_chars(18)
            text.append(name)
            text.append(label(f"{item.completed} of {item.games}", "dim-label", "caption"))
            button.set_hexpand(True)
            button.set_child(text)
            button.connect("clicked", lambda _b, rnd=item.round: self.controller.choose_round(rnd))
            box.append(button)
        return box

    def _strip(self, rounds) -> Gtk.Widget:
        box = Gtk.Box(spacing=6)
        box.set_margin_start(20)
        box.set_margin_end(20)
        for item in rounds:
            button = Gtk.Button(label=item.name)
            button.set_focus_on_click(False)
            if item.round == self.controller.round:
                button.add_css_class("suggested-action")
            else:
                button.add_css_class("flat")
            button.connect("clicked", lambda _b, rnd=item.round: self.controller.choose_round(rnd))
            box.append(button)
        window = Gtk.ScrolledWindow()
        window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        window.set_propagate_natural_width(False)
        window.set_child(box)
        pin_viewports(window)
        self._round_scroll = window
        return window

    def _row(self, game, teams, day: str) -> _GameRow:
        row = _GameRow(game.id, day)
        row.set_focusable(False)
        row.set_cursor_from_name("pointer")
        row.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"{game.home_name} versus {game.away_name}"],
        )
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("match")
        card.append(self._status_row(game))
        card.append(self._scoreboard(game, teams))
        if game.call is None:
            card.append(label("No model tips for this game", "dim-label"))
        else:
            card.append(self._call_footer(game))
        row.set_child(card)
        self._cards[game.id] = card
        self._rows[game.id] = row
        return row

    def _status_row(self, game) -> Gtk.Widget:
        row = Gtk.Box(spacing=8)
        text, tone = ribbon(game)
        row.append(pill(text, tone))
        if game.is_grand_final:
            row.append(pill("Grand Final", "gold"))
        elif game.is_final:
            row.append(pill("Final", "gold"))
        if game.venue:
            venue = label(game.venue, "dim-label", "caption", xalign=1, ellipsize=True)
            venue.set_hexpand(True)
            row.append(venue)
        return row

    def _scoreboard(self, game, teams) -> Gtk.Widget:
        if self._stacked:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.append(self._stacked_side(game, teams, home=True))
            box.append(self._stacked_side(game, teams, home=False))
        else:
            # CenterBox keeps the score dash on the card midline regardless of
            # how long each club name is.
            row = Gtk.CenterBox()
            row.set_start_widget(self._wide_side(game, teams, home=True))
            scores = Gtk.Box(spacing=8)
            scores.set_valign(Gtk.Align.CENTER)
            home = label("–" if game.home_score is None else str(game.home_score), "score")
            home.set_width_chars(4)
            home.set_xalign(1)
            mark = label("–" if game.complete > 0 else "v", "dim-label")
            mark.set_xalign(0.5)
            away = label("–" if game.away_score is None else str(game.away_score), "score")
            away.set_width_chars(4)
            away.set_xalign(0)
            scores.append(home)
            scores.append(mark)
            scores.append(away)
            row.set_center_widget(scores)
            row.set_end_widget(self._wide_side(game, teams, home=False))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.append(row)
        line = centre_line(game)
        if line:
            box.append(label(line, "dim-label"))
        return box

    def _wide_side(self, game, teams, home: bool) -> Gtk.Widget:
        name = game.home_name if home else game.away_name
        team_id = game.home_id if home else game.away_id
        won = game.complete >= 100 and game.winner_id == team_id
        pending = game.complete < 100
        classes = ["heading"] if won or pending else ["dim-label"]
        text = label(name, *classes, xalign=1 if home else 0, ellipsize=True)
        text.set_hexpand(True)
        crest = self.crests.widget(team_id, name, teams, 50)
        row = Gtk.Box(spacing=10)
        row.set_valign(Gtk.Align.CENTER)
        if home:
            row.append(text)
            row.append(crest)
        else:
            row.append(crest)
            row.append(text)
        return row

    def _stacked_side(self, game, teams, home: bool) -> Gtk.Widget:
        name = game.home_name if home else game.away_name
        team_id = game.home_id if home else game.away_id
        score = game.home_score if home else game.away_score
        won = game.complete >= 100 and game.winner_id == team_id
        pending = game.complete < 100
        classes = ["heading"] if won or pending else ["dim-label"]
        row = Gtk.Box(spacing=10)
        row.append(self.crests.widget(team_id, name, teams, 50))
        text = label(name, *classes, ellipsize=True)
        text.set_hexpand(True)
        row.append(text)
        row.append(label("–" if score is None else str(score), "score"))
        return row

    def _call_footer(self, game) -> Gtk.Widget:
        call = game.call
        pick = team_side_name(call.pick_team_id, game.home_id, game.home_name, game.away_id, game.away_name)
        consensus = team_side_name(
            call.consensus_team_id, game.home_id, game.home_name, game.away_id, game.away_name
        )
        vote = f" · {call.consensus_votes} of {call.models_used}" if call.models_used else ""
        mark, tone = outcome(game)
        row = Gtk.Box(spacing=8)
        summary = Gtk.Box(spacing=8)
        summary.set_hexpand(True)
        summary.append(label("Footy Cheat", "dim-label"))
        summary.append(label(pick, "heading", ellipsize=True))
        percent = label(f"{int(call.confidence)}%", "confidence")
        summary.append(percent)
        row.append(summary)
        row.append(pill(mark, tone))
        bar = Gtk.ProgressBar(fraction=max(0, min(1, call.confidence / 100)))
        bar.add_css_class("thin")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(row)
        box.append(bar)
        box.append(label(f"Consensus {consensus}{vote}", "dim-label", "caption"))
        return box

    def _tip_inspector(self, game) -> Gtk.Widget:
        call = game.call
        teams = [] if self.controller.boot is None else self.controller.boot.teams
        pick = team_side_name(call.pick_team_id, game.home_id, game.home_name, game.away_id, game.away_name)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(16)
        box.set_margin_end(18)
        box.append(label("TIP", "dim-label", "caption"))
        row = Gtk.Box(spacing=12)
        row.append(self.crests.widget(call.pick_team_id or 0, pick, teams, 40))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        text.append(label(pick, "title-2", wrap=True))
        text.append(label(f"{int(call.confidence)}% confidence", "confidence", "figures"))
        row.append(text)
        box.append(row)
        box.append(self._tip_body(game))
        return box

    def _tip_body(self, game) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(label(game.call.summary, wrap=True))
        box.append(label("MODELS", "dim-label", "caption"))
        tips = self.controller.tips.get(game.id)
        if tips is None:
            box.append(label("Loading tips…", "dim-label"))
        elif not tips:
            box.append(label("No individual tips stored.", "dim-label"))
        else:
            for tip in tips:
                box.append(self._tip_row(game, tip))
        return box

    def _tip_row(self, game, tip) -> Gtk.Widget:
        settled = game.complete >= 100
        right = settled and game.winner_id is not None and tip.tip_team_id == game.winner_id
        rank = "No games this year" if tip.year_rank is None else f"{ordinal(tip.year_rank)} this year"
        detail = rank
        confidence = format_confidence(tip.confidence)
        if confidence:
            detail += f" · {confidence}"
        margin = format_margin(tip.margin)
        if margin:
            detail += f" · {margin}"
        row = Gtk.Box(spacing=6)
        if settled:
            icon = Gtk.Image.new_from_icon_name(
                "object-select-symbolic" if right else "window-close-symbolic"
            )
            icon.set_pixel_size(16)
            icon.set_valign(Gtk.Align.CENTER)
            icon.add_css_class("mark")
            icon.add_css_class("right" if right else "wrong")
            icon.set_tooltip_text("Right" if right else "Wrong")
            row.append(icon)
        name = label(tip.name, "heading", ellipsize=True)
        name.set_hexpand(True)
        row.append(name)
        tip_classes = ["heading"]
        if settled:
            tip_classes.append("success" if right else "error")
        choice = label(tip.tip, *tip_classes, xalign=1, ellipsize=True)
        row.append(choice)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_bottom(8)
        box.append(row)
        box.append(label(detail, "dim-label", "caption"))
        return box


# The tip column stays at this width until a share of the space beside the
# round list would be wider. The match keeps the rest.
_TIP_MIN = 320
_TIP_SHARE = 0.32


def _column_widths(total: int, round_nat: int, round_min: int) -> tuple[int, int, int]:
    round_w = max(0, round_nat)
    flexible = max(0, total - round_w)
    tip_w = max(_TIP_MIN, int(flexible * _TIP_SHARE))
    if tip_w > flexible:
        round_w = min(round_w, max(0, round_min))
        flexible = max(0, total - round_w)
        tip_w = min(max(_TIP_MIN, int(flexible * _TIP_SHARE)), flexible)
    match_w = max(0, total - round_w - tip_w)
    return round_w, match_w, tip_w


class _TipSplitLayout(Gtk.LayoutManager):
    def do_measure(self, widget, orientation, for_size):
        rounds, match, tip = widget.rounds, widget.match, widget.tip
        if rounds is None or match is None or tip is None:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.HORIZONTAL:
            widths = [child.measure(orientation, for_size) for child in (rounds, match, tip)]
            minimum = widths[0][0] + widths[1][0] + max(widths[2][0], _TIP_MIN)
            natural = widths[0][1] + widths[1][1] + max(widths[2][1], _TIP_MIN)
            return minimum, natural, -1, -1
        if for_size < 0:
            heights = [child.measure(orientation, -1) for child in (rounds, match, tip)]
        else:
            round_min, round_nat, _baseline, _natural_baseline = rounds.measure(
                Gtk.Orientation.HORIZONTAL, -1
            )
            round_w, match_w, tip_w = _column_widths(for_size, round_nat, round_min)
            heights = [
                rounds.measure(orientation, round_w),
                match.measure(orientation, match_w),
                tip.measure(orientation, tip_w),
            ]
        return max(item[0] for item in heights), max(item[1] for item in heights), -1, -1

    def do_allocate(self, widget, width, height, baseline):
        rounds, match, tip = widget.rounds, widget.match, widget.tip
        if rounds is None or match is None or tip is None:
            return
        round_min, round_nat, _baseline, _natural_baseline = rounds.measure(
            Gtk.Orientation.HORIZONTAL, height
        )
        round_w, match_w, tip_w = _column_widths(width, round_nat, round_min)
        _place(rounds, 0, 0, round_w, height, baseline)
        _place(match, round_w, 0, match_w, height, baseline)
        _place(tip, round_w + match_w, 0, tip_w, height, baseline)


class _TipSplit(Gtk.Widget):
    def __init__(self, rounds: Gtk.Widget, match: Gtk.Widget, tip: Gtk.Widget):
        super().__init__()
        self.rounds = rounds
        self.match = match
        self.tip = tip
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_layout_manager(_TipSplitLayout())
        rounds.set_parent(self)
        match.set_parent(self)
        tip.set_parent(self)

    def do_dispose(self):
        for name in ("rounds", "match", "tip"):
            child = getattr(self, name)
            if child is not None:
                child.unparent()
                setattr(self, name, None)
        Gtk.Widget.do_dispose(self)


def _place(child: Gtk.Widget, x: int, y: int, width: int, height: int, baseline: int) -> None:
    allocation = Gdk.Rectangle()
    allocation.x = x
    allocation.y = y
    allocation.width = max(0, width)
    allocation.height = max(0, height)
    child.size_allocate(allocation, baseline)


def _adjustment(window: Gtk.ScrolledWindow) -> Gtk.Adjustment:
    horizontal, vertical = window.get_policy()
    if horizontal != Gtk.PolicyType.NEVER and vertical == Gtk.PolicyType.NEVER:
        return window.get_hadjustment()
    return window.get_vadjustment()


def _content(window: Gtk.ScrolledWindow | None) -> Gtk.Widget | None:
    if window is None:
        return None
    child = window.get_child()
    if isinstance(child, Gtk.Viewport):
        return child.get_child()
    return child


def _scroll_value(window: Gtk.ScrolledWindow | None) -> float:
    if window is None:
        return 0.0
    return _adjustment(window).get_value()

