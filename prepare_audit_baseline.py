from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from export_current_excel import is_dated_export
from collect_official_direct import MINIMUM_BRAND_ROWS, MINIMUM_MODEL_COUNTS
from main import EXPECTED_BRANDS


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "data" / "reports" / "onceki_basarili_excel.json"
REQUIRED = [
    "Tarih", "Marka", "Model", "Versiyon", "Model Yılı", "Liste Fiyatı",
    "Kampanyalı Fiyat", "TSB Kodu", "Eşleşme Durumu",
]


def brand_coverage_errors(rows: list) -> list[str]:
    """Reject a partial brand even when the workbook has 30 nonempty brands."""
    counts = Counter(row[1] for row in rows)
    errors = []
    if set(counts) != EXPECTED_BRANDS:
        errors.append(f"Marka kapsamı farklı: {sorted(set(counts) ^ EXPECTED_BRANDS)}")
    for brand, minimum in MINIMUM_BRAND_ROWS.items():
        if counts[brand] < minimum:
            errors.append(f"Marka kapsamı eksik: {brand} {counts[brand]}/{minimum}")
    for brand, minimum in MINIMUM_MODEL_COUNTS.items():
        models = {str(row[2]).casefold() for row in rows if row[1] == brand}
        if len(models) < minimum:
            errors.append(f"Model ailesi eksik: {brand} {len(models)}/{minimum}")
    return errors


def select_latest_eligible_export(paths: list[Path], run_date: date | None = None,
                                  minimum_total: int = 750) -> Path | None:
    for path in sorted((p for p in paths if p.stem[-10:] < (run_date or date.today()).isoformat()),
                       key=lambda p: p.name.casefold(), reverse=True):
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                sheet = workbook["Guncel_Fiyatlar"]
                headers = [cell.value for cell in sheet[1]]
                if headers != REQUIRED:
                    continue
                rows = list(sheet.iter_rows(min_row=2, max_col=9, values_only=True))
                if len(rows) >= minimum_total and not brand_coverage_errors(rows):
                    return path
            finally:
                workbook.close()
        except (OSError, KeyError, ValueError):
            continue
    return None


def select_latest_export(paths: list[Path], run_date: date | None = None) -> Path | None:
    # A manual retry on the same day must still compare with the previous day,
    # otherwise the trend report incorrectly reports zero changes.
    run_date = run_date or date.today()
    prior_exports = [path for path in paths if path.stem[-10:] < run_date.isoformat()]
    return max(prior_exports, key=lambda path: path.name.casefold(), default=None)


def select_current_export(paths: list[Path], run_date: date | None = None) -> Path | None:
    """Select today's deliverable, never a prior-day trend baseline."""
    run_date = run_date or date.today()
    expected = f"Sifir_arac_{run_date:%Y-%m-%d}.xlsx"
    return next((path for path in paths if path.name.casefold() == expected.casefold()), None)


def main() -> None:
    exports = sorted(path for path in (ROOT / "data").glob("*.xlsx") if is_dated_export(path))
    payload = {"source": None, "headers": [], "rows": []}
    if exports:
        source = select_latest_eligible_export(exports)
        if source is None:
            raise RuntimeError("Önceki Excel dosyalarının hiçbiri marka kapsamı denetimini geçmedi")
        workbook = load_workbook(source, read_only=True, data_only=True)
        sheet = workbook["Guncel_Fiyatlar"]
        headers = [cell.value for cell in sheet[1]]
        indexes = [headers.index(name) for name in REQUIRED]
        rows = [[row[index].isoformat() if index == indexes[0] and hasattr(row[index], "isoformat") else row[index]
                 for index in indexes]
                for row in sheet.iter_rows(min_row=2, values_only=True)]
        workbook.close()
        payload = {"source": source.name, "headers": REQUIRED, "rows": rows}
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"baseline": payload["source"], "rows": len(payload["rows"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
