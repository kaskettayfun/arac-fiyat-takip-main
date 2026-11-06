import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook

import collect_official_direct as collector
from vehicle_prices.schema import PriceRecord


class SourceFallbackTest(unittest.TestCase):
    def test_loads_only_latest_verified_brand_snapshot(self):
        root = Path(__file__).parent / "fixtures" / ".fallback_test"
        root.mkdir(parents=True, exist_ok=True)
        history = root / "history.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Tum_Fiyatlar"
        sheet.append(PriceRecord.columns())
        for captured, price in ((datetime(2026, 8, 21), 1_000_000), (datetime(2026, 8, 28), 1_100_000)):
            sheet.append([captured, captured.date(), "Dacia", "Duster", "Journey", 2026,
                          "Benzin", "Otomatik", None, "", price, None, "TL",
                          "https://www.dacia.com.tr/dacia-fiyat-listesi.html", "OK", "test"])
        workbook.save(history)
        workbook.close()
        try:
            with patch.object(collector, "HISTORY", history), \
                 patch.object(collector, "coverage_errors", return_value={}):
                rows, source_date = collector.previous_verified_brand("Dacia")
            self.assertEqual(source_date, "2026-08-28")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].Liste_Fiyati_TL, 1_100_000)
            self.assertEqual(rows[0].Kayit_Tarihi.date().isoformat(), "2026-08-28")
            self.assertIn("B planı", rows[0].Aciklama)
        finally:
            history.unlink(missing_ok=True)
            root.rmdir()

    def test_combines_same_day_binek_and_commercial_snapshots(self):
        root = Path(__file__).parent / "fixtures" / ".fallback_same_day_test"
        root.mkdir(parents=True, exist_ok=True)
        history = root / "history.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Tum_Fiyatlar"
        sheet.append(PriceRecord.columns())
        for captured, model in (
            (datetime(2026, 8, 30, 9, 0), "Golf"),
            (datetime(2026, 8, 30, 9, 8), "Caddy Cargo"),
        ):
            sheet.append([captured, captured.date(), "Volkswagen", model, "Test", 2026,
                          "Dizel", "Otomatik", None, "", 2_000_000, None, "TL",
                          "https://www.volkswagen.com.tr/", "OK", "test"])
        workbook.save(history)
        workbook.close()
        try:
            with patch.object(collector, "HISTORY", history), \
                 patch.object(collector, "coverage_errors", return_value={}):
                rows, source_date = collector.previous_verified_brand("Volkswagen")
            self.assertEqual(source_date, "2026-08-30")
            self.assertEqual({row.Model for row in rows}, {"Golf", "Caddy Cargo"})
        finally:
            history.unlink(missing_ok=True)
            root.rmdir()

    def test_skips_latest_partial_mercedes_snapshot(self):
        with TemporaryDirectory() as directory:
            history = Path(directory) / "history.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Tum_Fiyatlar"
            sheet.append(PriceRecord.columns())
            for index in range(80):
                captured = datetime(2026, 10, 30)
                sheet.append([captured, captured.date(), "Mercedes-Benz",
                              "Vito" if index % 2 else "Sprinter", f"V{index}", 2026,
                              "Dizel", "Otomatik", None, "", 2_000_000 + index,
                              None, "TL", "https://fiyat.mercedes-benz.com.tr/model", "OK", "test"])
            captured = datetime(2026, 11, 2)
            sheet.append([captured, captured.date(), "Mercedes-Benz", "CLA", "V0", 2026,
                          "Benzin", "Otomatik", None, "", 3_000_000, None, "TL",
                          "https://fiyat.mercedes-benz.com.tr/model", "OK", "test"])
            workbook.save(history)
            workbook.close()
            with patch.object(collector, "HISTORY", history):
                rows, source_date = collector.previous_verified_brand("Mercedes-Benz")
            self.assertEqual(source_date, "2026-10-30")
            self.assertEqual(len(rows), 80)

    def test_prefers_complete_export_over_delta_history(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            headers = ["Tarih", "Marka", "Model", "Versiyon", "Model Yılı",
                       "Liste Fiyatı", "Kampanyalı Fiyat", "TSB Kodu", "Eşleşme Durumu"]
            for day, mercedes_models in (
                ("2026-10-30", ["Vito", "Sprinter"]),
                ("2026-11-02", ["CLA"]),
            ):
                workbook = Workbook()
                sheet = workbook.active
                sheet.title = "Guncel_Fiyatlar"
                sheet.append(headers)
                for model in mercedes_models:
                    sheet.append([day, "Mercedes-Benz", model, f"{model} - Base", 2026,
                                  2_000_000, None, None, "TSB_KATALOGUNDA_YOK"])
                for index in range(4 - len(mercedes_models)):
                    sheet.append([day, "BMW", "X3", f"X3 - V{index}", 2026,
                                  3_000_000 + index, None, None, "TSB_KATALOGUNDA_YOK"])
                workbook.save(folder / f"Sifir_arac_{day}.xlsx")
                workbook.close()
            with patch.object(collector, "HISTORY", folder / "missing_history.xlsx"), \
                 patch.object(collector, "NOW", datetime(2026, 11, 3)), \
                 patch.object(collector, "MINIMUM_FALLBACK_EXPORT_ROWS", 4), \
                 patch.object(collector, "MINIMUM_BRAND_ROWS", {"Mercedes-Benz": 2, "BMW": 2}), \
                 patch.object(collector, "MINIMUM_MODEL_COUNTS", {}):
                rows, source_date = collector.previous_verified_brand("Mercedes-Benz")
            self.assertEqual(source_date, "2026-10-30")
            self.assertEqual({row.Model for row in rows}, {"Vito", "Sprinter"})

    def test_secondary_source_date_survives_export_fallback(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Guncel_Fiyatlar"
            sheet.append(["Tarih", "Marka", "Model", "Versiyon", "Model Yılı",
                          "Liste Fiyatı", "Kampanyalı Fiyat", "TSB Kodu", "Eşleşme Durumu"])
            for brand in ("Tesla", "BMW"):
                sheet.append(["2026-10-30", brand, "Model Y" if brand == "Tesla" else "X3",
                              "Base", 2026, 2_000_000, None, None, "TSB_KATALOGUNDA_YOK"])
            source = workbook.create_sheet("Kaynak_Durumu")
            source.append(["Marka", "Kaynak Durumu", "Son Doğrulanmış Gün", "Satır", "Teknik Neden"])
            source.append(["Tesla", "İKİNCİL KAYNAK", "2026-10-01", 1,
                           "https://example.com/tesla-october"])
            workbook.save(folder / "Sifir_arac_2026-10-30.xlsx")
            workbook.close()
            with patch.object(collector, "HISTORY", folder / "missing_history.xlsx"), \
                 patch.object(collector, "NOW", datetime(2026, 11, 3)), \
                 patch.object(collector, "MINIMUM_FALLBACK_EXPORT_ROWS", 2), \
                 patch.object(collector, "MINIMUM_BRAND_ROWS", {"Tesla": 1, "BMW": 1}), \
                 patch.object(collector, "MINIMUM_MODEL_COUNTS", {}):
                rows, source_date = collector.previous_verified_brand("Tesla")
            self.assertEqual(source_date, "2026-10-01")
            self.assertEqual(rows[0].Liste_Tarihi.isoformat(), "2026-10-01")
            self.assertEqual(rows[0].Kaynak_URL, "https://example.com/tesla-october")


if __name__ == "__main__":
    unittest.main()
