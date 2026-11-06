import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook

from export_current_excel import is_dated_export
from audit_current_run import baseline_anomaly_errors
from source_quality import restored_scope_brands
from prepare_audit_baseline import select_current_export, select_latest_export
import prepare_audit_baseline as baseline


class AuditBaselineTest(unittest.TestCase):
    def test_only_dated_current_exports_are_baselines(self):
        self.assertTrue(is_dated_export(Path("Sifir_arac_2026-08-24.xlsx")))
        self.assertFalse(is_dated_export(Path("Sifir_Arac_Fiyat_Gecmisi.xlsx")))

    def test_controller_catches_large_count_drop_and_price_jump(self):
        previous = [["2026-01-01", "Test", "X", f"V{i}", 2026, 100, None] for i in range(10)]
        current = [["2026-01-08", "Test", "X", f"V{i}", 2026, 200 if i == 0 else 100, None] for i in range(5)]
        errors = baseline_anomaly_errors(previous, current)
        self.assertTrue(any("olağan dışı düştü" in error for error in errors))
        self.assertTrue(any("Fiyat değişimi olağan dışı" in error for error in errors))

    def test_reported_fallback_does_not_block_other_brand_anomalies(self):
        previous = [["2026-01-01", brand, "X", f"V{i}", 2026, 100, None]
                    for brand in ("Volvo", "BMW") for i in range(10)]
        current = [["2026-01-08", brand, "X", f"V{i}", 2026, 100, None]
                   for brand in ("Volvo", "BMW") for i in range(5)]
        errors = baseline_anomaly_errors(previous, current, {"Volvo"})
        self.assertTrue(any("BMW 10->5" in error for error in errors))
        self.assertFalse(any("Volvo" in error for error in errors))

    def test_explicit_scope_restoration_allows_only_that_count_increase(self):
        previous = [["2026-01-01", brand, "X", f"V{i}", 2026, 100, None]
                    for brand in ("Volvo", "BMW") for i in range(8)]
        current = [["2026-01-08", brand, "X", f"V{i}", 2026, 100, None]
                   for brand in ("Volvo", "BMW") for i in range(48)]
        errors = baseline_anomaly_errors(previous, current, restored_scope_brands={"Volvo"})
        self.assertFalse(any("Volvo" in error for error in errors))
        self.assertTrue(any("BMW 8->48" in error for error in errors))

    def test_scope_restoration_requires_dated_volvo_source_and_eight_models(self):
        previous = [["2026-10-22", "Volvo", "EX30", "Old", 2025, 2_000_000, None] for _ in range(8)]
        current = [["2026-10-26", "Volvo", f"Model {i % 8}", f"V{i}", 2027, 3_000_000, None]
                   for i in range(48)]
        source = [{"Marka": "Volvo", "Kaynak_URL": "https://tekerli.com/fiyat-listesi/volvo",
                   "Liste_Tarihi": "2026-10-01"}]
        self.assertEqual(restored_scope_brands(previous, current, source), {"Volvo"})
        self.assertEqual(restored_scope_brands(previous, current[:10], source), set())
        self.assertEqual(restored_scope_brands(previous, current, []), set())

    def test_retired_older_year_does_not_fail_when_current_models_are_complete(self):
        previous = [["2026-01-01", "Fiat", "Ducato", f"V{i}", 2026, 100, None] for i in range(6)]
        previous += [["2026-01-01", "Fiat", "Ducato", f"Old{i}", 2025, 100, None] for i in range(5)]
        current = [["2026-01-08", "Fiat", "Ducato", f"V{i}", 2026, 100, None] for i in range(6)]
        self.assertFalse(any("olağan dışı düştü" in error
                             for error in baseline_anomaly_errors(previous, current)))

    def test_retired_older_year_does_not_hide_current_model_loss(self):
        previous = [["2026-01-01", "Fiat", "Ducato", f"V{i}", 2026, 100, None] for i in range(6)]
        previous += [["2026-01-01", "Fiat", "Scudo", f"V{i}", 2026, 100, None] for i in range(2)]
        previous += [["2026-01-01", "Fiat", "Ducato", f"Old{i}", 2025, 100, None] for i in range(6)]
        current = [["2026-01-08", "Fiat", "Ducato", f"V{i}", 2026, 100, None] for i in range(6)]
        self.assertTrue(any("olağan dışı düştü" in error
                            for error in baseline_anomaly_errors(previous, current)))

    def test_latest_baseline_is_selected_by_filename_date(self):
        paths = [Path("Sifir_arac_2026-08-21.xlsx"), Path("Sifir_arac_2026-08-24.xlsx")]
        self.assertEqual(select_latest_export(paths, date(2026, 8, 25)).name, "Sifir_arac_2026-08-24.xlsx")

    def test_incomplete_latest_export_is_not_used_as_baseline(self):
        with TemporaryDirectory() as directory:
            paths = []
            for day, mercedes_count in (("2026-10-30", 2), ("2026-11-02", 1)):
                path = Path(directory) / f"Sifir_arac_{day}.xlsx"
                workbook = Workbook()
                sheet = workbook.active
                sheet.title = "Guncel_Fiyatlar"
                sheet.append(baseline.REQUIRED)
                for brand, count in (("Mercedes-Benz", mercedes_count), ("BMW", 2)):
                    for index in range(count):
                        sheet.append([day, brand, "Model", f"V{index}", 2026,
                                      1_000_000, None, None, "TSB_KATALOGUNDA_YOK"])
                workbook.save(path)
                workbook.close()
                paths.append(path)
            with patch.object(baseline, "EXPECTED_BRANDS", {"Mercedes-Benz", "BMW"}), \
                 patch.object(baseline, "MINIMUM_BRAND_ROWS", {"Mercedes-Benz": 2, "BMW": 2}), \
                 patch.object(baseline, "MINIMUM_MODEL_COUNTS", {}):
                selected = baseline.select_latest_eligible_export(paths, date(2026, 11, 3), minimum_total=4)
            self.assertEqual(selected, paths[0])

    def test_same_day_export_is_not_the_trend_baseline(self):
        paths = [Path("Sifir_arac_2026-10-16.xlsx"), Path("Sifir_arac_2026-10-19.xlsx")]
        self.assertEqual(select_latest_export(paths, date(2026, 10, 19)).name, "Sifir_arac_2026-10-16.xlsx")

    def test_no_prior_day_export_gives_no_baseline(self):
        self.assertIsNone(select_latest_export([Path("Sifir_arac_2026-10-19.xlsx")], date(2026, 10, 19)))

    def test_current_export_is_today_not_previous_baseline(self):
        paths = [Path("Sifir_arac_2026-10-16.xlsx"), Path("Sifir_arac_2026-10-19.xlsx")]
        self.assertEqual(select_current_export(paths, date(2026, 10, 19)), paths[1])
        self.assertIsNone(select_current_export(paths[:1], date(2026, 10, 19)))


if __name__ == "__main__":
    unittest.main()
