from dataclasses import dataclass, field

from .numbers import dart_round
from .types import ModelRow, RaceLine

TIPPING_RULE_REVISION = 2
MIN_RATE_SAMPLE = 12
FOOTY_NAME = "Footy Cheat"


@dataclass
class GameIn:
    id: int
    year: int
    unixtime: int
    complete: int
    home_id: int
    away_id: int
    home_name: str
    away_name: str
    winner_id: int | None


@dataclass
class TipIn:
    game_id: int
    source_id: int
    source_name: str
    tip_team_id: int
    confidence: float | None


@dataclass
class GameCall:
    game_id: int
    pick_team_id: int | None
    confidence: float
    consensus_team_id: int | None
    consensus_votes: int
    models_used: int
    followed_consensus: bool
    result_was_upset: bool | None
    summary: str
    prior_model_tips: int


@dataclass
class SourceRanking:
    source_id: int
    name: str
    tips: int
    correct: int
    accuracy: float
    recent_tips: int
    recent_correct: int
    recent_accuracy: float
    upset_chances: int
    upset_hits: int
    upset_accuracy: float
    dissent_tips: int
    dissent_correct: int
    dissent_accuracy: float
    score: float


@dataclass
class Analysis:
    calls: list[GameCall]
    rankings: list[SourceRanking]


@dataclass
class _Acc:
    tips: int = 0
    correct: int = 0
    upset_chances: int = 0
    upset_hits: int = 0
    dissent_tips: int = 0
    dissent_correct: int = 0
    by_year: dict[int, tuple[int, int]] = field(default_factory=dict)


@dataclass
class _Consensus:
    team: int
    votes: int
    total: int
    share: float


def is_aggregate_source(name: str) -> bool:
    return name.strip().lower() == "aggregate"


def analyse(games: list[GameIn], tips: list[TipIn]) -> Analysis:
    by_key: dict[tuple[int, int], TipIn] = {}
    for tip in tips:
        if is_aggregate_source(tip.source_name):
            continue
        by_key[(tip.game_id, tip.source_id)] = tip
    unique = list(by_key.values())

    names: dict[int, str] = {}
    for tip in unique:
        names.setdefault(tip.source_id, tip.source_name)

    tips_by_game: dict[int, list[TipIn]] = {}
    for tip in unique:
        tips_by_game.setdefault(tip.game_id, []).append(tip)

    finished: list[GameIn] = []
    upcoming: list[GameIn] = []
    for game in games:
        if game.complete >= 100:
            finished.append(game)
        else:
            upcoming.append(game)

    def by_time(game: GameIn) -> tuple[int, int]:
        return (game.unixtime, game.id)

    finished.sort(key=by_time)
    upcoming.sort(key=by_time)

    stats: dict[int, _Acc] = {source_id: _Acc() for source_id in names}
    follow_buckets: dict[int, tuple[int, int]] = {}
    split_bucket = (0, 0)
    calls: list[GameCall] = []
    if finished:
        max_year = max(game.year for game in finished)
        recent_from = max_year - 1 if max_year > 0 else 0
    else:
        recent_from = 0

    for game in finished:
        game_tips = tips_by_game.get(game.id, [])
        prior = _prior_tips(stats)
        call = _decide(game, game_tips, stats, follow_buckets, split_bucket, prior)
        if call is not None:
            winner = _finished_winner(game)
            if winner is not None:
                split_bucket = _record_calibration(
                    call, winner, follow_buckets, split_bucket
                )
            calls.append(call)
        _learn(game, game_tips, stats)

    for game in upcoming:
        game_tips = tips_by_game.get(game.id, [])
        prior = _prior_tips(stats)
        call = _decide(game, game_tips, stats, follow_buckets, split_bucket, prior)
        if call is not None:
            calls.append(call)

    rankings: list[SourceRanking] = []
    for source_id, acc in stats.items():
        name = names.get(source_id, f"Model {source_id}")
        rankings.append(_ranking_of(source_id, name, acc, recent_from))
    rankings.sort(key=lambda row: (-row.score, -row.tips, row.name))
    return Analysis(calls=calls, rankings=rankings)


@dataclass
class SeasonStat:
    source_id: int
    name: str
    tips: int
    correct: int
    accuracy: float
    upset_chances: int
    upset_hits: int
    upset_accuracy: float
    dissent_tips: int
    dissent_correct: int
    dissent_accuracy: float


def season_record(games: list[GameIn], tips: list[TipIn]) -> list[SeasonStat]:
    """Settled results for one season. Unfinished games do not count."""
    by_key: dict[tuple[int, int], TipIn] = {}
    names: dict[int, str] = {}
    for tip in tips:
        if is_aggregate_source(tip.source_name):
            continue
        by_key[(tip.game_id, tip.source_id)] = tip
        names.setdefault(tip.source_id, tip.source_name)
    tips_by_game: dict[int, list[TipIn]] = {}
    for tip in by_key.values():
        tips_by_game.setdefault(tip.game_id, []).append(tip)
    stats: dict[int, _Acc] = {}
    finished = [game for game in games if game.complete >= 100]
    finished.sort(key=lambda game: (game.unixtime, game.id))
    for game in finished:
        _learn(game, tips_by_game.get(game.id, []), stats)
    rows: list[SeasonStat] = []
    for source_id, acc in stats.items():
        if acc.tips <= 0:
            continue
        rows.append(
            SeasonStat(
                source_id=source_id,
                name=names.get(source_id, f"Model {source_id}"),
                tips=acc.tips,
                correct=acc.correct,
                accuracy=_ratio(acc.correct, acc.tips),
                upset_chances=acc.upset_chances,
                upset_hits=acc.upset_hits,
                upset_accuracy=(
                    0.0
                    if acc.upset_chances == 0
                    else _ratio(acc.upset_hits, acc.upset_chances)
                ),
                dissent_tips=acc.dissent_tips,
                dissent_correct=acc.dissent_correct,
                dissent_accuracy=_ratio(acc.dissent_correct, acc.dissent_tips),
            )
        )
    rows.sort(key=lambda row: (-row.accuracy, -row.tips, row.name))
    return rows


def _prior_tips(stats: dict[int, _Acc]) -> int:
    return sum(acc.tips for acc in stats.values())


def _finished_winner(game: GameIn) -> int | None:
    return game.winner_id if game.complete >= 100 else None


def _on_side(game: GameIn, team: int) -> bool:
    return team == game.home_id or team == game.away_id


def _team_name(game: GameIn, team: int) -> str:
    if team == game.home_id:
        return game.home_name
    if team == game.away_id:
        return game.away_name
    return f"Team {team}"


def _majority(tips: list[TipIn]) -> _Consensus | None:
    votes: dict[int, tuple[int, float]] = {}
    for tip in tips:
        count, stated = votes.get(tip.tip_team_id, (0, 0.0))
        votes[tip.tip_team_id] = (count + 1, stated + (tip.confidence if tip.confidence is not None else 50.0))
    ranked = [(team, count, stated) for team, (count, stated) in votes.items()]
    ranked.sort(key=lambda item: (-item[1], -item[2]))
    if not ranked:
        return None
    if (
        len(ranked) > 1
        and ranked[0][1] == ranked[1][1]
        and abs(ranked[0][2] - ranked[1][2]) < 1e-9
    ):
        return None
    top = ranked[0]
    total = len(tips)
    return _Consensus(team=top[0], votes=top[1], total=total, share=top[1] / total)


def _bucket(share: float) -> int:
    pct = dart_round(share * 100)
    bucket = (pct // 5) * 5
    if bucket < 50:
        return 50
    if bucket > 95:
        return 95
    return bucket


def _calibrated(hits: int, n: int, fallback: float) -> float:
    smooth = (hits + 2.0) / (n + 4.0)
    if n >= 30:
        return smooth
    weight = n / 30.0
    return weight * smooth + (1.0 - weight) * fallback


def _decide(
    game: GameIn,
    game_tips: list[TipIn],
    stats: dict[int, _Acc],
    follow_buckets: dict[int, tuple[int, int]],
    split_bucket: tuple[int, int],
    prior: int,
) -> GameCall | None:
    usable = [tip for tip in game_tips if _on_side(game, tip.tip_team_id)]
    if not usable:
        return None

    consensus = _majority(usable)
    pick = consensus.team if consensus is not None else None
    followed = consensus is not None
    if consensus is None:
        weight: dict[int, float] = {}
        for tip in usable:
            acc = stats.get(tip.source_id)
            skill = (
                (acc.correct + 2.0) / (acc.tips + 4.0)
                if acc is not None and acc.tips >= 8
                else 0.5
            )
            weight[tip.tip_team_id] = weight.get(tip.tip_team_id, 0) + skill
        best_team = None
        best_weight = None
        tied = False
        for team, value in weight.items():
            if best_weight is None or value > best_weight:
                best_team = team
                best_weight = value
                tied = False
            elif value == best_weight:
                tied = True
        pick = None if tied else best_team
        followed = False

    if consensus is not None:
        bucket = follow_buckets.get(_bucket(consensus.share), (0, 0))
        fallback = 0.5 + (consensus.share - 0.5) * 0.85
        probability = _calibrated(bucket[0], bucket[1], fallback)
    else:
        probability = _calibrated(split_bucket[0], split_bucket[1], 0.52)
    rounded = min(99, max(1, dart_round(probability * 100)))
    confidence = float(rounded)
    summary = _summary_text(game, pick, consensus, confidence)
    winner = _finished_winner(game)
    if winner is None or consensus is None:
        result_was_upset = None
    else:
        result_was_upset = winner != consensus.team

    return GameCall(
        game_id=game.id,
        pick_team_id=pick,
        confidence=confidence,
        consensus_team_id=None if consensus is None else consensus.team,
        consensus_votes=0 if consensus is None else consensus.votes,
        models_used=len(usable),
        followed_consensus=followed,
        result_was_upset=result_was_upset,
        summary=summary,
        prior_model_tips=prior,
    )


def _summary_text(
    game: GameIn,
    pick: int | None,
    consensus: _Consensus | None,
    confidence: float,
) -> str:
    pct = dart_round(confidence)
    if consensus is not None and pick is not None and pick == consensus.team:
        level = consensus.votes * 2 == consensus.total
        if level:
            return (
                f"The models are level at {consensus.votes} each. "
                f"More confidence is stated for {_team_name(game, pick)}, so Footy Cheat follows that side. "
                f"Confidence {pct}%, from how often a vote this close has held."
            )
        return (
            f"Consensus tips {_team_name(game, consensus.team)} "
            f"({consensus.votes} of {consensus.total} models). "
            f"Footy Cheat follows that majority. "
            f"Confidence {pct}%, from how often a consensus this strong has held."
        )
    if pick is not None:
        return (
            f"The count is level and the stated confidence is level too. "
            f"Footy Cheat leans {_team_name(game, pick)} on the models with the stronger records so far. "
            f"Confidence {pct}%."
        )
    return "The models are level, and so are their records. No tip."


def _record_calibration(
    call: GameCall,
    winner: int,
    follow_buckets: dict[int, tuple[int, int]],
    split_bucket: tuple[int, int],
) -> tuple[int, int]:
    pick = call.pick_team_id
    if pick is None:
        return split_bucket
    won = pick == winner
    if call.followed_consensus and call.models_used > 0:
        share = call.consensus_votes / call.models_used
        key = _bucket(share)
        hits, n = follow_buckets.get(key, (0, 0))
        follow_buckets[key] = (hits + (1 if won else 0), n + 1)
    else:
        split_bucket = (split_bucket[0] + (1 if won else 0), split_bucket[1] + 1)
    return split_bucket


def _learn(game: GameIn, game_tips: list[TipIn], stats: dict[int, _Acc]) -> None:
    if game.complete < 100:
        return
    usable = [tip for tip in game_tips if _on_side(game, tip.tip_team_id)]
    consensus = _majority(usable)
    winner = game.winner_id
    upset = winner is not None and consensus is not None and winner != consensus.team

    for tip in usable:
        acc = stats.setdefault(tip.source_id, _Acc())
        acc.tips += 1
        right = winner is not None and winner == tip.tip_team_id
        if right:
            acc.correct += 1
        year_tips, year_correct = acc.by_year.get(game.year, (0, 0))
        acc.by_year[game.year] = (year_tips + 1, year_correct + (1 if right else 0))
        if consensus is not None and tip.tip_team_id != consensus.team:
            acc.dissent_tips += 1
            if right:
                acc.dissent_correct += 1
        if upset:
            acc.upset_chances += 1
            if right:
                acc.upset_hits += 1


def _ratio(hits: int, n: int) -> float:
    return 0.0 if n <= 0 else hits / n


def _ranking_of(source_id: int, name: str, acc: _Acc, recent_from: int) -> SourceRanking:
    recent_tips = 0
    recent_correct = 0
    for year, (tips, correct) in acc.by_year.items():
        if year >= recent_from:
            recent_tips += tips
            recent_correct += correct
    accuracy = _ratio(acc.correct, acc.tips)
    recent_accuracy = accuracy if recent_tips == 0 else _ratio(recent_correct, recent_tips)
    upset_accuracy = 0.0 if acc.upset_chances == 0 else _ratio(acc.upset_hits, acc.upset_chances)
    upset_for_score = upset_accuracy if acc.upset_chances >= MIN_RATE_SAMPLE else accuracy
    score = 100.0 * (0.45 * accuracy + 0.25 * recent_accuracy + 0.30 * upset_for_score)
    if acc.tips < 30:
        score *= acc.tips / 30.0
    return SourceRanking(
        source_id=source_id,
        name=name,
        tips=acc.tips,
        correct=acc.correct,
        accuracy=accuracy,
        recent_tips=recent_tips,
        recent_correct=recent_correct,
        recent_accuracy=recent_accuracy,
        upset_chances=acc.upset_chances,
        upset_hits=acc.upset_hits,
        upset_accuracy=upset_accuracy,
        dissent_tips=acc.dissent_tips,
        dissent_correct=acc.dissent_correct,
        dissent_accuracy=_ratio(acc.dissent_correct, acc.dissent_tips),
        score=score,
    )


def field_median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return 0.0
    mid = count // 2
    if count % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def games_clear(correct: int, tips: int, median_accuracy: float) -> float:
    """Wins above a model that tipped the same games at the median accuracy."""
    if tips <= 0:
        return 0.0
    return correct - median_accuracy * tips


def side_margin_error(margins: list[float], actual: float, correct: bool) -> float | None:
    """Error of the median predicted margin on one side of a game.

    A right tip misses by the gap between that line and the result. A wrong tip,
    or a draw, misses by the line plus the actual margin. That is how Squiggle
    records ``err``.
    """
    if not margins:
        return None
    predicted = field_median(margins)
    if correct:
        return abs(predicted - actual)
    return abs(predicted) + actual


def running_clear(
    increments: list[tuple[int, str, dict[int, tuple[int, int]]]],
    leaders: list[tuple[int, str]],
    footy: dict[int, tuple[int, int]] | None,
) -> tuple[list[int], list[str], list[RaceLine]]:
    """Games ahead of the median model after each round.

    increments are (round, round name, {source_id: (tips, correct)}) for that
    round only. footy maps a round to that round's own tips and correct.
    """
    merged: dict[int, tuple[str, dict[int, tuple[int, int]]]] = {}
    for rnd, name, counts in increments:
        title, bucket = merged.get(rnd, (name, {}))
        for source_id, (tips, correct) in counts.items():
            old_tips, old_correct = bucket.get(source_id, (0, 0))
            bucket[source_id] = (old_tips + tips, old_correct + correct)
        merged[rnd] = (title, bucket)
    if footy is not None:
        for rnd in footy:
            merged.setdefault(rnd, (f"Round {rnd}" if rnd else "Opening Round", {}))

    cumulative: dict[int, list[int]] = {}
    footy_total = [0, 0]
    leader_points = {source_id: [] for source_id, _name in leaders}
    footy_points: list[float] = []
    rounds: list[int] = []
    names: list[str] = []
    for rnd in sorted(merged):
        title, counts = merged[rnd]
        for source_id, (tips, correct) in counts.items():
            total = cumulative.setdefault(source_id, [0, 0])
            total[0] += tips
            total[1] += correct
        if footy is not None:
            add_tips, add_correct = footy.get(rnd, (0, 0))
            footy_total[0] += add_tips
            footy_total[1] += add_correct
        accuracies = [correct / tips for tips, correct in cumulative.values() if tips > 0]
        if not accuracies:
            continue
        median_accuracy = field_median(accuracies)
        for source_id, _name in leaders:
            tips, correct = cumulative.get(source_id, [0, 0])
            leader_points[source_id].append(games_clear(correct, tips, median_accuracy))
        if footy is not None:
            footy_points.append(games_clear(footy_total[1], footy_total[0], median_accuracy))
        rounds.append(rnd)
        names.append(title)

    lines = [
        RaceLine(name=name, role="leader", points=leader_points[source_id])
        for source_id, name in leaders
    ]
    if footy is not None:
        lines.append(RaceLine(name=FOOTY_NAME, role="footy", points=footy_points))
    return rounds, names, lines


def sort_models(rows: list[ModelRow], sort: str) -> list[ModelRow]:
    ordered = list(rows)
    if sort == "upset":
        ordered.sort(key=_upset_key)
    elif sort == "margin":
        ordered.sort(key=_margin_key)
    else:
        ordered.sort(key=lambda row: (-row.accuracy, -row.tips, row.name))
    return ordered


def _upset_key(row: ModelRow) -> tuple:
    ready = row.upset_chances >= MIN_RATE_SAMPLE
    return (0 if ready else 1, -row.upset_accuracy, -row.upset_chances, row.name)


def _margin_key(row: ModelRow) -> tuple:
    ready = row.margin_error is not None and row.margin_samples >= MIN_RATE_SAMPLE
    error = row.margin_error if row.margin_error is not None else 1e6
    return (0 if ready else 1, error, -row.margin_samples, row.name)
