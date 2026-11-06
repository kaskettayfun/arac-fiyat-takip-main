from datetime import datetime
from unittest.mock import patch
import unittest

import collect_official_direct as collector
from collect_official_direct import _webtekno_month, parse_tesla_dated_secondary, tesla_tax_inclusive_price


class TeslaFallbackTest(unittest.TestCase):
    def test_extracts_month_from_monthly_article(self):
        self.assertEqual(
            _webtekno_month("Ağustos 2026 Tesla Fiyat Listesi h221797"),
            (2026, 8),
        )

    def test_rejects_article_without_month(self):
        self.assertIsNone(_webtekno_month("Tesla fiyatları değişti 2026"))

    def test_uses_tax_inclusive_tesla_footer_not_ex_tax_card(self):
        self.assertEqual(
            tesla_tax_inclusive_price("₺4.620.000 Tahmini fiyatlara ÖTV ve KDV dahildir"),
            4_620_000,
        )
        self.assertIsNone(tesla_tax_inclusive_price("Model Y ₺2.195.000* ÖTV ve KDV hariçtir"))

    def test_parses_tesla_dated_secondary_with_canonical_variant_names(self):
        html = """
        <html><body>Son güncelleme: 5 Kasım 2026<table>
          <tr class="grp"><th colspan="4"><a href="/araba/tesla/model-y">Tesla Model Y</a></th></tr>
          <tr><td>Arkadan Çekiş <small>2026 model</small></td><td>2.474.985 TL</td><td>—</td><td>20 Ağustos 2026</td></tr>
          <tr><td>Long Range Arkadan Çekiş <small>2026 model</small></td><td>3.906.000 TL</td><td>—</td><td>29 Ekim 2026</td></tr>
          <tr><td>Long Range Dört Çeker <small>2026 model</small></td><td>4.620.000 TL</td><td>—</td><td>20 Ağustos 2026</td></tr>
          <tr><td>Performance Dört Çeker <small>2026 model</small></td><td>4.966.500 TL</td><td>—</td><td>20 Ağustos 2026</td></tr>
        </table></body></html>
        """
        with patch.object(collector, "NOW", datetime(2026, 11, 5)):
            rows = parse_tesla_dated_secondary(html, collector.TESLA_DATED_SECONDARY_URL)
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [(r.Versiyon_Paket, r.Liste_Fiyati_TL) for r in rows],
            [
                ("Arkadan Çekiş", 2_474_985),
                ("Premium Long Range Arkadan Çekiş", 3_906_000),
                ("Premium Long Range Dört Çeker", 4_620_000),
                ("Performance Dört Çeker", 4_966_500),
            ],
        )


if __name__ == "__main__":
    unittest.main()
