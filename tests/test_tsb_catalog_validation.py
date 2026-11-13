import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from audit_current_run import catalog_brand
from tsb_only_matcher import NO_TSB_STATUS, TSBOnlyMatcher


ROOT = Path(__file__).resolve().parents[1]


class TSBCatalogValidationTest(unittest.TestCase):
    def test_catalog_brand_aliases_do_not_create_false_conflicts(self):
        self.assertEqual(catalog_brand("RENAULT OYAK"), catalog_brand("Renault"))
        self.assertEqual(catalog_brand("KGMOBILITY"), catalog_brand("KGM"))
        self.assertEqual(catalog_brand("MERCEDES"), catalog_brand("Mercedes-Benz"))
        self.assertEqual(catalog_brand("TOFAS-FIAT"), catalog_brand("Fiat"))
        self.assertEqual(catalog_brand("VOLVO-TR"), catalog_brand("Volvo"))

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

    def test_november_2026_tsb_catalog_matches_volvo_2026_and_keeps_2027_unmatched(self):
        matcher = TSBOnlyMatcher()
        volvo_2026_expected = {
            ("EX40", "EX40 - Ultra, Single Motor Extended Range"): 1541333,
            ("EC40", "EC40 - Ultra, Single Motor Extended Range"): 1541332,
            ("V60", "V60 - B4 FWD Mild hybrid, Plus, Dark"): 1541334,
            ("V60", "V60 - Plus, B4 Mild hybrid, Dark"): 1541334,
            ("XC60", "XC60 - Plus, B5 AWD Mild hybrid, Dark"): 1541294,
            ("XC60", "XC60 - Black Edition Plus, B5 AWD Mild hybrid"): 1541314,
            ("XC60", "XC60 - Plus, T8 AWD Plug-in hybrid, Bright"): 1541272,
            ("XC60", "XC60 - Plus, T8 AWD Plug-in hybrid, Dark"): 1541273,
            ("XC60", "XC60 - T8 AWD Plug-in hybrid, Polestar Engineered"): 1541275,
            ("XC90", "XC90 - Plus, B5 AWD Mild hybrid, Bright"): 1541325,
            ("XC90", "XC90 - Black Edition Plus, B5 AWD Mild hybrid"): 1541346,
            ("XC90", "XC90 - Plus, T8 AWD Plug-in hybrid, Bright"): 1541327,
            ("XC90", "XC90 - Black Edition, T8 AWD Plug-in hybrid, Plus"): 1541345,
        }
        for (model, version), code in volvo_2026_expected.items():
            rec_2026 = SimpleNamespace(
                Marka="Volvo", Model=model, Versiyon_Paket=version,
                Model_Yili=2026, Kaynak_URL="https://www.volvocars.com/tr/l/fiyat-listesi/",
            )
            match_2026 = matcher.match(rec_2026)
            self.assertEqual(match_2026.status, "KESİN")
            self.assertEqual(match_2026.tsb_kodu, code)

            rec_2027 = SimpleNamespace(
                Marka="Volvo", Model=model, Versiyon_Paket=version,
                Model_Yili=2027, Kaynak_URL="https://www.volvocars.com/tr/l/fiyat-listesi/",
            )
            match_2027 = matcher.match(rec_2027)
            self.assertEqual(match_2027.status, NO_TSB_STATUS)
            self.assertIsNone(match_2027.tsb_kodu)

    def test_november_2026_newly_added_and_normalized_models_match(self):
        matcher = TSBOnlyMatcher()
        cases = [
            ("Dacia", "Yeni Jogger", "Yeni Jogger - expression Eco-G 120 - 5 koltuklu", 2026, 4451206),
            ("Dacia", "Yeni Jogger", "Yeni Jogger - expression Eco-G 120 - 7 koltuklu", 2026, 4451207),
            ("Renault", "Duster", "Duster - techno hybrid 4x4 150 hp", 2026, 1232316),
            ("Renault", "Boreal", "Boreal - techno Turbo TCe EDC 145 hp", 2026, 1221271),
            ("Kia", "Sportage", "Sportage 1.6L 150 PS DCT (Otomatik) GT-Line Design", 2026, 8001319),
            ("Kia", "Sportage", "Sportage 1.6L 150 PS DCT (Otomatik) GT-Line", 2026, 8001318),
            ("Volkswagen", "ID.Buzz Pure", "ID.Buzz Pure - ID. Buzz Pure (4+1) Standart Şasi 190 PS (61kWh)", 2026, 1531709),
            ("Audi", "Audi Q7", "Audi Q7 - Q7 SUV TDI quattro 220 kW tiptronic", 2026, 91681),
            ("DS", "N°7", "N°7 Pallas Hybrid 145 Otomatik", 2026, 7481057),
            ("MG", "MG HS", "MG HS Hybrid+ Luxury Plus", 2026, 5881035),
            ("Toyota", "GR Yaris", "GR Yaris - Aero Performance 4x4 280HP M/T", 2026, 1441434),
            ("Hyundai", "IONIQ 9", "IONIQ 9 - 160kW Uzun Menzil 4x2 Progressive (Bluelink) Elektrik Otomatik", 2026, 1771395),
        ]
        for brand, model, version, year, code in cases:
            rec = SimpleNamespace(Marka=brand, Model=model, Versiyon_Paket=version, Model_Yili=year, Kaynak_URL="")
            res = matcher.match(rec)
            self.assertEqual(res.status, "KESİN", f"{brand} | {model} | {version}")
            self.assertEqual(res.tsb_kodu, code, f"{brand} | {model} | {version}")

        # Genuinely absent from TSB catalog must remain TSB_KATALOGUNDA_YOK
        absent_cases = [
            ("Audi", "Q3", "Q3 SUV e-hybrid 200 kW S tronic", 2026),
            ("Audi", "Q3 Sportback", "Q3 Sportback e-hybrid 200 kW S tronic", 2026),
            ("Ford", "Transit Van", "Transit Van - Trend Van (Ambulans, Jumbo Şasi), 410L MT 4X4, Yüksek Tavan, 2.0L EcoBlue Upgrade 165PS, 6 İleri Manuel, Dizel", 2026),
        ]
        for brand, model, version, year in absent_cases:
            rec = SimpleNamespace(Marka=brand, Model=model, Versiyon_Paket=version, Model_Yili=year, Kaynak_URL="")
            res = matcher.match(rec)
            self.assertEqual(res.status, NO_TSB_STATUS, f"{brand} | {model} | {version}")
            self.assertIsNone(res.tsb_kodu)


if __name__ == "__main__":
    unittest.main()
