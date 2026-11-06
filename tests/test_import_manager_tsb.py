import json
import unittest
from pathlib import Path
from unittest.mock import patch

import import_user_confirmed_tsb as importer


class FakeSheet:
    def iter_rows(self, min_row, values_only):
        assert min_row == 2 and values_only
        yield (None, "Renault", "Kangoo Van", "Kangoo Van - L1 EDC 115", 2026, None, None, 1232286)
        yield (None, "Audi", "Q7", "Q7 - TDI quattro", 2026, None, None, "-")


class FakeWorkbook:
    def __getitem__(self, name):
        assert name == "Guncel_Fiyatlar"
        return FakeSheet()

    def close(self):
        pass


class ImportManagerTSBTest(unittest.TestCase):
    def test_manager_code_overrides_old_code_and_dash_clears_it(self):
        old = [
            {"Marka": "Renault", "Model": "Kangoo Van", "Versiyon": "L1 EDC 115",
             "Model_Yili": 2026, "Kaynak_URL": "", "TSB_Kodu": 1232285, "Karar": "KESİN"},
            {"Marka": "Audi", "Model": "Q7", "Versiyon": "TDI quattro",
             "Model_Yili": 2026, "Kaynak_URL": "", "TSB_Kodu": 999999, "Karar": "KESİN"},
        ]
        saved = []
        with patch.object(importer, "TARGET", Path("mappings.json")), patch.object(importer, "EXACT_CATALOG_ADDITIONS", []), patch.object(importer, "load_workbook", return_value=FakeWorkbook()), patch.object(Path, "read_text", return_value=json.dumps({"records": old})), patch.object(Path, "write_text", side_effect=lambda value, **_: saved.append(value)):
            result = importer.import_workbook(Path("manager.xlsx"))
        records = json.loads(saved[0])["records"]
        self.assertEqual(result["imported_numeric_rows"], 1)
        self.assertEqual(result["skipped_dash_or_blank"], 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["TSB_Kodu"], 1232286)
        self.assertEqual(records[0]["Dogrulama_Kaynagi"], "manager.xlsx")


if __name__ == "__main__":
    unittest.main()
