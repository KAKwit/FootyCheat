import unittest

from footy_cheat.engine.model import (
    MIN_RATE_SAMPLE,
    GameIn,
    ModelRow,
    TipIn,
    analyse,
    games_clear,
    running_clear,
    side_margin_error,
    sort_models,
)
from footy_cheat.format import format_clear


def game(game_id, when, winner, complete):
    return GameIn(
        id=game_id,
        year=2024,
        unixtime=when,
        complete=complete,
        home_id=1,
        away_id=2,
        home_name="Home",
        away_name="Away",
        winner_id=winner,
    )


def tip(game_id, source, name, team, confidence=60):
    return TipIn(
        game_id=game_id,
        source_id=source,
        source_name=name,
        tip_team_id=team,
        confidence=confidence,
    )


def crowd(game_id, home_tippers, away_tippers):
    tips = []
    for n in range(home_tippers):
        tips.append(tip(game_id, 100 + n, f"Crowd {n}", 1))
    for n in range(away_tippers):
        tips.append(tip(game_id, 200 + n, f"Away {n}", 2))
    return tips


class ModelTests(unittest.TestCase):
    def test_no_tips_means_no_call(self):
        analysis = analyse([game(1, 1, 1, 100)], [])
        self.assertEqual(analysis.calls, [])

    def test_aggregate_is_not_part_of_the_consensus(self):
        analysis = analyse(
            [game(1, 1, 1, 100)],
            [
                tip(1, 8, "Aggregate", 2),
                tip(1, 8, "Aggregate", 2),
                tip(1, 1, "Squiggle", 1),
            ],
        )
        call = analysis.calls[0]
        self.assertEqual(len(analysis.calls), 1)
        self.assertEqual(call.consensus_team_id, 1)
        self.assertEqual(call.models_used, 1)
        self.assertEqual(call.pick_team_id, 1)
        self.assertEqual([row.name for row in analysis.rankings], ["Squiggle"])

    def test_only_aggregate_tips_produce_no_call(self):
        analysis = analyse([game(1, 1, 1, 100)], [tip(1, 8, "Aggregate", 1)])
        self.assertEqual(analysis.calls, [])
        self.assertEqual(analysis.rankings, [])

    def test_earlier_game_cannot_see_later_results(self):
        analysis = analyse(
            [game(1, 10, 1, 100), game(2, 20, 2, 100)],
            [
                tip(1, 1, "A", 1),
                tip(1, 2, "B", 1),
                tip(2, 1, "A", 2),
                tip(2, 2, "B", 1),
            ],
        )
        first = next(call for call in analysis.calls if call.game_id == 1)
        second = next(call for call in analysis.calls if call.game_id == 2)
        self.assertEqual(first.prior_model_tips, 0)
        self.assertEqual(second.prior_model_tips, 2)

    def test_a_mild_consensus_is_not_overturned(self):
        games = []
        tips = []
        for n in range(1, 31):
            games.append(game(n, n, 2, 100))
            tips.extend(crowd(n, 4, 0))
            tips.append(tip(n, 5, "U", 2))
            tips.append(tip(n, 6, "V", 2))
        games.append(game(99, 1000, None, 0))
        tips.extend(crowd(99, 4, 0))
        tips.append(tip(99, 5, "U", 2))
        tips.append(tip(99, 6, "V", 2))
        analysis = analyse(games, tips)
        call = next(item for item in analysis.calls if item.game_id == 99)
        self.assertEqual(call.consensus_team_id, 1)
        self.assertEqual(call.pick_team_id, 1)
        self.assertTrue(call.followed_consensus)
        self.assertIn("follows that majority", call.summary)
        self.assertIn("Home", call.summary)
        first = next(item for item in analysis.calls if item.game_id == 1)
        self.assertTrue(first.followed_consensus)
        self.assertEqual(first.prior_model_tips, 0)

    def test_a_level_vote_follows_the_greater_stated_confidence(self):
        analysis = analyse(
            [game(1, 1, 1, 100)],
            [
                TipIn(1, 1, "High", 1, 80),
                TipIn(1, 2, "Low", 2, 55),
            ],
        )
        call = analysis.calls[0]
        self.assertEqual(len(analysis.calls), 1)
        self.assertEqual(call.consensus_team_id, 1)
        self.assertEqual(call.pick_team_id, 1)
        self.assertTrue(call.followed_consensus)
        self.assertEqual(call.consensus_votes, 1)
        self.assertIn("level", call.summary)
        self.assertIn("Home", call.summary)

    def test_a_small_confidence_gap_breaks_a_level_vote(self):
        analysis = analyse(
            [game(1, 1, 2, 100)],
            [
                TipIn(1, 1, "A", 1, 60),
                TipIn(1, 2, "B", 2, 60.04),
            ],
        )
        call = analysis.calls[0]
        self.assertEqual(call.pick_team_id, 2)
        self.assertTrue(call.followed_consensus)
        self.assertEqual(call.consensus_votes, 1)

    def test_a_landslide_is_not_flipped(self):
        games = []
        tips = []
        for n in range(1, 31):
            games.append(game(n, n, 2, 100))
            tips.extend(crowd(n, 9, 0))
            tips.append(tip(n, 5, "U", 2))
            tips.append(tip(n, 6, "V", 2))
        games.append(game(99, 1000, None, 0))
        tips.extend(crowd(99, 9, 0))
        tips.append(tip(99, 5, "U", 2))
        tips.append(tip(99, 6, "V", 2))
        call = next(item for item in analyse(games, tips).calls if item.game_id == 99)
        self.assertTrue(call.followed_consensus)
        self.assertEqual(call.pick_team_id, 1)

    def test_short_history_does_not_chase_upsets(self):
        games = []
        tips = []
        for n in range(1, 6):
            games.append(game(n, n, 2, 100))
            tips.extend(crowd(n, 4, 0))
            tips.append(tip(n, 5, "U", 2))
            tips.append(tip(n, 6, "V", 2))
        games.append(game(99, 100, None, 0))
        tips.extend(crowd(99, 4, 0))
        tips.append(tip(99, 5, "U", 2))
        tips.append(tip(99, 6, "V", 2))
        call = next(item for item in analyse(games, tips).calls if item.game_id == 99)
        self.assertTrue(call.followed_consensus)
        self.assertEqual(call.pick_team_id, 1)

    def test_confidence_rises_when_a_split_keeps_winning(self):
        games = []
        tips = []
        for n in range(1, 41):
            games.append(game(n, n, 1, 100))
            tips.extend(crowd(n, 4, 2))
        analysis = analyse(games, tips)
        first = next(call for call in analysis.calls if call.game_id == 1)
        later = next(call for call in analysis.calls if call.game_id == 40)
        self.assertGreater(later.confidence, first.confidence + 10)
        self.assertGreater(later.confidence, 85)

    def test_tiny_samples_do_not_top_the_board(self):
        games = []
        tips = []
        for n in range(1, 101):
            games.append(game(n, n, 1, 100))
            tips.append(tip(n, 1, "Solid", 2 if n > 70 else 1))
        games.append(game(201, 201, 1, 100))
        games.append(game(202, 202, 1, 100))
        tips.append(tip(201, 2, "Lucky", 1))
        tips.append(tip(202, 2, "Lucky", 1))
        rankings = analyse(games, tips).rankings
        solid = next(row for row in rankings if row.name == "Solid")
        lucky = next(row for row in rankings if row.name == "Lucky")
        self.assertGreater(solid.score, lucky.score)
        self.assertEqual(rankings[0].name, "Solid")

    def test_draws_are_not_upsets_and_are_not_correct_tips(self):
        analysis = analyse(
            [game(1, 1, None, 100)],
            [tip(1, 1, "A", 1), tip(1, 2, "B", 1), tip(1, 3, "C", 2)],
        )
        self.assertIsNone(analysis.calls[0].result_was_upset)
        row = next(item for item in analysis.rankings if item.name == "A")
        self.assertEqual(row.tips, 1)
        self.assertEqual(row.correct, 0)
        self.assertEqual(row.upset_chances, 0)

    def test_future_games_do_not_train_the_model(self):
        analysis = analyse(
            [game(1, 10, None, 40), game(2, 20, 1, 100)],
            [tip(1, 1, "A", 2), tip(2, 1, "A", 1)],
        )
        live = next(call for call in analysis.calls if call.game_id == 1)
        self.assertIsNone(live.result_was_upset)
        self.assertEqual(len(analysis.rankings), 1)
        self.assertEqual(analysis.rankings[0].tips, 1)
        self.assertEqual(analysis.rankings[0].correct, 1)


class FieldTests(unittest.TestCase):
    def test_running_clear_ends_on_the_season_margin(self):
        increments = [
            (2, "Round 2", {1: (1, 1), 2: (1, 1)}),
            (1, "Round 1", {1: (1, 1), 2: (1, 0)}),
        ]
        rounds, names, lines = running_clear(increments, [(1, "Alpha")], {1: (1, 1)})
        self.assertEqual(rounds, [1, 2])
        self.assertEqual(names, ["Round 1", "Round 2"])
        self.assertEqual(lines[0].role, "leader")
        self.assertEqual(lines[0].points, [0.5, 0.5])
        self.assertEqual(lines[1].name, "Footy Cheat")
        self.assertEqual(lines[1].points, [0.5, 0.25])
        self.assertEqual(games_clear(2, 2, 0.75), lines[0].points[-1])
        self.assertEqual(games_clear(1, 1, 0.75), lines[1].points[-1])

    def test_a_thin_rate_cannot_outrank_a_full_sample(self):
        lucky = _row("Lucky", upset_chances=1, upset_hits=1, upset_accuracy=1.0)
        steady = _row(
            "Steady",
            upset_chances=MIN_RATE_SAMPLE,
            upset_hits=6,
            upset_accuracy=0.5,
        )
        self.assertEqual(
            [row.name for row in sort_models([lucky, steady], "upset")],
            ["Steady", "Lucky"],
        )
        fluke = _row("Fluke", margin_error=1.0, margin_samples=2)
        measured = _row("Measured", margin_error=26.0, margin_samples=MIN_RATE_SAMPLE)
        closer = _row("Closer", margin_error=20.0, margin_samples=MIN_RATE_SAMPLE)
        ordered = [row.name for row in sort_models([fluke, measured, closer], "margin")]
        self.assertEqual(ordered, ["Closer", "Measured", "Fluke"])

    def test_a_side_margin_uses_the_median_line(self):
        self.assertEqual(side_margin_error([12, 18, 30], 10, False), 28)
        self.assertEqual(side_margin_error([4, 10, 22], 10, True), 0)
        self.assertEqual(side_margin_error([8], 0, False), 8)
        self.assertIsNone(side_margin_error([], 10, True))

    def test_clear_labels_round_half_a_game_away_from_zero(self):
        self.assertEqual(format_clear(0), "0")
        self.assertEqual(format_clear(0.04), "0")
        self.assertEqual(format_clear(0.5), "+0.5")
        self.assertEqual(format_clear(3), "+3")
        self.assertEqual(format_clear(-2), "−2")
        self.assertEqual(format_clear(-0.26), "−0.3")


def _row(name, **overrides):
    values = dict(
        source_id=len(name),
        name=name,
        tips=30,
        correct=15,
        accuracy=0.5,
        upset_chances=0,
        upset_hits=0,
        upset_accuracy=0.0,
        dissent_tips=0,
        dissent_accuracy=0.0,
    )
    values.update(overrides)
    return ModelRow(**values)


if __name__ == "__main__":
    unittest.main()
