import unittest

from collect_official_direct import toyota_model_name


class ToyotaModelNamesTest(unittest.TestCase):
    def test_same_vehicle_has_one_name_across_xml_and_web_table(self):
        self.assertEqual(toyota_model_name("Hilux"), toyota_model_name("Yeni Hilux"))
        self.assertEqual(toyota_model_name("YARIS CROSS"), toyota_model_name("Yeni Yaris Cross Hybrid"))
        self.assertEqual(toyota_model_name("YARIS"), toyota_model_name("Yaris Hybrid"))


if __name__ == "__main__":
    unittest.main()
