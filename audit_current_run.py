from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path

from openpyxl import load_workbook

from main import load_records
from smartiq_matcher import DEFAULT_CATALOG
from smartiq_matcher import normalize
from tsb_only_matcher import DEFAULT_MAPPINGS, canonical_identity
from export_current_excel import campaign_price, display_version
from prepare_audit_baseline import brand_coverage_errors, select_current_export
from tsb_only_matcher import NO_TSB_STATUS
from source_quality import restored_scope_brands


ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "data" / "reports" / "ikinci_kontrol.json"
BASELINE = ROOT / "data" / "reports" / "onceki_basarili_excel.json"
KASKO_TSB_CATALOG = ROOT / "data" / "catalog" / "kasko_tsb_202608.json"
SOURCE_PAYLOAD = ROOT / "data" / "official" / "direct_latest.json"
HEADERS = [
    "Tarih", "Marka", "Model", "Versiyon", "Model Yılı", "Liste Fiyatı",
    "Kampanyalı Fiyat", "TSB Kodu", "Eşleşme Durumu",
]


def catalog_brand(value: object) -> str:
    name = normalize(value)
    return {
        "renault oyak": "renault",
        "kgmobility": "kgm",
        "mercedes": "mercedes benz",
        "tofas fiat": "fiat",
        "otoyol iveco fiat": "fiat",
        "volvo tr": "volvo",
    }.get(name, name)


def price_key_from_record(row) -> tuple:
    model, year = canonical_identity(row)
    return (
        row.Kayit_Tarihi.date().isoformat(), row.Marka, model,
        display_version(model, row.Versiyon_Paket), year, row.Liste_Fiyati_TL,
        campaign_price(row.Liste_Fiyati_TL, row.Kampanyali_Fiyat_TL),
    )


def price_key_from_excel(values: tuple) -> tuple:
    day = values[0]
    if isinstance(day, datetime):
        day = day.date()
    return (day.isoformat(), *values[1:7])


def baseline_anomaly_errors(previous_rows: list, current_rows: list,
                            fallback_brands: set[str] | None = None,
                            restored_scope_brands: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    fallback_brands = fallback_brands or set()
    restored_scope_brands = restored_scope_brands or set()
    previous_counts = Counter(row[1] for row in previous_rows)
    current_counts = Counter(row[1] for row in current_rows)
    for brand, previous in previous_counts.items():
        if brand in fallback_brands:
            continue
        current = current_counts.get(brand, 0)
        if (previous and current < max(1, int(previous * 0.70))
                and not older_model_year_retired(brand, previous_rows, current_rows)):
            errors.append(f"Marka satır sayısı olağan dışı düştü: {brand} {previous}->{current}")
        if previous and current > max(previous * 2, previous + 20) and brand not in restored_scope_brands:
            errors.append(f"Marka satır sayısı olağan dışı arttı: {brand} {previous}->{current}")
    previous_prices = {(row[1], row[2], row[3], row[4]): row[5] for row in previous_rows if row[5]}
    current_prices = {(row[1], row[2], row[3], row[4]): row[5] for row in current_rows if row[5]}
    for key in previous_prices.keys() & current_prices.keys():
        if key[0] in fallback_brands:
            continue
        old, new = previous_prices[key], current_prices[key]
        if old > 0 and abs(new - old) / old > 0.45:
            errors.append(f"Fiyat değişimi olağan dışı: {' | '.join(str(x) for x in key)} {old}->{new}")
    return errors


def older_model_year_retired(brand: str, previous_rows: list, current_rows: list) -> bool:
    """Allow a total drop only when every current-year model retains its coverage.

    This catches the normal withdrawal of an old model year's stock without
    weakening the guard against a partially parsed current price list.
    """
    old = [row for row in previous_rows if row[1] == brand]
    new = [row for row in current_rows if row[1] == brand]
    years = [int(row[4]) for row in old + new if str(row[4]).isdigit()]
    if not old or not new or not years:
        return False
    latest = max(years)
    old_latest = Counter(row[2] for row in old if row[4] == latest)
    new_latest = Counter(row[2] for row in new if row[4] == latest)
    old_older = sum(1 for row in old if str(row[4]).isdigit() and int(row[4]) < latest)
    new_older = sum(1 for row in new if str(row[4]).isdigit() and int(row[4]) < latest)
    return (old_older > new_older and bool(old_latest)
            and all(new_latest[model] >= count for model, count in old_latest.items()))


def audit() -> dict:
    errors: list[str] = []
    records, source_errors = load_records()
    if source_errors:
        errors.append(f"Kaynak çıktısı hata içeriyor: {source_errors}")
    exports = list((ROOT / "data").glob("Sifir_arac_????-??-??.xlsx"))
    current_export = select_current_export(exports)
    if current_export is None:
        errors.append("Güncel Excel bulunamadı")
        return {"status": "BASARISIZ", "errors": errors}

    workbook = load_workbook(current_export, read_only=True, data_only=True)
    sheet = workbook["Guncel_Fiyatlar"]
    headers = [cell.value for cell in sheet[1]]
    if headers != HEADERS:
        errors.append(f"Kolon şeması farklı: {headers}")
    excel_rows = list(sheet.iter_rows(min_row=2, max_col=9, values_only=True))
    workbook.close()

    source_keys = Counter(price_key_from_record(row) for row in records)
    excel_keys = Counter(price_key_from_excel(row) for row in excel_rows)
    if source_keys != excel_keys:
        errors.append("Kaynak JSON ile Excel fiyat satırları birebir eşleşmiyor")
    if len(excel_rows) < 750:
        errors.append(f"Toplam satır güvenlik eşiğinin altında: {len(excel_rows)}/750")
    brands = Counter(row[1] for row in excel_rows)
    errors.extend(brand_coverage_errors(excel_rows))
    if any(count <= 0 for count in brands.values()):
        errors.append("Boş marka bulundu")
    if len(excel_keys) != len(excel_rows):
        errors.append("Mükerrer fiyat satırı bulundu")

    baseline_checked = False
    fallback_brands = set(json.loads(SOURCE_PAYLOAD.read_text(encoding="utf-8")).get("fallbacks", {})) if SOURCE_PAYLOAD.exists() else set()
    if BASELINE.exists():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        previous_rows = baseline.get("rows", [])
        if previous_rows:
            baseline_checked = True
            restored_brands = restored_scope_brands(previous_rows, excel_rows, records)
            errors.extend(baseline_anomaly_errors(previous_rows, excel_rows, fallback_brands,
                                                  restored_brands))

    catalog_payload = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
    catalog_tsb_keys = {
        (int(row["TSB_Kodu"]), int(row["Model_Yili"]), catalog_brand(row["Marka"]))
        for row in catalog_payload["records"] if row.get("TSB_Kodu") and row.get("Model_Yili")
    }
    confirmed_payload = json.loads(DEFAULT_MAPPINGS.read_text(encoding="utf-8"))
    confirmed_tsb_keys = {
        (int(row["TSB_Kodu"]), int(row["Model_Yili"]), catalog_brand(row["Marka"]))
        for row in confirmed_payload["records"]
        if row.get("Karar") == "KESİN" and row.get("TSB_Kodu") and row.get("Model_Yili")
    }
    kasko_payload = json.loads(KASKO_TSB_CATALOG.read_text(encoding="utf-8"))
    kasko_unique_keys = [(int(row["TSB_Kodu"]), int(row["Model_Yili"])) for row in kasko_payload["records"]]
    if len(kasko_unique_keys) != len(set(kasko_unique_keys)) or len(kasko_unique_keys) != kasko_payload["record_count"]:
        errors.append("Kasko kataloğunda TSB Kodu + Model Yılı tekil değil")
    kasko_keys = {(int(row["TSB_Kodu"]), int(row["Model_Yili"]), catalog_brand(row["Marka"]))
                  for row in kasko_payload["records"]}
    external_keys = kasko_keys | catalog_tsb_keys
    matched = external_verified = manual_only = 0
    for index, excel_row in enumerate(excel_rows, 2):
        list_price, campaign, tsb_kodu, status = excel_row[5], excel_row[6], excel_row[7], excel_row[8]
        if not isinstance(list_price, int) or list_price <= 0:
            errors.append(f"Geçersiz liste fiyatı: satır {index}")
        if campaign is not None and (not isinstance(campaign, int) or campaign <= 0):
            errors.append(f"Geçersiz kampanyalı fiyat: satır {index}")
        if campaign is not None and campaign >= list_price:
            errors.append(f"Kampanyalı fiyat liste fiyatından düşük değil: satır {index}")
        if status == "KESİN":
            matched += 1
            if not isinstance(tsb_kodu, int) or tsb_kodu <= 0:
                errors.append(f"Geçersiz TSB kodu: satır {index}")
            else:
                tsb_key = (tsb_kodu, excel_row[4], catalog_brand(excel_row[1]))
                if tsb_key in external_keys:
                    external_verified += 1
                elif tsb_key in confirmed_tsb_keys:
                    manual_only += 1
                else:
                    errors.append(f"TSB Kodu + Model Yılı + Marka kataloglarda yok: satır {index}")
        elif status == NO_TSB_STATUS:
            if tsb_kodu is not None:
                errors.append(f"TSB kataloğunda yok satırında kod dolu: satır {index}")
        else:
            errors.append(f"Geçersiz eşleşme durumu: satır {index}")
    if matched / max(len(excel_rows), 1) < 0.20:
        errors.append(f"TSB eşleşme oranı güvenlik eşiğinin altında: {matched}/{len(excel_rows)}")

    return {
        "status": "BASARILI" if not errors else "BASARISIZ",
        "excel": current_export.name,
        "rows": len(excel_rows),
        "brands": len(brands),
        "tsb_matched": matched,
        "tsb_yok": len(excel_rows) - matched,
        "tsb_external_verified": external_verified,
        "tsb_manual_only": manual_only,
        "baseline_checked": baseline_checked,
        "checks": [
            "JSON_EXCEL_BIREBIR", "30_MARKA", "SATIR_ESIGI", "MUKERRER",
            "FIYAT_POZITIF", "MARKA_ADET_ANOMALI", "FIYAT_ANOMALI",
            "TSB_KATALOG", "TSB_MODEL_YILI_TEKIL", "TSB_MARKA_YIL_DOGRULAMA",
        ],
        "errors": errors[:50],
    }


def main() -> None:
    result = audit()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "BASARILI":
        raise RuntimeError("İkinci kontrolör başarısız: " + json.dumps(result["errors"], ensure_ascii=False))


if __name__ == "__main__":
    main()
