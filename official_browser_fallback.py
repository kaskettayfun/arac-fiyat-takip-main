from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

TARGETS = {"Dacia", "Fiat", "Renault"}


def price_tokens(text: str) -> int:
    return len(re.findall(r"(?:₺|TL|TRY|\d{1,3}(?:[.,]\d{3}){2,})", text, re.IGNORECASE))


def main() -> None:
    root = Path(__file__).resolve().parent
    health_path = root / "data" / "official" / "source_health.json"
    health = json.loads(health_path.read_text(encoding="utf-8"))
    pending = [
        item for item in health
        if item["brand"] in TARGETS
        and (not item.get("reachable") or item.get("price_token_count", 0) < 3)
    ]
    if pending:
        snapshot_dir = root / "data" / "official" / "browser_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="tr-TR", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36")
            for item in pending:
                page = context.new_page()
                try:
                    response = page.goto(item["url"], wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(8000)
                    texts = []
                    for frame in page.frames:
                        try:
                            texts.append(frame.locator("body").inner_text(timeout=5000))
                            texts.append(frame.content())
                        except Exception:
                            continue
                    body = "\n".join(texts)
                    count = price_tokens(body)
                    if count < 3:
                        raise RuntimeError(f"resmi sayfada yeterli fiyat sinyali yok: {count}")
                    snapshot_path = snapshot_dir / f"{item['brand'].lower()}_latest.txt"
                    snapshot_path.write_text(body, encoding="utf-8")
                    item.update({
                        "reachable": True,
                        "status": response.status if response else "BROWSER_OK",
                        "final_url": page.url,
                        "content_type": "text/browser-snapshot",
                        "price_token_count": count,
                        "browser_snapshot_text": str(snapshot_path.relative_to(root)),
                        "fallback": "playwright",
                        "checked_at": datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
                    })
                    item.pop("error", None)
                except Exception as exc:
                    item.update({"reachable": False, "error": f"browser fallback: {exc}"[:300]})
                finally:
                    page.close()
            browser.close()
    health_path.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [item["brand"] for item in health if item["brand"] in TARGETS and (not item.get("reachable") or item.get("price_token_count", 0) < 3)]
    if failed:
        raise RuntimeError(f"Resmi fiyat alınamayan kritik markalar: {', '.join(failed)}")
    print("Kritik resmi kaynaklar doğrulandı: Dacia, Fiat, Renault")


if __name__ == "__main__":
    main()
