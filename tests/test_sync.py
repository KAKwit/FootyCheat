import sqlite3
import tempfile
import unittest
from pathlib import Path

from footy_cheat.engine.cutoff import FIRST_SEASON_YEAR, StateError, season_span
from footy_cheat.engine.parse import (
    LiveScore,
    ParsedGame,
    ParsedSource,
    ParsedTeam,
    ParsedTip,
    logo_mime,
    logo_url,
    looks_like_image,
    parse_games,
    parse_sources,
    parse_tips,
    user_agent,
)
from footy_cheat.engine.store import Store
from footy_cheat.engine.sync import CancelToken, Fetcher, SyncMode, run_sync


_PNG = b"\x89PNG\r\n\x1a\n"


class FakeFetcher(Fetcher):
    def __init__(self, payload, files=None):
        self.payload = payload
        self.files = {} if files is None else files
        self.hits = {}
        self.fetched = []

    def get_json(self, query):
        self.hits[query] = self.hits.get(query, 0) + 1
        if query in self.payload:
            return self.payload[query]
        if query.startswith("q=games;"):
            return {"games": []}
        if query.startswith("q=tips;"):
            return {"tips": []}
        if query.startswith("q=standings;"):
            return {"standings": []}
        raise RuntimeError(f"missing {query}")

    def get_bytes(self, url):
        self.fetched.append(url)
        if url not in self.files:
            raise RuntimeError(url)
        return self.files[url]


def match(game_id, complete, winner, year=2024, rnd=1, roundname=None, when=None, grand=0):
    return ParsedGame(
        id=game_id,
        year=year,
        round=rnd,
        roundname=roundname or f"Round {rnd}",
        hteam_id=1,
        ateam_id=2,
        hteam="Adelaide",
        ateam="Brisbane Lions",
        hscore=80 if complete >= 100 else None,
        ascore=70 if complete >= 100 else None,
        hgoals=None,
        hbehinds=None,
        agoals=None,
        abehinds=None,
        complete=complete,
        winner_team_id=winner,
        winner="Adelaide" if winner == 1 else "",
        venue="",
        date="",
        localtime="",
        unixtime=game_id if when is None else when,
        tz="",
        updated="",
        timestr="",
        is_final=0,
        is_grand_final=grand,
    )


def model_tip(
    game_id,
    source_id,
    source,
    team_id,
    margin=None,
    hmargin=None,
    confidence=None,
    year=2024,
    err=None,
    rnd=1,
):
    return ParsedTip(
        game_id=game_id,
        source_id=source_id,
        source_name=source,
        year=year,
        round=rnd,
        tip_team_id=team_id,
        tip="Adelaide" if team_id == 1 else "Brisbane Lions",
        hteam="Adelaide",
        ateam="Brisbane Lions",
        hteam_id=1,
        ateam_id=2,
        confidence=confidence,
        hconfidence=None,
        margin=margin,
        hmargin=hmargin,
        err=err,
        bits=None,
        api_correct=None,
        date="",
        venue="",
        updated="",
    )


class SyncTests(unittest.TestCase):
    def test_recompute_marks_the_current_tipping_rule(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        self.assertFalse(store.tip_rule_current())
        store.recompute()
        self.assertTrue(store.tip_rule_current())

    def test_fill_starts_at_the_cutoff_and_does_not_refetch_a_finished_year(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        fake = FakeFetcher(
            {
                "q=sources": {
                    "sources": [{"id": 1, "name": "Squiggle", "url": "", "icon": ""}]
                },
                "q=teams": {
                    "teams": [{"id": 1, "name": "Adelaide", "abbrev": "ADE", "logo": ""}]
                },
                "q=games;year=2024": {
                    "games": [
                        {
                            "id": 1,
                            "year": 2024,
                            "round": 1,
                            "roundname": "Round 1",
                            "hteamid": 1,
                            "ateamid": 2,
                            "hteam": "Adelaide",
                            "ateam": "Brisbane Lions",
                            "hscore": 80,
                            "ascore": 70,
                            "complete": 100,
                            "winnerteamid": 1,
                            "unixtime": 100,
                            "is_final": 0,
                            "is_grand_final": 0,
                        },
                        {
                            "id": 2,
                            "year": 1897,
                            "round": 1,
                            "roundname": "Round 1",
                            "hteamid": 1,
                            "ateamid": 2,
                            "hteam": "South Melbourne",
                            "ateam": "Carlton",
                            "complete": 100,
                            "unixtime": 1,
                            "is_final": 0,
                            "is_grand_final": 0,
                        },
                    ]
                },
                "q=tips;year=2024": {
                    "tips": [
                        {
                            "gameid": 1,
                            "sourceid": 1,
                            "source": "Squiggle",
                            "year": 1999,
                            "round": 1,
                            "tipteamid": 1,
                            "tip": "Adelaide",
                            "confidence": "60",
                        }
                    ]
                },
            }
        )
        report = run_sync(
            store=store,
            fetcher=fake,
            mode=SyncMode.FILL,
            now_year=2023,
            now=1700000000,
            cancel=CancelToken(),
            progress=lambda _progress: None,
        )
        self.assertEqual(report.action, "imported")
        self.assertTrue(store.import_complete())
        self.assertEqual(store.count_games_in_year(2024), 1)
        self.assertEqual(store.count_games_in_year(1897), 0)
        self.assertEqual(store.data_status(2023).tips, 0)
        self.assertEqual(fake.hits["q=games;year=2024"], 1)
        self.assertFalse(
            any("year=1897" in query or "year=1999" in query for query in fake.hits)
        )
        self.assertIn(f"q=games;year={FIRST_SEASON_YEAR}", fake.hits)
        self.assertEqual(
            len([query for query in fake.hits if query.startswith("q=games;")]),
            len(season_span(2023)),
        )
        run_sync(
            store=store,
            fetcher=fake,
            mode=SyncMode.FILL,
            now_year=2023,
            now=1700000100,
            cancel=CancelToken(),
            progress=lambda _progress: None,
        )
        self.assertEqual(fake.hits["q=games;year=2024"], 1)

    def test_replace_games_refuses_a_season_before_the_cutoff(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        with self.assertRaises(StateError):
            store.replace_games(2016, [])

    def test_opening_the_library_drops_seasons_already_stored_before_the_cutoff(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.db.execute(
            """
            INSERT INTO games (
              id, year, round, roundname, hteam_id, ateam_id, hteam, ateam,
              complete, unixtime, is_final, is_grand_final
            ) VALUES (7, 2016, 1, 'Round 1', 1, 2, 'South Melbourne', 'Carlton', 100, 1, 0, 0)
            """
        )
        store.db.execute(
            """
            INSERT INTO tips (game_id, source_id, year, round, tip_team_id, tip)
            VALUES (7, 1, 2016, 1, 1, 'South Melbourne')
            """
        )
        store.db.execute(
            """
            INSERT INTO standings (
              year, team_id, rank, name, played, wins, losses, draws, points,
              percentage, points_for, points_against
            ) VALUES (2016, 1, 1, 'South Melbourne', 1, 1, 0, 0, 4, 100, 20, 10)
            """
        )
        store.db.execute(
            "INSERT INTO year_sync (year, kind, rows, fetched_at) VALUES (2016, 'games', 1, 1)"
        )
        store.purge_before_cutoff()
        self.assertEqual(store.count_games_in_year(2016), 0)
        self.assertEqual(store.data_status(2026).tips, 0)
        self.assertEqual(store.bootstrap(1700000000).seasons, [])

    def test_parses_a_game_and_a_stringly_typed_tip(self):
        games = parse_games(
            {
                "games": [
                    {
                        "id": 10,
                        "year": 2026,
                        "round": 0,
                        "roundname": "Opening Round",
                        "hteamid": 16,
                        "ateamid": 3,
                        "hteam": "Sydney",
                        "ateam": "Carlton",
                        "hscore": 132,
                        "ascore": 69,
                        "complete": 100,
                        "winnerteamid": 16,
                        "winner": "Sydney",
                        "venue": "S.C.G.",
                        "unixtime": 1772699400,
                        "is_final": 0,
                        "is_grand_final": 0,
                    }
                ]
            }
        )
        self.assertEqual(games[0].hteam, "Sydney")
        self.assertEqual(games[0].winner_team_id, 16)
        tips = parse_tips(
            {
                "tips": [
                    {
                        "gameid": 10,
                        "sourceid": 1,
                        "source": "Squiggle",
                        "year": 2026,
                        "round": 0,
                        "tipteamid": 16,
                        "tip": "Sydney",
                        "confidence": "64.20",
                        "margin": "12.5",
                        "correct": 1,
                    },
                    {
                        "gameid": 10,
                        "sourceid": 8,
                        "source": "Aggregate",
                        "year": 2026,
                        "round": 0,
                        "tipteamid": 3,
                        "tip": "Carlton",
                    },
                ]
            }
        )
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0].confidence, 64.20)
        self.assertEqual(tips[0].margin, 12.5)
        names = [
            source.name
            for source in parse_sources(
                {
                    "sources": [
                        {"id": 8, "name": "Aggregate", "url": "", "icon": ""},
                        {"id": 1, "name": "Squiggle", "url": "", "icon": ""},
                    ]
                }
            )
        ]
        self.assertEqual(names, ["Squiggle"])

    def test_round_tips_are_ordered_by_this_years_rank(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.save_sources(
            [
                ParsedSource(1, "Steady", "", ""),
                ParsedSource(2, "Hot", "", ""),
                ParsedSource(3, "New", "", ""),
                ParsedSource(8, "Aggregate", "", ""),
            ]
        )
        names = [
            row["name"]
            for row in store.db.execute("SELECT name FROM sources ORDER BY id")
        ]
        self.assertEqual(names, ["Steady", "Hot", "New"])
        store.replace_games(
            2024,
            [
                match(1, 100, 1),
                match(2, 100, 1),
                match(3, 0, None),
            ],
        )
        store.replace_tips(
            2024,
            [
                model_tip(1, 2, "Hot", 1),
                model_tip(1, 1, "Steady", 2),
                model_tip(2, 2, "Hot", 1),
                model_tip(2, 1, "Steady", 1),
                model_tip(3, 2, "Hot", 1, margin=21.5, confidence=71.6),
                model_tip(3, 1, "Steady", 2, margin=9),
                model_tip(3, 3, "New", 1, hmargin=-7),
                model_tip(3, 8, "Aggregate", 1, margin=40),
            ],
        )
        stored = store.db.execute(
            "SELECT COUNT(*) AS n FROM tips WHERE source_id = 8"
        ).fetchone()
        self.assertEqual(stored["n"], 0)
        store.db.execute(
            "INSERT INTO sources (id, name, url, icon) VALUES (8, 'Aggregate', '', '')"
        )
        store.db.execute(
            """
            INSERT INTO tips (game_id, source_id, year, round, tip_team_id, tip, margin)
            VALUES (3, 8, 2024, 1, 1, 'Adelaide', 40)
            """
        )
        store.purge_aggregate()
        tips = store.game_tips(3)
        self.assertEqual([tip.name for tip in tips], ["Hot", "Steady", "New"])
        self.assertEqual([tip.year_rank for tip in tips], [1, 2, None])
        self.assertEqual([tip.margin for tip in tips], [21.5, 9, 7])
        self.assertEqual([tip.confidence for tip in tips], [71.6, None, None])
        store.recompute()
        board = store.model_board(2024)
        self.assertEqual([row.name for row in board.rows], ["Hot", "Steady"])
        self.assertEqual(board.rows[0].honour, "leader")
        self.assertEqual(board.rows[0].tips, 2)
        self.assertIsNone(board.rows[1].honour)

    def test_season_board_uses_that_year_and_badges_leaders_or_winners(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.save_sources(
            [
                ParsedSource(1, "Alpha", "", ""),
                ParsedSource(2, "Bravo", "", ""),
                ParsedSource(3, "Charlie", "", ""),
            ]
        )
        store.replace_games(
            2025,
            [match(101, 100, 1, 2025), match(102, 100, 1, 2025)],
        )
        store.replace_games(
            2026,
            [match(201, 100, 1, 2026), match(202, 0, None, 2026)],
        )
        store.replace_tips(
            2025,
            [
                model_tip(101, 1, "Alpha", 1, year=2025),
                model_tip(102, 1, "Alpha", 1, year=2025),
                model_tip(101, 2, "Bravo", 2, year=2025),
                model_tip(102, 2, "Bravo", 2, year=2025),
                model_tip(101, 3, "Charlie", 1, year=2025),
                model_tip(102, 3, "Charlie", 2, year=2025),
            ],
        )
        store.replace_tips(
            2026,
            [
                model_tip(201, 1, "Alpha", 1, year=2026),
                model_tip(201, 2, "Bravo", 1, year=2026),
                model_tip(201, 3, "Charlie", 2, year=2026),
            ],
        )
        done = {row.name: row for row in store.model_board(2025).rows}
        running = {row.name: row for row in store.model_board(2026).rows}
        self.assertEqual(done["Alpha"].tips, 2)
        self.assertEqual(done["Alpha"].correct, 2)
        self.assertEqual(done["Alpha"].honour, "winner")
        self.assertIsNone(done["Bravo"].honour)
        self.assertIsNone(done["Charlie"].honour)
        self.assertEqual(running["Alpha"].tips, 1)
        self.assertEqual(running["Alpha"].honour, "leader")
        self.assertEqual(running["Bravo"].honour, "leader")
        self.assertIsNone(running["Charlie"].honour)

        store.replace_games(
            2025,
            [match(101, 100, 1, 2025), match(102, 0, None, 2025)],
        )
        running_year = {row.name: row for row in store.model_board(2025).rows}
        self.assertEqual(running_year["Alpha"].tips, 1)
        self.assertEqual(running_year["Alpha"].honour, "leader")
        self.assertEqual(running_year["Charlie"].honour, "leader")
        self.assertIsNone(running_year["Bravo"].honour)

    def test_model_board_shows_margin_career_and_footy_cheat(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.save_sources(
            [
                ParsedSource(1, "Alpha", "", ""),
                ParsedSource(2, "Bravo", "", ""),
            ]
        )
        store.replace_games(2024, [match(301, 100, 1, 2024)])
        store.replace_tips(
            2024,
            [
                model_tip(301, 1, "Alpha", 1, year=2024),
                model_tip(301, 2, "Bravo", 1, year=2024),
            ],
        )
        store.replace_games(
            2025,
            [
                match(401, 100, 1, 2025, rnd=1),
                match(402, 100, 1, 2025, rnd=2),
            ],
        )
        store.replace_tips(
            2025,
            [
                model_tip(401, 1, "Alpha", 1, year=2025, err=10, rnd=1),
                model_tip(401, 2, "Bravo", 1, year=2025, err=30, rnd=1),
                model_tip(402, 1, "Alpha", 1, year=2025, err=20, rnd=2),
                model_tip(402, 2, "Bravo", 2, year=2025, err=10, rnd=2),
            ],
        )
        store.recompute()
        board = store.model_board(2025)
        rows = {row.name: row for row in board.rows}
        self.assertEqual(rows["Alpha"].margin_error, 15)
        self.assertEqual(rows["Bravo"].margin_error, 20)
        self.assertEqual(rows["Alpha"].margin_samples, 2)
        self.assertEqual(rows["Alpha"].clear, 0.5)
        self.assertEqual(rows["Bravo"].clear, -0.5)
        self.assertEqual(rows["Alpha"].career_from, 2024)
        self.assertEqual(rows["Alpha"].career_accuracy, 1)
        self.assertAlmostEqual(rows["Bravo"].career_accuracy, 2 / 3)
        self.assertIsNotNone(board.footy)
        self.assertEqual(board.footy.tips, 1)
        self.assertEqual(board.footy.correct, 1)
        self.assertEqual(board.footy.clear, 0.25)
        self.assertEqual(board.footy.career_from, 2024)
        self.assertEqual(board.rounds, [1, 2])
        by_role = {line.role: line for line in board.lines}
        self.assertEqual(by_role["leader"].name, "Alpha")
        self.assertEqual(by_role["leader"].points, [0.0, 0.5])
        self.assertEqual(by_role["footy"].points, [0.0, 0.25])
        self.assertEqual(by_role["leader"].points[-1], rows["Alpha"].clear)
        self.assertEqual(by_role["footy"].points[-1], board.footy.clear)

    def test_footy_cheat_follows_upsets_and_margin(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.save_sources(
            [
                ParsedSource(1, "Alpha", "", ""),
                ParsedSource(2, "Bravo", "", ""),
                ParsedSource(3, "Charlie", "", ""),
            ]
        )
        store.replace_games(
            2025,
            [
                match(501, 100, 2, 2025, rnd=1),
                match(502, 100, 1, 2025, rnd=2),
            ],
        )
        store.replace_tips(
            2025,
            [
                model_tip(501, 1, "Alpha", 1, margin=12, year=2025, rnd=1),
                model_tip(501, 2, "Bravo", 1, margin=18, year=2025, rnd=1),
                model_tip(501, 3, "Charlie", 2, margin=40, year=2025, rnd=1),
                model_tip(502, 1, "Alpha", 1, margin=4, year=2025, rnd=2),
                model_tip(502, 2, "Bravo", 1, margin=10, year=2025, rnd=2),
                model_tip(502, 3, "Charlie", 1, margin=22, year=2025, rnd=2),
            ],
        )
        store.recompute()
        footy = store.model_board(2025).footy
        self.assertIsNotNone(footy)
        self.assertEqual(footy.tips, 2)
        self.assertEqual(footy.correct, 1)
        self.assertEqual(footy.upset_chances, 1)
        self.assertEqual(footy.upset_hits, 0)
        self.assertEqual(footy.upset_accuracy, 0)
        self.assertEqual(footy.margin_samples, 2)
        self.assertEqual(footy.margin_error, 12.5)

    def test_the_first_copy_stores_a_club_crest(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        crest = _PNG + b"adelaide"
        address = "https://squiggle.com.au/wp-content/themes/squiggle/assets/images/Adelaide.png"
        fake = FakeFetcher(
            {
                "q=sources": {
                    "sources": [{"id": 1, "name": "Squiggle", "url": "", "icon": ""}]
                },
                "q=teams": {
                    "teams": [
                        {
                            "id": 1,
                            "name": "Adelaide",
                            "abbrev": "ADE",
                            "logo": "/wp-content/themes/squiggle/assets/images/Adelaide.png",
                        }
                    ]
                },
            },
            {address: crest},
        )
        report = run_sync(
            store=store,
            fetcher=fake,
            mode=SyncMode.FILL,
            now_year=FIRST_SEASON_YEAR,
            now=1_700_000_000,
            cancel=CancelToken(),
            progress=lambda _progress: None,
        )
        self.assertEqual(report.action, "imported")
        self.assertEqual(_crest(store, 1), crest)
        self.assertEqual(fake.fetched, [address])

    def test_a_recent_library_does_not_ask_squiggle(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.replace_games(2026, [match(1, 100, 1, year=2026, when=1)])
        store.set_import_complete(True)
        store.touch_sync(1_800_000_000, None)
        fake = FakeFetcher({})
        report = run_sync(
            store=store,
            fetcher=fake,
            mode=SyncMode.SMART,
            now_year=2026,
            now=1_800_000_000,
            cancel=CancelToken(),
            progress=lambda _progress: None,
        )
        self.assertEqual(report.action, "fresh")
        self.assertEqual(fake.hits, {})
        self.assertEqual(fake.fetched, [])

    def test_an_update_downloads_a_crest_the_app_does_not_ship(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        old = _PNG + b"old"
        new = _PNG + b"new"
        tasmania = _PNG + b"tas"
        store.save_teams(
            [
                ParsedTeam(
                    1,
                    "Adelaide",
                    "ADE",
                    "/old/Adelaide.png",
                    1991,
                    9999,
                )
            ]
        )
        store.save_logo(1, old, "image/png")
        store.replace_games(2026, [match(1, 100, 1, year=2026, when=1)])
        store.set_import_complete(True)
        store.touch_sync(1_800_000_000, None)
        adelaide = "https://squiggle.com.au/new/Adelaide.png"
        tasmania_url = "https://squiggle.com.au/wp-content/themes/squiggle/assets/images/Tasmania.png"
        junk = "https://squiggle.com.au/not-an-image.png"
        broken = "https://squiggle.com.au/broken.png"
        fake = FakeFetcher(
            {
                "q=teams": {
                    "teams": [
                        {"id": 1, "name": "Adelaide", "abbrev": "ADE", "logo": "/new/Adelaide.png"},
                        {
                            "id": 19,
                            "name": "Tasmania",
                            "abbrev": "TAS",
                            "logo": "/wp-content/themes/squiggle/assets/images/Tasmania.png",
                        },
                        {"id": 20, "name": "Example", "abbrev": "EXM", "logo": "/not-an-image.png"},
                        {"id": 21, "name": "Broken", "abbrev": "BRK", "logo": "/broken.png"},
                    ]
                }
            },
            {adelaide: new, tasmania_url: tasmania, junk: b"nope"},
        )
        report = run_sync(
            store=store,
            fetcher=fake,
            mode=SyncMode.SMART,
            now_year=2026,
            now=1_800_000_000 + 24 * 60 * 60,
            cancel=CancelToken(),
            progress=lambda _progress: None,
        )
        self.assertEqual(report.action, "checked")
        self.assertEqual(_crest(store, 1), new)
        self.assertEqual(_crest(store, 19), tasmania)
        self.assertIsNone(_crest(store, 20))
        self.assertIsNone(_crest(store, 21))
        self.assertEqual(set(fake.fetched), {adelaide, tasmania_url, junk, broken})
        self.assertNotIn("q=games;year=2026", fake.hits)
        self.assertEqual(fake.hits["q=teams"], 1)

    def test_logo_addresses_and_image_checks(self):
        self.assertIsNone(logo_url("  "))
        self.assertIsNone(logo_url("Adelaide.png"))
        self.assertEqual(logo_url("/a.png"), "https://squiggle.com.au/a.png")
        self.assertEqual(
            logo_url("https://squiggle.com.au/a.png"),
            "https://squiggle.com.au/a.png",
        )
        self.assertTrue(looks_like_image(_PNG))
        self.assertFalse(looks_like_image(b"<html>"))
        self.assertEqual(logo_mime("/a.webp"), "image/webp")
        self.assertEqual(logo_mime("/a.png"), "image/png")

    def test_user_agent_follows_the_package_version(self):
        from footy_cheat import __version__

        bare = f"Footy Cheat/{__version__} (GNOME; local cache)"
        self.assertEqual(user_agent(""), bare)
        self.assertEqual(user_agent("not an email"), bare)
        self.assertEqual(user_agent(" tipper@example.com "), f"{bare} tipper@example.com")

    def test_a_live_result_is_rated_again_only_when_it_changes(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.replace_games(2024, [match(1, 0, None, when=50)])
        playing = _live(1, 40, 12, 8)
        self.assertFalse(store.apply_live_score(playing))
        self.assertFalse(store.apply_live_score(playing))
        finished = _live(1, 100, 80, 70, winner=1)
        self.assertTrue(store.apply_live_score(finished))
        self.assertFalse(store.apply_live_score(finished))
        corrected = _live(1, 100, 81, 70, winner=1)
        self.assertTrue(store.apply_live_score(corrected))
        card = store.round_view(2024, 1).games[0]
        self.assertEqual(card.home_score, 81)
        self.assertEqual(card.winner_id, 1)

    def test_round_view_keeps_the_grand_final_flag(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.replace_games(2024, [match(1, 100, 1, grand=1, roundname="Grand Final")])
        card = store.round_view(2024, 1).games[0]
        self.assertEqual(card.is_grand_final, 1)
        self.assertEqual(card.round_name, "Grand Final")

    def test_opening_drops_the_unused_excluded_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            raw = sqlite3.connect(path)
            raw.execute(
                """
                CREATE TABLE source_stats (
                    source_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    excluded INTEGER NOT NULL,
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
                """
            )
            raw.execute(
                """
                INSERT INTO source_stats VALUES
                  (1, 'Squiggle', 1, 10, 6, 0.6, 10, 6, 0.6, 0, 0, 0, 0, 0, 0, 1)
                """
            )
            raw.commit()
            raw.close()
            store = Store.open_file(path)
            self.addCleanup(store.close)
            names = [
                row["name"] for row in store.db.execute("PRAGMA table_info(source_stats)")
            ]
            self.assertNotIn("excluded", names)
            store.recompute()
            self.assertTrue(store.tip_rule_current())


def _crest(store: Store, team_id: int) -> bytes | None:
    for team in store.bootstrap(0).teams:
        if team.id == team_id:
            return team.logo_bytes
    return None


def _live(game_id, complete, home, away, winner=None):
    return LiveScore(
        id=game_id,
        complete=complete,
        hscore=home,
        ascore=away,
        hgoals=None,
        hbehinds=None,
        agoals=None,
        abehinds=None,
        winner_team_id=winner,
        timestr="",
        updated="",
    )


if __name__ == "__main__":
    unittest.main()
