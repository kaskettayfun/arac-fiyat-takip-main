from datetime import date
import unittest

from collect_official_direct import byd_model_for, extract_page_effective_date, nissan_model_for, table_price


class TableParsingTest(unittest.TestCase):
    def test_motor_description_is_not_a_price(self):
        self.assertIsNone(table_price("1.3 DIG-T Mild Hybrid 158PS Auto Skypack 4x4"))

    def test_currency_cell_is_a_price(self):
        self.assertEqual(table_price("3.454.500 TL"), 3_454_500)
        self.assertEqual(table_price("2.855.800 TL *"), 2_855_800)
        self.assertEqual(table_price("₺ 4.077.000(*)"), 4_077_000)

    def test_byd_models_are_inferred_from_heading_or_cell(self):
        self.assertEqual(byd_model_for("", "BYD SEAL 390 kW AWD Excellence %75"), "BYD SEAL")
        self.assertEqual(byd_model_for("BYD TANG", "BYD TANG 380 kW AWD Flagship %75"), "BYD TANG")
        self.assertEqual(byd_model_for("", "BYD SEAL U DM-i 160 kW AWD Design"), "BYD SEAL U DM-i")

    def test_extracts_page_effective_date_from_turkish_text(self):
        self.assertEqual(
            extract_page_effective_date("Fiyatlar 5 Kasım 2026 tarihinden itibaren geçerlidir."),
            date(2026, 11, 5),
        )
        self.assertEqual(
            extract_page_effective_date("04.11.2026 tarihi itibarıyla geçerli tavsiye edilen anahtar teslim fiyat listesi"),
            date(2026, 11, 4),
        )

    def test_nissan_models_are_inferred_from_official_variants(self):
        self.assertEqual(nissan_model_for("1.3 DIG-T Mild Hybrid 158PS Auto"), "Qashqai")
        self.assertEqual(nissan_model_for("1.0 DIG-T 115PS DCT"), "Juke")
        self.assertEqual(nissan_model_for("1.5 VC-T Mild Hybrid 163PS Auto"), "X-Trail")
        self.assertEqual(nissan_model_for("EV L2 Tekna"), "Townstar")
        self.assertEqual(nissan_model_for("EV Platinum"), "Townstar")
        self.assertEqual(nissan_model_for("1.3 DIG-T 130PS 6MT L1 Visia"), "Townstar")


if __name__ == "__main__":
    unittest.main()
