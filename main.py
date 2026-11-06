from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from vehicle_prices.excel_store import ExcelStore
from vehicle_prices.schema import PriceRecord

ROOT = Path(__file__).resolve().parent
DIRECT = ROOT / "data" / "official" / "direct_latest.json"
EXPECTED_BRANDS = {"Audi", "BMW", "BYD", "Chery", "Citroen", "CUPRA", "Lexus", "Alfa Romeo", "DS", "MG", "SEAT", "Dacia", "Fiat", "Ford", "Honda", "Hyundai", "KGM", "Kia", "Mercedes-Benz", "MINI", "Nissan", "Opel", "Peugeot", "Renault", "Skoda", "Tesla", "Togg", "Toyota", "Volkswagen", "Volvo"}


def load_records() -> tuple[list[PriceRecord], dict[str, str]]:
    payload = json.loads(DIRECT.read_text(encoding="utf-8"))
    records = []
    for item in payload.get("records", []):
        row = dict(item)
        row["Kayit_Tarihi"] = datetime.fromisoformat(row["Kayit_Tarihi"])
        row["Liste_Tarihi"] = date.fromisoformat(row["Liste_Tarihi"]) if row.get("Liste_Tarihi") else None
        records.append(PriceRecord(**row))
    return records, payload.get("errors", {})


def main() -> None:
    records, errors = load_records()
    counts = {brand: sum(row.Marka == brand for row in records) for brand in EXPECTED_BRANDS}
    missing = sorted(brand for brand, count in counts.items() if count == 0)
    if errors or missing:
        details = {"missing": missing, "errors": errors, "counts": counts}
        raise RuntimeError("Eksik resmî kaynak nedeniyle Excel güncellenmedi: " + json.dumps(details, ensure_ascii=False))
    for row in records:
        row.validate()
    result = ExcelStore(ROOT / "data" / "Sifir_Arac_Fiyat_Gecmisi.xlsx").append(records)
    print(json.dumps({"records": len(records), "brands": len(counts), "added": result.added_count, "workbook": str(result.workbook_path), "archive": str(result.archive_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
