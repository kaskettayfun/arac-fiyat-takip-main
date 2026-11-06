from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from shutil import copy2

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from vehicle_prices.schema import PriceRecord


@dataclass(frozen=True)
class AppendResult:
    added_count: int
    workbook_path: Path
    archive_path: Path


class ExcelStore:
    DATA_SHEET = "Tum_Fiyatlar"
    SUMMARY_SHEET = "Haftalik_Ozet"

    def __init__(self, workbook_path: Path) -> None:
        self.workbook_path = workbook_path

    def append(self, records: list[PriceRecord]) -> AppendResult:
        for record in records:
            record.validate()

        self.workbook_path.parent.mkdir(parents=True, exist_ok=True)
        workbook = self._load_or_create()
        sheet = workbook[self.DATA_SHEET]
        self._assert_schema(sheet)

        existing = self._existing_keys(sheet)
        new_records = [record for record in records if record.dedupe_key() not in existing]
        for record in new_records:
            sheet.append(record.as_row())

        self._format_data_sheet(sheet)
        self._write_summary(workbook, records, len(new_records))
        temporary_path = self.workbook_path.with_name(f".{self.workbook_path.stem}.tmp.xlsx")
        temporary_path.unlink(missing_ok=True)
        try:
            workbook.save(temporary_path)
            workbook.close()
            self._verify_saved_workbook(temporary_path, len(new_records))
            os.replace(temporary_path, self.workbook_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        archive_dir = self.workbook_path.parent / "arsiv"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{datetime.now():%Y-%m-%d}_sifir_arac_fiyatlari.xlsx"
        copy2(self.workbook_path, archive_path)

        self._verify_saved_workbook(self.workbook_path, len(new_records))
        return AppendResult(len(new_records), self.workbook_path, archive_path)

    def _load_or_create(self):
        if self.workbook_path.exists():
            return load_workbook(self.workbook_path)

        workbook = Workbook()
        data_sheet = workbook.active
        data_sheet.title = self.DATA_SHEET
        data_sheet.append(PriceRecord.columns())
        workbook.create_sheet(self.SUMMARY_SHEET)
        return workbook

    @staticmethod
    def _assert_schema(sheet) -> None:
        actual = [cell.value for cell in sheet[1]]
        if actual != PriceRecord.columns():
            raise ValueError(f"Excel şeması değişmiş: {actual}")

    @staticmethod
    def _existing_keys(sheet) -> set[tuple[object, ...]]:
        keys: set[tuple[object, ...]] = set()
        columns = {cell.value: cell.column for cell in sheet[1]}
        for row in range(2, sheet.max_row + 1):
            list_date = sheet.cell(row, columns["Liste_Tarihi"]).value
            if isinstance(list_date, datetime):
                list_date = list_date.date()
            keys.add(
                (
                    list_date,
                    str(sheet.cell(row, columns["Marka"]).value or "").casefold(),
                    str(sheet.cell(row, columns["Model"]).value or "").casefold(),
                    str(sheet.cell(row, columns["Versiyon_Paket"]).value or "").casefold(),
                    sheet.cell(row, columns["Model_Yili"]).value,
                )
            )
        return keys

    @classmethod
    def _format_data_sheet(cls, sheet) -> None:
        header_fill = PatternFill("solid", fgColor="1F4E78")
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        widths = [19, 15, 12, 28, 24, 12, 22, 13, 17, 18, 19, 22, 13, 48, 16, 48]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        for cell in sheet["A"][1:]:
            cell.number_format = "yyyy-mm-dd hh:mm"
        for cell in sheet["B"][1:]:
            cell.number_format = "yyyy-mm-dd"
        for column in ("K", "L"):
            for cell in sheet[column][1:]:
                cell.number_format = '#,##0 "TL"'

    @classmethod
    def _write_summary(cls, workbook, records: list[PriceRecord], added_count: int) -> None:
        if cls.SUMMARY_SHEET in workbook.sheetnames:
            del workbook[cls.SUMMARY_SHEET]
        sheet = workbook.create_sheet(cls.SUMMARY_SHEET)
        latest = max(record.Kayit_Tarihi for record in records)
        sheet.append(["Haftalık Sıfır Araç Fiyatları Özeti", None])
        sheet.append(["Çalışma zamanı", latest])
        sheet.append(["Okunan satır", len(records)])
        sheet.append(["Yeni eklenen satır", added_count])
        sheet.append(["Aktif markalar", ", ".join(sorted({r.Marka for r in records}))])
        sheet.append(["Durum", "BAŞARILI"])
        sheet["A1"] = "Haftalık Sıfır Araç Fiyatları Özeti"
        sheet["A2"] = "Çalışma zamanı"
        sheet["A3"] = "Okunan satır"
        sheet["A4"] = "Yeni eklenen satır"
        sheet["A5"] = "Aktif markalar"
        sheet["A6"] = "Durum"
        sheet["B6"] = "BAŞARILI"
        sheet["A1"].font = Font(size=16, bold=True, color="FFFFFF")
        sheet["A1"].fill = PatternFill("solid", fgColor="1F4E78")
        sheet["B1"].fill = PatternFill("solid", fgColor="1F4E78")
        sheet["A2"].font = Font(bold=True)
        sheet["A3"].font = Font(bold=True)
        sheet["A4"].font = Font(bold=True)
        sheet["A5"].font = Font(bold=True)
        sheet["A6"].font = Font(bold=True)
        sheet["B2"].number_format = "yyyy-mm-dd hh:mm"
        sheet.column_dimensions["A"].width = 28
        sheet.column_dimensions["B"].width = 55
        sheet.sheet_view.showGridLines = False

    def _verify_saved_workbook(self, path: Path, expected_added: int) -> None:
        workbook = load_workbook(path, data_only=False, read_only=False)
        sheet = workbook[self.DATA_SHEET]
        self._assert_schema(sheet)
        if sheet.max_row < expected_added + 1:
            raise RuntimeError("Excel doğrulamasında beklenen satır sayısı bulunamadı")
        prices = [sheet.cell(row, 11).value for row in range(2, min(sheet.max_row, 6) + 1)]
        if not prices or any(not isinstance(value, int) or value <= 0 for value in prices):
            raise RuntimeError("Excel doğrulamasında fiyat hücreleri sayısal değil")
        workbook.close()
