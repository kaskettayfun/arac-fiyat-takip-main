from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from main import load_records
from source_quality import secondary_source_details
from tsb_only_matcher import NO_TSB_STATUS, TSBOnlyMatcher

ROOT = Path(__file__).resolve().parent
DATED_EXPORT = re.compile(r"^Sifir_arac_\d{4}-\d{2}-\d{2}\.xlsx$", re.IGNORECASE)
KASKO_TSB_CATALOG = ROOT / "data" / "catalog" / "kasko_tsb_202608.json"


def output_path(day: date | None = None) -> Path:
    return ROOT / "data" / f"Sifir_arac_{day or date.today():%Y-%m-%d}.xlsx"


def is_dated_export(path: Path) -> bool:
    return bool(DATED_EXPORT.fullmatch(path.name))


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def display_version(model: str, version: str) -> str:
    """Versiyonu modelden bağımsız okunabilecek tam kimlik olarak göster."""
    model_text = clean_text(model)
    version_text = clean_text(version)
    if not version_text:
        return model_text
    if model_text.casefold() in version_text.casefold():
        return version_text
    return f"{model_text} - {version_text}"


def campaign_price(list_price: int, campaign: int | None) -> int | None:
    """Yalnız gerçek ve liste fiyatından düşük kampanyayı dışa aktar."""
    if not isinstance(campaign, int) or campaign <= 0 or campaign >= list_price:
        return None
    return campaign


def add_source_status_sheet(workbook: Workbook, rows: list[list], fallbacks: dict,
                            secondary_sources: dict | None = None) -> None:
    secondary_sources = secondary_sources or {}
    source_sheet = workbook.create_sheet("Kaynak_Durumu")
    source_sheet.append(["Marka", "Kaynak Durumu", "Son Doğrulanmış Gün", "Satır", "Teknik Neden"])
    for brand in sorted({row[1] for row in rows}):
        detail = fallbacks.get(brand)
        secondary = secondary_sources.get(brand)
        count = sum(row[1] == brand for row in rows)
        source_sheet.append([
            brand, "B PLANI" if detail else ("İKİNCİL KAYNAK" if secondary else "DOĞRUDAN"),
            (detail or secondary or {}).get("source_date", ""), count,
            detail.get("reason", "") if detail else (secondary.get("url", "") if secondary else ""),
        ])
    source_sheet.freeze_panes = "A2"
    for cell in source_sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="172033")
    for column, width in {"A": 20, "B": 18, "C": 24, "D": 12, "E": 85}.items():
        source_sheet.column_dimensions[column].width = width


def main() -> None:
    records, errors = load_records()
    if errors:
        raise RuntimeError(f"Güncel snapshot kaynak hatası içeriyor: {errors}")
    matcher = TSBOnlyMatcher()
    headers = [
        "Tarih", "Marka", "Model", "Versiyon", "Model Yılı", "Liste Fiyatı",
        "Kampanyalı Fiyat", "TSB Kodu", "Eşleşme Durumu",
    ]
    rows = []
    for record in records:
        match = matcher.match(record)
        rows.append([
            record.Kayit_Tarihi.date(), record.Marka, match.model,
            display_version(match.model, record.Versiyon_Paket),
            match.model_yili, record.Liste_Fiyati_TL,
            campaign_price(record.Liste_Fiyati_TL, record.Kampanyali_Fiyat_TL),
            match.tsb_kodu, match.status,
        ])
    if not rows:
        raise RuntimeError("Güncel Excel için doğrulanmış fiyat kaydı yok")
    if len({row[1] for row in rows}) != 30:
        raise RuntimeError("Güncel snapshot 30 markayı içermiyor")

    workbook = Workbook()
    current = workbook.active
    current.title = "Guncel_Fiyatlar"
    current.append(headers)
    for row in rows: current.append(row)
    snapshot = json.loads((ROOT / "data" / "official" / "direct_latest.json").read_text(encoding="utf-8"))
    fallbacks = snapshot.get("fallbacks", {})
    secondary_sources = {brand: detail for brand, detail in secondary_source_details(snapshot.get("records", [])).items()
                         if brand not in fallbacks}
    add_source_status_sheet(workbook, rows, fallbacks, secondary_sources)
    fill = PatternFill("solid", fgColor="172033")
    for cell in current[1]:
        cell.font = Font(color="FFFFFF", bold=True); cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    current.freeze_panes = "A2"
    widths = [14, 18, 28, 48, 12, 20, 22, 14, 20]
    for index, width in enumerate(widths, 1): current.column_dimensions[get_column_letter(index)].width = width
    for cell in current["A"][1:]: cell.number_format = "yyyy-mm-dd"
    for column in ("F", "G"):
        for cell in current[column][1:]: cell.number_format = '#,##0 "TL"'
    output = output_path()
    # Windows dosya sistemi büyük/küçük harfe duyarsızdır; geniş glob geçmiş
    # dosyasını (Sifir_Arac_Fiyat_Gecmisi.xlsx) yanlışlıkla silebiliyordu.
    for old in output.parent.glob("*.xlsx"):
        if old != output and is_dated_export(old):
            old.unlink()
    workbook.save(output); workbook.close()
    check = load_workbook(output, read_only=True, data_only=True)
    check_sheet = check["Guncel_Fiyatlar"]
    if [c.value for c in check_sheet[1]] != headers or check_sheet.max_row != len(rows) + 1:
        raise RuntimeError("Güncel Excel yeniden okuma doğrulaması başarısız")
    source_check = check["Kaynak_Durumu"]
    if source_check.max_row != 31 or sum(row[1] == "B PLANI" for row in source_check.iter_rows(min_row=2, values_only=True)) != len(fallbacks):
        raise RuntimeError("Excel kaynak durumu sayfası doğrulanamadı")
    if sum(row[1] == "İKİNCİL KAYNAK" for row in source_check.iter_rows(min_row=2, values_only=True)) != len(secondary_sources):
        raise RuntimeError("Excel ikincil kaynak durumu doğrulanamadı")
    samples = [check_sheet.cell(i, 6).value for i in range(2, min(7, check_sheet.max_row + 1))]
    if len(samples) < 5 or any(not isinstance(value, int) or value <= 0 for value in samples):
        raise RuntimeError("Güncel Excel örnek fiyat doğrulaması başarısız")
    checked_matches = 0
    for index in range(2, check_sheet.max_row + 1):
        tsb_kodu = check_sheet.cell(index, 8).value
        status = check_sheet.cell(index, 9).value
        if status == "KESİN":
            if not isinstance(tsb_kodu, int) or tsb_kodu <= 0:
                raise RuntimeError(f"TSB eşleşme doğrulaması başarısız: satır={index}")
            checked_matches += 1
        elif tsb_kodu is not None or status != NO_TSB_STATUS:
            raise RuntimeError(f"TSB güvenli boş bırakma doğrulaması başarısız: satır={index}")
    if checked_matches == 0:
        raise RuntimeError("Güncel Excel içinde doğrulanmış TSB eşleşmesi yok")
    check.close()
    matched = sum(row[8] == "KESİN" for row in rows)
    print(f"{output.name}: {len(rows)} satır, 30 marka, 9 kolon doğrulandı; TSB kesin={matched}, yok={len(rows)-matched}")


if __name__ == "__main__":
    main()
