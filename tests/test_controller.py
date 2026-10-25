import unittest

from footy_cheat.controller import AppController
from footy_cheat.engine.store import Store
from footy_cheat.engine.sync import Fetcher
from footy_cheat.engine.types import SyncMode
from tests.test_sync import match


class _Fetcher(Fetcher):
    def get_json(self, query: str) -> object:
        raise AssertionError(query)

    def get_bytes(self, url: str) -> bytes:
        return b""


class _Session:
    def __init__(self, plan: list[str]):
        self.stop = False
        self.plan = plan
        self.calls = 0

    def run(self, _email: str, _on_payload) -> None:
        self.calls += 1
        action = self.plan[self.calls - 1]
        if action == "error":
            raise ConnectionError("dropped")
        if action == "stop":
            self.stop = True


class ControllerTests(unittest.TestCase):
    def test_choosing_a_season_opens_the_round_still_to_play(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.replace_games(
            2024,
            [
                match(1, 100, 1, year=2024, rnd=1, when=10),
                match(2, 100, 1, year=2024, rnd=2, when=20),
            ],
        )
        store.replace_games(
            2025,
            [
                match(3, 0, None, year=2025, rnd=1, when=100),
                match(4, 0, None, year=2025, rnd=24, when=200),
            ],
        )
        store.replace_games(2026, [match(5, 40, None, year=2026, rnd=5, when=30)])
        controller = AppController(store, _Fetcher())
        controller.boot = store.bootstrap(30)
        self.assertEqual(controller.boot.focus.year, 2026)
        controller.choose_year(2025)
        self.assertEqual(controller.round, 1)
        controller.choose_year(2024)
        self.assertEqual(controller.round, 2)
        controller.choose_year(2026)
        self.assertEqual(controller.round, 5)

    def test_the_live_stream_reconnects_while_a_game_is_near(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        now = 1_700_000_000
        store.replace_games(2024, [match(1, 0, None, when=now)])
        controller = AppController(store, _Fetcher(), clock=lambda: _moment(now))
        slept: list[float] = []
        controller._sleep = slept.append
        session = _Session(["error", "error", "stop"])
        controller._live = session
        controller._live_running = True
        controller._run_live(session, "")
        self.assertEqual(session.calls, 3)
        self.assertEqual(slept, [2, 4])
        self.assertIsNone(controller._live)
        self.assertFalse(controller._live_running)

    def test_the_live_stream_stops_when_no_game_is_near(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        controller = AppController(store, _Fetcher())
        controller._sleep = lambda _seconds: self.fail("slept with nothing to follow")
        session = _Session(["eof", "eof"])
        controller._live = session
        controller._live_running = True
        controller._run_live(session, "")
        self.assertEqual(session.calls, 1)
        self.assertFalse(controller._live_running)

    def test_arrows_move_within_the_open_fixture(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        store.replace_games(
            2026,
            [
                match(1, 100, 1, year=2026, rnd=1, when=10),
                match(2, 0, None, year=2026, rnd=1, when=20),
                match(3, 0, None, year=2026, rnd=1, when=30),
                match(4, 0, None, year=2026, rnd=2, when=40),
            ],
        )
        controller = AppController(store, _Fetcher())
        controller.boot = store.bootstrap(15)
        controller.year = 2026
        controller.round = 1
        controller._load_round(2026, 1)
        self.assertEqual(controller.selected_id, 2)
        controller.move_game(1)
        self.assertEqual(controller.selected_id, 3)
        controller.move_game(1)
        self.assertEqual(controller.selected_id, 3)
        controller.move_game(-1)
        self.assertEqual(controller.selected_id, 2)
        controller.move_round(1)
        self.assertEqual(controller.round, 2)
        self.assertEqual(controller.selected_id, 4)
        controller.move_round(1)
        self.assertEqual(controller.round, 2)
        controller.move_round(-1)
        self.assertEqual(controller.round, 1)

    def test_a_second_update_is_a_notice(self):
        store = Store.open_memory()
        self.addCleanup(store.close)
        controller = AppController(store, _Fetcher())
        controller._running = True
        controller._spawn(SyncMode.FORCE)
        self.assertEqual(controller.notice, "An update is already running.")
        self.assertIsNone(controller.error)
        self.assertIsNone(controller._cancel)


def _moment(unix: int):
    from datetime import datetime

    return datetime.fromtimestamp(unix)


if __name__ == "__main__":
    unittest.main()
