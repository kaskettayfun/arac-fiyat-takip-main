import csv
import io
import json
import re
import ssl
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin

from pypdf import PdfReader

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def response_text(data: bytes, content_type: str, charset: str | None, url: str) -> str:
    if content_type == "application/pdf" or url.lower().split("?", 1)[0].endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return data.decode(charset or "utf-8", errors="replace")


def model_price_links(body: str, base_url: str) -> list[str]:
    links = re.findall(r'href=["\']([^"\']+/fiyat(?:/\d{4})?)["\']', body, flags=re.IGNORECASE)
    return sorted({urljoin(base_url, link) for link in links if link != base_url})


def money_values(body: str) -> set[int]:
    values: set[int] = set()
    patterns = [
        r"(?:₺|TRY\s*)?\d{1,3}(?:\.\d{3}){2,}(?:\s*(?:TL|TRY))?",
        r"(?:₺|TRY\s*)?\d{1,3}(?:,\d{3}){2,}(?:\s*(?:TL|TRY))?",
        r"(?:₺|TRY\s*)?\d{7,9}(?:\s*(?:TL|TRY))",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, body, flags=re.IGNORECASE):
            digits = re.sub(r"\D", "", match)
            if digits:
                values.add(int(digits))
    return values


def main() -> None:
    root = Path(__file__).resolve().parent
    source_health = json.loads((root / "data" / "official" / "source_health.json").read_text(encoding="utf-8"))
    candidates = sorted((root / "data" / "normalized").glob("*_tum_markalar.csv"))
    if not candidates:
        raise FileNotFoundError("Normalize edilmiş toplu veri seti bulunamadı")
    normalized_path = candidates[-1]
    with normalized_path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    health = {item["brand"]: item for item in source_health}
    official_values: dict[str, set[int]] = {}
    context = ssl.create_default_context()
    for brand, item in health.items():
        if not item.get("reachable"):
            continue
        if item.get("official_price_values"):
            official_values[brand] = {int(value) for value in item["official_price_values"]}
            continue
        if item.get("browser_snapshot_text"):
            body = (root / item["browser_snapshot_text"]).read_text(encoding="utf-8")
            official_values[brand] = money_values(body)
            continue
        if brand == "Tesla" and item.get("browser_snapshot"):
            snapshot = json.loads((root / item["browser_snapshot"]).read_text(encoding="utf-8"))
            official_values[brand] = {
                int(value)
                for record in snapshot
                for value in (record.get("configuration_price_excluding_taxes_tl"), record.get("purchase_price_tl"))
                if value
            }
            continue
        request = Request(item.get("final_url") or item["url"], headers=BROWSER_HEADERS)
        with urlopen(request, timeout=45, context=context) as response:
            data = response.read()
            body = response_text(data, response.headers.get_content_type(), response.headers.get_content_charset(), response.url)
            if item.get("type") == "crawl_model_prices":
                for child_url in model_price_links(body, response.url):
                    child_request = Request(child_url, headers=BROWSER_HEADERS)
                    with urlopen(child_request, timeout=45, context=context) as child_response:
                        child_data = child_response.read()
                        body += "\n" + response_text(child_data, child_response.headers.get_content_type(), child_response.headers.get_content_charset(), child_response.url)
        official_values[brand] = money_values(body)

    for row in rows:
        brand = row["Marka"]
        raw_price = row["Liste_Fiyati_TL"]
        if not raw_price:
            row["Resmi_Dogrulama"] = "FIYAT_YOK"
        elif brand not in official_values:
            row["Resmi_Dogrulama"] = "RESMI_KAYNAK_TARAYICI_GEREKLI"
        elif int(raw_price) in official_values[brand]:
            row["Resmi_Dogrulama"] = "RESMI_FIYAT_ESLESTI"
        else:
            row["Resmi_Dogrulama"] = "RESMI_FIYAT_ESLESMEDI"
        row["Resmi_Kaynak_URL"] = (health.get(brand) or {}).get("final_url") or (health.get(brand) or {}).get("url", "")

    output = root / "data" / "official" / f"{date.today():%Y-%m-%d}_fiyat_dogrulama.csv"
    fieldnames = list(rows[0].keys())
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    critical = {"Dacia", "Fiat", "Renault"}
    missing_official = sorted(brand for brand in critical if not official_values.get(brand))
    if missing_official:
        raise RuntimeError(f"Resmi fiyat kümesi boş: {', '.join(missing_official)}")
    no_matches = sorted(
        brand for brand in critical
        if not any(row["Marka"] == brand and row["Resmi_Dogrulama"] == "RESMI_FIYAT_ESLESTI" for row in rows)
    )
    if no_matches:
        raise RuntimeError(f"Güncel veriyle resmi fiyat eşleşmesi yok: {', '.join(no_matches)}")
    print(json.dumps(Counter(row["Resmi_Dogrulama"] for row in rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
