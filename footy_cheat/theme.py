"""Club colours used for the accent, carried over from the desktop app."""

CLUBS: dict[int, tuple[str, str, str]] = {
    1: ("Adelaide", "#002B5C", "#E5A900"),
    2: ("Brisbane Lions", "#5C0028", "#B81D58"),
    3: ("Carlton", "#0D1C4B", "#1C3B5E"),
    4: ("Collingwood", "#161616", "#707070"),
    5: ("Essendon", "#1A1A1A", "#E21B23"),
    6: ("Fremantle", "#2A0845", "#603B9B"),
    7: ("Geelong", "#0B2340", "#27558C"),
    8: ("Gold Coast", "#8E1020", "#FFC20E"),
    9: ("Greater Western Sydney", "#2C2C2C", "#EB561C"),
    10: ("Hawthorn", "#4D2004", "#A85A00"),
    11: ("Melbourne", "#0A1628", "#0045A3"),
    12: ("North Melbourne", "#0033A0", "#0063EC"),
    13: ("Port Adelaide", "#04252B", "#009CBF"),
    14: ("Richmond", "#1A1A1A", "#E5AC00"),
    15: ("St Kilda", "#1A1A1A", "#D22630"),
    16: ("Sydney", "#3A0710", "#FF3333"),
    17: ("West Coast", "#002B5C", "#004FBA"),
    18: ("Western Bulldogs", "#01426A", "#0256D7"),
    19: ("Tasmania", "#013322", "#016943"),
}


def _channel(value: float) -> float:
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    hex_color = color.removeprefix("#")
    red = _channel(int(hex_color[0:2], 16) / 255)
    green = _channel(int(hex_color[2:4], 16) / 255)
    blue = _channel(int(hex_color[4:6], 16) / 255)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def accent_for(team_id: int | None) -> tuple[str, str] | None:
    """Club fill colour and a foreground for that fill.

    Returns None when no club is chosen so Adwaita can keep the system accent.
    """
    if team_id is None or team_id not in CLUBS:
        return None
    fill = CLUBS[team_id][2]
    on_fill = "#1A1406" if luminance(fill) > 0.42 else "#FFFFFF"
    return fill, on_fill


def readable_on_window(color: str, dark: bool) -> str:
    """Move a colour toward black or white until it can be read on the window."""
    paper = 0.018 if dark else 0.96
    toward = "#FFFFFF" if dark else "#000000"
    for step in range(0, 9):
        candidate = color if step == 0 else _blend(color, toward, step / 8)
        if _contrast(luminance(candidate), paper) >= 4.5:
            return candidate
    return _blend(color, toward, 1)


def accent_css(team_id: int | None, dark: bool) -> str:
    colors = accent_for(team_id)
    if colors is None:
        return ""
    fill, on_fill = colors
    text = readable_on_window(fill, dark)
    return f"""
    @define-color accent_color {text};
    @define-color accent_bg_color {fill};
    @define-color accent_fg_color {on_fill};
    """


def _rgb(color: str) -> tuple[int, int, int]:
    text = color.removeprefix("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _blend(color: str, toward: str, amount: float) -> str:
    red, green, blue = _rgb(color)
    target_red, target_green, target_blue = _rgb(toward)

    def mix(origin: int, target: int) -> int:
        return round(origin + (target - origin) * amount)

    return f"#{mix(red, target_red):02X}{mix(green, target_green):02X}{mix(blue, target_blue):02X}"


def _contrast(left: float, right: float) -> float:
    lighter = max(left, right)
    darker = min(left, right)
    return (lighter + 0.05) / (darker + 0.05)
