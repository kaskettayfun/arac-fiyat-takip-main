from datetime import date, datetime
from pathlib import Path
import unittest

from vehicle_prices.excel_store import ExcelStore
from vehicle_prices.schema import PriceRecord


class ExcelStoreTest(unittest.TestCase):
    def test_second_append_is_idempotent(self) -> None:
        record = PriceRecord(
            Kayit_Tarihi=datetime(2026, 8, 16, 9, 0),
            Liste_Tarihi=date(2026, 8, 16),
            Marka="Test", Model="Model", Versiyon_Paket="Paket", Model_Yili=2026,
            Yakit_Tipi="Benzin", Sanziman="Otomatik", Motor_Hacmi_CC=None,
            Motor_Gucu_BG="100", Liste_Fiyati_TL=1_000_000,
            Kampanyali_Fiyat_TL=None, Para_Birimi="TL",
            Kaynak_URL="https://example.com", Veri_Durumu="OK", Aciklama="test",
        )
        workbook = Path(__file__).with_name("fixtures") / ".test_prices.xlsx"
        archive = workbook.parent / "arsiv" / f"{datetime.now():%Y-%m-%d}_sifir_arac_fiyatlari.xlsx"
        workbook.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        try:
            store = ExcelStore(workbook)
            self.assertEqual(store.append([record]).added_count, 1)
            self.assertEqual(store.append([record]).added_count, 0)
        finally:
            workbook.unlink(missing_ok=True)
            archive.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
