"""First AFL season this app will request or keep."""

FIRST_SEASON_YEAR = 2017


class StateError(Exception):
    """A season before the cutoff was offered to the library."""


def importable_year(year: int) -> bool:
    return year >= FIRST_SEASON_YEAR


def span_end(now_year: int) -> int:
    return now_year + 1


def years_total(now_year: int) -> int:
    return span_end(now_year) - FIRST_SEASON_YEAR + 1


def season_span(now_year: int) -> list[int]:
    end = span_end(now_year)
    return list(range(FIRST_SEASON_YEAR, end + 1))


def refuse_old(year: int) -> None:
    if not importable_year(year):
        raise StateError(
            f"Refusing to import {year}. Seasons before {FIRST_SEASON_YEAR} are not imported."
        )
