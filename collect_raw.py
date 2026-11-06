import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vehicle_prices.scrapers.otobul_raw import OtoBulRawScraper


def main() -> None:
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    root = Path(__file__).resolve().parent
    raw_dir = root / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    rows = OtoBulRawScraper().fetch()
    if not rows:
        raise RuntimeError("Toplu katalogdan hedef markalara ait kayıt alınamadı")
    counts = Counter(OtoBulRawScraper._brand_name(row) for row in rows)
    missing = sorted(OtoBulRawScraper.TARGET_BRANDS - set(counts))
    if missing:
        raise RuntimeError(f"Eksik marka nedeniyle snapshot yazılmadı: {missing}")
    if len(rows) < 300:
        raise RuntimeError(f"Beklenmeyen kayıt azalması nedeniyle snapshot yazılmadı: {len(rows)}")

    output = raw_dir / f"{now:%Y-%m-%d}_tum_markalar.jsonl"
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    report = {
        "cekilme_zamani": now.isoformat(),
        "kaynak": OtoBulRawScraper.SOURCE_URL,
        "kaynak_turu": "IKINCIL_KATALOG",
        "toplam_kayit": len(rows),
        "marka_sayisi": len(counts),
        "marka_kayitlari": dict(sorted(counts.items())),
        "eksik_markalar": missing,
    }
    report_path = raw_dir / f"{now:%Y-%m-%d}_kapsam_raporu.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
