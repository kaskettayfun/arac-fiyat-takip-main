import unittest
from unittest.mock import patch

from collect_official_direct import collect_dacia, collect_renault, renault_catalog_price


class RenaultDaciaDecimalPricesTest(unittest.TestCase):
    def test_fractional_lira_values_are_rounded_and_out_of_range_values_rejected(self):
        self.assertEqual(renault_catalog_price("2049999.99"), 2_050_000)
        self.assertEqual(renault_catalog_price("2386000.01"), 2_386_000)
        self.assertIsNone(renault_catalog_price("444646.67"))

    @patch("collect_official_direct.fetch_json")
    def test_dacia_keeps_fractional_price_rows(self, fetch_json):
        fetch_json.return_value = {"results": [{
            "ModelAdi": "Yeni Sandero Stepway",
            "VersiyonAdi": "stepway expression Eco-G 120 auto",
            "ModelYili": "2026",
            "AntesFiyati": "1786000.01",
        }]}
        rows = collect_dacia()
        self.assertEqual([(row.Versiyon_Paket, row.Liste_Fiyati_TL) for row in rows],
                         [("stepway expression Eco-G 120 auto", 1_786_000)])

    @patch("collect_official_direct.fetch_json")
    def test_renault_keeps_fractional_price_rows(self, fetch_json):
        fetch_json.return_value = {"results": [{
            "ModelAdi": "Boreal",
            "VersiyonAdi": "evolution Turbo TCe EDC 145 hp",
            "ModelYili": "2026",
            "AntesFiyati": "2379000.01",
        }]}
        rows = collect_renault()
        self.assertEqual([(row.Versiyon_Paket, row.Liste_Fiyati_TL) for row in rows],
                         [("evolution Turbo TCe EDC 145 hp", 2_379_000)])


if __name__ == "__main__":
    unittest.main()
