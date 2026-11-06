from pathlib import Path
import unittest

from vehicle_prices.scrapers.bmw import BMWPriceScraper


class BMWParserTest(unittest.TestCase):
    def test_parser_reads_standard_price_table(self) -> None:
        fixture = Path(__file__).with_name("fixtures") / "bmw_sample.html"
        records = BMWPriceScraper().parse(fixture.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].Model, "BMW 120")
        self.assertEqual(records[0].Versiyon_Paket, "Sport Line")
        self.assertEqual(records[0].Motor_Hacmi_CC, 1499)
        self.assertEqual(records[0].Liste_Fiyati_TL, 3_724_500)
        self.assertEqual(records[1].Versiyon_Paket, "M Sport")
        self.assertEqual(records[1].Liste_Fiyati_TL, 4_283_100)


if __name__ == "__main__":
    unittest.main()
