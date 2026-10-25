from dataclasses import dataclass, field
from enum import Enum


class AppPage(Enum):
    ROUND = "round"
    LADDER = "ladder"
    MODELS = "models"


class SyncMode(Enum):
    FILL = "fill"
    REBUILD = "rebuild"
    SMART = "smart"
    FORCE = "force"


class SeasonPhase(Enum):
    LIVE = "live"
    IN_SEASON = "inSeason"
    PRESEASON = "preseason"
    OFF_SEASON = "offSeason"


@dataclass
class Settings:
    theme: str = "system"
    font_size: str = "md"
    team_theme: int | None = None
    contact_email: str = ""

    def copy(self) -> "Settings":
        return Settings(
            theme=self.theme,
            font_size=self.font_size,
            team_theme=self.team_theme,
            contact_email=self.contact_email,
        )


@dataclass
class DataStatus:
    imported: bool
    games: int
    tips: int
    years_done: int
    years_total: int
    last_sync: int | None
    last_error: str | None


@dataclass
class ImportStatus:
    imported: bool
    running: bool
    games: int
    tips: int
    years_done: int
    years_total: int
    last_sync: int | None
    error: str | None
    phase: str
    done: int
    total: int
    message: str


@dataclass
class TeamInfo:
    id: int
    name: str
    abbrev: str
    logo_bytes: bytes | None = None


@dataclass
class RoundInfo:
    round: int
    name: str
    games: int
    completed: int


@dataclass
class SeasonInfo:
    year: int
    rounds: list[RoundInfo]


@dataclass
class SeasonFocus:
    year: int
    round: int
    out_of_season: bool
    title: str
    subtitle: str


@dataclass
class Bootstrap:
    settings: Settings
    status: DataStatus
    teams: list[TeamInfo]
    seasons: list[SeasonInfo]
    focus: SeasonFocus | None


@dataclass
class CallView:
    pick_team_id: int | None
    confidence: float
    consensus_team_id: int | None
    consensus_votes: int
    models_used: int
    followed_consensus: bool
    summary: str


@dataclass
class GameCard:
    id: int
    year: int
    round: int
    round_name: str
    home_id: int
    away_id: int
    home_name: str
    away_name: str
    home_score: int | None
    away_score: int | None
    complete: int
    winner_id: int | None
    venue: str
    date: str
    timestr: str
    is_final: int
    is_grand_final: int
    call: CallView | None


@dataclass
class RoundView:
    year: int
    round: int
    round_name: str
    games: list[GameCard]


@dataclass
class LadderRow:
    rank: int
    team_id: int
    name: str
    played: int
    wins: int
    losses: int
    draws: int
    points_for: int
    points_against: int
    percentage: float
    points: int
    form: list[str] = field(default_factory=list)
    latest_team_id: int | None = None
    latest_abbrev: str = ""
    next_team_id: int | None = None
    next_abbrev: str = ""


@dataclass
class Ladder:
    year: int
    rows: list[LadderRow]


@dataclass
class ModelRow:
    source_id: int
    name: str
    tips: int
    correct: int
    accuracy: float
    upset_chances: int
    upset_hits: int
    upset_accuracy: float
    dissent_tips: int
    dissent_accuracy: float
    honour: str | None = None
    margin_error: float | None = None
    margin_samples: int = 0
    career_accuracy: float | None = None
    career_from: int | None = None
    clear: float = 0.0


@dataclass
class RaceLine:
    name: str
    role: str
    points: list[float]


@dataclass
class ModelBoard:
    rows: list[ModelRow]
    footy: ModelRow | None
    rounds: list[int]
    round_names: list[str]
    lines: list[RaceLine]


@dataclass
class TipDetail:
    source_id: int
    name: str
    tip_team_id: int
    tip: str
    confidence: float | None
    margin: float | None
    year_rank: int | None


@dataclass
class Progress:
    phase: str
    done: int
    total: int
    message: str


@dataclass
class SyncReport:
    action: str
    message: str
    changed: bool
