from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from openpyxl import load_workbook

from smartiq_matcher import normalize


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "catalog" / "kasko_tsb_202608.json"
TARGET_NAMES = {
    "alfa romeo", "audi", "bmw", "byd", "chery", "citroen", "cupra",
    "dacia", "ds", "fiat", "tofas fiat", "otoyol iveco fiat", "ford",
    "honda", "hyundai", "kgmobility", "kia", "lexus", "mercedes", "mg",
    "mini", "nissan", "opel", "peugeot", "renault", "renault oyak",
    "seat", "skoda", "tesla", "togg", "toyota", "volkswagen", "volvo",
    "volvo tr",
}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Kullanım: python extract_kasko_tsb_catalog.py <202608R2.xlsx>")
    source = Path(sys.argv[1]).resolve()
    workbook = load_workbook(source, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    headers = [cell.value for cell in sheet[2]]
    year_indexes = {year: headers.index(year) for year in (2025, 2026)}
    records = []
    seen = set()
    for row in sheet.iter_rows(min_row=3, values_only=True):
        brand_code, type_code, brand, type_name = row[:4]
        if brand_code is None or type_code is None or normalize(brand) not in TARGET_NAMES:
            continue
        tsb_code = int(f"{int(brand_code)}{int(type_code)}")
        for model_year, year_index in year_indexes.items():
            value = row[year_index]
            if not isinstance(value, (int, float)) or value <= 0:
                continue
            key = (tsb_code, model_year)
            if key in seen:
                raise RuntimeError(f"Mükerrer TSB + model yılı: {key}")
            seen.add(key)
            records.append({
                "TSB_Kodu": tsb_code, "Model_Yili": model_year,
                "Marka_Kodu": int(brand_code), "Tip_Kodu": int(type_code),
                "Marka": str(brand), "Tip_Adi": str(type_name),
                "Kasko_Degeri_TL": int(value),
            })
    workbook.close()
    payload = {
        "source_file": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "period": "2026-08",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "unique_key": ["TSB_Kodu", "Model_Yili"],
        "record_count": len(records),
        "records": sorted(records, key=lambda row: (row["TSB_Kodu"], row["Model_Yili"])),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{OUTPUT}: {len(records)} benzersiz TSB + model yılı")


if __name__ == "__main__":
    main()
