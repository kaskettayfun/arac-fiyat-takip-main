import unittest
from pathlib import Path
from openpyxl import Workbook

from export_current_excel import add_source_status_sheet, campaign_price, display_version, is_dated_export, output_path


class CurrentExportNamingTest(unittest.TestCase):
    def test_current_export_name_does_not_equal_history_name(self):
        self.assertRegex(output_path().name, r"^Sifir_arac_\d{4}-\d{2}-\d{2}\.xlsx$")
        self.assertNotEqual(output_path().name.casefold(), "sifir_arac_fiyat_gecmisi.xlsx")
        self.assertTrue(is_dated_export(Path("Sifir_arac_2026-08-21.xlsx")))
        self.assertFalse(is_dated_export(Path("Sifir_Arac_Fiyat_Gecmisi.xlsx")))

    def test_current_export_has_tsb_only_columns(self):
        source = Path(__file__).parents[1] / "export_current_excel.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn('"SmartiqId"', text)
        self.assertIn('"TSB Kodu"', text)
        self.assertIn('"Eşleşme Durumu"', text)

    def test_version_is_self_explanatory(self):
        self.assertEqual(
            display_version("MINI Countryman C", "John Cooper Works"),
            "MINI Countryman C - John Cooper Works",
        )
        self.assertEqual(
            display_version("A3 Sedan", "A3 Sedan TFSI S tronic"),
            "A3 Sedan TFSI S tronic",
        )

    def test_campaign_is_blank_when_missing_or_not_discounted(self):
        self.assertIsNone(campaign_price(2_000_000, None))
        self.assertIsNone(campaign_price(2_000_000, 2_000_000))
        self.assertIsNone(campaign_price(2_000_000, 2_100_000))
        self.assertEqual(campaign_price(2_000_000, 1_900_000), 1_900_000)

    def test_fallback_is_visible_in_excel_source_sheet(self):
        book = Workbook()
        add_source_status_sheet(book, [[None, "Chery"], [None, "Fiat"], [None, "Tesla"]], {
            "Chery": {"source_date": "2026-08-31", "reason": "kaynak boş"},
        }, {"Tesla": {"source_date": "2026-09-01", "url": "https://www.webtekno.com/tesla"}})
        rows = list(book["Kaynak_Durumu"].values)
        self.assertEqual(rows[1], ("Chery", "B PLANI", "2026-08-31", 1, "kaynak boş"))
        self.assertEqual(rows[2], ("Fiat", "DOĞRUDAN", "", 1, ""))
        self.assertEqual(rows[3], ("Tesla", "İKİNCİL KAYNAK", "2026-09-01", 1, "https://www.webtekno.com/tesla"))
        book.close()


if __name__ == "__main__":
    unittest.main()
