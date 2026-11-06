import unittest
from types import SimpleNamespace

from smartiq_matcher import SmartIQMatcher, compatible, model_key, normalize, same_model_family


class SmartIQMatcherTest(unittest.TestCase):
    def test_normalization_handles_turkish_and_noise(self):
        self.assertEqual(normalize("ŠKODA Türkiye"), "skoda turkiye")
        self.assertEqual(model_key("Yeni C3 Aircross SUV"), "c3 aircross")

    def test_match_never_returns_id_for_ambiguous_candidates(self):
        matcher = SmartIQMatcher.__new__(SmartIQMatcher)
        matcher.records = []
        matcher.by_brand = {"test": [
            {"SmartiqId": 1, "TSB_Kodu": 10, "Marka": "Test", "Model": "X", "Versiyon": "Plus", "Model_Yili": 2026},
            {"SmartiqId": 2, "TSB_Kodu": 20, "Marka": "Test", "Model": "X", "Versiyon": "Plus", "Model_Yili": 2026},
        ]}
        record = SimpleNamespace(Marka="Test", Model="X", Versiyon_Paket="Plus", Model_Yili=2026,
                                 Yakit_Tipi="", Sanziman="", Motor_Hacmi_CC=None, Motor_Gucu_BG="")
        result = matcher.match(record)
        self.assertEqual(result.status, "KONTROL_GEREKLI")
        self.assertIsNone(result.smartiq_id)

    def test_incompatible_powertrains_are_rejected(self):
        record = SimpleNamespace(Versiyon_Paket="Hybrid 1.2 e-DCT6", Yakit_Tipi="Hibrit",
                                 Sanziman="Otomatik", Motor_Hacmi_CC=1199, Motor_Gucu_BG="110 PS")
        petrol_manual = {"Versiyon": "1.2 MT6", "Yakit_Tipi": "Benzin", "Sanziman": "Manuel"}
        self.assertFalse(compatible(record, petrol_manual))

    def test_awd_variant_does_not_select_rwd_catalog_row(self):
        matcher = SmartIQMatcher.__new__(SmartIQMatcher)
        matcher.records = []
        matcher.by_brand = {"test": [
            {"SmartiqId": 1, "TSB_Kodu": 10, "Marka": "Test", "Model": "Y", "Versiyon": "Long Range 218HP", "Model_Yili": 2026},
            {"SmartiqId": 2, "TSB_Kodu": 20, "Marka": "Test", "Model": "Y", "Versiyon": "Long Range 514HP 4x4", "Model_Yili": 2026},
        ]}
        record = SimpleNamespace(Marka="Test", Model="Y", Versiyon_Paket="Long Range D�rt �eker",
                                 Model_Yili=2026, Yakit_Tipi="Elektrik", Sanziman="Otomatik",
                                 Motor_Hacmi_CC=0, Motor_Gucu_BG="")
        self.assertEqual(matcher.match(record).smartiq_id, 2)

    def test_c4_does_not_match_c4_x(self):
        self.assertFalse(same_model_family("C4", "C4 X", "Citroen"))

    def test_spacing_and_noise_do_not_break_same_family(self):
        self.assertTrue(same_model_family("Yeni e-C3 Aircross SUV", "eC3 AirCross", "Citroen"))


if __name__ == "__main__":
    unittest.main()
