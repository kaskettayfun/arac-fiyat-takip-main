from datetime import date
import unittest

from vehicle_prices.periods import choose_period, price_for


class PeriodSelectionTest(unittest.TestCase):
    def test_uses_current_or_latest_past_period(self) -> None:
        row = {"liste_2026_08": 100, "liste_2026_09": 110}
        self.assertEqual(choose_period(row, date(2026, 8, 20)), (2026, 8))
        self.assertEqual(price_for(row, "liste", date(2026, 8, 20)), 100)
        self.assertEqual(price_for(row, "liste", date(2026, 10, 1)), 110)

    def test_does_not_treat_zero_as_price(self) -> None:
        self.assertIsNone(price_for({"liste_2026_08": 0}, "liste", date(2026, 8, 1)))


if __name__ == "__main__":
    unittest.main()
