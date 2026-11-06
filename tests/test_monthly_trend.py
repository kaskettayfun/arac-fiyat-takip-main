import unittest
from monthly_trend import month_key


class MonthlyTrendTests(unittest.TestCase):
    def test_month_key(self):
        self.assertEqual(month_key("2026-08-28T00:00:00"), "2026-08")


if __name__ == "__main__": unittest.main()
