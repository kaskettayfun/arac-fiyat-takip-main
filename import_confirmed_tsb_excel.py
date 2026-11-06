from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "catalog" / "confirmed_tsb_only_mappings.json"
SMARTIQ = ROOT / "data" / "catalog" / "smartiq_catalog.json"
KASKO = ROOT / "data" / "catalog" / "kasko_tsb_202608.json"


def raw_version(model: str, displayed: str) -> str:
    prefix = f"{model} - "
    return displayed[len(prefix):] if displayed.casefold().startswith(prefix.casefold()) else displayed


def import_excel(source: Path, output: Path = OUTPUT) -> int:
    valid_tsb_years = set()
    for catalog_path in (SMARTIQ, KASKO):
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        valid_tsb_years.update(
            (int(row["TSB_Kodu"]), int(row["Model_Yili"]))
            for row in payload["records"]
            if row.get("TSB_Kodu") and row.get("Model_Yili")
        )
    workbook = load_workbook(source, read_only=True, data_only=True)
    sheet = workbook["Guncel_Fiyatlar"]
    headers = [cell.value for cell in sheet[1]]
    expected = [
        "Tarih", "Marka", "Model", "Versiyon", "Model Yılı", "Liste Fiyatı",
        "Kampanyalı Fiyat", "TSB Kodu", "Eşleşme Durumu",
    ]
    if headers != expected:
        raise RuntimeError(f"TSB Excel şeması farklı: {headers}")
    records = []
    tsb_years = set()
    identities = set()
    for values in sheet.iter_rows(min_row=2, max_col=9, values_only=True):
        _, brand, model, version, year, _, _, tsb, status = values
        if status != "KESİN":
            continue
        try:
            tsb = int(tsb)
        except (TypeError, ValueError):
            tsb = 0
        if tsb <= 0 or not isinstance(year, int):
            raise RuntimeError(f"Geçersiz kesin TSB satırı: {values}")
        if (tsb, year) not in valid_tsb_years:
            continue
        identity = (brand, model, raw_version(model, version), year)
        tsb_year = (tsb, year)
        if identity in identities or tsb_year in tsb_years:
            raise RuntimeError(f"Tekil olmayan TSB eşleşmesi: {identity} / {tsb_year}")
        identities.add(identity)
        tsb_years.add(tsb_year)
        records.append({
            "Marka": brand,
            "Model": model,
            "Versiyon": identity[2],
            "Model_Yili": year,
            "Kaynak_URL": "",
            "TSB_Kodu": tsb,
            "Karar": "KESİN",
        })
    workbook.close()
    payload = {
        "source": source.name,
        "rule": "Kullanıcı tarafından doğrulanmış TSB-only eşleşmeler; marka, model, versiyon ve model yılı tekil",
        "record_count": len(records),
        "records": records,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(f"TSB kesin eşleşme kataloğu: {import_excel(args.source)} kayıt")


if __name__ == "__main__":
    main()
