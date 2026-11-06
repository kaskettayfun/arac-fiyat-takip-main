import unittest

from collect_official_direct import parse_chery_html


class CheryRoleTableTest(unittest.TestCase):
    def test_prices_and_campaign_from_accessible_table(self):
        html = """
        <div class="et_pb_row">
          <img title="chery-tiggo8-fiyat-listesi">
          <div role="table">
            <div role="row" aria-hidden="true"><div role="columnheader">Model Yılı</div></div>
            <div role="row"><div role="cell">2026</div>
              <div role="cell">Prestige 1.6 TGDI 145hp 7DCT</div>
              <div role="cell">₺ 2.930.000</div><div role="cell">₺ 2.730.000</div></div>
          </div>
        </div>
        <p>Fiyatlar 08.10.2026 – 31.10.2026 tarihleri arasında geçerlidir.</p>
        """
        rows = parse_chery_html(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].Model, rows[0].Liste_Fiyati_TL, rows[0].Kampanyali_Fiyat_TL),
                         ("TIGGO8", 2930000, 2730000))
        self.assertEqual(rows[0].Liste_Tarihi.isoformat(), "2026-10-08")

    def test_prices_from_standard_html_table_template(self):
        html = """
        <div>
          <h3>TIGGO 7 PRO MAX</h3>
          <table>
            <tr><th>Model Yılı</th><th>Versiyon</th><th>Liste Fiyatı</th><th>Kampanyalı Fiyat</th></tr>
            <tr><td>2026</td><td>Intelligent 1.6 TGDI 145hp 7DCT</td><td>₺ 2.450.000</td><td>₺ 2.300.000</td></tr>
          </table>
        </div>
        <p>Fiyatlar 05.11.2026 – 30.11.2026 tarihleri arasında geçerlidir.</p>
        """
        rows = parse_chery_html(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].Model, rows[0].Liste_Fiyati_TL, rows[0].Kampanyali_Fiyat_TL),
                         ("TIGGO7PROMAX", 2450000, 2300000))
        self.assertEqual(rows[0].Liste_Tarihi.isoformat(), "2026-11-05")


if __name__ == "__main__":
    unittest.main()
