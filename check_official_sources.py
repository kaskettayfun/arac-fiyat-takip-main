import json
import io
import re
import ssl
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

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


def main() -> None:
    root = Path(__file__).resolve().parent
    sources = json.loads((root / "config" / "official_sources.json").read_text(encoding="utf-8"))
    context = ssl.create_default_context()
    results = []
    for source in sources:
        result = dict(source)
        try:
            request = Request(source["url"], headers=BROWSER_HEADERS)
            with urlopen(request, timeout=35, context=context) as response:
                data = response.read()
                content_type = response.headers.get_content_type()
                body = response_text(data, content_type, response.headers.get_content_charset(), response.url)
                if source.get("type") == "crawl_model_prices":
                    for child_url in model_price_links(body, response.url):
                        child_request = Request(child_url, headers=BROWSER_HEADERS)
                        with urlopen(child_request, timeout=35, context=context) as child_response:
                            child_data = child_response.read()
                            body += "\n" + response_text(child_data, child_response.headers.get_content_type(), child_response.headers.get_content_charset(), child_response.url)
                result.update({
                    "status": response.status,
                    "final_url": response.url,
                    "content_type": content_type,
                    "price_token_count": len(re.findall(r"(?:₺|TL|TRY|\d{1,3}(?:\.\d{3}){2,})", body, re.IGNORECASE)),
                    "reachable": True,
                })
        except Exception as exc:
            tesla_snapshot = root / "data" / "official" / "tesla_latest.json"
            if source["brand"] == "Tesla" and tesla_snapshot.exists():
                records = json.loads(tesla_snapshot.read_text(encoding="utf-8"))
                result.update({
                    "reachable": True,
                    "status": "BROWSER_SNAPSHOT",
                    "final_url": source["url"],
                    "content_type": "application/json",
                    "price_token_count": sum(
                        bool(item.get("purchase_price_tl") or item.get("configuration_price_excluding_taxes_tl"))
                        for item in records
                    ),
                    "browser_snapshot": str(tesla_snapshot.relative_to(root)),
                })
            else:
                result.update({"reachable": False, "error": str(exc)[:300]})
        result["checked_at"] = datetime.now(ZoneInfo("Europe/Istanbul")).isoformat()
        results.append(result)

    output = root / "data" / "official" / "source_health.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "total": len(results),
        "reachable": sum(bool(item.get("reachable")) for item in results),
        "unreachable": [item["brand"] for item in results if not item.get("reachable")],
        "low_price_signal": [item["brand"] for item in results if item.get("reachable") and item.get("price_token_count", 0) < 3],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
