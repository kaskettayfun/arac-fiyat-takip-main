from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "data" / "catalog" / "smartiq_catalog.json"
YEARS = {2025, 2026, 2027}
BRAND_MAP = {
    "Alfa Romeo": "Alfa Romeo", "Audi": "Audi", "BMW": "BMW", "Byd": "BYD",
    "Chery": "Chery", "Citroen": "Citroen", "Cupra": "CUPRA",
    "DS Automobiles": "DS", "Dacia": "Dacia", "Fiat": "Fiat", "Ford": "Ford",
    "Honda": "Honda", "Hyundai": "Hyundai", "Kia": "Kia", "Lexus": "Lexus",
    "MG": "MG", "Mercedes-Benz": "Mercedes-Benz", "Mini": "MINI",
    "Nissan": "Nissan", "Opel": "Opel", "Peugeot": "Peugeot",
    "Renault": "Renault", "Seat": "SEAT", "Skoda": "Skoda",
    "Ssangyong/KGM": "KGM", "Tesla": "Tesla", "Togg": "Togg",
    "Toyota": "Toyota", "Volkswagen": "Volkswagen", "Volvo": "Volvo",
}
OUTPUT_FIELDS = (
    "SmartiqId", "TSB_Kodu", "Marka", "Model", "Versiyon", "Model_Yili",
    "Yakit_Tipi", "Sanziman", "Motor_Hacmi_CC", "Motor_Gucu_BG",
    "Govde_Tipi", "SmartHash",
)


def clean_tsb(value):
    return None if value in (None, "", "NULL", "null", 0, "0") else value


def extract(source: Path) -> dict:
    workbook = load_workbook(source, read_only=True, data_only=True)
    sheet = workbook["Vehicles"]
    headers = [cell.value for cell in sheet[1]]
    indexes = {str(value): index for index, value in enumerate(headers) if value is not None}
    required = {
        "SmartiqId", "TSB", "VehicleBrand", "VehicleModel", "Type", "ModelYear",
        "FuelType", "GearType", "EngineVolumeCc", "HorsePower", "BodyType", "SmartHash",
    }
    missing = sorted(required - indexes.keys())
    if missing:
        raise RuntimeError(f"Katalogda zorunlu alanlar eksik: {missing}")

    records = []
    for row in sheet.iter_rows(min_row=2, max_col=max(indexes.values()) + 1, values_only=True):
        brand = row[indexes["VehicleBrand"]]
        year = row[indexes["ModelYear"]]
        if brand not in BRAND_MAP or year not in YEARS:
            continue
        record = {
            "SmartiqId": row[indexes["SmartiqId"]],
            "TSB_Kodu": clean_tsb(row[indexes["TSB"]]),
            "Marka": BRAND_MAP[brand],
            "Model": row[indexes["VehicleModel"]],
            "Versiyon": row[indexes["Type"]],
            "Model_Yili": year,
            "Yakit_Tipi": row[indexes["FuelType"]],
            "Sanziman": row[indexes["GearType"]],
            "Motor_Hacmi_CC": row[indexes["EngineVolumeCc"]],
            "Motor_Gucu_BG": row[indexes["HorsePower"]],
            "Govde_Tipi": row[indexes["BodyType"]],
            "SmartHash": row[indexes["SmartHash"]],
        }
        records.append(record)
    workbook.close()

    ids = [row["SmartiqId"] for row in records]
    if len(ids) != len(set(ids)) or any(value in (None, "") for value in ids):
        raise RuntimeError("Filtrelenmiş katalogda SmartiqId benzersizliği bozuldu")
    brands = {row["Marka"] for row in records}
    expected = set(BRAND_MAP.values())
    if brands != expected:
        raise RuntimeError(f"Marka kapsamı eksik/fazla: eksik={sorted(expected-brands)}, fazla={sorted(brands-expected)}")

    records.sort(key=lambda row: (row["Marka"], row["Model"], row["Versiyon"], row["Model_Yili"], row["SmartiqId"]))
    return {
        "metadata": {
            "source_file": source.name,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "model_years": sorted(YEARS),
            "record_count": len(records),
            "brand_count": len(brands),
            "tsb_filled_count": sum(row["TSB_Kodu"] is not None for row in records),
            "fields": list(OUTPUT_FIELDS),
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["metadata"], ensure_ascii=False))


if __name__ == "__main__":
    main()
