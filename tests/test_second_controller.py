import unittest

from audit_current_run import HEADERS
from tsb_only_matcher import NO_TSB_STATUS, canonical_version


class SecondControllerTest(unittest.TestCase):
    def test_schema_contains_only_tsb_identity(self):
        self.assertNotIn("SmartiqId", HEADERS)
        self.assertIn("TSB Kodu", HEADERS)
        self.assertEqual(len(HEADERS), 9)

    def test_displayed_and_raw_versions_share_identity(self):
        self.assertEqual(
            canonical_version("i20", "i20 - 1.0 T-GDI Style"),
            canonical_version("i20", "1.0 T-GDI Style"),
        )

    def test_missing_tsb_status_is_explicit(self):
        self.assertEqual(NO_TSB_STATUS, "TSB_KATALOGUNDA_YOK")


if __name__ == "__main__":
    unittest.main()
