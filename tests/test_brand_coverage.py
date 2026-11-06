import unittest

from collect_official_direct import (
    MINIMUM_BRAND_ROWS, minimum_coverage_errors, semantic_coverage_errors,
    parse_alfa_romeo_html, record, source_update_notice, volkswagen_commercial_price,
    volkswagen_commercial_button_pattern,
)


class BrandCoverageTest(unittest.TestCase):
    def test_rejects_silent_fiat_collapse(self):
        counts = dict(MINIMUM_BRAND_ROWS)
        counts["Fiat"] = 6
        self.assertIn("Fiat", minimum_coverage_errors(counts))

    def test_fiat_current_scope_still_requires_core_passenger_models(self):
        rows = [record("Fiat", "Egea Sedan", "Easy", 1_500_000)]
        self.assertIn("Grande Panda Elektrikli", semantic_coverage_errors(rows)["Fiat"])

    def test_accepts_all_minimums(self):
        self.assertEqual(minimum_coverage_errors(dict(MINIMUM_BRAND_ROWS)), {})

    def test_accepts_november_byd_nissan_and_fiat_official_lineup_counts(self):
        counts = dict(MINIMUM_BRAND_ROWS)
        counts["BYD"] = 2
        counts["Nissan"] = 20
        counts["Fiat"] = 59
        self.assertEqual(minimum_coverage_errors(counts), {})

    def test_ford_requires_commercial_vehicle_scope(self):
        counts = dict(MINIMUM_BRAND_ROWS)
        counts["Ford"] = 17
        self.assertIn("Ford", minimum_coverage_errors(counts))

    def test_rejects_missing_vw_and_mercedes_commercial_scope(self):
        rows = [
            record("Volkswagen", "Golf", "Life", 2_000_000),
            record("Mercedes-Benz", "A 200", "Standart", 3_000_000),
        ]
        errors = semantic_coverage_errors(rows)
        self.assertIn("Volkswagen", errors)
        self.assertIn("Mercedes-Benz", errors)

    def test_vw_requires_every_official_commercial_model_family(self):
        models = ("Caddy", "Transporter", "Caravelle", "Multivan", "ID.Buzz", "Crafter", "Amarok")
        rows = [record("Volkswagen", model, "Test", 2_000_000) for model in models]
        self.assertIn("Grand California", semantic_coverage_errors(rows)["Volkswagen"])

        rows.append(record("Volkswagen", "Grand California", "Test", 5_000_000))
        self.assertNotIn("Volkswagen", semantic_coverage_errors(rows))

    def test_vw_commercial_price_ignores_footnote_number(self):
        text = "Anahtar Teslim Fiyatı\n11\n5.000.000 TL\nNet Fiyat\n2.763.983 TL"
        self.assertEqual(volkswagen_commercial_price(text), 5_000_000)

    def test_vw_commercial_model_button_matches_visible_label(self):
        self.assertIsNotNone(volkswagen_commercial_button_pattern("Caddy").search("Caddy Caddy"))
        self.assertIsNotNone(volkswagen_commercial_button_pattern("ID.Buzz").search("ID.Buzz ID.Buzz"))
        self.assertIsNone(volkswagen_commercial_button_pattern("Caddy").search("Transporter Transporter"))

    def test_source_update_notice_requires_explicit_official_message(self):
        self.assertEqual(source_update_notice("Fiyat listemiz güncellenmektedir."),
                         "Fiyat listemiz güncellenmektedir")
        self.assertEqual(source_update_notice("Fiyatlarımızı güncelliyoruz. Bu sırada modellerimizi inceleyebilirsiniz."),
                         "Fiyatlarımızı güncelliyoruz")
        self.assertIsNone(source_update_notice("Fiyat tablosunda satır bulunamadı"))

    def test_togg_requires_both_official_price_pages(self):
        rows = [record("Togg", "T10X", "V1", 1_900_000)]
        self.assertIn("Togg", semantic_coverage_errors(rows))

    def test_rejects_page_heading_as_mercedes_model(self):
        rows = [record("Mercedes-Benz", "A-Serisi Fiyat Listesi", "A 200", 3_000_000)]
        self.assertIn("Mercedes-Benz", semantic_coverage_errors(rows))

    def test_alfa_parser_reads_official_hidden_table_rows(self):
        document = """
        <html><body>Fiyatlari 03.08.2026 tarihi itibariyle geçerli
        <table><tr class="mobile-disable"><td>JUNIOR ELETTRICA</td><td>4x2</td>
        <td>Speciale+</td><td>Otomatik</td><td>Elektrik</td><td>2.474.300TL</td></tr></table>
        </body></html>"""
        rows = parse_alfa_romeo_html(document, "https://example.test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].Model, "JUNIOR ELETTRICA")
        self.assertEqual(rows[0].Liste_Fiyati_TL, 2_474_300)
        self.assertEqual(rows[0].Liste_Tarihi.isoformat(), "2026-08-03")


if __name__ == "__main__":
    unittest.main()
