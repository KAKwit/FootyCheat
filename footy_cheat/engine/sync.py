import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable

from .cutoff import FIRST_SEASON_YEAR, importable_year, season_span
from .parse import (
    logo_mime,
    logo_url,
    looks_like_image,
    parse_games,
    parse_sources,
    parse_standings,
    parse_teams,
    parse_tips,
)
from .store import Store
from .types import Progress, SeasonPhase, SyncMode, SyncReport

_RETRYABLE = {429, 500, 502, 503, 504}


class SyncStopped(Exception):
    def __str__(self) -> str:
        return "Stopped. What's already saved will be here next time."


class CancelToken:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def check(self) -> None:
        if self.cancelled:
            raise SyncStopped()


class Fetcher(ABC):
    @abstractmethod
    def get_json(self, query: str) -> object:
        """Fetch one Squiggle query string, without the leading URL."""

    @abstractmethod
    def get_bytes(self, url: str) -> bytes:
        """Fetch a logo or other binary URL."""

    def close(self) -> None:
        return None


class HttpFetcher(Fetcher):
    def __init__(self, user_agent: Callable[[], str]):
        self.user_agent = user_agent
        self._last: float | None = None

    def _pace(self) -> None:
        if self._last is not None:
            rest = 0.3 - (time.monotonic() - self._last)
            if rest > 0:
                time.sleep(rest)
        self._last = time.monotonic()

    def _send(self, url: str, accept: str) -> bytes:
        attempt = 0
        while True:
            attempt += 1
            self._pace()
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent(),
                    "Accept": accept,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    status = response.status
                    if 200 <= status < 300:
                        return response.read()
                    code = status
            except urllib.error.HTTPError as error:
                code = error.code
                if code not in _RETRYABLE or attempt != 1:
                    raise RuntimeError(f"Squiggle returned {code} for {url}") from error
            else:
                if code not in _RETRYABLE or attempt != 1:
                    raise RuntimeError(f"Squiggle returned {code} for {url}")
            time.sleep(5 if code == 429 else 2)

    def get_json(self, query: str) -> object:
        url = f"https://api.squiggle.com.au/?{query}"
        body = self._send(url, "application/json")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Bad JSON from {query}: {error}") from error

    def get_bytes(self, url: str) -> bytes:
        return self._send(url, "*/*")


def run_sync(
    store: Store,
    fetcher: Fetcher,
    mode: SyncMode,
    now_year: int,
    now: int,
    cancel: CancelToken,
    progress: Callable[[Progress], None],
) -> SyncReport:
    if mode in (SyncMode.SMART, SyncMode.FORCE):
        return _smart(store, fetcher, now_year, now, mode is SyncMode.FORCE, cancel, progress)
    return _fill(store, fetcher, now_year, now, mode is SyncMode.REBUILD, cancel, progress)


def _fill(
    store: Store,
    fetcher: Fetcher,
    now_year: int,
    now: int,
    rebuild: bool,
    cancel: CancelToken,
    progress: Callable[[Progress], None],
) -> SyncReport:
    if rebuild:
        store.set_import_complete(False)
        store.clear_year_sync()
    years = season_span(now_year)
    total = len(years) * 3 + 2
    done = 0

    cancel.check()
    _report(progress, "sources", done, total, "Model list")
    store.save_sources(parse_sources(fetcher.get_json("q=sources")))
    done += 1

    cancel.check()
    _report(progress, "teams", done, total, "Clubs and logos")
    store.save_teams(parse_teams(fetcher.get_json("q=teams")))
    done += 1
    _fetch_crests(store, fetcher, cancel)

    for year in years:
        if not importable_year(year):
            raise RuntimeError(
                f"Refusing to import {year}. Seasons before {FIRST_SEASON_YEAR} are not imported."
            )
        if store.year_is_complete(year):
            done += 3
            continue
        done = _fetch_year(store, fetcher, year, now, cancel, progress, done, total)

    _report(progress, "model", done, total, "Rating the models")
    store.recompute()
    store.set_import_complete(True)
    store.touch_sync(now, None)
    status = store.data_status(now_year)
    return SyncReport(
        action="imported",
        message=f"Stored {status.games} games and {status.tips} tips on this computer.",
        changed=True,
    )


def _fetch_year(
    store: Store,
    fetcher: Fetcher,
    year: int,
    now: int,
    cancel: CancelToken,
    progress: Callable[[Progress], None],
    done: int,
    total: int,
) -> int:
    if not importable_year(year):
        raise RuntimeError(
            f"Refusing to import {year}. Seasons before {FIRST_SEASON_YEAR} are not imported."
        )
    cancel.check()
    _report(progress, "games", done, total, f"Games {year}")
    games = parse_games(fetcher.get_json(f"q=games;year={year}"))
    kept_games = [game for game in games if importable_year(game.year) and game.year == year]
    store.replace_games(year, kept_games)
    store.mark_year(year, "games", len(kept_games), now)
    done += 1

    cancel.check()
    _report(progress, "tips", done, total, f"Tips {year}")
    tips = parse_tips(fetcher.get_json(f"q=tips;year={year}"))
    kept_tips = [
        tip
        for tip in tips
        if tip.year == 0 or (importable_year(tip.year) and tip.year == year)
    ]
    store.replace_tips(year, kept_tips)
    store.mark_year(year, "tips", len(kept_tips), now)
    done += 1

    cancel.check()
    _report(progress, "ladder", done, total, f"Ladder {year}")
    standings = parse_standings(fetcher.get_json(f"q=standings;year={year}"))
    store.replace_standings(year, standings)
    store.mark_year(year, "standings", len(standings), now)
    done += 1
    return done


def _smart(
    store: Store,
    fetcher: Fetcher,
    now_year: int,
    now: int,
    force: bool,
    cancel: CancelToken,
    progress: Callable[[Progress], None],
) -> SyncReport:
    if not store.import_complete():
        return SyncReport(
            action="not-ready",
            message="The full history isn't in yet.",
            changed=False,
        )
    phase = store.season_phase(now)
    last = store.last_sync_unix()
    if not force and not _is_stale(phase, last, now):
        return SyncReport(action="fresh", message="Already up to date.", changed=False)
    targets = _target_years(store, now_year, phase, force)
    total = len(targets) * 3 + 1
    done = 0
    cancel.check()
    _report(progress, "teams", done, total, "Clubs and logos")
    store.save_teams(parse_teams(fetcher.get_json("q=teams")))
    done += 1
    _fetch_crests(store, fetcher, cancel)
    changed = False
    for year in targets:
        cancel.check()
        done = _fetch_year(store, fetcher, year, now, cancel, progress, done, total)
        if store.count_games_in_year(year) > 0:
            changed = True
    if changed:
        _report(progress, "model", done, total, "Updating the tips")
        store.recompute()
    store.touch_sync(now, None)
    return SyncReport(
        action="updated" if changed else "checked",
        message="Saved the latest games and tips." if changed else "No new fixture yet.",
        changed=changed,
    )


def _is_stale(phase: SeasonPhase, last: int | None, now: int) -> bool:
    if last is None:
        return True
    window = 15 * 60 if phase in (SeasonPhase.LIVE, SeasonPhase.IN_SEASON) else 24 * 60 * 60
    return now - last >= window


def _target_years(store: Store, now_year: int, phase: SeasonPhase, force: bool) -> list[int]:
    latest = store.latest_season_year() or now_year
    incomplete = store.next_incomplete_year()
    if force and phase is SeasonPhase.OFF_SEASON:
        years = [latest, latest + 1]
    elif phase is SeasonPhase.OFF_SEASON:
        years = [latest + 1]
    else:
        years = [incomplete if incomplete is not None else latest]
    return [year for year in years if importable_year(year)]


def _fetch_crests(store: Store, fetcher: Fetcher, cancel: CancelToken) -> None:
    """Store a crest for every club that does not already have this exact file."""
    for team_id, path in store.teams_missing_logos():
        cancel.check()
        url = logo_url(path)
        if url is None:
            continue
        try:
            data = fetcher.get_bytes(url)
        except Exception:
            continue
        if data and looks_like_image(data):
            store.save_logo(team_id, data, logo_mime(path))


def _report(
    progress: Callable[[Progress], None],
    phase: str,
    done: int,
    total: int,
    message: str,
) -> None:
    progress(Progress(phase=phase, done=done, total=total, message=message))
