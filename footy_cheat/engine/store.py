import sqlite3
import threading
from pathlib import Path

from .cutoff import FIRST_SEASON_YEAR, importable_year, refuse_old, years_total

# A game inside this window of its start, either side, keeps the live stream open.
LIVE_WINDOW_SECONDS = 6 * 3600
from .model import (
    FOOTY_NAME,
    TIPPING_RULE_REVISION,
    GameIn,
    TipIn,
    analyse,
    field_median,
    games_clear,
    is_aggregate_source,
    running_clear,
    season_record,
    side_margin_error,
)
from .parse import (
    LiveScore,
    ParsedGame,
    ParsedSource,
    ParsedStanding,
    ParsedTeam,
    ParsedTip,
)
from .time import civil_year
from .types import (
    Bootstrap,
    CallView,
    DataStatus,
    GameCard,
    Ladder,
    LadderRow,
    ModelBoard,
    ModelRow,
    RoundInfo,
    RoundView,
    SeasonFocus,
    SeasonInfo,
    SeasonPhase,
    Settings,
    TeamInfo,
    TipDetail,
)

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        abbrev TEXT NOT NULL,
        logo TEXT NOT NULL,
        debut INTEGER,
        retirement INTEGER,
        logo_blob BLOB,
        logo_mime TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        icon TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY,
        year INTEGER NOT NULL,
        round INTEGER NOT NULL,
        roundname TEXT NOT NULL,
        hteam_id INTEGER NOT NULL,
        ateam_id INTEGER NOT NULL,
        hteam TEXT NOT NULL,
        ateam TEXT NOT NULL,
        hscore INTEGER,
        ascore INTEGER,
        hgoals INTEGER,
        hbehinds INTEGER,
        agoals INTEGER,
        abehinds INTEGER,
        complete INTEGER NOT NULL,
        winner_team_id INTEGER,
        winner TEXT,
        venue TEXT,
        date TEXT,
        localtime TEXT,
        unixtime INTEGER NOT NULL,
        tz TEXT,
        updated TEXT,
        timestr TEXT,
        is_final INTEGER NOT NULL,
        is_grand_final INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_games_year_round ON games(year, round)",
    "CREATE INDEX IF NOT EXISTS idx_games_unixtime ON games(unixtime)",
    """
    CREATE TABLE IF NOT EXISTS tips (
        game_id INTEGER NOT NULL,
        source_id INTEGER NOT NULL,
        year INTEGER NOT NULL,
        round INTEGER NOT NULL,
        tip_team_id INTEGER NOT NULL,
        tip TEXT NOT NULL,
        hteam TEXT,
        ateam TEXT,
        hteam_id INTEGER,
        ateam_id INTEGER,
        confidence REAL,
        hconfidence REAL,
        margin REAL,
        hmargin REAL,
        err REAL,
        bits REAL,
        api_correct INTEGER,
        date TEXT,
        venue TEXT,
        updated TEXT,
        PRIMARY KEY (game_id, source_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tips_year ON tips(year)",
    """
    CREATE TABLE IF NOT EXISTS standings (
        year INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        rank INTEGER NOT NULL,
        name TEXT NOT NULL,
        played INTEGER NOT NULL,
        wins INTEGER NOT NULL,
        losses INTEGER NOT NULL,
        draws INTEGER NOT NULL,
        points INTEGER NOT NULL,
        percentage REAL NOT NULL,
        points_for INTEGER NOT NULL,
        points_against INTEGER NOT NULL,
        goals_for INTEGER,
        goals_against INTEGER,
        behinds_for INTEGER,
        behinds_against INTEGER,
        PRIMARY KEY (year, team_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS year_sync (
        year INTEGER NOT NULL,
        kind TEXT NOT NULL,
        rows INTEGER NOT NULL,
        fetched_at INTEGER NOT NULL,
        PRIMARY KEY (year, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS calls (
        game_id INTEGER PRIMARY KEY,
        pick_team_id INTEGER,
        confidence REAL NOT NULL,
        consensus_team_id INTEGER,
        consensus_votes INTEGER NOT NULL,
        models_used INTEGER NOT NULL,
        followed_consensus INTEGER NOT NULL,
        result_was_upset INTEGER,
        summary TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_stats (
        source_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        tips INTEGER NOT NULL,
        correct INTEGER NOT NULL,
        accuracy REAL NOT NULL,
        recent_tips INTEGER NOT NULL,
        recent_correct INTEGER NOT NULL,
        recent_accuracy REAL NOT NULL,
        upset_chances INTEGER NOT NULL,
        upset_hits INTEGER NOT NULL,
        upset_accuracy REAL NOT NULL,
        dissent_tips INTEGER NOT NULL,
        dissent_correct INTEGER NOT NULL,
        dissent_accuracy REAL NOT NULL,
        score REAL NOT NULL
    )
    """,
]


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


class Store:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.updated_rows = 0
        self._lock = threading.RLock()
        with self._lock:
            self._migrate()
            self.purge_before_cutoff()
            self.purge_aggregate()

    @staticmethod
    def open_file(path: str | Path) -> "Store":
        db = _connect(str(path))
        db.execute("PRAGMA busy_timeout = 8000")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
        return Store(db)

    @staticmethod
    def open_memory() -> "Store":
        return Store(_connect(":memory:"))

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def _migrate(self) -> None:
        for sql in _SCHEMA:
            self.db.execute(sql)
        columns = {
            row["name"] for row in self.db.execute("PRAGMA table_info(source_stats)")
        }
        if "excluded" in columns:
            self.db.execute("ALTER TABLE source_stats DROP COLUMN excluded")

    def _transaction(self, body) -> None:
        self.db.execute("BEGIN")
        try:
            body()
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _exec(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        cursor = self.db.execute(sql, params)
        self.updated_rows = cursor.rowcount if cursor.rowcount is not None else 0
        return cursor

    def meta_get(self, key: str) -> str | None:
        with self._lock:
            return self._meta(key)

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            self._meta_set(key, value)

    def load_settings(self) -> Settings:
        with self._lock:
            return self._load_settings()

    def save_settings(self, settings: Settings) -> None:
        theme = settings.theme if settings.theme in {"light", "dark", "system"} else "system"
        font = settings.font_size if settings.font_size in {"sm", "md", "lg", "xl"} else "md"
        self.meta_set("theme", theme)
        self.meta_set("font_size", font)
        self.meta_set("contact_email", settings.contact_email.strip())
        self.meta_set(
            "team_theme",
            "" if settings.team_theme is None else str(settings.team_theme),
        )

    def import_complete(self) -> bool:
        return self.meta_get("import_complete") == "1"

    def set_import_complete(self, complete: bool) -> None:
        self.meta_set("import_complete", "1" if complete else "0")

    def purge_before_cutoff(self) -> None:
        with self._lock:
            def body() -> None:
                self.db.execute("DELETE FROM games WHERE year < ?", (FIRST_SEASON_YEAR,))
                self.db.execute("DELETE FROM tips WHERE year < ?", (FIRST_SEASON_YEAR,))
                self.db.execute(
                    "DELETE FROM standings WHERE year < ?", (FIRST_SEASON_YEAR,)
                )
                self.db.execute(
                    "DELETE FROM year_sync WHERE year < ?", (FIRST_SEASON_YEAR,)
                )
                self.db.execute(
                    "DELETE FROM calls WHERE game_id NOT IN (SELECT id FROM games)"
                )

            self._transaction(body)

    def purge_aggregate(self) -> None:
        with self._lock:
            self.db.execute(
                """
                DELETE FROM tips WHERE source_id IN (
                  SELECT id FROM sources WHERE lower(trim(name)) = 'aggregate'
                  UNION
                  SELECT source_id FROM source_stats WHERE lower(trim(name)) = 'aggregate'
                )
                """
            )
            self.db.execute(
                "DELETE FROM source_stats WHERE lower(trim(name)) = 'aggregate'"
            )
            self.db.execute("DELETE FROM sources WHERE lower(trim(name)) = 'aggregate'")

    def data_status(self, now_year: int) -> DataStatus:
        with self._lock:
            return self._data_status(now_year)

    def year_is_complete(self, year: int) -> bool:
        if not importable_year(year):
            return False
        with self._lock:
            count = self._count(
                """
                SELECT COUNT(*) AS n FROM year_sync
                WHERE year = ? AND kind IN ('games', 'tips', 'standings')
                """,
                (year,),
            )
            return count >= 3

    def mark_year(self, year: int, kind: str, rows: int, fetched_at: int) -> None:
        refuse_old(year)
        with self._lock:
            self.db.execute(
                """
                INSERT INTO year_sync (year, kind, rows, fetched_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(year, kind) DO UPDATE SET
                  rows = excluded.rows, fetched_at = excluded.fetched_at
                """,
                (year, kind, rows, fetched_at),
            )

    def clear_year_sync(self) -> None:
        with self._lock:
            self.db.execute("DELETE FROM year_sync")

    def save_sources(self, sources: list[ParsedSource]) -> None:
        with self._lock:
            def body() -> None:
                for source in sources:
                    if is_aggregate_source(source.name):
                        continue
                    self.db.execute(
                        """
                        INSERT INTO sources (id, name, url, icon) VALUES (?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                          name = excluded.name, url = excluded.url, icon = excluded.icon
                        """,
                        (source.id, source.name, source.url, source.icon),
                    )

            self._transaction(body)

    def save_teams(self, teams: list[ParsedTeam]) -> None:
        with self._lock:
            def body() -> None:
                for team in teams:
                    self.db.execute(
                        """
                        INSERT INTO teams (id, name, abbrev, logo, debut, retirement, logo_blob, logo_mime)
                        VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                        ON CONFLICT(id) DO UPDATE SET
                          name = excluded.name,
                          abbrev = excluded.abbrev,
                          logo = excluded.logo,
                          debut = excluded.debut,
                          retirement = excluded.retirement,
                          logo_blob = CASE WHEN teams.logo = excluded.logo THEN teams.logo_blob ELSE NULL END,
                          logo_mime = CASE WHEN teams.logo = excluded.logo THEN teams.logo_mime ELSE NULL END
                        """,
                        (team.id, team.name, team.abbrev, team.logo, team.debut, team.retirement),
                    )

            self._transaction(body)

    def teams_missing_logos(self) -> list[tuple[int, str]]:
        with self._lock:
            rows = self.db.execute(
                """
                SELECT id, logo FROM teams
                WHERE logo != '' AND (logo_blob IS NULL OR length(logo_blob) = 0)
                """
            ).fetchall()
            return [(int(row["id"]), row["logo"]) for row in rows]

    def save_logo(self, team_id: int, data: bytes, mime: str) -> None:
        with self._lock:
            self.db.execute(
                "UPDATE teams SET logo_blob = ?, logo_mime = ? WHERE id = ?",
                (data, mime, team_id),
            )

    def replace_games(self, year: int, games: list[ParsedGame]) -> None:
        refuse_old(year)
        with self._lock:
            def body() -> None:
                self.db.execute("DELETE FROM games WHERE year = ?", (year,))
                for game in games:
                    if game.year != year or not importable_year(game.year):
                        continue
                    self.db.execute(
                        """
                        INSERT INTO games (
                          id, year, round, roundname, hteam_id, ateam_id, hteam, ateam,
                          hscore, ascore, hgoals, hbehinds, agoals, abehinds, complete,
                          winner_team_id, winner, venue, date, localtime, unixtime, tz, updated,
                          timestr, is_final, is_grand_final
                        ) VALUES (
                          ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?
                        )
                        """,
                        (
                            game.id,
                            game.year,
                            game.round,
                            game.roundname,
                            game.hteam_id,
                            game.ateam_id,
                            game.hteam,
                            game.ateam,
                            game.hscore,
                            game.ascore,
                            game.hgoals,
                            game.hbehinds,
                            game.agoals,
                            game.abehinds,
                            game.complete,
                            game.winner_team_id,
                            game.winner,
                            game.venue,
                            game.date,
                            game.localtime,
                            game.unixtime,
                            game.tz,
                            game.updated,
                            game.timestr,
                            game.is_final,
                            game.is_grand_final,
                        ),
                    )
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO teams (id, name, abbrev, logo)
                    SELECT hteam_id, hteam, upper(substr(hteam, 1, 3)), ''
                    FROM games WHERE year = ? GROUP BY hteam_id
                    """,
                    (year,),
                )
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO teams (id, name, abbrev, logo)
                    SELECT ateam_id, ateam, upper(substr(ateam, 1, 3)), ''
                    FROM games WHERE year = ? GROUP BY ateam_id
                    """,
                    (year,),
                )

            self._transaction(body)

    def replace_tips(self, year: int, tips: list[ParsedTip]) -> None:
        refuse_old(year)
        with self._lock:
            def body() -> None:
                self.db.execute("DELETE FROM tips WHERE year = ?", (year,))
                for tip in tips:
                    if is_aggregate_source(tip.source_name):
                        continue
                    if tip.year != year and tip.year != 0:
                        continue
                    if tip.year != 0 and not importable_year(tip.year):
                        continue
                    stored_year = year if tip.year == 0 else tip.year
                    if not importable_year(stored_year):
                        continue
                    self.db.execute(
                        """
                        INSERT OR REPLACE INTO tips (
                          game_id, source_id, year, round, tip_team_id, tip, hteam, ateam,
                          hteam_id, ateam_id, confidence, hconfidence, margin, hmargin, err, bits,
                          api_correct, date, venue, updated
                        ) VALUES (
                          ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?
                        )
                        """,
                        (
                            tip.game_id,
                            tip.source_id,
                            stored_year,
                            tip.round,
                            tip.tip_team_id,
                            tip.tip,
                            tip.hteam,
                            tip.ateam,
                            tip.hteam_id,
                            tip.ateam_id,
                            tip.confidence,
                            tip.hconfidence,
                            tip.margin,
                            tip.hmargin,
                            tip.err,
                            tip.bits,
                            tip.api_correct,
                            tip.date,
                            tip.venue,
                            tip.updated,
                        ),
                    )

            self._transaction(body)

    def replace_standings(self, year: int, rows: list[ParsedStanding]) -> None:
        refuse_old(year)
        with self._lock:
            def body() -> None:
                self.db.execute("DELETE FROM standings WHERE year = ?", (year,))
                for row in rows:
                    self.db.execute(
                        """
                        INSERT INTO standings (
                          year, team_id, rank, name, played, wins, losses, draws, points, percentage,
                          points_for, points_against, goals_for, goals_against, behinds_for, behinds_against
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            year,
                            row.team_id,
                            row.rank,
                            row.name,
                            row.played,
                            row.wins,
                            row.losses,
                            row.draws,
                            row.points,
                            row.percentage,
                            row.points_for,
                            row.points_against,
                            row.goals_for,
                            row.goals_against,
                            row.behinds_for,
                            row.behinds_against,
                        ),
                    )

            self._transaction(body)

    def tip_rule_current(self) -> bool:
        return self.meta_get("tip_rule") == str(TIPPING_RULE_REVISION)

    def recompute(self) -> None:
        with self._lock:
            games = self._load_games()
            tips = self._load_tips()
            analysis = analyse(games, tips)

            def body() -> None:
                self.db.execute("DELETE FROM calls")
                self.db.execute("DELETE FROM source_stats")
                for call in analysis.calls:
                    upset = None if call.result_was_upset is None else int(call.result_was_upset)
                    self.db.execute(
                        """
                        INSERT INTO calls (
                          game_id, pick_team_id, confidence, consensus_team_id, consensus_votes,
                          models_used, followed_consensus, result_was_upset, summary
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            call.game_id,
                            call.pick_team_id,
                            call.confidence,
                            call.consensus_team_id,
                            call.consensus_votes,
                            call.models_used,
                            1 if call.followed_consensus else 0,
                            upset,
                            call.summary,
                        ),
                    )
                for row in analysis.rankings:
                    self.db.execute(
                        """
                        INSERT INTO source_stats (
                          source_id, name, tips, correct, accuracy, recent_tips, recent_correct,
                          recent_accuracy, upset_chances, upset_hits, upset_accuracy, dissent_tips,
                          dissent_correct, dissent_accuracy, score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row.source_id,
                            row.name,
                            row.tips,
                            row.correct,
                            row.accuracy,
                            row.recent_tips,
                            row.recent_correct,
                            row.recent_accuracy,
                            row.upset_chances,
                            row.upset_hits,
                            row.upset_accuracy,
                            row.dissent_tips,
                            row.dissent_correct,
                            row.dissent_accuracy,
                            row.score,
                        ),
                    )

            self._transaction(body)
            self._meta_set("tip_rule", str(TIPPING_RULE_REVISION))

    def season_phase(self, now: int) -> SeasonPhase:
        with self._lock:
            live = self._count(
                "SELECT COUNT(*) AS n FROM games WHERE complete > 0 AND complete < 100"
            )
            if live > 0:
                return SeasonPhase.LIVE
            row = self.db.execute(
                "SELECT MIN(unixtime) AS when_unix FROM games WHERE complete < 100"
            ).fetchone()
            when = None if row is None else row["when_unix"]
            if when is None:
                return SeasonPhase.OFF_SEASON
            if int(when) - now > 14 * 86400:
                return SeasonPhase.PRESEASON
            return SeasonPhase.IN_SEASON

    def latest_season_year(self) -> int | None:
        with self._lock:
            row = self.db.execute("SELECT MAX(year) AS year FROM games").fetchone()
            if row is None or row["year"] is None:
                return None
            return int(row["year"])

    def next_incomplete_year(self) -> int | None:
        with self._lock:
            row = self.db.execute(
                """
                SELECT year FROM games
                WHERE year >= ? AND complete < 100
                ORDER BY unixtime ASC LIMIT 1
                """,
                (FIRST_SEASON_YEAR,),
            ).fetchone()
            if row is None:
                return None
            return int(row["year"])

    def game_starting_soon(self, now: int) -> bool:
        with self._lock:
            count = self._count(
                """
                SELECT COUNT(*) AS n FROM games
                WHERE complete < 100
                  AND unixtime BETWEEN ? - ? AND ? + ?
                """,
                (now, LIVE_WINDOW_SECONDS, now, LIVE_WINDOW_SECONDS),
            )
            return count > 0

    def apply_live_score(self, score: LiveScore) -> bool:
        """Write one live update. True when a finished result changed and the model should be rated again."""
        with self._lock:
            previous = self.db.execute(
                """
                SELECT complete, hscore, ascore, winner_team_id
                FROM games WHERE id = ? AND year >= ?
                """,
                (score.id, FIRST_SEASON_YEAR),
            ).fetchone()
            if previous is None:
                return False
            was_finished = int(previous["complete"]) >= 100
            self._exec(
                """
                UPDATE games SET
                  complete = ?,
                  hscore = COALESCE(?, hscore),
                  ascore = COALESCE(?, ascore),
                  hgoals = COALESCE(?, hgoals),
                  hbehinds = COALESCE(?, hbehinds),
                  agoals = COALESCE(?, agoals),
                  abehinds = COALESCE(?, abehinds),
                  winner_team_id = COALESCE(?, winner_team_id),
                  timestr = CASE WHEN ? = '' THEN timestr ELSE ? END,
                  updated = CASE WHEN ? = '' THEN updated ELSE ? END,
                  winner = CASE
                    WHEN ? IS NULL THEN winner
                    WHEN ? = hteam_id THEN hteam
                    WHEN ? = ateam_id THEN ateam
                    ELSE winner
                  END
                WHERE id = ? AND year >= ?
                """,
                (
                    score.complete,
                    score.hscore,
                    score.ascore,
                    score.hgoals,
                    score.hbehinds,
                    score.agoals,
                    score.abehinds,
                    score.winner_team_id,
                    score.timestr,
                    score.timestr,
                    score.updated,
                    score.updated,
                    score.winner_team_id,
                    score.winner_team_id,
                    score.winner_team_id,
                    score.id,
                    FIRST_SEASON_YEAR,
                ),
            )
            if self.updated_rows <= 0 or score.complete < 100:
                return False
            if not was_finished:
                return True
            return _result_changed(previous, score)

    def bootstrap(self, now: int) -> Bootstrap:
        with self._lock:
            return Bootstrap(
                settings=self._load_settings(),
                status=self._data_status(civil_year(now)),
                teams=self._load_teams(),
                seasons=self._load_seasons(),
                focus=self._focus_for(now),
            )

    def round_view(self, year: int, rnd: int) -> RoundView:
        if not importable_year(year):
            return RoundView(year=year, round=rnd, round_name=f"Round {rnd}", games=[])
        with self._lock:
            rows = self.db.execute(
                """
                SELECT g.id, g.year, g.round, g.roundname, g.hteam_id, g.ateam_id, g.hteam, g.ateam,
                       g.hscore, g.ascore, g.complete, g.winner_team_id, g.venue, g.date, g.timestr,
                       g.is_final, g.is_grand_final,
                       c.pick_team_id, c.confidence, c.consensus_team_id, c.consensus_votes, c.models_used,
                       c.followed_consensus, c.summary
                FROM games g
                LEFT JOIN calls c ON c.game_id = g.id
                WHERE g.year = ? AND g.round = ?
                ORDER BY g.unixtime, g.id
                """,
                (year, rnd),
            ).fetchall()
            games: list[GameCard] = []
            for row in rows:
                complete = int(row["complete"])
                confidence = row["confidence"]
                call = None
                if confidence is not None:
                    call = CallView(
                        pick_team_id=_int_opt(row["pick_team_id"]),
                        confidence=float(confidence),
                        consensus_team_id=_int_opt(row["consensus_team_id"]),
                        consensus_votes=_int_opt(row["consensus_votes"]) or 0,
                        models_used=_int_opt(row["models_used"]) or 0,
                        followed_consensus=(_int_opt(row["followed_consensus"]) or 0) == 1,
                        summary=row["summary"] or "",
                    )
                games.append(
                    GameCard(
                        id=int(row["id"]),
                        year=int(row["year"]),
                        round=int(row["round"]),
                        round_name=row["roundname"],
                        home_id=int(row["hteam_id"]),
                        away_id=int(row["ateam_id"]),
                        home_name=row["hteam"],
                        away_name=row["ateam"],
                        home_score=_int_opt(row["hscore"]) if complete > 0 else None,
                        away_score=_int_opt(row["ascore"]) if complete > 0 else None,
                        complete=complete,
                        winner_id=_int_opt(row["winner_team_id"]) if complete >= 100 else None,
                        venue=row["venue"] or "",
                        date=row["date"] or "",
                        timestr=row["timestr"] or "",
                        is_final=int(row["is_final"]),
                        is_grand_final=int(row["is_grand_final"]),
                        call=call,
                    )
                )
            round_name = f"Round {rnd}" if not games else games[0].round_name
            return RoundView(year=year, round=rnd, round_name=round_name, games=games)

    def ladder(self, year: int) -> Ladder:
        if not importable_year(year):
            return Ladder(year=year, rows=[])
        with self._lock:
            rows = self.db.execute(
                """
                SELECT rank, team_id, name, played, wins, losses, draws,
                       points_for, points_against, percentage, points
                FROM standings WHERE year = ? ORDER BY rank
                """,
                (year,),
            ).fetchall()
            ladder_rows = [
                LadderRow(
                    rank=int(row["rank"]),
                    team_id=int(row["team_id"]),
                    name=row["name"],
                    played=int(row["played"]),
                    wins=int(row["wins"]),
                    losses=int(row["losses"]),
                    draws=int(row["draws"]),
                    points_for=int(row["points_for"]),
                    points_against=int(row["points_against"]),
                    percentage=float(row["percentage"]),
                    points=int(row["points"]),
                )
                for row in rows
            ]
            self._attach_ladder_context(year, ladder_rows)
            return Ladder(year=year, rows=ladder_rows)

    def model_board(self, year: int) -> ModelBoard:
        with self._lock:
            records = season_record(self._load_games(year), self._load_tips(year))
            if not records:
                return ModelBoard(rows=[], footy=None, rounds=[], round_names=[], lines=[])
            margins = self._margin_errors(year)
            careers = self._career_rates()
            honour = "winner" if self._year_complete(year) else "leader"
            top = records[0]
            median_accuracy = field_median([row.accuracy for row in records])
            rows: list[ModelRow] = []
            for row in records:
                margin = margins.get(row.source_id)
                career_accuracy = None
                career_from = None
                found = careers.get(row.source_id)
                if found is not None:
                    first_year, accuracy, tips = found
                    if first_year < year and tips > row.tips:
                        career_accuracy = accuracy
                        career_from = first_year
                rows.append(
                    ModelRow(
                        source_id=row.source_id,
                        name=row.name,
                        tips=row.tips,
                        correct=row.correct,
                        accuracy=row.accuracy,
                        upset_chances=row.upset_chances,
                        upset_hits=row.upset_hits,
                        upset_accuracy=row.upset_accuracy,
                        dissent_tips=row.dissent_tips,
                        dissent_accuracy=row.dissent_accuracy,
                        honour=(
                            honour
                            if row.tips == top.tips and row.correct == top.correct
                            else None
                        ),
                        margin_error=None if margin is None else margin[0],
                        margin_samples=0 if margin is None else margin[1],
                        career_accuracy=career_accuracy,
                        career_from=career_from,
                        clear=games_clear(row.correct, row.tips, median_accuracy),
                    )
                )
            footy = self._footy_row(year, median_accuracy)
            leaders = [(row.source_id, row.name) for row in rows if row.honour]
            rounds, names, lines = running_clear(
                self._round_counts(year),
                leaders,
                None if footy is None else self._footy_rounds(year),
            )
            return ModelBoard(
                rows=rows,
                footy=footy,
                rounds=rounds,
                round_names=names,
                lines=lines,
            )

    def _margin_errors(self, year: int) -> dict[int, tuple[float, int]]:
        rows = self.db.execute(
            """
            SELECT t.source_id AS source_id, AVG(t.err) AS mae, COUNT(t.err) AS samples
            FROM tips t
            JOIN games g ON g.id = t.game_id
            LEFT JOIN sources s ON s.id = t.source_id
            LEFT JOIN source_stats st ON st.source_id = t.source_id
            WHERE g.year = ? AND g.complete >= 100 AND t.err IS NOT NULL
              AND (t.tip_team_id = g.hteam_id OR t.tip_team_id = g.ateam_id)
              AND lower(trim(COALESCE(s.name, st.name, ''))) != 'aggregate'
            GROUP BY t.source_id
            """,
            (year,),
        ).fetchall()
        return {
            int(row["source_id"]): (float(row["mae"]), int(row["samples"]))
            for row in rows
            if row["mae"] is not None
        }

    def _career_rates(self) -> dict[int, tuple[int, float, int]]:
        rows = self.db.execute(
            """
            SELECT st.source_id AS source_id,
                   st.accuracy AS accuracy,
                   st.tips AS tips,
                   MIN(t.year) AS first_year
            FROM source_stats st
            JOIN tips t ON t.source_id = st.source_id AND t.year >= ?
            GROUP BY st.source_id
            """,
            (FIRST_SEASON_YEAR,),
        ).fetchall()
        return {
            int(row["source_id"]): (
                int(row["first_year"]),
                float(row["accuracy"]),
                int(row["tips"]),
            )
            for row in rows
            if row["first_year"] is not None
        }

    def _round_counts(self, year: int) -> list[tuple[int, str, dict[int, tuple[int, int]]]]:
        rows = self.db.execute(
            """
            SELECT g.round AS round,
                   MIN(g.roundname) AS name,
                   t.source_id AS source_id,
                   COUNT(*) AS tips,
                   SUM(CASE WHEN g.winner_team_id = t.tip_team_id THEN 1 ELSE 0 END) AS correct
            FROM tips t
            JOIN games g ON g.id = t.game_id
            LEFT JOIN sources s ON s.id = t.source_id
            LEFT JOIN source_stats st ON st.source_id = t.source_id
            WHERE g.year = ? AND g.complete >= 100
              AND (t.tip_team_id = g.hteam_id OR t.tip_team_id = g.ateam_id)
              AND lower(trim(COALESCE(s.name, st.name, ''))) != 'aggregate'
            GROUP BY g.round, t.source_id
            ORDER BY g.round, t.source_id
            """,
            (year,),
        ).fetchall()
        order: list[tuple[int, str]] = []
        counts: dict[int, dict[int, tuple[int, int]]] = {}
        for row in rows:
            rnd = int(row["round"])
            if rnd not in counts:
                order.append((rnd, row["name"] or f"Round {rnd}"))
                counts[rnd] = {}
            counts[rnd][int(row["source_id"])] = (int(row["tips"]), int(row["correct"] or 0))
        return [(rnd, name, counts[rnd]) for rnd, name in order]

    def _footy_rounds(self, year: int) -> dict[int, tuple[int, int]]:
        rows = self.db.execute(
            """
            SELECT g.round AS round,
                   COUNT(*) AS tips,
                   SUM(CASE WHEN c.pick_team_id = g.winner_team_id THEN 1 ELSE 0 END) AS correct
            FROM calls c
            JOIN games g ON g.id = c.game_id
            WHERE g.year = ? AND g.complete >= 100 AND c.pick_team_id IS NOT NULL
            GROUP BY g.round
            """,
            (year,),
        ).fetchall()
        return {
            int(row["round"]): (int(row["tips"]), int(row["correct"] or 0)) for row in rows
        }

    def _footy_row(self, year: int, median_accuracy: float) -> ModelRow | None:
        season = self._footy_rounds(year)
        tips = sum(count for count, _correct in season.values())
        correct = sum(hits for _count, hits in season.values())
        if tips <= 0:
            return None
        career = self.db.execute(
            """
            SELECT COUNT(*) AS tips,
                   SUM(CASE WHEN c.pick_team_id = g.winner_team_id THEN 1 ELSE 0 END) AS correct,
                   MIN(g.year) AS first_year
            FROM calls c
            JOIN games g ON g.id = c.game_id
            WHERE g.complete >= 100 AND g.year >= ? AND c.pick_team_id IS NOT NULL
            """,
            (FIRST_SEASON_YEAR,),
        ).fetchone()
        career_accuracy = None
        career_from = None
        if career is not None:
            career_tips = int(career["tips"] or 0)
            first_year = career["first_year"]
            if first_year is not None and int(first_year) < year and career_tips > tips:
                career_accuracy = int(career["correct"] or 0) / career_tips
                career_from = int(first_year)
        upset_chances, upset_hits, dissent_tips, dissent_hits = self._footy_splits(year)
        margin = self._footy_margin(year)
        return ModelRow(
            source_id=0,
            name=FOOTY_NAME,
            tips=tips,
            correct=correct,
            accuracy=correct / tips,
            upset_chances=upset_chances,
            upset_hits=upset_hits,
            upset_accuracy=0.0 if upset_chances == 0 else upset_hits / upset_chances,
            dissent_tips=dissent_tips,
            dissent_accuracy=0.0 if dissent_tips == 0 else dissent_hits / dissent_tips,
            margin_error=None if margin is None else margin[0],
            margin_samples=0 if margin is None else margin[1],
            career_accuracy=career_accuracy,
            career_from=career_from,
            clear=games_clear(correct, tips, median_accuracy),
        )

    def _footy_splits(self, year: int) -> tuple[int, int, int, int]:
        row = self.db.execute(
            """
            SELECT
              SUM(CASE
                    WHEN c.result_was_upset = 1 AND c.pick_team_id IS NOT NULL THEN 1
                    ELSE 0
                  END) AS chances,
              SUM(CASE
                    WHEN c.result_was_upset = 1 AND c.pick_team_id = g.winner_team_id THEN 1
                    ELSE 0
                  END) AS hits,
              SUM(CASE
                    WHEN c.pick_team_id IS NOT NULL AND c.consensus_team_id IS NOT NULL
                         AND c.pick_team_id != c.consensus_team_id THEN 1
                    ELSE 0
                  END) AS dissent,
              SUM(CASE
                    WHEN c.pick_team_id IS NOT NULL AND c.consensus_team_id IS NOT NULL
                         AND c.pick_team_id != c.consensus_team_id
                         AND c.pick_team_id = g.winner_team_id THEN 1
                    ELSE 0
                  END) AS dissent_hits
            FROM calls c
            JOIN games g ON g.id = c.game_id
            WHERE g.year = ? AND g.complete >= 100
            """,
            (year,),
        ).fetchone()
        if row is None:
            return 0, 0, 0, 0
        return (
            int(row["chances"] or 0),
            int(row["hits"] or 0),
            int(row["dissent"] or 0),
            int(row["dissent_hits"] or 0),
        )

    def _footy_margin(self, year: int) -> tuple[float, int] | None:
        games = self.db.execute(
            """
            SELECT g.id AS game_id,
                   c.pick_team_id AS pick,
                   g.winner_team_id AS winner,
                   ABS(COALESCE(g.hscore, 0) - COALESCE(g.ascore, 0)) AS actual
            FROM calls c
            JOIN games g ON g.id = c.game_id
            WHERE g.year = ? AND g.complete >= 100 AND c.pick_team_id IS NOT NULL
              AND g.hscore IS NOT NULL AND g.ascore IS NOT NULL
            """,
            (year,),
        ).fetchall()
        if not games:
            return None
        tips = self.db.execute(
            """
            SELECT t.game_id AS game_id, t.tip_team_id AS team, t.margin AS margin, t.hmargin AS hmargin
            FROM tips t
            JOIN games g ON g.id = t.game_id
            LEFT JOIN sources s ON s.id = t.source_id
            LEFT JOIN source_stats st ON st.source_id = t.source_id
            WHERE g.year = ? AND g.complete >= 100
              AND (t.margin IS NOT NULL OR t.hmargin IS NOT NULL)
              AND lower(trim(COALESCE(s.name, st.name, ''))) != 'aggregate'
            """,
            (year,),
        ).fetchall()
        by_game: dict[int, dict[int, list[float]]] = {}
        for tip in tips:
            margin = _predicted_margin(tip["margin"], tip["hmargin"])
            if margin is None:
                continue
            sides = by_game.setdefault(int(tip["game_id"]), {})
            sides.setdefault(int(tip["team"]), []).append(margin)
        errors: list[float] = []
        for game in games:
            margins = by_game.get(int(game["game_id"]), {}).get(int(game["pick"]), [])
            winner = game["winner"]
            correct = winner is not None and int(winner) == int(game["pick"])
            error = side_margin_error(margins, float(game["actual"]), correct)
            if error is not None:
                errors.append(error)
        if not errors:
            return None
        return sum(errors) / len(errors), len(errors)

    def game_tips(self, game_id: int) -> list[TipDetail]:
        with self._lock:
            year_row = self.db.execute(
                "SELECT year FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            if year_row is None:
                return []
            year = int(year_row["year"])
            ranks = self._year_ranks(year)
            rows = self.db.execute(
                """
                SELECT t.source_id,
                       COALESCE(s.name, st.name, 'Model ' || t.source_id) AS name,
                       t.tip_team_id, t.tip, t.confidence, t.margin, t.hmargin
                FROM tips t
                LEFT JOIN sources s ON s.id = t.source_id
                LEFT JOIN source_stats st ON st.source_id = t.source_id
                WHERE t.game_id = ? AND t.year >= ?
                  AND lower(trim(COALESCE(s.name, st.name, ''))) != 'aggregate'
                """,
                (game_id, FIRST_SEASON_YEAR),
            ).fetchall()
            details = [
                TipDetail(
                    source_id=int(row["source_id"]),
                    name=row["name"],
                    tip_team_id=int(row["tip_team_id"]),
                    tip=row["tip"],
                    confidence=None if row["confidence"] is None else float(row["confidence"]),
                    margin=_predicted_margin(row["margin"], row["hmargin"]),
                    year_rank=ranks.get(int(row["source_id"])),
                )
                for row in rows
            ]
            details.sort(key=lambda tip: (tip.year_rank if tip.year_rank is not None else 1 << 30, tip.name))
            return details

    def touch_sync(self, now: int, error: str | None) -> None:
        if error is not None:
            self.meta_set("last_error", error)
        else:
            self.meta_set("last_error", "")
            self.meta_set("last_sync", str(now))

    def last_sync_unix(self) -> int | None:
        raw = self.meta_get("last_sync") or ""
        try:
            return int(raw)
        except ValueError:
            return None

    def count_games_in_year(self, year: int) -> int:
        with self._lock:
            return self._count("SELECT COUNT(*) AS n FROM games WHERE year = ?", (year,))

    def _year_complete(self, year: int) -> bool:
        row = self.db.execute(
            """
            SELECT COUNT(*) AS games,
                   SUM(CASE WHEN complete >= 100 THEN 1 ELSE 0 END) AS done
            FROM games WHERE year = ?
            """,
            (year,),
        ).fetchone()
        games = 0 if row is None else int(row["games"] or 0)
        done = 0 if row is None else int(row["done"] or 0)
        return games > 0 and done == games

    def _year_records(self, year: int) -> list[tuple[int, str, int, int]]:
        rows = self.db.execute(
            """
            SELECT t.source_id,
                   COALESCE(s.name, st.name, 'Model ' || t.source_id) AS name,
                   COUNT(*) AS tips,
                   SUM(CASE WHEN g.winner_team_id = t.tip_team_id THEN 1 ELSE 0 END) AS correct
            FROM tips t
            JOIN games g ON g.id = t.game_id
            LEFT JOIN sources s ON s.id = t.source_id
            LEFT JOIN source_stats st ON st.source_id = t.source_id
            WHERE g.year = ? AND g.complete >= 100
              AND (t.tip_team_id = g.hteam_id OR t.tip_team_id = g.ateam_id)
              AND lower(trim(COALESCE(s.name, st.name, ''))) != 'aggregate'
            GROUP BY t.source_id
            """,
            (year,),
        ).fetchall()
        return [
            (
                int(row["source_id"]),
                row["name"],
                int(row["tips"]),
                int(row["correct"] or 0),
            )
            for row in rows
        ]

    def _year_ranks(self, year: int) -> dict[int, int]:
        records = self._year_records(year)
        records.sort(key=lambda item: (-_ratio(item[3], item[2]), -item[2], item[1]))
        return {item[0]: index + 1 for index, item in enumerate(records)}

    def _load_games(self, year: int | None = None) -> list[GameIn]:
        clause = "year = ?" if year is not None else "year >= ?"
        bound = FIRST_SEASON_YEAR if year is None else year
        rows = self.db.execute(
            f"""
            SELECT id, year, unixtime, complete, hteam_id, ateam_id, hteam, ateam, winner_team_id
            FROM games WHERE {clause}
            """,
            (bound,),
        ).fetchall()
        return [
            GameIn(
                id=int(row["id"]),
                year=int(row["year"]),
                unixtime=int(row["unixtime"]),
                complete=int(row["complete"]),
                home_id=int(row["hteam_id"]),
                away_id=int(row["ateam_id"]),
                home_name=row["hteam"],
                away_name=row["ateam"],
                winner_id=_int_opt(row["winner_team_id"]),
            )
            for row in rows
        ]

    def _load_tips(self, year: int | None = None) -> list[TipIn]:
        clause = "t.year = ?" if year is not None else "t.year >= ?"
        bound = FIRST_SEASON_YEAR if year is None else year
        rows = self.db.execute(
            f"""
            SELECT t.game_id, t.source_id,
                   COALESCE(s.name, 'Model ' || t.source_id) AS name,
                   t.tip_team_id, t.confidence
            FROM tips t
            LEFT JOIN sources s ON s.id = t.source_id
            WHERE {clause}
            """,
            (bound,),
        ).fetchall()
        return [
            TipIn(
                game_id=int(row["game_id"]),
                source_id=int(row["source_id"]),
                source_name=row["name"],
                tip_team_id=int(row["tip_team_id"]),
                confidence=None if row["confidence"] is None else float(row["confidence"]),
            )
            for row in rows
        ]

    def _load_teams(self) -> list[TeamInfo]:
        rows = self.db.execute(
            "SELECT id, name, abbrev, logo_blob FROM teams ORDER BY name"
        ).fetchall()
        return [
            TeamInfo(
                id=int(row["id"]),
                name=row["name"],
                abbrev=row["abbrev"],
                logo_bytes=_bytes(row["logo_blob"]),
            )
            for row in rows
        ]

    def _load_seasons(self) -> list[SeasonInfo]:
        years = self.db.execute(
            "SELECT DISTINCT year FROM games WHERE year >= ? ORDER BY year DESC",
            (FIRST_SEASON_YEAR,),
        ).fetchall()
        seasons: list[SeasonInfo] = []
        for year_row in years:
            year = int(year_row["year"])
            rounds = self.db.execute(
                """
                SELECT round, MIN(roundname) AS name, COUNT(*) AS games,
                       SUM(CASE WHEN complete >= 100 THEN 1 ELSE 0 END) AS completed
                FROM games WHERE year = ? GROUP BY round ORDER BY round
                """,
                (year,),
            ).fetchall()
            seasons.append(
                SeasonInfo(
                    year=year,
                    rounds=[
                        RoundInfo(
                            round=int(row["round"]),
                            name=row["name"],
                            games=int(row["games"]),
                            completed=int(row["completed"] or 0),
                        )
                        for row in rounds
                    ],
                )
            )
        return seasons

    def _focus_for(self, now: int) -> SeasonFocus | None:
        live = self.db.execute(
            """
            SELECT year, round, roundname FROM games
            WHERE year >= ? AND complete > 0 AND complete < 100
            ORDER BY unixtime ASC LIMIT 1
            """,
            (FIRST_SEASON_YEAR,),
        ).fetchone()
        if live is not None:
            year = int(live["year"])
            return SeasonFocus(
                year=year,
                round=int(live["round"]),
                out_of_season=False,
                title=live["roundname"],
                subtitle=f"{year} is on. This round is in progress.",
            )
        upcoming = self.db.execute(
            """
            SELECT year, round, roundname FROM games
            WHERE year >= ? AND complete < 100 AND unixtime >= ? - 86400
            ORDER BY unixtime ASC LIMIT 1
            """,
            (FIRST_SEASON_YEAR, now),
        ).fetchone()
        if upcoming is not None:
            year = int(upcoming["year"])
            return SeasonFocus(
                year=year,
                round=int(upcoming["round"]),
                out_of_season=False,
                title=upcoming["roundname"],
                subtitle=f"Next up in {year}.",
            )
        last = self.db.execute(
            """
            SELECT year, round, roundname, hteam, ateam FROM games
            WHERE year >= ?
            ORDER BY unixtime DESC LIMIT 1
            """,
            (FIRST_SEASON_YEAR,),
        ).fetchone()
        if last is None:
            return None
        year = int(last["year"])
        return SeasonFocus(
            year=year,
            round=int(last["round"]),
            out_of_season=True,
            title=last["roundname"],
            subtitle=(
                f"The {year} season is finished. Showing the last game, "
                f"{last['hteam']} v {last['ateam']}, until next year's fixture is published."
            ),
        )

    def _attach_ladder_context(self, year: int, rows: list[LadderRow]) -> None:
        abbrev_rows = self.db.execute("SELECT id, abbrev FROM teams").fetchall()
        abbrevs = {int(row["id"]): row["abbrev"] for row in abbrev_rows}
        games = self.db.execute(
            """
            SELECT hteam_id, ateam_id, winner_team_id, complete
            FROM games WHERE year = ? ORDER BY unixtime, id
            """,
            (year,),
        ).fetchall()
        for row in rows:
            marks: list[str] = []
            for game in games:
                home = int(game["hteam_id"])
                away = int(game["ateam_id"])
                if home != row.team_id and away != row.team_id:
                    continue
                opponent = away if home == row.team_id else home
                complete = int(game["complete"])
                winner = _int_opt(game["winner_team_id"])
                if complete >= 100:
                    if winner == row.team_id:
                        mark = "W"
                    elif winner is None:
                        mark = "D"
                    else:
                        mark = "L"
                    marks.append(mark)
                    row.latest_team_id = opponent
                    row.latest_abbrev = abbrevs.get(opponent, "")
                elif row.next_team_id is None:
                    row.next_team_id = opponent
                    row.next_abbrev = abbrevs.get(opponent, "")
            start = max(0, len(marks) - 5)
            row.form = marks[start:]

    def _load_settings(self) -> Settings:
        settings = Settings()
        theme = self._meta("theme")
        if theme is not None:
            settings.theme = theme
        font = self._meta("font_size")
        if font is not None:
            settings.font_size = font
        email = self._meta("contact_email")
        if email is not None:
            settings.contact_email = email
        team = self._meta("team_theme")
        if team:
            try:
                settings.team_theme = int(team)
            except ValueError:
                settings.team_theme = None
        return settings

    def _data_status(self, now_year: int) -> DataStatus:
        games = self._count("SELECT COUNT(*) AS n FROM games")
        tips = self._count("SELECT COUNT(*) AS n FROM tips")
        years_done = self._count(
            """
            SELECT COUNT(*) AS n FROM (
              SELECT year FROM year_sync WHERE kind = 'games'
              INTERSECT
              SELECT year FROM year_sync WHERE kind = 'tips'
              INTERSECT
              SELECT year FROM year_sync WHERE kind = 'standings'
            )
            """
        )
        raw_sync = self._meta("last_sync") or ""
        try:
            last_sync = int(raw_sync)
        except ValueError:
            last_sync = None
        return DataStatus(
            imported=self._meta("import_complete") == "1",
            games=games,
            tips=tips,
            years_done=years_done,
            years_total=years_total(now_year),
            last_sync=last_sync,
            last_error=self._meta("last_error"),
        )

    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return row["value"]

    def _meta_set(self, key: str, value: str) -> None:
        self.db.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _count(self, sql: str, args: tuple = ()) -> int:
        row = self.db.execute(sql, args).fetchone()
        if row is None:
            return 0
        value = row["n"] if "n" in row.keys() else row[0]
        if value is None:
            return 0
        return int(value)


def _result_changed(previous: sqlite3.Row, score: LiveScore) -> bool:
    if score.hscore is not None and _int_opt(previous["hscore"]) != score.hscore:
        return True
    if score.ascore is not None and _int_opt(previous["ascore"]) != score.ascore:
        return True
    if score.winner_team_id is not None and _int_opt(previous["winner_team_id"]) != score.winner_team_id:
        return True
    return False


def _ratio(hits: int, n: int) -> float:
    return 0.0 if n <= 0 else hits / n


def _int_opt(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _predicted_margin(margin: object, hmargin: object) -> float | None:
    if margin is not None:
        return abs(float(margin))
    if hmargin is not None:
        return abs(float(hmargin))
    return None


def _bytes(value: object) -> bytes | None:
    if isinstance(value, bytes) and value:
        return value
    return None
