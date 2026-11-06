import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from vehicle_prices.periods import price_for


def main() -> None:
    root = Path(__file__).resolve().parent
    source = root / "data" / "raw" / f"{date.today():%Y-%m-%d}_tum_markalar.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    cutoff = date.today() - timedelta(days=7)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.get("marka_adi", "BILINMIYOR")].append(row)

    audit_rows = []
    for brand, items in sorted(grouped.items()):
        priced = [item for item in items if price_for(item, "liste") is not None]
        campaign = [item for item in items if price_for(item, "kampanya") is not None]
        fresh = []
        for item in items:
            raw_date = str(item.get("guncelleme_tarihi") or "")[:10]
            try:
                updated = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if updated >= cutoff:
                fresh.append(item)
        audit_rows.append({
            "Marka": brand,
            "Toplam_Kayit": len(items),
            "Liste_Fiyatli": len(priced),
            "Kampanya_Fiyatli": len(campaign),
            "Fiyati_Eksik": len(items) - len(priced),
            "Son_7_Gun_Guncel": len(fresh),
            "Guncellik_Orani": round(len(fresh) / len(items), 4),
            "Oncelik": "YUKSEK" if len(priced) < len(items) or len(fresh) < len(items) else "NORMAL",
        })

    output = root / "data" / "raw" / f"{date.today():%Y-%m-%d}_kalite_denetime.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)
    print(json.dumps(audit_rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
