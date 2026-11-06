from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path
import re
import unicodedata

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data" / "Sifir_Arac_Fiyat_Gecmisi.xlsx"
OUT = ROOT / "v2_output" / "reports"


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold().replace("ı", "i")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def identity(row: dict) -> tuple:
    model = str(row["Model"] or "").strip()
    version = str(row["Versiyon"] or "").strip()
    prefix = normalized(model)
    norm_version = normalized(version)
    if prefix and norm_version.startswith(prefix + " "):
        norm_version = norm_version[len(prefix) + 1:]
    return normalized(row["Marka"]), normalized(model), norm_version, row["Model Yılı"]


def month_key(value) -> str:
    return str(value)[:7]


def snapshot(rows: list[tuple], day: str) -> dict:
    result = {}
    for row in rows:
        if str(row[0])[:10] != day:
            continue
        item = {"Marka": row[2], "Model": row[3], "Versiyon": row[4], "Model Yılı": row[5]}
        result[identity(item)] = {"brand": row[2], "model": row[3], "version": row[4], "year": row[5],
                                  "list_price": row[10], "campaign_price": row[11]}
    return result


def build(today: date | None = None) -> dict:
    today = today or date.today()
    book = load_workbook(HISTORY, read_only=True, data_only=True)
    rows = list(book["Tum_Fiyatlar"].iter_rows(min_row=2, values_only=True)); book.close()
    months = sorted({month_key(row[0]) for row in rows if row[0]})
    current_month = f"{today:%Y-%m}"
    previous_months = [month for month in months if month < current_month]
    current_days = sorted({str(row[0])[:10] for row in rows if row[0] and month_key(row[0]) == current_month})
    if not previous_months or not current_days:
        return {"status": "VERI_BEKLENIYOR", "period": current_month, "message": "Önceki ay kapanışı veya ayın 3'ü snapshot'ı henüz oluşmadı."}
    previous_month = previous_months[-1]
    previous_day = max(str(row[0])[:10] for row in rows if row[0] and month_key(row[0]) == previous_month)
    current_day = current_days[0]
    old, new = snapshot(rows, previous_day), snapshot(rows, current_day)
    changes = []
    campaign_entered = campaign_exited = 0
    for key in old.keys() & new.keys():
        before, after = old[key], new[key]
        if before["list_price"] and after["list_price"] and before["list_price"] != after["list_price"]:
            delta = after["list_price"] - before["list_price"]
            changes.append({**after, "old_price": before["list_price"], "new_price": after["list_price"],
                            "change_try": delta, "change_pct": round(delta * 100 / before["list_price"], 2)})
        campaign_entered += int(not before["campaign_price"] and bool(after["campaign_price"]))
        campaign_exited += int(bool(before["campaign_price"]) and not after["campaign_price"])
    return {
        "status": "OK", "period": current_month, "previous_snapshot": previous_day, "current_snapshot": current_day,
        "old_rows": len(old), "new_rows": len(new), "price_changes": changes,
        "largest_increases": sorted((x for x in changes if x["change_try"] > 0), key=lambda x: x["change_pct"], reverse=True)[:10],
        "largest_decreases": sorted((x for x in changes if x["change_try"] < 0), key=lambda x: x["change_pct"])[:10],
        "new_versions": len(new.keys() - old.keys()), "removed_versions": len(old.keys() - new.keys()),
        "campaign_entered": campaign_entered, "campaign_exited": campaign_exited,
        "brands_with_changes": dict(Counter(x["brand"] for x in changes)),
    }


def main() -> None:
    result = build(); OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "monthly_trend.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["AYLIK SIFIR ARAÇ FİYAT TRENDİ", f"Dönem: {result['period']}"]
    if result["status"] != "OK":
        lines.append(result["message"])
    else:
        lines += [f"Karşılaştırma: {result['previous_snapshot']} → {result['current_snapshot']}",
                  f"Fiyatı değişen: {len(result['price_changes'])} | Yeni: {result['new_versions']} | Kalkan: {result['removed_versions']}",
                  f"Kampanyaya giren: {result['campaign_entered']} | Kampanyadan çıkan: {result['campaign_exited']}", "",
                  "En yüksek artışlar:"]
        lines += [f"- {x['brand']} {x['model']}: %{x['change_pct']:+.2f} ({x['change_try']:+,} TL)" for x in result["largest_increases"]]
        lines += ["", "En yüksek düşüşler:"]
        lines += [f"- {x['brand']} {x['model']}: %{x['change_pct']:+.2f} ({x['change_try']:+,} TL)" for x in result["largest_decreases"]]
    (OUT / "monthly_trend.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "period": result["period"], "changes": len(result.get("price_changes", []))}, ensure_ascii=False))


if __name__ == "__main__": main()
