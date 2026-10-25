import re
from datetime import datetime, timezone

from .engine.numbers import dart_round, to_fixed

_WEEKDAYS_LONG = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTHS_LONG = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_DAY_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_KICK_PATTERN = re.compile(r"(?:[ T])(\d{2}):(\d{2})")


def _weekday_index(year: int, month: int, day: int) -> int:
    # Dart DateTime.utc.weekday is Monday=1 … Sunday=7, then `% 7` makes Sunday 0.
    return (datetime(year, month, day, tzinfo=timezone.utc).weekday() + 1) % 7


def format_afl_day(value: str) -> str:
    match = _DAY_PATTERN.match(value)
    if match is None:
        return "Date to be confirmed"
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    month_name = _MONTHS_LONG[month - 1] if 1 <= month <= 12 else ""
    return f"{_WEEKDAYS_LONG[_weekday_index(year, month, day)]} {day} {month_name}"


def format_kickoff(value: str) -> str:
    match = _KICK_PATTERN.search(value)
    if match is None:
        return "Upcoming"
    hour = int(match.group(1))
    minute = match.group(2)
    h12 = ((hour + 11) % 12) + 1
    suffix = "pm" if hour >= 12 else "am"
    return f"{h12}:{minute} {suffix}"


def format_percent(value: float, digits: int = 0) -> str:
    if value != value or value in (float("inf"), float("-inf")):
        return "–"
    return f"{to_fixed(value * 100, digits)}%"


def format_clear(value: float) -> str:
    """Games ahead of the median model. Half a game rounds away from zero."""
    if value != value or value in (float("inf"), float("-inf")):
        return "–"
    tenths = dart_round(value * 10) / 10
    if tenths == 0:
        return "0"
    text = to_fixed(abs(tenths), 1)
    if text.endswith(".0"):
        text = text[:-2]
    sign = "+" if tenths > 0 else "−"
    return sign + text


def ordinal(value: int) -> str:
    mod100 = abs(value) % 100
    if 11 <= mod100 <= 13:
        return f"{value}th"
    return {
        1: f"{value}st",
        2: f"{value}nd",
        3: f"{value}rd",
    }.get(abs(value) % 10, f"{value}th")


def format_confidence(value: float | None) -> str | None:
    if value is None or value != value or value in (float("inf"), float("-inf")):
        return None
    return f"{dart_round(value)}% confidence"


def format_margin(value: float | None) -> str | None:
    if value is None or value != value or value in (float("inf"), float("-inf")):
        return None
    points = dart_round(value)
    unit = "point" if points in (1, -1) else "points"
    return f"by {points} {unit}"


def points_percent(value: float) -> str:
    return to_fixed(value, 1)


def team_side_name(
    team_id: int | None,
    home_id: int,
    home: str,
    away_id: int,
    away: str,
) -> str:
    if team_id is None:
        return "No pick"
    if team_id == home_id:
        return home
    if team_id == away_id:
        return away
    return "Unknown"


def grouped(value: int) -> str:
    text = str(value)
    parts: list[str] = []
    for index, char in enumerate(text):
        if index > 0 and (len(text) - index) % 3 == 0:
            parts.append(",")
        parts.append(char)
    return "".join(parts)


def synced_label(unix: int | None) -> str:
    if unix is None:
        return "Not synced yet"
    moment = datetime.fromtimestamp(unix)
    hour = moment.hour
    h12 = ((hour + 11) % 12) + 1
    minute = f"{moment.minute:02d}"
    suffix = "pm" if hour >= 12 else "am"
    month = _MONTHS[moment.month - 1]
    return f"Synced {moment.day} {month}, {h12}:{minute} {suffix}"
