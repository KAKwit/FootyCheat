from dataclasses import dataclass

from .. import __version__
from .model import is_aggregate_source


@dataclass
class ParsedTeam:
    id: int
    name: str
    abbrev: str
    logo: str
    debut: int | None
    retirement: int | None


@dataclass
class ParsedSource:
    id: int
    name: str
    url: str
    icon: str


@dataclass
class ParsedGame:
    id: int
    year: int
    round: int
    roundname: str
    hteam_id: int
    ateam_id: int
    hteam: str
    ateam: str
    hscore: int | None
    ascore: int | None
    hgoals: int | None
    hbehinds: int | None
    agoals: int | None
    abehinds: int | None
    complete: int
    winner_team_id: int | None
    winner: str
    venue: str
    date: str
    localtime: str
    unixtime: int
    tz: str
    updated: str
    timestr: str
    is_final: int
    is_grand_final: int


@dataclass
class ParsedTip:
    game_id: int
    source_id: int
    source_name: str
    year: int
    round: int
    tip_team_id: int
    tip: str
    hteam: str
    ateam: str
    hteam_id: int | None
    ateam_id: int | None
    confidence: float | None
    hconfidence: float | None
    margin: float | None
    hmargin: float | None
    err: float | None
    bits: float | None
    api_correct: int | None
    date: str
    venue: str
    updated: str


@dataclass
class ParsedStanding:
    team_id: int
    rank: int
    name: str
    played: int
    wins: int
    losses: int
    draws: int
    points: int
    percentage: float
    points_for: int
    points_against: int
    goals_for: int | None
    goals_against: int | None
    behinds_for: int | None
    behinds_against: int | None


@dataclass
class LiveScore:
    id: int
    complete: int
    hscore: int | None
    ascore: int | None
    hgoals: int | None
    hbehinds: int | None
    agoals: int | None
    abehinds: int | None
    winner_team_id: int | None
    timestr: str
    updated: str


def user_agent(email: str) -> str:
    product = f"Footy Cheat/{__version__} (GNOME; local cache)"
    trimmed = email.strip()
    if "@" in trimmed and not any(char.isspace() for char in trimmed):
        return f"{product} {trimmed}"
    return product


def logo_url(path: str) -> str | None:
    trimmed = path.strip()
    if not trimmed:
        return None
    if trimmed.startswith("http://") or trimmed.startswith("https://"):
        return trimmed
    if trimmed.startswith("/"):
        return f"https://squiggle.com.au{trimmed}"
    return None


def logo_mime(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/png"


def looks_like_image(data: bytes) -> bool:
    if len(data) >= 4 and data[0:4] == b"\x89PNG":
        return True
    if len(data) >= 3 and data[0:3] == b"\xff\xd8\xff":
        return True
    if len(data) >= 4 and data[0:4] == b"GIF8":
        return True
    if len(data) > 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def parse_teams(value: object) -> list[ParsedTeam]:
    teams: list[ParsedTeam] = []
    for row in _arr(value, "teams"):
        team_id = _num_int(row.get("id"))
        if team_id is None:
            continue
        teams.append(
            ParsedTeam(
                id=team_id,
                name=_text(row.get("name")),
                abbrev=_text(row.get("abbrev")),
                logo=_text(row.get("logo")),
                debut=_num_int(row.get("debut")),
                retirement=_num_int(row.get("retirement")),
            )
        )
    if not teams:
        raise ValueError("Squiggle returned no teams")
    return teams


def parse_sources(value: object) -> list[ParsedSource]:
    sources: list[ParsedSource] = []
    for row in _arr(value, "sources"):
        source_id = _num_int(row.get("id"))
        name = _text(row.get("name"))
        if source_id is None or is_aggregate_source(name):
            continue
        sources.append(
            ParsedSource(
                id=source_id,
                name=name,
                url=_text(row.get("url")),
                icon=_text(row.get("icon")),
            )
        )
    if not sources:
        raise ValueError("Squiggle returned no sources")
    return sources


def parse_games(value: object) -> list[ParsedGame]:
    games: list[ParsedGame] = []
    for row in _arr(value, "games"):
        game_id = _num_int(row.get("id"))
        hteam_id = _num_int(row.get("hteamid"))
        ateam_id = _num_int(row.get("ateamid"))
        if game_id is None or hteam_id is None or ateam_id is None:
            continue
        year = _num_int(row.get("year")) or 0
        winner = _num_int(row.get("winnerteamid"))
        rnd = _num_int(row.get("round")) or 0
        name = _text(row.get("roundname"))
        games.append(
            ParsedGame(
                id=game_id,
                year=year,
                round=rnd,
                roundname=name if name else f"Round {rnd}",
                hteam_id=hteam_id,
                ateam_id=ateam_id,
                hteam=_text(row.get("hteam")),
                ateam=_text(row.get("ateam")),
                hscore=_num_int(row.get("hscore")),
                ascore=_num_int(row.get("ascore")),
                hgoals=_num_int(row.get("hgoals")),
                hbehinds=_num_int(row.get("hbehinds")),
                agoals=_num_int(row.get("agoals")),
                abehinds=_num_int(row.get("abehinds")),
                complete=_num_int(row.get("complete")) or 0,
                winner_team_id=winner if winner is not None and winner > 0 else None,
                winner=_text(row.get("winner")),
                venue=_text(row.get("venue")),
                date=_text(row.get("date")),
                localtime=_text(row.get("localtime")),
                unixtime=_num_int(row.get("unixtime")) or 0,
                tz=_text(row.get("tz")),
                updated=_text(row.get("updated")),
                timestr=_text(row.get("timestr")),
                is_final=_num_int(row.get("is_final")) or 0,
                is_grand_final=_num_int(row.get("is_grand_final")) or 0,
            )
        )
    return games


def parse_tips(value: object) -> list[ParsedTip]:
    tips: list[ParsedTip] = []
    for row in _arr(value, "tips"):
        game_id = _num_int(row.get("gameid"))
        source_id = _num_int(row.get("sourceid"))
        tip_team_id = _num_int(row.get("tipteamid"))
        source = _text(row.get("source"))
        if (
            game_id is None
            or source_id is None
            or tip_team_id is None
            or tip_team_id <= 0
            or is_aggregate_source(source)
        ):
            continue
        tips.append(
            ParsedTip(
                game_id=game_id,
                source_id=source_id,
                source_name=source,
                year=_num_int(row.get("year")) or 0,
                round=_num_int(row.get("round")) or 0,
                tip_team_id=tip_team_id,
                tip=_text(row.get("tip")),
                hteam=_text(row.get("hteam")),
                ateam=_text(row.get("ateam")),
                hteam_id=_num_int(row.get("hteamid")),
                ateam_id=_num_int(row.get("ateamid")),
                confidence=_num_float(row.get("confidence")),
                hconfidence=_num_float(row.get("hconfidence")),
                margin=_num_float(row.get("margin")),
                hmargin=_num_float(row.get("hmargin")),
                err=_num_float(row.get("err")),
                bits=_num_float(row.get("bits")),
                api_correct=_num_int(row.get("correct")),
                date=_text(row.get("date")),
                venue=_text(row.get("venue")),
                updated=_text(row.get("updated")),
            )
        )
    return tips


def parse_standings(value: object) -> list[ParsedStanding]:
    rows: list[ParsedStanding] = []
    for row in _arr(value, "standings"):
        team_id = _num_int(row.get("id"))
        if team_id is None:
            continue
        rows.append(
            ParsedStanding(
                team_id=team_id,
                rank=_num_int(row.get("rank")) or 0,
                name=_text(row.get("name")),
                played=_num_int(row.get("played")) or 0,
                wins=_num_int(row.get("wins")) or 0,
                losses=_num_int(row.get("losses")) or 0,
                draws=_num_int(row.get("draws")) or 0,
                points=_num_int(row.get("pts")) or 0,
                percentage=_num_float(row.get("percentage")) or 0,
                points_for=_num_int(row.get("for")) or 0,
                points_against=_num_int(row.get("against")) or 0,
                goals_for=_num_int(row.get("goals_for")),
                goals_against=_num_int(row.get("goals_against")),
                behinds_for=_num_int(row.get("behinds_for")),
                behinds_against=_num_int(row.get("behinds_against")),
            )
        )
    return rows


def parse_live_scores(value: object) -> list[LiveScore]:
    if isinstance(value, list):
        scores = []
        for row in value:
            if isinstance(row, dict):
                score = _parse_live(row)
                if score is not None:
                    scores.append(score)
        return scores
    if isinstance(value, dict):
        score = _parse_live(value)
        return [] if score is None else [score]
    return []


def _parse_live(row: dict) -> LiveScore | None:
    game_id = _num_int(row.get("id"))
    if game_id is None:
        return None
    winner = None
    winner_value = row.get("winner")
    if isinstance(winner_value, (int, float)) and not isinstance(winner_value, bool):
        number = int(winner_value)
        if number > 0:
            winner = number
    else:
        parsed = _num_int(row.get("winnerteamid"))
        if parsed is not None and parsed > 0:
            winner = parsed
    return LiveScore(
        id=game_id,
        complete=_num_int(row.get("complete")) or 0,
        hscore=_num_int(row.get("hscore")),
        ascore=_num_int(row.get("ascore")),
        hgoals=_num_int(row.get("hgoals")),
        hbehinds=_num_int(row.get("hbehinds")),
        agoals=_num_int(row.get("agoals")),
        abehinds=_num_int(row.get("abehinds")),
        winner_team_id=winner,
        timestr=_text(row.get("timestr")),
        updated=_text(row.get("updated")),
    )


def _arr(value: object, key: str) -> list[dict]:
    _check_error(value)
    if not isinstance(value, dict):
        raise ValueError(f"Squiggle response had no '{key}' list")
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ValueError(f"Squiggle response had no '{key}' list")
    return [dict(row) for row in raw if isinstance(row, dict)]


def _check_error(value: object) -> None:
    if isinstance(value, dict) and value.get("error") is not None:
        raise ValueError(f"Squiggle: {value['error']}")


def _num_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        try:
            return int(trimmed)
        except ValueError:
            try:
                return int(float(trimmed))
            except ValueError:
                return None
    return None


def _num_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""
