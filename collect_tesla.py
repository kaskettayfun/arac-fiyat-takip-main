import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright


URL = "https://www.tesla.com/tr_tr/modely/design#overview"
OUTPUT = Path(__file__).resolve().parent / "data" / "official" / "tesla_latest.json"
VARIANTS = [
    "Arkadan Çekiş",
    "Long Range Arkadan Çekiş",
    "Long Range Dört Çeker",
    "Dört Çeker",
]


def tl_value(value: str) -> int:
    return int(re.sub(r"\D", "", value))


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        context = await browser.new_context(
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        await page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        await page.get_by_text("Satın Alma Fiyatı", exact=False).first.wait_for(timeout=120_000)

        records = []
        for variant in VARIANTS:
            choices = page.get_by_text(variant, exact=True)
            await choices.last.click()
            await page.wait_for_timeout(1800)
            body = await page.locator("body").inner_text()
            purchase_matches = re.findall(r"Satın Alma Fiyatı\s*₺\s*([\d.]+)", body)
            configuration_matches = re.findall(rf"{re.escape(variant)}\s*₺\s*([\d.]+)", body)
            if not purchase_matches:
                raise RuntimeError(f"Tesla satın alma fiyatı okunamadı: {variant}")
            records.append({
                "brand": "Tesla",
                "model": "Model Y",
                "variant": variant,
                "configuration_price_excluding_taxes_tl": tl_value(configuration_matches[-1]) if configuration_matches else None,
                "purchase_price_tl": tl_value(purchase_matches[-1]),
                "source_url": URL,
                "collected_at": datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
            })
        await browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"brand": "Tesla", "records": len(records), "output": str(OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        if not OUTPUT.exists():
            raise
        print(json.dumps({
            "brand": "Tesla",
            "status": "BROWSER_BLOCKED_LAST_SNAPSHOT_PRESERVED",
            "error": str(exc)[:300],
            "snapshot": str(OUTPUT),
        }, ensure_ascii=False))
