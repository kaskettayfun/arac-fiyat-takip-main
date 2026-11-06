from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parent
NORMALIZED = ROOT / "data" / "normalized"
OUT = ROOT / "data" / "sql"

COLUMNS = {
    "Kayit_Tarihi": "collected_at",
    "Marka": "brand",
    "Model": "model",
    "Versiyon_Paket": "version_trim",
    "Yakit_Tipi": "fuel_type",
    "Vites_Tipi": "transmission",
    "Motor_Gucu": "engine_power_hp",
    "Liste_Fiyati_TL": "list_price_try",
    "Kampanyali_Fiyat_TL": "campaign_price_try",
    "Kaynak_URL": "source_url",
}

SCHEMA = """CREATE TABLE IF NOT EXISTS vehicle_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    version_trim TEXT,
    fuel_type TEXT,
    transmission TEXT,
    engine_power_hp INTEGER,
    list_price_try INTEGER NOT NULL CHECK (list_price_try > 0),
    campaign_price_try INTEGER,
    source_url TEXT NOT NULL,
    UNIQUE (collected_at, brand, model, version_trim, list_price_try)
);
CREATE INDEX IF NOT EXISTS idx_vehicle_prices_brand_model
    ON vehicle_prices (brand, model);
CREATE INDEX IF NOT EXISTS idx_vehicle_prices_collected_at
    ON vehicle_prices (collected_at);
"""


def latest_csv() -> Path:
    files = sorted(NORMALIZED.glob("*_tum_markalar.csv"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise FileNotFoundError("Normalize edilmiş CSV bulunamadı")
    return files[-1]


def integer(value: str) -> int | None:
    value = (value or "").strip()
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def main() -> None:
    source = latest_csv()
    OUT.mkdir(parents=True, exist_ok=True)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        raw_rows = list(csv.DictReader(stream))
    rows = [{target: row.get(source_name, "") for source_name, target in COLUMNS.items()} for row in raw_rows]
    for row in rows:
        for field in ("engine_power_hp", "list_price_try", "campaign_price_try"):
            row[field] = integer(row[field])
    rows = [row for row in rows if row["list_price_try"] is not None]

    csv_path = OUT / "vehicle_prices_latest.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(COLUMNS.values()))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "schema.sql").write_text(SCHEMA, encoding="utf-8")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Guncel_Fiyatlar"
    excel_headers = ["Tarih", "Marka", "Model", "Versiyon_Paket", "Yakit_Tipi", "Sanziman", "Motor_Gucu_BG", "Liste_Fiyati_TL", "Kampanyali_Fiyat_TL", "Kaynak_URL"]
    sheet.append(excel_headers)
    for row in rows:
        sheet.append([row[field] for field in COLUMNS.values()])
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="172033")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = [23, 16, 24, 36, 15, 15, 18, 20, 23, 55]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[chr(64 + index)].width = width
    table = Table(displayName="GuncelAracFiyatlari", ref=sheet.dimensions)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(table)
    workbook.save(OUT / "guncel_arac_fiyatlari.xlsx")

    db_path = OUT / "vehicle_prices.db"
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA)
        fields = list(COLUMNS.values())
        placeholders = ", ".join("?" for _ in fields)
        connection.executemany(
            f"INSERT INTO vehicle_prices ({', '.join(fields)}) VALUES ({placeholders})",
            ([row[field] for field in fields] for row in rows),
        )
    print(f"Temiz Excel ve SQL çıktıları hazır: {len(rows)} kayıt, {len({row['brand'] for row in rows})} marka")


if __name__ == "__main__":
    main()
