"""Classify price records whose source is outside the manufacturers' sites."""

from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlparse

SECONDARY_DOMAINS = {"webtekno.com", "www.webtekno.com", "tekerli.com", "www.tekerli.com"}


def field(record, name: str):
    return record.get(name) if isinstance(record, dict) else getattr(record, name, None)


def secondary_source_details(records) -> dict[str, dict]:
    grouped = defaultdict(lambda: {"rows": 0, "source_date": "", "url": ""})
    for record in records:
        url = str(field(record, "Kaynak_URL") or "")
        if urlparse(url).hostname not in SECONDARY_DOMAINS:
            continue
        brand = str(field(record, "Marka") or "")
        detail = grouped[brand]
        detail["rows"] += 1
        source_date = field(record, "Liste_Tarihi")
        if source_date:
            detail["source_date"] = str(source_date)
        detail["url"] = url
    return dict(grouped)


def restored_scope_brands(previous_rows: list, current_rows: list, records) -> set[str]:
    """Identify a narrowly verified recovery from a tiny old Volvo snapshot."""
    detail = secondary_source_details(records).get("Volvo")
    if not detail or detail["url"] != "https://tekerli.com/fiyat-listesi/volvo":
        return set()
    previous_counts = Counter(row[1] for row in previous_rows)
    current_counts = Counter(row[1] for row in current_rows)
    models = {row[2] for row in current_rows if row[1] == "Volvo"}
    if previous_counts.get("Volvo", 0) <= 12 and current_counts.get("Volvo", 0) >= 40 and len(models) >= 8:
        return {"Volvo"}
    return set()
