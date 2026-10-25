import math


def dart_round(value: float) -> int:
    """Round half away from zero, matching Dart's num.round()."""
    if not math.isfinite(value):
        raise ValueError("not finite")
    if value >= 0:
        return math.floor(value + 0.5)
    return math.ceil(value - 0.5)


def to_fixed(value: float, digits: int) -> str:
    scale = 10**digits
    rounded = dart_round(value * scale) / scale
    return f"{rounded:.{digits}f}"
