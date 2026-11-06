from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from openpyxl import load_workbook

from smartiq_matcher import normalize
from tsb_only_matcher import canonical_version


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "data" / "catalog" / "confirmed_tsb_only_mappings.json"
EXACT_CATALOG_ADDITIONS = [
    ("Volvo", "EX30", "Twin Motor, Ultra Elektrik - 315KW/428hp -", 2026, 1541341),
    ("Volvo", "EX30 Cross Country", "Twin Motor Performance, Ultra Elektrik - 315KW/428hp -", 2026, 1541344),
    ("BMW", "Yeni BMW iX M70 xDrive", "M", 2026, 212037),
    ("BMW", "Yeni BMW iX3 50 xDrive", "M Sport", 2026, 212064),
    ("BMW", "Yeni BMW iX xDrive60", "M Sport", 2026, 212036),
    ("BMW", "BMW X3 20", "M Sport", 2025, 212046),
    ("BMW", "BMW X3 20", "X-Line", 2025, 212045),
    ("Opel", "Frontera Elektrik", "44 kW h Batarya GS", 2026, 1111701),
    ("Opel", "Grandland Elektrik", "239 kW AW D GS", 2026, 1111722),
    ("Volkswagen", "Caddy Cargo", "2.0 TDI 122 PS DSG", 2026, 1531518),
    ("Volkswagen", "Caddy Cargo", "Maxi 2.0 TDI 122 PS DSG", 2026, 1531520),
    ("Volkswagen", "Transporter Panel Van", "2.0 TDI (2+1) Uzun Şasi 150 PS", 2026, 1531647),
    ("Volkswagen", "Transporter Panel Van", "2.0 TDI (2+1) Uzun Şasi 170 PS Otomatik", 2026, 1531648),
    ("Volkswagen", "Multivan Style", "1.5 TSI eHybrid (6+1) Uzun Şasi 245 PS DSG 4Motion", 2026, 1531656),
    ("Volkswagen", "ID.Buzz GTX", "ID. Buzz GTX (5+1) Uzun Şasi 340 PS (91kWh) 4Motion", 2026, 1531649),
    ("Volkswagen", "ID.Buzz Pro", "ID. Buzz Pro (4+1) Standart Şasi 286 PS (84kWh)", 2026, 1531636),
    ("Volkswagen", "ID.Buzz Pure", "ID. Buzz Pure (4+1) Standart Şasi 170 PS (63kWh)", 2026, 1531658),
    ("Volkswagen", "ID.Buzz Cargo", "ID. Buzz Cargo (2+1) Standart Şasi 286 PS (84kWh)", 2026, 1531637),
    ("Volkswagen", "Crafter Panel Van", "2.0 TDI (2+1) MWB HR 140 PS 3,5 T Comfortline", 2026, 1531421),
    ("Volkswagen", "Crafter Panel Van", "2.0 TDI (2+1) LWB HR 140 PS 3,5 T Comfortline", 2026, 1531422),
    ("Volkswagen", "Crafter Panel Van", "2.0 TDI (2+1) LWB HR 177 PS 3,5 T Comfortline", 2026, 1531582),
    ("Volkswagen", "Crafter Panel Van", "2.0 TDI (1+1) LWB HR 177 PS 3.88T Comfortline", 2026, 1531681),
    ("Volkswagen", "Amarok Aventura", "Amarok V6 3.0 TDI 240 PS Aventura Oto. 4Motion", 2026, 1531589),
    ("Mercedes-Benz", "Sprinter Panelvan", "Panelvan PRO Ekstra Uzun 4.1T 190 BG 4x4 Kamyonet", 2026, 903008),
]


def numeric_code(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text.split(".")[0]) if re.fullmatch(r"\d+(?:\.0)?", text) else None


def identity(row: dict) -> tuple:
    return (
        normalize(row["Marka"]), normalize(row["Model"]),
        canonical_version(row["Model"], row["Versiyon"]), int(row["Model_Yili"]),
    )


def import_workbook(source: Path) -> dict:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    merged = {identity(row): row for row in payload.get("records", []) if row.get("Karar") == "KESİN"}
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        sheet = workbook["Guncel_Fiyatlar"]
        imported = skipped = 0
        for values in sheet.iter_rows(min_row=2, values_only=True):
            if not values[1] or not values[2] or not values[3]:
                raise RuntimeError(f"Eksik araç kimliği: {values}")
            code = numeric_code(values[7])
            year = numeric_code(values[4])
            if not year:
                raise RuntimeError(f"Eksik model yılı: {values}")
            row = {
                "Marka": str(values[1]).strip(), "Model": str(values[2]).strip(),
                "Versiyon": " ".join(str(values[3]).split()), "Model_Yili": year,
                "Kaynak_URL": "", "TSB_Kodu": code, "Karar": "KESİN",
                "Dogrulama_Kaynagi": source.name,
            }
            if not code:
                # Müdürün referansındaki '-' eski bir eşleşmeyi de geçersiz kılar.
                merged.pop(identity(row), None)
                skipped += 1
                continue
            merged[identity(row)] = row
            imported += 1
    finally:
        workbook.close()
    for brand, model, version, year, code in EXACT_CATALOG_ADDITIONS:
        row = {
            "Marka": brand, "Model": model, "Versiyon": version,
            "Model_Yili": year, "Kaynak_URL": "", "TSB_Kodu": code,
            "Karar": "KESİN", "Dogrulama_Kaynagi": "202608R2.xlsx tam tip adı + model yılı",
        }
        merged.setdefault(identity(row), row)
    records = sorted(merged.values(), key=lambda row: (
        normalize(row["Marka"]), normalize(row["Model"]),
        canonical_version(row["Model"], row["Versiyon"]), row["Model_Yili"], row["TSB_Kodu"],
    ))
    output = {
        "source": source.name,
        "rule": "Yönetici referansındaki sayısal kodlar aynı araç kimliğinde önceki eşleşmenin önüne geçer; dosyada olmayan eski eşleşmeler korunur; dış katalog teyidi ayrıca raporlanır",
        "record_count": len(records), "records": records,
    }
    TARGET.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"imported_numeric_rows": imported, "skipped_dash_or_blank": skipped, "mapping_records": len(records)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_workbook(args.workbook), ensure_ascii=False))


if __name__ == "__main__":
    main()
