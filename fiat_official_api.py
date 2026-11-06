from __future__ import annotations

import json
import re
import base64
import os
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

BUNDLE_URL = "https://talep.fiat.com.tr/main.55e191173649a601.js"
LANDING_URL = "https://talep.fiat.com.tr/fiyat-listesi/Binek-Ara%C3%A7-Fiyat-Listesi"
API_ROOT = "https://prlapi.now.tofas.com.tr/api/PriceList"
API_URL = f"{API_ROOT}/categories"
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://talep.fiat.com.tr", "Referer": "https://talep.fiat.com.tr/"}


def discover_bundle_url() -> str:
    try:
        html = urlopen(Request(LANDING_URL, headers=HEADERS), timeout=30).read().decode("utf-8", errors="replace")
        match = re.search(r'src=["\']([^"\']*main\.[a-f0-9]+\.js)["\']', html, re.I)
        if match:
            src = match.group(1)
            return src if src.startswith("http") else f"https://talep.fiat.com.tr/{src.lstrip('/')}"
    except Exception:
        pass
    return BUNDLE_URL


def all_prices(value) -> set[int]:
    prices: set[int] = set()
    if isinstance(value, dict):
        descriptor = " ".join(str(value.get(k, "")) for k in ("fieldKey", "displayName"))
        if "fiyat" in descriptor.lower() or "price" in descriptor.lower():
            raw = value.get("value")
            digits = re.sub(r"\D", "", str(raw))
            if digits and 500_000 <= int(digits) <= 100_000_000:
                prices.add(int(digits))
        for key, child in value.items():
            if "price" in key.lower() or "fiyat" in key.lower():
                digits = re.sub(r"\D", "", str(child))
                if digits and 500_000 <= int(digits) <= 100_000_000:
                    prices.add(int(digits))
            prices.update(all_prices(child))
    elif isinstance(value, list):
        for child in value:
            prices.update(all_prices(child))
    return prices


def main() -> None:
    root = Path(__file__).resolve().parent
    token = os.environ.get("FIAT_API_AUTH", "").strip()
    if not token:
        bundle = urlopen(Request(discover_bundle_url(), headers=HEADERS), timeout=45).read().decode("utf-8", errors="replace")
        auth = re.search(r'auth:\{username:"([^"]+)",password:"([^"]+)"\}', bundle)
    else:
        auth = None
    if not token and not auth:
        raise RuntimeError("Fiat resmi web paketinde API yetkilendirmesi bulunamadı")
    if auth:
        token = base64.b64encode(f"{auth.group(1)}:{auth.group(2)}".encode()).decode()
    api_headers = dict(HEADERS)
    api_headers["Authorization"] = "Basic " + token
    category_payload = json.loads(urlopen(Request(API_URL, headers=api_headers), timeout=45).read())
    categories = category_payload.get("value", [])
    passenger_categories = [c for c in categories if "binek" in str(c.get("name", "")).casefold()]
    selected_categories = passenger_categories or categories
    selected_category_ids = {str(c.get("id")) for c in selected_categories if c.get("id")}
    models_by_id = {}
    for category in selected_categories:
        category_url = f"{API_ROOT}/categories/{category['id']}/models"
        payload = json.loads(urlopen(Request(category_url, headers=api_headers), timeout=45).read())
        category_models = [
            item for item in payload.get("value", [])
            if item.get("id") and str(item.get("vehicleCategoryId")) in selected_category_ids
        ]
        models_by_id.update({item["id"]: item for item in category_models})
    models = list(models_by_id.values())
    if not models:
        raise RuntimeError("Fiat resmi API model listesi boş")
    details = []
    detail_errors = []
    for model in models:
        model_id = model.get("id")
        if not model_id:
            continue
        detail_url = f"{API_ROOT}/models/{model_id}/details"
        try:
            details.append(json.loads(urlopen(Request(detail_url, headers=api_headers), timeout=45).read()))
        except HTTPError as exc:
            detail_errors.append({"model": model.get("name"), "id": model_id, "status": exc.code})
    payload = {"categories": category_payload, "models": {"value": models}, "details": details, "detail_errors": detail_errors}
    snapshot = root / "data" / "official" / "fiat_api_latest.json"
    snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    prices = sorted(all_prices(payload))
    if len(prices) < 3:
        raise RuntimeError(f"Fiat resmi API fiyat kümesi yetersiz: {len(prices)}")

    health_path = root / "data" / "official" / "source_health.json"
    health = json.loads(health_path.read_text(encoding="utf-8"))
    fiat = next(item for item in health if item["brand"] == "Fiat")
    fiat.update({
        "reachable": True,
        "status": 200,
        "final_url": API_URL,
        "content_type": "application/json",
        "price_token_count": len(prices),
        "official_price_values": prices,
        "api_snapshot": str(snapshot.relative_to(root)),
        "fallback": "official_api",
        "checked_at": datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
    })
    fiat.pop("error", None)
    health_path.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fiat resmi API: {len(prices)} benzersiz fiyat")


if __name__ == "__main__":
    main()
