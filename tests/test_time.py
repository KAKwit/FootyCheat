import unittest

from footy_cheat.format import format_afl_day, format_kickoff
from footy_cheat.engine.time import civil_year


class TimeTests(unittest.TestCase):
    def test_unix_epoch_is_1970(self):
        self.assertEqual(civil_year(0), 1970)

    def test_known_afl_dates_stay_in_the_right_civil_year(self):
        self.assertEqual(civil_year(1790380800), 2026)
        self.assertEqual(civil_year(1767225600), 2026)
        self.assertEqual(civil_year(1767222000), 2025)

    def test_fixture_days_use_the_published_date(self):
        self.assertEqual(format_afl_day("2026-03-01"), "Sunday 1 March")
        self.assertEqual(format_kickoff("2026-03-01 19:10"), "7:10 pm")


if __name__ == "__main__":
    unittest.main()
