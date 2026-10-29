import re
import unittest

from footy_cheat.theme import accent_css, accent_for, luminance

_COLOR = re.compile(r"@define-color (\w+) (#[0-9A-Fa-f]{6})")


def _colors(css: str) -> dict[str, str]:
    return dict(_COLOR.findall(css))


def _contrast(left: float, right: float) -> float:
    lighter = max(left, right)
    darker = min(left, right)
    return (lighter + 0.05) / (darker + 0.05)


class ThemeTests(unittest.TestCase):
    def test_no_club_leaves_the_system_accent_alone(self):
        self.assertIsNone(accent_for(None))
        self.assertEqual(accent_css(None, False), "")
        self.assertEqual(accent_css(None, True), "")

    def test_a_bright_club_is_darkened_for_text_on_a_light_window(self):
        fill, _on_fill = accent_for(8)
        self.assertEqual(fill, "#FFC20E")
        parsed = _colors(accent_css(8, False))
        text = parsed["accent_color"]
        self.assertEqual(parsed["accent_bg_color"], fill)
        self.assertLess(luminance(text), luminance(fill))
        self.assertGreaterEqual(_contrast(luminance(text), 0.96), 4.5)

    def test_a_dark_club_is_lightened_for_text_on_a_dark_window(self):
        fill, _on_fill = accent_for(19)
        parsed = _colors(accent_css(19, True))
        text = parsed["accent_color"]
        self.assertEqual(parsed["accent_bg_color"], fill)
        self.assertGreater(luminance(text), luminance(fill))
        self.assertGreaterEqual(_contrast(luminance(text), 0.018), 4.5)


if __name__ == "__main__":
    unittest.main()
