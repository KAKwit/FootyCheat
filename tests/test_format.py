import unittest

from footy_cheat.format import (
    format_afl_day,
    format_confidence,
    format_kickoff,
    format_margin,
    grouped,
    ordinal,
    synced_label,
    team_side_name,
)


class FormatTests(unittest.TestCase):
    def test_a_missing_date_stays_unconfirmed(self):
        self.assertEqual(format_afl_day(""), "Date to be confirmed")
        self.assertEqual(format_kickoff("Friday"), "Upcoming")

    def test_noon_and_midnight_use_a_twelve_hour_clock(self):
        self.assertEqual(format_kickoff("2026-03-01 00:05"), "12:05 am")
        self.assertEqual(format_kickoff("2026-03-01 12:00"), "12:00 pm")

    def test_ordinals_keep_the_teens_in_words(self):
        self.assertEqual(ordinal(1), "1st")
        self.assertEqual(ordinal(2), "2nd")
        self.assertEqual(ordinal(3), "3rd")
        self.assertEqual(ordinal(11), "11th")
        self.assertEqual(ordinal(12), "12th")
        self.assertEqual(ordinal(13), "13th")
        self.assertEqual(ordinal(21), "21st")

    def test_a_one_point_margin_is_singular(self):
        self.assertEqual(format_margin(1), "by 1 point")
        self.assertEqual(format_margin(2.2), "by 2 points")
        self.assertIsNone(format_margin(None))

    def test_confidence_is_a_whole_percent(self):
        self.assertEqual(format_confidence(62.4), "62% confidence")
        self.assertIsNone(format_confidence(None))

    def test_counts_are_grouped_and_an_unsynced_library_says_so(self):
        self.assertEqual(grouped(1234567), "1,234,567")
        self.assertEqual(grouped(12), "12")
        self.assertEqual(synced_label(None), "Not synced yet")

    def test_a_tip_names_the_side_it_picked(self):
        self.assertEqual(team_side_name(None, 1, "Adelaide", 2, "Carlton"), "No pick")
        self.assertEqual(team_side_name(2, 1, "Adelaide", 2, "Carlton"), "Carlton")
        self.assertEqual(team_side_name(9, 1, "Adelaide", 2, "Carlton"), "Unknown")


if __name__ == "__main__":
    unittest.main()
