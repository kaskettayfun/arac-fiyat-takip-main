import unittest
from types import SimpleNamespace

from collect_official_direct import semantic_coverage_errors


class AudiCoverageTest(unittest.TestCase):
    def test_missing_priced_q3_family_is_rejected(self):
        partial = [SimpleNamespace(Marka="Audi", Model="A3")]
        self.assertIn("Q3", semantic_coverage_errors(partial)["Audi"])
        complete = partial + [SimpleNamespace(Marka="Audi", Model="Q3"),
                              SimpleNamespace(Marka="Audi", Model="Q3 Sportback")]
        self.assertNotIn("Audi", semantic_coverage_errors(complete))


if __name__ == "__main__":
    unittest.main()
