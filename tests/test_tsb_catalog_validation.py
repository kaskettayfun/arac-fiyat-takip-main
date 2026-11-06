import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from audit_current_run import catalog_brand
from tsb_only_matcher import TSBOnlyMatcher


ROOT = Path(__file__).resolve().parents[1]


class TSBCatalogValidationTest(unittest.TestCase):
    def test_catalog_brand_aliases_do_not_create_false_conflicts(self):
        self.assertEqual(catalog_brand("RENAULT OYAK"), catalog_brand("Renault"))
        self.assertEqual(catalog_brand("KGMOBILITY"), catalog_brand("KGM"))
        self.assertEqual(catalog_brand("MERCEDES"), catalog_brand("Mercedes-Benz"))

    def test_seven_renault_codes_match_supplied_kasko_list(self):
        expected = {
            ("Captur", "Captur - techno mild hybrid EDC 140 hp"): 1232319,
            ("Megane E-Tech ELEKTRİKLİ", "Megane E-Tech ELEKTRİKLİ - Techno EV60 220 hp"): 1232270,
            ("Megane Sedan", "Megane Sedan - Touch 1.3 TCe 140 bg"): 1221265,
            ("Megane Sedan", "Megane Sedan - Icon 1.3 TCe EDC 140 bg"): 1221246,
            ("Megane Sedan", "Megane Sedan - Icon 1.5 Blue dCi EDC 115 bg"): 1221247,
            ("Boreal", "Boreal - evolution Turbo TCe EDC 145 hp"): 1221272,
            ("Boreal", "Boreal - iconic Full hybrid E-Tech 160 hp"): 1221270,
        }
        matcher = TSBOnlyMatcher()
        kasko = json.loads((ROOT / "data/catalog/kasko_tsb_202608.json").read_text(encoding="utf-8"))["records"]
        kasko_keys = {(int(row["TSB_Kodu"]), int(row["Model_Yili"]), catalog_brand(row["Marka"])) for row in kasko}
        for (model, version), code in expected.items():
            record = SimpleNamespace(Marka="Renault", Model=model, Versiyon_Paket=version,
                                     Model_Yili=2026, Kaynak_URL="https://www.renault.com.tr/")
            self.assertEqual(matcher.match(record).tsb_kodu, code)
            self.assertIn((code, 2026, "renault"), kasko_keys)


if __name__ == "__main__":
    unittest.main()
