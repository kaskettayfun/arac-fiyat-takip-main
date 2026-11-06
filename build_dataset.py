import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from vehicle_prices.periods import price_for


OUTPUT_COLUMNS = [
    "Kayit_Tarihi", "Marka", "Model", "Versiyon_Paket", "Yakit_Tipi",
    "Vites_Tipi", "Motor_Gucu", "Liste_Fiyati_TL", "Kampanyali_Fiyat_TL",
    "Kaynak_Guncelleme_Tarihi", "Kaynak_Turu", "Kaynak_URL", "Fiyat_Durumu",
    "Guncellik_Durumu", "Kaynak_Kayit_ID",
]


def main() -> None:
    root = Path(__file__).resolve().parent
    raw_path = root / "data" / "raw" / f"{date.today():%Y-%m-%d}_tum_markalar.jsonl"
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    cutoff = date.today() - timedelta(days=7)
    normalized = []
    for row in rows:
        raw_updated = str(row.get("guncelleme_tarihi") or "")
        try:
            updated = datetime.fromisoformat(raw_updated).date()
        except ValueError:
            updated = None
        list_price = price_for(row, "liste")
        campaign_price = price_for(row, "kampanya")
        normalized.append({
            "Kayit_Tarihi": row.get("_cekilme_zamani", ""),
            "Marka": row.get("marka_adi", ""),
            "Model": row.get("model_adi", ""),
            "Versiyon_Paket": row.get("donanim_paketi", ""),
            "Yakit_Tipi": row.get("yakit_tipi", ""),
            "Vites_Tipi": row.get("vites_tipi", ""),
            "Motor_Gucu": row.get("motor_gucu", ""),
            "Liste_Fiyati_TL": list_price,
            "Kampanyali_Fiyat_TL": campaign_price,
            "Kaynak_Guncelleme_Tarihi": raw_updated,
            "Kaynak_Turu": row.get("_kaynak_turu", ""),
            "Kaynak_URL": row.get("_kaynak_url", ""),
            "Fiyat_Durumu": "FIYAT_VAR" if list_price is not None else "FIYAT_YAYINLANMAMIS",
            "Guncellik_Durumu": "GUNCEL" if updated and updated >= cutoff else "ESKI_KAYIT",
            "Kaynak_Kayit_ID": row.get("id"),
        })

    normalized.sort(key=lambda item: (item["Marka"], item["Model"], item["Versiyon_Paket"]))
    output_dir = root / "data" / "normalized"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{date.today():%Y-%m-%d}_tum_markalar.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(normalized)

    assert len(normalized) == len(rows)
    assert len({(r["Marka"], r["Model"], r["Versiyon_Paket"], r["Kaynak_Kayit_ID"]) for r in normalized}) == len(normalized)
    assert all(isinstance(r["Liste_Fiyati_TL"], int) and r["Liste_Fiyati_TL"] > 0 for r in normalized if r["Liste_Fiyati_TL"] is not None)
    print(f"{len(normalized)} kayıt yazıldı: {output_path}")


if __name__ == "__main__":
    main()
