import unittest

from vehicle_prices.weekly_changes import compare


class WeeklyChangesTest(unittest.TestCase):
    def test_reports_price_version_campaign_and_tsb_changes(self):
        old = [
            ["2026-10-16", "Renault", "Captur", "Captur - techno mild hybrid EDC 140 hp", 2026, 2_300_000, None, None, "TSB_KATALOGUNDA_YOK"],
            ["2026-10-16", "Kia", "Stonic", "Stonic Cool", 2026, 1_900_000, 1_800_000, 8001304, "KESİN"],
            ["2026-10-16", "Volvo", "XC60", "XC60 Ultra", 2026, 4_000_000, None, 1541300, "KESİN"],
        ]
        new = [
            ["2026-10-19", "Renault", "Captur", "Captur - techno mild hybrid EDC 140 hp", 2026, 2_325_000, 2_200_000, 1232319, "KESİN"],
            ["2026-10-19", "Kia", "EV3", "EV3 Cool", 2026, 2_450_000, None, None, "TSB_KATALOGUNDA_YOK"],
            ["2026-10-19", "Volvo", "XC60", "XC60 Ultra", 2026, 4_900_000, None, 1541300, "KESİN"],
        ]
        result = compare(old, new, {"Volvo"})
        self.assertEqual(len(result["price_changes"]), 1)
        self.assertEqual(result["price_changes"][0][-1], 25_000)
        self.assertEqual(len(result["new_versions"]), 1)
        self.assertEqual(len(result["removed_versions"]), 1)
        self.assertEqual(result["campaigns_entered"], 1)
        self.assertEqual(result["newly_missing_tsb"], ["Kia EV3 Cool (2026)"])
        self.assertEqual(result["total_missing_tsb"], 1)
        self.assertEqual(result["tsb_changes"], [("Renault Captur - techno mild hybrid EDC 140 hp (2026)", None, 1232319)])


if __name__ == "__main__":
    unittest.main()
