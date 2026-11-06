from pathlib import Path
from datetime import date, datetime
import sys
import unittest
from unittest.mock import patch
from source_quality import secondary_source_details


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import collect_official_direct as collector


class VolvoRegistrationYearTest(unittest.TestCase):
    def test_dated_secondary_reads_current_price_not_crossed_out_price(self):
        models = ("EC40", "ES90", "EX30", "EX30 Cross Country", "EX40", "V60", "XC60", "XC90")
        rows = []
        for model in models:
            rows.append(f'<tr class="grp"><th colspan="4"><a href="/araba/{model}">Volvo {model}</a></th></tr>')
            for i in range(5):
                rows.append('<tr><td>Ultra, Twin Motor <small>2027 model</small><small>elektrikli · otomatik</small></td>'
                            '<td><s>4.409.184 TL</s> → 4.396.184 TL</td><td>—</td><td>1 Ekim 2026</td></tr>'.replace('Ultra, Twin Motor', f'Ultra {i}, Twin Motor'))
        document = ('<html><body>Son güncelleme: 26 Ekim 2026<table>'
                    + ''.join(rows) + '</table></body></html>')
        with patch.object(collector, "NOW", datetime(2026, 10, 26)):
            parsed = collector.parse_volvo_dated_secondary(document, collector.VOLVO_DATED_SECONDARY_URL)
        self.assertEqual(len(parsed), 40)
        self.assertEqual((parsed[0].Model, parsed[0].Model_Yili, parsed[0].Liste_Fiyati_TL),
                         ("EC40", 2027, 4_396_184))
        self.assertEqual(secondary_source_details(parsed)["Volvo"]["rows"], 40)

    def test_rejects_old_secondary_page(self):
        with patch.object(collector, "NOW", datetime(2026, 10, 26)):
            with self.assertRaisesRegex(RuntimeError, "güncel değil"):
                collector.parse_volvo_dated_secondary(
                    "<html><body>Son güncelleme: 1 Eylül 2026</body></html>", collector.VOLVO_DATED_SECONDARY_URL)

    def test_reads_current_model_page_and_factory_model_year(self):
        document = """<table><thead><tr><th>Model</th><th>Fabrika Model Yılı</th>
        <th>Yakıt Cinsi</th><th>Motor Hacmi</th><th>Güç</th><th>Şanzıman</th>
        <th>ÖTV</th><th>Tavsiye Edilen Liste Fiyatı (TL)</th></tr></thead>
        <tbody><tr><td>EX30 Cross Country Ultra, P8 AWD</td><td>2027</td>
        <td>Elektrik</td><td>-</td><td>315kW/428hp</td><td>-</td><td>%75</td>
        <td>3.950.016 3.950.016 Türk lirası</td></tr></tbody></table>"""
        rows = collector.parse_volvo_web_table(
            document, "https://www.volvocars.com/tr/l/fiyat-listesi/2026/ex30", date(2026, 10, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].Model, rows[0].Versiyon_Paket),
                         ("EX30 Cross Country", "Ultra, P8 AWD"))
        self.assertEqual((rows[0].Model_Yili, rows[0].Liste_Fiyati_TL), (2027, 3_950_016))

    def test_stale_fallback_is_reported_without_blocking_other_brands(self):
        errors = collector.coverage_errors([], {"Volvo": 8}, {"Volvo"})
        self.assertNotIn("Volvo", errors)
        self.assertIn("BMW", errors)

    def test_keeps_same_version_for_different_registration_years(self):
        text = """
MODEL YAKIT CİNSİ MOTOR HACMİ GÜÇ ŞANZIMAN
EX40, Single Motor Extended Range, Ultra Elektrik - 150kW/204hp - 2.103.760 55% 3.260.828 3.912.994 13.000 3.925.994
MODEL YAKIT CİNSİ MOTOR HACMİ GÜÇ ŞANZIMAN
EX40, Single Motor Extended Range, Ultra Elektrik - 150kW/204hp - 2.314.140 55% 3.586.917 4.304.300 13.000 4.317.300
2026 FABRİKA MODEL YILI, 2025 TESCİL YILI
2026 FABRİKA MODEL YILI, 2026 TESCİL YILI
Tarih : 2 Haziran 2026
"""
        with patch.object(collector, "pdf_text", return_value=text), patch.object(collector, "NOW", datetime(2026, 6, 5)):
            rows = collector.collect_volvo()

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {(row.Model_Yili, row.Liste_Fiyati_TL) for row in rows},
            {(2025, 3_925_994), (2026, 4_317_300)},
        )

    def test_rejects_stale_pdf_instead_of_marking_prices_current(self):
        with patch.object(collector, "pdf_text", return_value="Tarih : 2 Haziran 2026"), patch.object(collector, "NOW", datetime(2026, 10, 19)):
            with self.assertRaisesRegex(RuntimeError, "Volvo resmi PDF eski"):
                collector.collect_volvo()
