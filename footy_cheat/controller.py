import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime

from .engine.live import LiveSession
from .engine.parse import parse_live_scores
from .engine.store import Store
from .engine.sync import CancelToken, Fetcher, HttpFetcher, SyncStopped, run_sync
from .engine.time import civil_year
from .engine.types import (
    AppPage,
    Bootstrap,
    GameCard,
    ImportStatus,
    Ladder,
    ModelBoard,
    Progress,
    RoundInfo,
    RoundView,
    SeasonFocus,
    Settings,
    SyncMode,
    TipDetail,
)

_LIVE_BACKOFF_START = 2
_LIVE_BACKOFF_MAX = 60
_LIVE_STABLE_SECONDS = 30
_LIVE_WATCH_SECONDS = 60


class AppController:
    def __init__(
        self,
        store: Store,
        fetcher: Fetcher,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.fetcher = fetcher
        self._clock = clock or datetime.now
        self.listeners: list[Callable[[], None]] = []
        self.boot: Bootstrap | None = None
        self.page = AppPage.ROUND
        self.year: int | None = None
        self.round: int | None = None
        self.games: RoundView | None = None
        self.ladder: Ladder | None = None
        self.models: ModelBoard | None = None
        self.tips: dict[int, list[TipDetail]] = {}
        self.selected_id: int | None = None
        self.importing = False
        self.status: ImportStatus | None = None
        self.error: str | None = None
        self.notice: str | None = None
        self.busy = ""
        self._cancel: CancelToken | None = None
        self._running = False
        self._poll_id: int | None = None
        self._live: LiveSession | None = None
        self._live_running = False
        self._live_watch: int | None = None
        self._closed = False
        self._sleep = time.sleep

    def add_listener(self, listener: Callable[[], None]) -> None:
        self.listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        if listener in self.listeners:
            self.listeners.remove(listener)

    @property
    def now_unix(self) -> int:
        return int(self._clock().timestamp())

    def start(self) -> None:
        if self.store.import_complete() and not self.store.tip_rule_current():
            self.store.recompute()
        self._reload(select_focus=True)
        self._arm_live_watch()
        imported = False if self.boot is None else self.boot.status.imported
        if not imported:
            self.importing = True
            self._notify()
            self.start_import()
            return
        self._notify()
        self.refresh_if_needed()
        self.ensure_live()

    def start_import(self) -> None:
        self._spawn(SyncMode.FILL)

    def refresh_if_needed(self) -> None:
        if not self.store.import_complete():
            return
        self._spawn(SyncMode.SMART)

    def refresh_now(self) -> None:
        self._spawn(SyncMode.FORCE)

    def rebuild_all(self) -> None:
        self._spawn(SyncMode.REBUILD)

    def cancel_sync(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()

    def set_page(self, page: AppPage) -> None:
        self.page = page
        if page is AppPage.LADDER and self.year is not None:
            self.ladder = self.store.ladder(self.year)
        if page is AppPage.MODELS and self.year is not None:
            self.models = self.store.model_board(self.year)
        self._notify()

    def choose_year(self, year: int) -> None:
        self.year = year
        self.ladder = self.store.ladder(year) if self.page is AppPage.LADDER else None
        self.models = self.store.model_board(year) if self.page is AppPage.MODELS else None
        rounds = []
        if self.boot is not None:
            for season in self.boot.seasons:
                if season.year == year:
                    rounds = season.rounds
                    break
        if not rounds:
            self.round = None
            self.games = None
            self._notify()
            return
        focus = None if self.boot is None else self.boot.focus
        self.round = _open_round(rounds, year, focus)
        self._load_round(year, self.round)

    def choose_round(self, rnd: int) -> None:
        if self.year is None:
            return
        self.round = rnd
        self._load_round(self.year, rnd)

    def select_game(self, game_id: int) -> None:
        self.selected_id = game_id
        self._notify()
        if game_id not in self.tips:
            self.tips[game_id] = self.store.game_tips(game_id)
            self._notify()

    def move_game(self, delta: int) -> None:
        games = [] if self.games is None else self.games.games
        if not games:
            return
        index = next((i for i, game in enumerate(games) if game.id == self.selected_id), -1)
        if index < 0:
            nxt = 0
        else:
            nxt = min(len(games) - 1, max(0, index + delta))
        if nxt == index and index >= 0:
            return
        self.select_game(games[nxt].id)

    def move_round(self, delta: int) -> None:
        if self.year is None or self.round is None or self.boot is None:
            return
        rounds = None
        for season in self.boot.seasons:
            if season.year == self.year:
                rounds = season.rounds
                break
        if not rounds:
            return
        index = next((i for i, item in enumerate(rounds) if item.round == self.round), -1)
        if index < 0:
            return
        nxt = index + 1 if delta > 0 else index - 1
        if nxt < 0 or nxt >= len(rounds):
            return
        self.choose_round(rounds[nxt].round)

    def save(self, settings: Settings) -> None:
        current = self.store.load_settings() if self.boot is None else self.boot.settings.copy()
        current.theme = settings.theme
        current.font_size = settings.font_size
        current.team_theme = settings.team_theme
        current.contact_email = settings.contact_email
        self.store.save_settings(current)
        self.boot = self.store.bootstrap(self.now_unix)
        self._notify()

    def ensure_live(self) -> None:
        if self._closed or self._live_running:
            return
        if not self.store.game_starting_soon(self.now_unix):
            return
        email = self.store.load_settings().contact_email
        session = LiveSession()
        self._live = session
        self._live_running = True
        threading.Thread(
            target=self._run_live,
            args=(session, email),
            name="footy-live",
            daemon=True,
        ).start()

    def dispose(self) -> None:
        self._closed = True
        self._stop_poll()
        self._stop_live_watch()
        self.cancel_sync()
        if self._live is not None:
            self._live.close()
        self.fetcher.close()

    def _arm_live_watch(self) -> None:
        if self._closed or self._live_watch is not None:
            return
        from gi.repository import GLib

        self._live_watch = GLib.timeout_add_seconds(_LIVE_WATCH_SECONDS, self._watch_live)

    def _stop_live_watch(self) -> None:
        if self._live_watch is None:
            return
        from gi.repository import GLib

        GLib.source_remove(self._live_watch)
        self._live_watch = None

    def _watch_live(self) -> bool:
        if self._closed:
            self._live_watch = None
            return False
        self.ensure_live()
        return True

    def _run_live(self, session: LiveSession, email: str) -> None:
        delay = _LIVE_BACKOFF_START
        try:
            while not session.stop and not self._closed:
                started = time.monotonic()
                try:
                    session.run(email, lambda payload: self._on_live(payload))
                except Exception:
                    if session.stop or self._closed:
                        break
                else:
                    if session.stop or self._closed:
                        break
                if not self.store.game_starting_soon(self.now_unix):
                    break
                if time.monotonic() - started >= _LIVE_STABLE_SECONDS:
                    delay = _LIVE_BACKOFF_START
                self._sleep(delay)
                delay = min(delay * 2, _LIVE_BACKOFF_MAX)
        finally:
            if self._live is session:
                self._live = None
                self._live_running = False

    def _on_live(self, payload: object) -> None:
        scores = parse_live_scores(payload)
        finished = False
        for score in scores:
            if self.store.apply_live_score(score):
                finished = True
        if finished:
            self.store.recompute()
        if scores:
            self._schedule(self._reload_visible_round)

    def _spawn(self, mode: SyncMode) -> None:
        if self._running:
            self.notice = "An update is already running."
            self._notify()
            return
        self._running = True
        token = CancelToken()
        self._cancel = token
        if mode in (SyncMode.FILL, SyncMode.REBUILD):
            self.importing = True
        self.busy = "Checking for updates" if mode is SyncMode.FORCE else "Starting"
        self.error = None
        self._publish_status()
        self._stop_poll()
        self._start_poll()
        threading.Thread(
            target=self._run_sync,
            args=(mode, token),
            name="footy-sync",
            daemon=True,
        ).start()

    def _run_sync(self, mode: SyncMode, token: CancelToken) -> None:
        error: str | None = None
        try:
            run_sync(
                store=self.store,
                fetcher=self.fetcher,
                mode=mode,
                now_year=civil_year(self.now_unix),
                now=self.now_unix,
                cancel=token,
                progress=lambda progress: self._schedule(
                    lambda progress=progress: self._on_progress(progress)
                ),
            )
        except Exception as err:
            if not isinstance(err, SyncStopped):
                traceback.print_exc()
            error = str(err)
            self.store.touch_sync(self.now_unix, error)
        self._schedule(lambda error=error: self._finish_sync(error))

    def _on_progress(self, progress: Progress) -> None:
        self.busy = progress.message
        self._publish_status(progress)

    def _finish_sync(self, error: str | None) -> None:
        self._running = False
        self._stop_poll()
        self.busy = ""
        self.error = error
        self._reload(select_focus=self.importing or self.year is None)
        self.importing = not (False if self.boot is None else self.boot.status.imported)
        self.models = None
        self.ladder = None
        if self.page is AppPage.LADDER and self.year is not None:
            self.ladder = self.store.ladder(self.year)
        if self.page is AppPage.MODELS and self.year is not None:
            self.models = self.store.model_board(self.year)
        self._publish_status()
        self.ensure_live()

    def _reload(self, select_focus: bool) -> None:
        previous_year = self.year
        previous_round = self.round
        self.boot = self.store.bootstrap(self.now_unix)
        if select_focus and self.boot.focus is not None:
            self.year = self.boot.focus.year
            self.round = self.boot.focus.round
            self._load_round(self.year, self.round, notify=False)
        elif previous_year is not None and previous_round is not None:
            self.year = previous_year
            self.round = previous_round
            self._load_round(previous_year, previous_round, notify=False)

    def _load_round(self, year: int, rnd: int, notify: bool = True) -> None:
        view = self.store.round_view(year, rnd)
        self.games = view
        still_there = self.selected_id is not None and any(
            game.id == self.selected_id for game in view.games
        )
        if not still_there:
            pick = _pick_game(view.games)
            self.selected_id = None if pick is None else pick.id
        if self.selected_id is not None and self.selected_id not in self.tips:
            self.tips[self.selected_id] = self.store.game_tips(self.selected_id)
        if notify:
            self._notify()

    def _reload_visible_round(self) -> None:
        if self.year is not None and self.round is not None:
            self._load_round(self.year, self.round)
        else:
            self._notify()

    def _publish_status(self, progress: Progress | None = None) -> None:
        data = self.store.data_status(civil_year(self.now_unix))
        stored_error = None if not (data.last_error or "") else data.last_error
        previous = self.status
        self.status = ImportStatus(
            imported=data.imported,
            running=self._running,
            games=data.games,
            tips=data.tips,
            years_done=data.years_done,
            years_total=data.years_total,
            last_sync=data.last_sync,
            error=self.error if self.error is not None else stored_error,
            phase=progress.phase if progress is not None else (previous.phase if previous else "start"),
            done=progress.done if progress is not None else (previous.done if previous else 0),
            total=progress.total if progress is not None else (previous.total if previous else 0),
            message=(
                progress.message
                if progress is not None
                else (self.busy or (previous.message if previous else "Starting"))
            ),
        )
        if not self._closed:
            self._notify()

    def _notify(self) -> None:
        if self._closed:
            return
        for listener in list(self.listeners):
            listener()

    def _schedule(self, fn: Callable[[], None]) -> None:
        if threading.current_thread() is threading.main_thread():
            fn()
            return
        from gi.repository import GLib

        GLib.idle_add(_idle, fn)

    def _start_poll(self) -> None:
        from gi.repository import GLib

        self._poll_id = GLib.timeout_add_seconds(1, self._poll)

    def _stop_poll(self) -> None:
        if self._poll_id is None:
            return
        from gi.repository import GLib

        GLib.source_remove(self._poll_id)
        self._poll_id = None

    def _poll(self) -> bool:
        if not self._running:
            self._poll_id = None
            return False
        self._publish_status()
        return True


def _idle(fn: Callable[[], None]) -> bool:
    fn()
    return False


def _open_round(rounds: list[RoundInfo], year: int, focus: SeasonFocus | None) -> int:
    if focus is not None and focus.year == year:
        for item in rounds:
            if item.round == focus.round:
                return focus.round
    for item in rounds:
        if item.completed < item.games:
            return item.round
    return rounds[-1].round


def _pick_game(games: list[GameCard]) -> GameCard | None:
    for game in games:
        if 0 < game.complete < 100:
            return game
    for game in games:
        if game.complete < 100:
            return game
    return games[0] if games else None
