from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

from openpyxl import load_workbook

from smartiq_matcher import normalize


ROOT = Path(__file__).resolve().parent
CATALOG_DIR = ROOT / "data" / "catalog"
OUTPUT = CATALOG_DIR / "kasko_tsb_202608.json"
TARGET_YEARS = (2025, 2026, 2027)
TARGET_NAMES = {
    "alfa romeo", "audi", "bmw", "byd", "chery", "citroen", "cupra",
    "dacia", "ds", "fiat", "tofas fiat", "otoyol iveco fiat", "ford",
    "honda", "hyundai", "kgmobility", "kia", "lexus", "mercedes", "mg",
    "mini", "nissan", "opel", "peugeot", "renault", "renault oyak",
    "seat", "skoda", "tesla", "togg", "toyota", "volkswagen", "volvo",
    "volvo tr",
}


def find_latest_catalog_excel(catalog_dir: Path = CATALOG_DIR) -> Path | None:
    if not catalog_dir.exists():
        return None
    candidates = [
        path for path in catalog_dir.glob("*.xlsx")
        if not path.name.startswith("~$")
    ]
    if not candidates:
        return None

    def sort_key(path: Path) -> tuple[int, float, str]:
        match = re.search(r"(20\d{2})(0[1-9]|1[0-2])", path.stem)
        period_num = int(match.group(1) + match.group(2)) if match else 0
        return (period_num, path.stat().st_mtime, path.name)

    return max(candidates, key=sort_key)


def infer_period(source: Path) -> str:
    match = re.search(r"(20\d{2})(0[1-9]|1[0-2])", source.stem)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return "2026-08"


def extract_catalog(source: Path, output: Path = OUTPUT, *, force: bool = True) -> bool:
    source = source.resolve()
    source_bytes = source.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    if not force and output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
            if existing.get("source_sha256") == source_sha256:
                print(f"{output}: Kasko TSB kataloğu zaten güncel ({source.name})")
                return False
        except Exception:
            pass

    workbook = load_workbook(source, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    headers = [
        str(cell.value).strip() if cell.value is not None else ""
        for cell in sheet[2]
    ]
    year_indexes: dict[int, int] = {}
    for year in TARGET_YEARS:
        year_str = str(year)
        if year_str in headers:
            year_indexes[year] = headers.index(year_str)

    if not year_indexes:
        workbook.close()
        raise RuntimeError(f"{source.name} içinde hedef model yılı sütunları bulunamadı: {headers}")

    records = []
    seen = set()
    for row in sheet.iter_rows(min_row=3, values_only=True):
        brand_code, type_code, brand, type_name = row[:4]
        if brand_code is None or type_code is None or normalize(brand) not in TARGET_NAMES:
            continue
        tsb_code = int(f"{int(brand_code)}{int(type_code)}")
        for model_year, year_index in year_indexes.items():
            if year_index >= len(row):
                continue
            value = row[year_index]
            if isinstance(value, str):
                cleaned = value.strip().replace(".", "").replace(",", ".")
                try:
                    value = float(cleaned)
                except ValueError:
                    continue
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
        "source_sha256": source_sha256,
        "period": infer_period(source),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "unique_key": ["TSB_Kodu", "Model_Yili"],
        "record_count": len(records),
        "records": sorted(records, key=lambda row: (row["TSB_Kodu"], row["Model_Yili"])),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{output}: {len(records)} benzersiz TSB + model yılı ({source.name})")
    return True


def main() -> None:
    args = sys.argv[1:]
    if not args or args == ["--auto"]:
        source = find_latest_catalog_excel()
        if source is None:
            print(f"{CATALOG_DIR}: TSB Excel dosyası bulunamadı, mevcut katalog korunuyor.")
            return
        extract_catalog(source, force=not bool(args == ["--auto"]))
        return
    if len(args) != 1:
        raise SystemExit("Kullanım: python extract_kasko_tsb_catalog.py [<202611R1.xlsx> | --auto]")
    extract_catalog(Path(args[0]), force=True)


if __name__ == "__main__":
    main()
