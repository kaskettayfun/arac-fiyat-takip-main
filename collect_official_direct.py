from __future__ import annotations

import asyncio
import json
import base64
import os
import re
from collections import Counter
from io import BytesIO
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urljoin
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright
from pypdf import PdfReader
from lxml import html as lxml_html
from openpyxl import load_workbook

from vehicle_prices.schema import PriceRecord


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "official" / "direct_latest.json"
HISTORY = ROOT / "data" / "Sifir_Arac_Fiyat_Gecmisi.xlsx"
MINIMUM_FALLBACK_EXPORT_ROWS = 750
SOURCES = {x["brand"]: x for x in json.loads((ROOT / "config" / "official_sources.json").read_text(encoding="utf-8"))}
NOW = datetime.now(ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36"}
SOURCE_UPDATING_PREFIX = "RESMÎ SİTEDE FİYATLAR GÜNCELLENİYOR:"
SOURCE_ACCESS_PREFIX = "RESMÎ KAYNAK ERİŞİM KORUMASI:"
VOLVO_DATED_SECONDARY_URL = "https://tekerli.com/fiyat-listesi/volvo"
TESLA_DATED_SECONDARY_URL = "https://tekerli.com/fiyat-listesi/tesla"
MINIMUM_BRAND_ROWS = {
    "CUPRA": 5, "Lexus": 5, "Alfa Romeo": 3, "DS": 3, "MG": 5, "SEAT": 4,
    "Audi": 40, "BMW": 40, "BYD": 2, "Chery": 4, "Citroen": 40,
    "Dacia": 4, "Fiat": 50, "Ford": 100, "Honda": 5, "Hyundai": 33,
    "KGM": 7, "Kia": 15, "Mercedes-Benz": 80, "MINI": 12,
    "Nissan": 18, "Opel": 20, "Peugeot": 30, "Renault": 20,
    "Skoda": 25, "Tesla": 4, "Togg": 8, "Toyota": 20,
    "Volkswagen": 55, "Volvo": 12,
}
MINIMUM_MODEL_COUNTS = {
    "Ford": 20, "Fiat": 17, "Citroen": 15, "Peugeot": 15, "Toyota": 9,
    "Hyundai": 12, "Nissan": 4, "CUPRA": 3, "SEAT": 4, "Lexus": 4,
    "Alfa Romeo": 4, "DS": 3, "MG": 3, "Togg": 2, "Honda": 5,
}
REQUIRED_PRICED_MODELS = {
    "Audi": {"Q3", "Q3 Sportback"},
    "Togg": {"T10X", "T10F"},
    "Honda": {"Jazz e:HEV", "HR-V e:HEV", "ZR-V e:HEV", "CR-V e:HEV", "Prelude e:HEV"},
    "Toyota": {"Corolla", "Yaris Hybrid", "Corolla Cross Hybrid", "C-HR Hybrid", "Hilux", "Proace City"},
    # 22.10.2026 resmî Fiat listesi 17 fiyatlı aile/60 versiyon yayımlıyor;
    # Grande Panda Hibrit artık listede yok. Eski 18/70 eşiği 29 satırlık
    # eski snapshot'ı haksız yere koruyordu. Çekirdek binekler ayrıca korunur.
    "Fiat": {"Egea Sedan", "Egea Cross", "Grande Panda Elektrikli", "500e", "Topolino", "600"},
}
FORBIDDEN_MODEL_PATTERNS = {
    "Mercedes-Benz": (r"Fiyat Listesi$",),
}
REQUIRED_COMMERCIAL_PATTERNS = {
    "Ford": (r"Transit", r"Tourneo"),
    "Fiat": (r"Doblo", r"Ducato", r"Scudo"),
    "Citroen": (r"Berlingo", r"Jumpy", r"Jumper"),
    "Peugeot": (r"Partner", r"Expert", r"Boxer"),
    "Toyota": (r"Proace", r"Hilux"),
    "Nissan": (r"Townstar",),
    "Renault": (r"Kangoo", r"Trafic", r"Master"),
    "Volkswagen": (r"Caddy", r"Transporter", r"Caravelle", r"Multivan", r"ID\.?\s*Buzz",
                   r"Crafter", r"Amarok", r"Grand California"),
    "Mercedes-Benz": (r"Vito", r"Sprinter"),
}
WEBTEKNO_TESLA_TOPIC = "https://www.webtekno.com/konu/tesla"
WEBTEKNO_TESLA_KNOWN_URLS = (
    "https://www.webtekno.com/tesla-fiyat-listesi-h226256.html",
    "https://www.webtekno.com/tesla-ekim-2026-fiyat-listesi-h226256.html",
)
TR_MONTHS = {
    "ocak": 1, "subat": 2, "şubat": 2, "mart": 3, "nisan": 4,
    "mayis": 5, "mayıs": 5, "haziran": 6, "temmuz": 7,
    "agustos": 8, "ağustos": 8, "eylul": 9, "eylül": 9,
    "ekim": 10, "kasim": 11, "kasım": 11, "aralik": 12, "aralık": 12,
}


def price(value) -> int | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    result = int(digits)
    return result if 500_000 <= result <= 100_000_000 else None


def renault_catalog_price(value) -> int | None:
    """Renault/Dacia servisinin kuruşlu TL değerini tam TL'ye yuvarla."""
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        return None
    result = int(Decimal(raw).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return result if 500_000 <= result <= 100_000_000 else None


def table_price(value) -> int | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not re.fullmatch(r"(?:₺\s*)?\d{1,3}(?:[.,]\d{3}){2}(?:\s*(?:₺|TL|TRY))?(?:\s*(?:[*†]+|\(\*+\)|\[\d+\]))?", text, re.I):
        return None
    return price(text)


def volkswagen_commercial_price(text: str) -> int | None:
    """VW Ticari kartındaki dipnotlardan etkilenmeden anahtar teslim fiyatını döndür."""
    match = re.search(r"Anahtar Teslim Fiyatı.*?(\d{1,3}(?:\.\d{3}){2}\s*TL)", text, re.I | re.S)
    return price(match.group(1)) if match else None


def volkswagen_commercial_button_pattern(model: str) -> re.Pattern[str]:
    """Match the visible model button name, including repeated image alt text."""
    return re.compile(rf"^{re.escape(model)}(?:\s|$)", re.I)


def source_update_notice(text: str) -> str | None:
    """Yalnız resmî sayfada açık bir fiyat güncelleme mesajı varsa döndür."""
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    match = re.search(
        r"(?:fiyat(?:larımız|lar)?|fiyat\s+list(?:emiz|esi|eleri))\s+"
        r"(?:güncellenmektedir|güncelleniyor|güncelleme\s+aşamasındadır)",
        normalized, re.I,
    )
    if not match:
        match = re.search(r"fiyatlarımızı\s+güncelliyoruz", normalized, re.I)
    return match.group(0) if match else None


def official_source_update_reason(brand: str) -> str | None:
    """Bir toplama hatasından sonra markanın resmî sayfasındaki ilanı teyit et."""
    try:
        content = urlopen(Request(SOURCES[brand]["url"], headers=HEADERS), timeout=30).read()
        notice = source_update_notice(content.decode("utf-8", "replace"))
        return f"{SOURCE_UPDATING_PREFIX} {notice}" if notice else None
    except Exception:
        return None


def extract_page_effective_date(text: str) -> date | None:
    """Sayfa metninde açıkça belirtilen geçerlilik/güncelleme tarihini çıkar."""
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    numeric = re.search(
        r"(\d{1,2})\.(\d{1,2})\.(20\d{2})\s*(?:tarih(?:inden|i\s+itibarıyla|i\s+itibariyle)|itibarıyla)",
        normalized, re.I,
    )
    if numeric:
        try:
            return date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
        except ValueError:
            pass
    named = re.search(
        r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(20\d{2})\s+tarih(?:inden|i)",
        normalized, re.I,
    )
    if named and named.group(2).casefold() in TR_MONTHS:
        try:
            return date(int(named.group(3)), TR_MONTHS[named.group(2).casefold()], int(named.group(1)))
        except ValueError:
            pass
    return None


def byd_model_for(heading: str, cell0: str) -> str:
    combined = f"{heading} {cell0}".strip()
    match = re.search(
        r"\b(BYD\s+(?:SEALION\s*\d+|SEAL\s*U(?:\s*DM-i)?|SEAL|TANG|HAN|ATTO\s*\d+|DOLPHIN))\b",
        combined, re.I,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).upper().replace("DM-I", "DM-i")
    return heading.strip() or cell0.strip()


def nissan_model_for(variant: str, heading: str = "") -> str:
    combined = f"{heading} {variant}".strip()
    if re.search(r"townstar", combined, re.I):
        return "Townstar"
    if re.search(r"^EV\s+(?:Designpack|Platinum|Tekna|Visia)", variant, re.I):
        return "Townstar"
    if re.search(r"qashqai", heading, re.I):
        return "Qashqai"
    if re.search(r"juke", heading, re.I):
        return "Juke"
    if re.search(r"x-?trail", heading, re.I):
        return "X-Trail"
    if re.search(r"\bL[12]\b", variant, re.I):
        return "Townstar"
    if re.search(r"^EV\s+(?:Designpack|Platinum)", variant, re.I):
        return "Townstar"
    if re.search(r"1\.3\s+DIG-T|e-POWER", variant, re.I):
        return "Qashqai"
    if re.search(r"1\.0\s+DIG-T", variant, re.I):
        return "Juke"
    if re.search(r"1\.5\s+VC-T", variant, re.I):
        return "X-Trail"
    return ""


def record(brand: str, model: str, variant: str, list_price: int, campaign: int | None = None,
           model_year: int | None = None, fuel: str = "", transmission: str = "",
           power: str = "", source_url: str | None = None, list_date: date | None = None,
           note: str = "Resmî Türkiye kaynağından doğrudan alınmıştır") -> PriceRecord:
    return PriceRecord(NOW, list_date or NOW.date(), brand, model.strip(), variant.strip(), model_year,
                       fuel.strip(), transmission.strip(), None, power.strip(), list_price, campaign,
                       "TL", source_url or SOURCES[brand]["url"], "OK", note)


def fetch_json(url: str):
    return json.loads(urlopen(Request(url, headers=HEADERS), timeout=60).read())


def previous_verified_brand(brand: str) -> tuple[list[PriceRecord], str | None]:
    """Son doğrulanmış marka snapshot'ını kontrollü B planı olarak yükle."""
    # Fiyat geçmişi yalnız değişen kayıtları tutabilir; tek bir günün kayıtları
    # tam marka snapshot'ı değildir. Önce kapsamı geçen son güncel Excel'i kullan.
    exports = sorted(HISTORY.parent.glob("Sifir_arac_????-??-??.xlsx"), reverse=True)
    for path in exports:
        if path.stem[-10:] >= NOW.date().isoformat():
            continue
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                sheet = workbook["Guncel_Fiyatlar"]
                headers = [cell.value for cell in sheet[1]]
                expected = ["Tarih", "Marka", "Model", "Versiyon", "Model Yılı",
                            "Liste Fiyatı", "Kampanyalı Fiyat", "TSB Kodu", "Eşleşme Durumu"]
                if headers != expected:
                    continue
                values = list(sheet.iter_rows(min_row=2, max_col=9, values_only=True))
                source_details = {}
                if "Kaynak_Durumu" in workbook:
                    source_details = {row[0]: row for row in workbook["Kaynak_Durumu"].iter_rows(
                        min_row=2, values_only=True) if row[0]}
            finally:
                workbook.close()
        except (OSError, KeyError, ValueError):
            continue
        counts = Counter(row[1] for row in values)
        if (len(values) < MINIMUM_FALLBACK_EXPORT_ROWS or set(counts) != set(MINIMUM_BRAND_ROWS)
                or any(counts[b] < minimum for b, minimum in MINIMUM_BRAND_ROWS.items())):
            continue
        if any(len({str(row[2]).casefold() for row in values if row[1] == b}) < minimum
               for b, minimum in MINIMUM_MODEL_COUNTS.items()):
            continue
        rows = []
        detail = source_details.get(brand, ())
        source_day = detail[2] if len(detail) > 2 and detail[2] else None
        source_url = detail[4] if len(detail) > 4 and str(detail[4] or "").startswith("https://") else SOURCES[brand]["url"]
        for item in values:
            if item[1] != brand or not isinstance(item[5], int) or item[5] <= 0:
                continue
            day = item[0].date() if isinstance(item[0], datetime) else item[0]
            if not isinstance(day, date):
                day = date.fromisoformat(str(day)[:10])
            list_day = date.fromisoformat(str(source_day)[:10]) if source_day else day
            rows.append(PriceRecord(
                datetime.combine(day, datetime.min.time()), list_day, brand,
                str(item[2]), str(item[3] or ""), item[4], "", "", None, "",
                item[5], item[6], "TL", source_url, "OK",
                f"B planı: {path.name} dosyasındaki son kapsamı doğrulanmış fiyat korundu",
            ))
        if brand not in coverage_errors(rows, {brand: len(rows)}):
            return unique(rows), str(source_day)[:10] if source_day else path.stem[-10:]
    if not HISTORY.exists():
        return [], None
    workbook = load_workbook(HISTORY, read_only=True, data_only=True)
    try:
        sheet = workbook["Tum_Fiyatlar"]
        headers = [cell.value for cell in sheet[1]]
        indexes = {name: headers.index(name) for name in PriceRecord.columns()}
        candidates = []
        for values in sheet.iter_rows(min_row=2, values_only=True):
            if str(values[indexes["Marka"]] or "") != brand:
                continue
            captured = values[indexes["Kayit_Tarihi"]]
            if isinstance(captured, datetime):
                candidates.append((captured, values))
        if not candidates:
            return [], None
        # Bir çalıştırmada binek ve ticari kaynaklar farklı saniyelerde
        # kaydedilebilir. Snapshot sınırı zaman damgası değil takvim günüdür;
        # aksi halde B planı aynı günün yalnız son alt grubunu döndürür.
        for snapshot_date in sorted({captured.date() for captured, _ in candidates}, reverse=True):
            rows = []
            for captured, values in candidates:
                if captured.date() != snapshot_date:
                    continue
                item = {name: values[index] for name, index in indexes.items()}
                list_date = item["Liste_Tarihi"]
                if isinstance(list_date, datetime):
                    list_date = list_date.date()
                rows.append(PriceRecord(
                    captured, list_date, str(item["Marka"]), str(item["Model"]),
                    str(item["Versiyon_Paket"] or ""), item["Model_Yili"],
                    str(item["Yakit_Tipi"] or ""), str(item["Sanziman"] or ""),
                    item["Motor_Hacmi_CC"], str(item["Motor_Gucu_BG"] or ""),
                    int(item["Liste_Fiyati_TL"]), item["Kampanyali_Fiyat_TL"], "TL",
                    str(item["Kaynak_URL"] or SOURCES[brand]["url"]), "OK",
                    f"B planı: resmî kaynak geçici olarak veri vermedi; {snapshot_date:%Y-%m-%d} tarihli son doğrulanmış kayıt korundu",
                ))
            rows = unique(rows)
            if brand not in coverage_errors(rows, {brand: len(rows)}):
                return rows, snapshot_date.isoformat()
        return [], None
    finally:
        workbook.close()


def minimum_coverage_errors(counts: dict[str, int]) -> dict[str, str]:
    return {
        brand: f"satır sayısı güvenlik eşiğinin altında: {counts.get(brand, 0)}/{minimum}"
        for brand, minimum in MINIMUM_BRAND_ROWS.items()
        if counts.get(brand, 0) < minimum
    }


def minimum_model_errors(rows: list[PriceRecord]) -> dict[str, str]:
    errors = {}
    for brand, minimum in MINIMUM_MODEL_COUNTS.items():
        count = len({r.Model.casefold() for r in rows if r.Marka == brand})
        if count < minimum:
            errors[brand] = f"model ailesi güvenlik eşiğinin altında: {count}/{minimum}"
    return errors


def coverage_model_key(value: str) -> str:
    value = value.casefold().replace("ı", "i")
    value = re.sub(r"^yeni\s+", "", value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def semantic_coverage_errors(rows: list[PriceRecord]) -> dict[str, str]:
    errors = {}
    def add_error(brand: str, message: str) -> None:
        errors[brand] = f"{errors[brand]}; {message}" if brand in errors else message

    by_brand = {}
    for row in rows:
        by_brand.setdefault(row.Marka, set()).add(row.Model.strip())
    for brand, required in REQUIRED_PRICED_MODELS.items():
        normalized = {coverage_model_key(x) for x in by_brand.get(brand, set())}
        missing = sorted(x for x in required if coverage_model_key(x) not in normalized)
        if missing:
            add_error(brand, "fiyatı yayımlanan model eksik: " + ", ".join(missing))
    for brand, patterns in FORBIDDEN_MODEL_PATTERNS.items():
        invalid = sorted(model for model in by_brand.get(brand, set())
                         if any(re.search(pattern, model, re.I) for pattern in patterns))
        if invalid:
            add_error(brand, "model yerine sayfa başlığı yakalandı: " + ", ".join(invalid[:5]))
    for brand, patterns in REQUIRED_COMMERCIAL_PATTERNS.items():
        models = by_brand.get(brand, set())
        missing = [("ID.Buzz" if pattern == r"ID\.?\s*Buzz" else pattern)
                   for pattern in patterns if not any(re.search(pattern, model, re.I) for model in models)]
        if missing:
            add_error(brand, "ticari model ailesi eksik: " + ", ".join(missing))
    return errors


def coverage_errors(rows: list[PriceRecord], counts: dict[str, int],
                    excluded_brands: set[str] | None = None) -> dict[str, str]:
    excluded = excluded_brands or set()
    combined = (minimum_coverage_errors(counts) | minimum_model_errors(rows)
                | semantic_coverage_errors(rows))
    return {brand: reason for brand, reason in combined.items() if brand not in excluded}


def pdf_text(url: str) -> str:
    data = urlopen(Request(url, headers=HEADERS), timeout=90).read()
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def pdf_pages(url: str) -> list[str]:
    data = urlopen(Request(url, headers=HEADERS), timeout=90).read()
    return [page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages]


def collect_volvo() -> list[PriceRecord]:
    url = SOURCES["Volvo"]["url"]
    text = pdf_text(url)
    date_match = re.search(r"Tarih\s*:\s*(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(20\d{2})", text)
    months = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
              "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12}
    list_date = NOW.date()
    if date_match and date_match.group(2).casefold() in months:
        list_date = date(int(date_match.group(3)), months[date_match.group(2).casefold()], int(date_match.group(1)))
    else:
        raise RuntimeError("Volvo PDF liste tarihi doğrulanamadı")
    if (NOW.date() - list_date).days > 90:
        raise RuntimeError(f"Volvo resmi PDF eski: liste tarihi {list_date}; güncel web fiyat listesi ayrıca doğrulanmalı")
    # Volvo aynı PDF içinde bazı dönemlerde iki ayrı tablo yayımlıyor:
    # "2026 fabrika model yılı / 2025 tescil yılı" ve
    # "2026 fabrika model yılı / 2026 tescil yılı". Operasyonel çıktıda
    # Model_Yili tescil yılını temsil eder; aksi halde aynı versiyonlar unique()
    # tarafından birleştirilip ilk tablo kayboluyordu.
    has_2025_registration = bool(re.search(r"2025\s+TESC[İI]L\s+YILI", text, re.I))
    has_2026_registration = bool(re.search(r"2026\s+TESC[İI]L\s+YILI", text, re.I))
    table_years = [2025, 2026] if has_2025_registration and has_2026_registration else [2026]
    table_index = -1
    out = []
    for line in text.splitlines():
        if re.match(r"^MODEL\s+YAKIT", line.strip(), re.I):
            table_index += 1
            continue
        values = re.findall(r"\d{1,3}(?:\.\d{3}){1,}", line)
        if len(values) < 4 or not re.match(r"^(?:EX|EC|V|XC)\d", line.strip(), re.I):
            continue
        lp = price(values[-1])
        if not lp:
            continue
        prefix = line[:line.rfind(values[0])].strip()
        model = prefix.split(",", 1)[0].strip()
        fuel_match = re.search(r"(Elektrik/Benzin|Elektrik|Benzin|Dizel)", prefix, re.I)
        fuel = fuel_match.group(1) if fuel_match else ""
        power_match = re.search(r"(\d+(?:\+\d+)?\s*(?:kW/)?\d*\s*hp)", prefix, re.I)
        model_year = table_years[min(max(table_index, 0), len(table_years) - 1)]
        out.append(record("Volvo", model, prefix[len(model):].lstrip(", "), lp, model_year=model_year,
                          fuel=fuel, transmission="Otomatik", power=power_match.group(1) if power_match else "",
                          source_url=url, list_date=list_date))
    return unique(out)


def _discover_fiat_bundle_url(default_url: str = "https://talep.fiat.com.tr/main.55e191173649a601.js") -> str:
    try:
        landing_html = urlopen(Request(SOURCES["Fiat"]["url"], headers=HEADERS), timeout=30).read().decode("utf-8", "replace")
        match = re.search(r'src=["\']([^"\']*main\.[a-f0-9]+\.js)["\']', landing_html, re.I)
        if match:
            src = match.group(1)
            return src if src.startswith("http") else f"https://talep.fiat.com.tr/{src.lstrip('/')}"
    except Exception:
        pass
    return default_url


def collect_fiat() -> list[PriceRecord]:
    # Tofaş API anahtarı (FIAT_API_AUTH) tanımlıysa talep.fiat.com.tr'ye bağlanma.
    api_root = "https://prlapi.now.tofas.com.tr/api/PriceList"
    token = os.environ.get("FIAT_API_AUTH", "").strip()
    if not token:
        bundle_url = _discover_fiat_bundle_url()
        bundle = urlopen(Request(bundle_url, headers=HEADERS), timeout=60).read().decode("utf-8", "replace")
        auth = re.search(r'auth:\{username:"([^"]+)",password:"([^"]+)"\}', bundle)
        if not auth:
            raise RuntimeError("Fiat resmî API yetkilendirmesi bulunamadı")
        token = base64.b64encode(f"{auth.group(1)}:{auth.group(2)}".encode()).decode()
    headers = {**HEADERS, "Authorization": "Basic " + token, "Origin": "https://talep.fiat.com.tr"}
    categories_url = f"{api_root}/categories"
    categories = json.loads(urlopen(Request(categories_url, headers=headers), timeout=60).read()).get("value", [])
    road_categories = [c for c in categories if any(
        word in str(c.get("name", "")).casefold() for word in ("binek", "ticari")
    )]
    selected_categories = road_categories or categories
    selected_category_ids = {str(c.get("id")) for c in selected_categories if c.get("id")}
    models_by_id = {}
    for category in selected_categories:
        category_url = f"{api_root}/categories/{category['id']}/models"
        category_models = json.loads(urlopen(Request(category_url, headers=headers), timeout=60).read()).get("value", [])
        category_models = [item for item in category_models if str(item.get("vehicleCategoryId")) in selected_category_ids]
        models_by_id.update({item["id"]: item for item in category_models if item.get("id")})
    models = list(models_by_id.values())
    if not models:
        models_url = f"{api_root}/brands/00000001-1111-1111-1111-111111111111/models"
        models = json.loads(urlopen(Request(models_url, headers=headers), timeout=60).read()).get("value", [])
    out = []
    for model in models:
        detail_url = f"{api_root}/models/{model['id']}/details"
        try:
            detail = json.loads(urlopen(Request(detail_url, headers=headers), timeout=60).read()).get("value", {})
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        for version in detail.get("vehicleVersions", []):
            fields = version.get("brandFieldData") or []
            values = [(str(x.get("fieldKey", "")).casefold(), price(x.get("value"))) for x in fields]
            positive = [(k, v) for k, v in values if v]
            if not positive:
                continue
            # API'nin ilk görünür alanı tavsiye edilen anahtar teslim liste fiyatıdır.
            lp = positive[0][1]
            campaign_values = [v for k, v in positive[1:] if v < lp]
            campaign = min(campaign_values) if campaign_values else None
            engine = str(version.get("engine", ""))
            power_match = re.search(r"(\d+(?:\+\d+)?\s*HP)", engine, re.I)
            out.append(record("Fiat", detail.get("name") or model.get("name", ""),
                              " ".join(filter(None, [version.get("name"), engine])), lp, campaign,
                              int(detail.get("year")) if str(detail.get("year", "")).isdigit() else None,
                              str(version.get("fuelType", "")), str(version.get("transmission", "")),
                              power_match.group(1) if power_match else "", source_url=detail_url))
    return unique(out)


def collect_opel() -> list[PriceRecord]:
    landing_url = SOURCES["Opel"]["url"]
    html = urlopen(Request(landing_url, headers=HEADERS), timeout=60).read().decode("utf-8", "replace")
    match = re.search(r'href=["\']([^"\']*Opel_Tum_Modeller_Fiyat_Listesi(\d{1,2})\.(\d{1,2})\.(20\d{2})\.pdf)["\']', html, re.I)
    if not match:
        raise RuntimeError("Opel resmî sayfasında güncel toplu PDF bulunamadı")
    url = urljoin(landing_url, match.group(1))
    list_date = date(int(match.group(4)), int(match.group(3)), int(match.group(2)))
    pages = pdf_pages(url)
    known_models = ("Corsa Elektrik", "Frontera Elektrik", "Mokka GSE", "Grandland Elektrik",
                    "Combo Elektrik", "Combo Cargo", "Vivaro City Van", "Vivaro Kamyonet",
                    "Movano Minibüs", "Vivaro Cargo", "Corsa", "Frontera", "Mokka", "Astra",
                    "Grandland", "Combo", "Zafira", "Movano")
    out = []
    for page_text in pages:
        model = next((m for m in known_models if re.search(rf"(?m)^{re.escape(m)}\s*$", page_text)), "")
        if not model or "Opsiyonlar" not in page_text:
            continue
        section = page_text.split("Opsiyonlar", 1)[0]
        section = section.split("(MY26)", 1)[-1]
        lines = [re.sub(r"\s+", " ", x).strip() for x in section.splitlines() if x.strip()]
        consumed = set()
        # Tek satırdaki sürümler en güvenilir PDF düzenidir.
        for i, line in enumerate(lines):
            values = [price(x) for x in re.findall(r"\d{1,3}(?:\.\d{3}){2,}\s*TL", line)]
            values = [x for x in values if x]
            if not values:
                continue
            prefix = re.split(r"\d{1,3}(?:\.\d{3}){2,}\s*TL", line, maxsplit=1)[0].strip()
            if prefix and not re.fullmatch(r"[\d.\sTL]+", prefix):
                fuel = "Elektrik" if ("kW" in prefix or "Batarya" in prefix or "GSE" in model) else ("Dizel" if "Dizel" in prefix else "Benzin" if "Benzin" in prefix or "Hybrid" in prefix else "")
                transmission = "Otomatik" if re.search(r"AT\d|DCT", prefix, re.I) else "Manuel" if re.search(r"MT\d", prefix, re.I) else ""
                power_match = re.search(r"(\d+\s*(?:HP|kW))", prefix, re.I)
                out.append(record("Opel", model, prefix, values[0], values[1] if len(values) > 1 else None,
                                  2026, fuel, transmission, power_match.group(1) if power_match else "", url,
                                  list_date))
                consumed.add(i)
        # PDF'de sürüm ve fiyat kolonları ayrı satırlara düşmüşse fiyatları sırayla eşleştir.
        names, values = [], []
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            p = price(line)
            if p and re.fullmatch(r"[\d.\sTL]+", line):
                values.append(p)
            elif not p and not line.startswith(("Motor /", "Kampanyalı", "Lansmana")):
                names.append(line)
        if names and values:
            trim_words = re.compile(r"^(Essential|Edition(?: Plus XL| XL)?|GS|Ultimate(?: XL)?|L\dH\d.+)$", re.I)
            expanded = []
            base = names[0]
            if len(names) > 1 and all(trim_words.match(x) for x in names[1:]):
                base_trim = re.search(r"\s(Essential|Edition(?: Plus XL| XL)?|GS|Ultimate(?: XL)?)$", base, re.I)
                if base_trim:
                    engine = base[:base_trim.start()].strip()
                    expanded = [base] + [f"{engine} {x}" for x in names[1:]]
                else:
                    expanded = [f"{base} {x}" for x in names[1:]]
            else:
                expanded = names
            for variant, lp in zip(expanded, values[:len(expanded)]):
                fuel = "Elektrik" if ("kW" in variant or "Batarya" in variant) else "Dizel" if "Dizel" in variant else "Benzin" if "Benzin" in variant or "Hybrid" in variant else ""
                transmission = "Otomatik" if re.search(r"AT\d|DCT", variant, re.I) else "Manuel" if re.search(r"MT\d", variant, re.I) else ""
                out.append(record("Opel", model, variant, lp, model_year=2026, fuel=fuel,
                                  transmission=transmission, source_url=url, list_date=list_date))
    return unique(out)


def collect_skoda() -> list[PriceRecord]:
    url = SOURCES["Skoda"]["url"]
    html = urlopen(Request(url, headers=HEADERS), timeout=60).read().decode("utf-8", "replace")
    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise RuntimeError("Škoda resmî fiyat JSON'u bulunamadı")
    payload = json.loads(match.group(1))["props"]["pageProps"]["initialData2026"]["priceListData"]
    months = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
              "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12}
    out = []
    for section in payload.get("priceListSections", []):
        for item in section.get("items", []):
            description = item.get("priceListDetailHeader", {}).get("description", "")
            dm = re.search(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(20\d{2})", description)
            list_date = NOW.date()
            if dm and dm.group(2).casefold() in months:
                list_date = date(int(dm.group(3)), months[dm.group(2).casefold()], int(dm.group(1)))
            for row in item.get("modelPricesTable", {}).get("data", []):
                value = lambda key: (row.get(key) or {}).get("value")
                lp = price(value("currentPrice"))
                if not lp:
                    continue
                model, variant = str(value("model") or item.get("title", "")), str(value("hardware") or "")
                fuel = "Elektrik" if re.search(r"\be-|Elektr", variant, re.I) else "Dizel" if "TDI" in variant else "Hibrit" if "mHEV" in variant else "Benzin"
                transmission = "Otomatik" if re.search(r"DSG", variant, re.I) else ""
                power_match = re.search(r"(\d+\s*PS)", variant, re.I)
                out.append(record("Skoda", model, variant, lp, price(value("discountPrice")), 2026,
                                  fuel, transmission, power_match.group(1) if power_match else "", url, list_date))
    return unique(out)


def collect_citroen() -> list[PriceRecord]:
    out = []
    for path in ("/fiyat-listesi", "/fiyat-listesi/ticari"):
        landing = "https://talep.citroen.com.tr" + path
        page = urlopen(Request(landing, headers=HEADERS), timeout=60).read().decode("utf-8", "replace")
        build = re.search(r'"buildId":"([^"]+)"', page)
        if not build:
            raise RuntimeError(f"Citroën Next.js build kimliği bulunamadı: {path}")
        url = f"https://talep.citroen.com.tr/_next/data/{build.group(1)}{path}.json"
        props = fetch_json(url)["pageProps"]
        names = {}
        for item in props.get("models", []):
            a = item.get("attributes", {})
            for key in ("Slug", "slug", "Code", "code", "Model", "model"):
                if a.get(key):
                    names[str(a[key]).casefold()] = a.get("Name") or a.get("name") or str(a[key])
        blocks = props.get("pricesAll") or []
        for block in blocks:
            rows = ((block.get("attributes") or {}).get("Data") or {}).get("prices") or []
            for x in rows:
                lp = price(x.get("list_price"))
                if not lp:
                    continue
                code = str(x.get("model", ""))
                out.append(record("Citroen", names.get(code.casefold(), code.replace("-", " ").title()),
                                  " ".join(filter(None, [x.get("motor1"), x.get("motor2"), x.get("donanim")])), lp,
                                  price(x.get("ay_kampanyali_price") or x.get("campaign_price")),
                                  int(x["model_yili"]) if str(x.get("model_yili", "")).isdigit() else None,
                                  fuel="Elektrik" if "elektr" in str(x.get("motor", "")).casefold() else "",
                                  power=str(x.get("motor", "")), source_url=landing))
    return unique(out)


def collect_dacia() -> list[PriceRecord]:
    url = "https://best.renault.com.tr/wp-json/service/v1/CatFiyatData?brand=DACIA&cat="
    payload = fetch_json(url)
    out = []
    for x in payload.get("results", payload if isinstance(payload, list) else []):
        lp = renault_catalog_price(x.get("AntesFiyati") or x.get("Fiyat"))
        if not lp:
            continue
        out.append(record("Dacia", str(x.get("ModelAdi", "")), str(x.get("VersiyonAdi", "")), lp,
                          renault_catalog_price(x.get("KampanyaliFiyat") or x.get("KampanyaFiyati")),
                          int(x["ModelYili"]) if str(x.get("ModelYili", "")).isdigit() else None,
                          str(x.get("YakitTipi", "")), str(x.get("VitesTipi", "")), source_url=url))
    return out


def collect_renault() -> list[PriceRecord]:
    url = "https://best.renault.com.tr/wp-json/service/v1/CatFiyatData?brand=RENAULT&cat="
    payload = fetch_json(url)
    out = []
    for x in payload.get("results", []):
        lp = renault_catalog_price(x.get("AntesFiyati"))
        if not lp:
            continue
        out.append(record("Renault", str(x.get("ModelAdi", "")), str(x.get("VersiyonAdi", "")), lp,
                          model_year=int(x["ModelYili"]) if str(x.get("ModelYili", "")).isdigit() else None,
                          fuel=str(x.get("YakitTipi", "")), transmission=str(x.get("VitesTipi", "")),
                          source_url=url))
    return unique(out)


def toyota_model_name(model: str) -> str:
    key = coverage_model_key(model)
    return {
        "yenihilux": "Hilux",
        "hilux": "Hilux",
        "yaris": "Yaris Hybrid",
        "yarishybrid": "Yaris Hybrid",
        "yariscross": "Yaris Cross Hybrid",
        "yariscrosshybrid": "Yaris Cross Hybrid",
        "yeniyariscrosshybrid": "Yaris Cross Hybrid",
    }.get(key, model.strip())


def collect_toyota() -> list[PriceRecord]:
    url = "https://turkiye.toyota.com.tr/middle/fiyat-listesi/fiyat_v3.xml"
    root = ElementTree.fromstring(urlopen(Request(url, headers=HEADERS), timeout=60).read())
    out = []
    for node in root.iter("ModelFiyat"):
        children = {c.tag: (c.text or "").strip() for c in list(node)}
        lp = price(children.get("ListeFiyati1") or children.get("ListeFiyati2"))
        model, variant = toyota_model_name(children.get("Govde", "")), children.get("Model", "")
        year = int(children["ModelYili"]) if children.get("ModelYili", "").isdigit() else None
        if lp and model and variant and year:
            campaign = price(children.get("KampanyaliFiyati2") or children.get("KampanyaliFiyati1"))
            out.append(record("Toyota", model, variant, lp, campaign, year,
                              children.get("MotorTipi", ""), children.get("VitesTipi", ""), source_url=url))
    return unique(out)


def unique(rows: list[PriceRecord]) -> list[PriceRecord]:
    result = {}
    for row in rows:
        key = (row.Marka.casefold(), row.Model.casefold(), row.Versiyon_Paket.casefold(), row.Model_Yili, row.Liste_Tarihi)
        result[key] = row
    return list(result.values())


async def table_rows(page, brand: str) -> list[PriceRecord]:
    await page.goto(SOURCES[brand]["url"], wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2000)
    body_text = await page.locator("body").inner_text()
    list_date = extract_page_effective_date(body_text)
    if list_date and (NOW.date() - list_date).days > 60:
        raise RuntimeError(f"{brand} resmî sayfa liste tarihi güncel değil: {list_date}")
    raw = await page.locator("table").evaluate_all("""tables => {
      const visible = tables.filter(t => {
        const s = window.getComputedStyle(t);
        return !t.hidden && s.display !== 'none' && s.visibility !== 'hidden' && t.offsetParent !== null;
      });
      const active = visible.length ? visible : tables;
      return active.map(t => ({
        heading: (() => { let p=t; while(p){ const h=p.querySelector?.('h1,h2,h3,h4,h5,h6'); if(h?.innerText) return h.innerText; p=p.parentElement } return '' })(),
        rows: [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim()))
      }));
    }""")
    out = []
    for table in raw:
        rows = table["rows"]
        if len(rows) < 2:
            continue
        headers = " ".join(rows[0]).casefold()
        model = re.sub(r"^(fiyat listesi\.?\s*)", "", table["heading"], flags=re.I).strip()
        for cells in rows[1:]:
            vals = [table_price(c) for c in cells]
            pidx = [i for i, v in enumerate(vals) if v]
            if not pidx:
                continue
            first = pidx[0]
            lp, campaign = vals[first], vals[pidx[1]] if len(pidx) > 1 else None
            variant = " ".join(c for c in cells[:first] if c and not re.fullmatch(r"20\d{2}", c))
            year = next((int(c) for c in cells if re.fullmatch(r"20\d{2}", c)), None)
            # Nissan ve BYD güncel yıl fiyat listelerinde model yılını satırda
            # tekrarlamıyor. Sayfa çalışma yılının resmî güncel listesidir.
            if year is None and brand in {"Nissan", "BYD"}:
                year = NOW.year
            fuel = next((c for c in cells if c.casefold() in {"benzin", "dizel", "elektrik", "hibrit"}), "")
            transmission = next((c for c in cells if c.casefold() in {"manuel", "otomatik", "dct", "mt", "at"}), "")
            row_model = model
            if brand == "Hyundai":
                row_model = rows[0][0].strip()
            elif brand == "Nissan":
                row_model = nissan_model_for(variant, model)
            elif brand == "BYD":
                row_model = byd_model_for(model, cells[0])
            out.append(record(brand, row_model or cells[0], variant or cells[0], lp, campaign, year, fuel, transmission, list_date=list_date))
    return unique(out)


async def collect_bmw_page(page, url: str, model_year: int) -> list[PriceRecord]:
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(3000)
    model_ids = await page.locator(".model-box[data-id]").evaluate_all("els => els.map(e => e.dataset.id)")
    out = []
    for model_id in model_ids or [None]:
        if model_id:
            await page.locator(f'.model-box[data-id="{model_id}"]').click()
            await page.wait_for_timeout(250)
        body = await page.locator("body").inner_text()
        lines = [re.sub(r"\s+", " ", x).strip() for x in body.splitlines() if x.strip()]
        lines = [x for x in lines if x not in {"DONANIMI KEŞFEDİN", "Online rezerve edin"}]
        last_model = ""
        for index, transmission in enumerate(lines):
            if transmission != "Otomatik" or index < 1 or index + 6 >= len(lines):
                continue
            # New launches are headed as "Yeni BMW ...". Treat that as a new
            # model boundary too; otherwise its first price is assigned to the
            # preceding model (e.g. iX3 price incorrectly attached to iX2).
            if index >= 2 and re.match(r"^(?:Yeni\s+)?BMW\s+", lines[index - 2]):
                last_model = lines[index - 2]
            # The official MY25 price list names this vehicle "BMW X3 20".
            # Do not turn it into X3 20d: that points to a different TSB type.
            if model_year == 2025 and last_model == "BMW X3 20d":
                last_model = "BMW X3 20"
            variant = lines[index - 1]
            fuel, displacement, power = lines[index + 1:index + 4]
            lp = price(lines[index + 6])
            if not last_model or not lp or not re.fullmatch(r"%\d+[^\d]*", lines[index + 5]):
                continue
            rec = record("BMW", last_model, variant, lp, model_year=model_year,
                         fuel=fuel, transmission=transmission, power=power, source_url=url)
            object.__setattr__(rec, "Motor_Hacmi_CC", int(re.sub(r"\D", "", displacement)) if re.sub(r"\D", "", displacement) else None)
            out.append(rec)
    return unique(out)


async def collect_bmw(page) -> list[PriceRecord]:
    out = []
    for url, year in (
        (SOURCES["BMW"]["url"], 2026),
        ("https://teknikoto.bmw.com.tr/fiyat-listesi-2024", 2025),
    ):
        out.extend(await collect_bmw_page(page, url, year))
    return unique(out)


async def collect_honda_page(page, url: str, model_year: int) -> list[PriceRecord]:
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2000)
    body = await page.locator("body").inner_text()
    effective = re.search(r"(\d{2}\.\d{2}\.\d{4}) tarihinden", body)
    list_date = datetime.strptime(effective.group(1), "%d.%m.%Y").date() if effective else NOW.date()
    navigation = body.split(f"{model_year} Model", 1)[-1].split("Karşılaştırın", 1)[0]
    models = re.findall(r"^([^\n]+(?:e:HEV|e:PHEV))$", navigation, re.M)
    groups = body.split("Karşılaştırın")[1:]
    out = []
    if len(models) != len(groups):
        raise RuntimeError(f"Honda model/fiyat grubu kapsamı değişti: {len(models)}/{len(groups)}")
    for model, group in zip(models, groups):
        lines = [re.sub(r"\s+", " ", x).strip() for x in group.splitlines() if x.strip()]
        engine = next((x for x in lines[:5] if re.match(r"\d(?:[.,]\d+)?L\s+", x)), "")
        for index, line in enumerate(lines):
            if not re.fullmatch(r"Tavsiye edilen satış fiyatı\d*", line, re.I) or index == 0:
                continue
            lp = price(lines[index + 1]) if index + 1 < len(lines) else None
            if not lp:
                continue
            trim = lines[index - 1]
            campaign = None
            if index + 3 < len(lines) and re.fullmatch(r"Tavsiye edilen kampanyalı satış fiyatı\d*", lines[index + 2], re.I):
                campaign = price(lines[index + 3])
            out.append(record("Honda", model, f"{engine} {trim}".strip(), lp, campaign,
                              model_year=model_year, fuel="Hibrit", transmission="Otomatik",
                              source_url=url, list_date=list_date))
    if {coverage_model_key(r.Model) for r in out} != {coverage_model_key(x) for x in models}:
        raise RuntimeError("Honda fiyatlı model gruplarından biri boş kaldı")
    return unique(out)


async def collect_honda(page) -> list[PriceRecord]:
    out = []
    for url, year in (
        (SOURCES["Honda"]["url"], 2026),
        ("https://www.honda.com.tr/otomobil/otomobil-fiyat-listesi-2025", 2025),
    ):
        out.extend(await collect_honda_page(page, url, year))
    return unique(out)


async def collect_toyota_browser(page) -> list[PriceRecord]:
    """Read every 2026 desktop price table, including binek and commercial tabs."""
    url = SOURCES["Toyota"]["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    # Commercial price panes can arrive after the passenger-car panes. Reading
    # the DOM too early silently drops Hilux and Proace while leaving 30 brands.
    await page.locator('#Detail_Hilux .tab-pane[id="content-Hilux-2026"] table.table-detail tbody tr').first.wait_for(state="attached", timeout=45_000)
    await page.locator('#Detail_ProaceCity .tab-pane[id="content-ProaceCity-2026"] table.table-detail tbody tr').first.wait_for(state="attached", timeout=45_000)
    groups = await page.locator("li.vehicle-item-detail").evaluate_all(r"""items => items.map(item => {
      const detail = item.querySelector('.vehicle-detail');
      const lines = (detail?.innerText || '').split('\n').map(x=>x.trim()).filter(Boolean);
      const model = lines[0] || item.id.replace(/^Detail_/, '');
      const panes = [...item.querySelectorAll('.tab-pane[id^="content-"][id$="-2026"]')]
        .filter(x => !x.id.includes('mobile'));
      const tables = panes.flatMap(p => [...p.querySelectorAll('table.table-detail')].map(t => ({
        header: t.tHead?.innerText || t.rows[0]?.innerText || '',
        rows: [...t.querySelectorAll('tbody tr')].map(r => [...r.cells].map(c=>c.innerText.trim()))
      })));
      return {model, tables};
    }).filter(x=>x.tables.length)""")
    # The official XML remains the authoritative commercial-vehicle feed; the
    # visible 2026 DOM additionally contains binek families omitted by that XML.
    out = collect_toyota()
    for group in groups:
        model = toyota_model_name(re.sub(r"^Toyota\s+", "", group["model"], flags=re.I))
        for table in group["tables"]:
            for cells in table["rows"]:
                if not cells:
                    continue
                # Some Toyota tables use one cell containing version/list/campaign lines.
                tokens = [re.sub(r"\s+", " ", x).strip() for cell in cells for x in cell.splitlines() if x.strip()]
                prices = [(i, table_price(token)) for i, token in enumerate(tokens)]
                prices = [(i, value) for i, value in prices if value]
                if not prices:
                    continue
                first_index, lp = prices[0]
                variant = next((tokens[i] for i in range(first_index - 1, -1, -1)
                                if not table_price(tokens[i]) and "Tavsiye" not in tokens[i]), "")
                if not variant:
                    continue
                campaign = next((value for _, value in prices[1:] if value < lp), None)
                fuel = "Hibrit" if "Hybrid" in (model + variant) else "Dizel" if re.search(r"D-4D|Dizel", variant, re.I) else "Benzin"
                transmission = "Otomatik" if re.search(r"CVT|Otomatik|A/T", variant, re.I) else "Manuel" if re.search(r"M/T|Manuel", variant, re.I) else ""
                out.append(record("Toyota", model, variant, lp, campaign, 2026, fuel, transmission,
                                  source_url=url, note="Toyota Türkiye resmî 2026 fiyat tablosu"))
    return unique(out)


def parse_chery_html(document: str) -> list[PriceRecord]:
    tree = lxml_html.fromstring(document)
    body = " ".join(tree.text_content().split())
    period = re.search(r"(\d{2})\.(\d{2})\.(20\d{2})\s*[–-]\s*\d{2}\.\d{2}\.20\d{2}", body)
    list_date = date(int(period.group(3)), int(period.group(2)), int(period.group(1))) if period else NOW.date()
    out = []
    for table in tree.xpath("//div[@role='table']"):
        sections = table.xpath("ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' et_pb_row ')][1]")
        if not sections:
            continue
        image = sections[0].xpath(".//img[contains(@title, 'tiggo') or contains(@alt, 'tiggo')][1]")
        caption = (image[0].get("title") or image[0].get("alt") or "") if image else ""
        model_match = re.search(r"tiggo[-\s]*(\d+)", caption, re.I)
        if not model_match:
            continue
        model = f"TIGGO{model_match.group(1)}"
        for row in table.xpath(".//*[@role='row' and not(@aria-hidden='true')]"):
            cells = [" ".join(cell.text_content().split()) for cell in row.xpath("./*[@role='cell']")]
            if len(cells) < 3 or not re.fullmatch(r"20\d{2}", cells[0]):
                continue
            listed_price = table_price(cells[2])
            if not listed_price or not cells[1]:
                continue
            campaign = table_price(cells[3]) if len(cells) > 3 else None
            out.append(record("Chery", model, cells[1], listed_price, campaign,
                              int(cells[0]), fuel="Benzin", transmission="DCT",
                              list_date=list_date))
    for html_table in tree.xpath("//table"):
        heading_nodes = html_table.xpath(
            "preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::img][position()<=5]"
        )
        heading_text = " ".join(
            (node.get("title") or node.get("alt") or " ".join(node.itertext()))
            for node in heading_nodes
        )
        model_match = re.search(r"(tiggo\s*\d+\s*(?:pro(?:\s*max)?)?|omoda\s*\d+|jaecoo\s*\d+)", heading_text, re.I)
        table_model = re.sub(r"\s+", "", model_match.group(1)).upper() if model_match else ""
        for tr in html_table.xpath(".//tr"):
            cells = [" ".join(td.itertext()).strip() for td in tr.xpath("./th|./td")]
            if len(cells) < 3 or not re.fullmatch(r"20\d{2}", cells[0]):
                continue
            listed_price = table_price(cells[2])
            if not listed_price or not cells[1]:
                continue
            campaign = table_price(cells[3]) if len(cells) > 3 else None
            row_model = table_model or "TIGGO"
            out.append(record("Chery", row_model, cells[1], listed_price, campaign,
                              int(cells[0]), fuel="Benzin", transmission="DCT",
                              list_date=list_date))
    return unique(out)


def parse_volvo_web_table(document: str, source_url: str, list_date: date) -> list[PriceRecord]:
    """Read only the priced vehicle rows from Volvo's current model pages."""
    tree = lxml_html.fromstring(document)
    out = []
    for table in tree.xpath("//table"):
        headers = [" ".join(cell.itertext()).casefold() for cell in table.xpath(".//tr[1]/*")]
        if not any("fabrika model yılı" in header for header in headers):
            continue
        if not any("liste" in header and "fiyat" in header for header in headers):
            continue
        for tr in table.xpath(".//tr"):
            cells = [" ".join(" ".join(td.itertext()).split()) for td in tr.xpath("./th|./td")]
            if len(cells) < 8 or not re.fullmatch(r"20\d{2}", cells[1]):
                continue
            model_match = re.match(r"^(EX30 Cross Country|EX30|EX40|ES90|EC40|XC60|XC90|V60)\b", cells[0], re.I)
            price_match = re.search(r"\d{1,3}(?:\.\d{3}){2,}", cells[7])
            lp = price(price_match.group(0)) if price_match else None
            if not model_match or not lp:
                continue
            model = model_match.group(1)
            out.append(record("Volvo", model, cells[0][len(model):].strip(" ,"), lp,
                              model_year=int(cells[1]), fuel=cells[2],
                              transmission="" if cells[5] == "-" else cells[5], power=cells[4],
                              source_url=source_url, list_date=list_date))
    return unique(out)


async def collect_volvo_browser(page) -> list[PriceRecord]:
    base = "https://www.volvocars.com/tr/l/fiyat-listesi/"
    out = []
    for year in (2025, 2026):
        response = await page.goto(base + str(year), wait_until="domcontentloaded", timeout=45_000)
        if response and response.status >= 400:
            raise RuntimeError(f"Volvo {year} resmî sayfa HTTP {response.status}")
        await page.get_by_text("Liste tarihi:", exact=False).first.wait_for(timeout=15_000)
        body = await page.locator("body").inner_text(timeout=10_000)
        match = re.search(r"Liste tarihi:\s*(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(20\d{2})", body)
        if not match or match.group(2).casefold() not in TR_MONTHS:
            raise RuntimeError(f"Volvo {year} liste tarihi bulunamadı")
        list_date = date(int(match.group(3)), TR_MONTHS[match.group(2).casefold()], int(match.group(1)))
        if (NOW.date() - list_date).days > 90:
            raise RuntimeError(f"Volvo {year} fiyat listesi eski: {list_date}")
        links = await page.locator(f'a[href*="/tr/l/fiyat-listesi/{year}/"]').evaluate_all(
            "els => [...new Set(els.map(el => el.href.split('#')[0]))]")
        if not links:
            raise RuntimeError(f"Volvo {year} model bağlantıları bulunamadı")
        for url in links:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            if response and response.status >= 400:
                raise RuntimeError(f"Volvo resmî model sayfası HTTP {response.status}: {url}")
            await page.locator("table").first.wait_for(timeout=15_000)
            rows = parse_volvo_web_table(await page.content(), url, list_date)
            if not rows:
                raise RuntimeError(f"Volvo model fiyat tablosu boş: {url}")
            out.extend(rows)
    return unique(out)


def parse_volvo_dated_secondary(document: str, source_url: str) -> list[PriceRecord]:
    """Parse a dated secondary snapshot, never presenting it as an official pull."""
    tree = lxml_html.fromstring(document)
    body = " ".join(tree.xpath("//body//text()"))
    updated = re.search(r"Son güncelleme:\s*(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(20\d{2})", body)
    if not updated or updated.group(2).casefold() not in TR_MONTHS:
        raise RuntimeError("Volvo ikincil kaynak güncelleme tarihi yok")
    updated_date = date(int(updated.group(3)), TR_MONTHS[updated.group(2).casefold()], int(updated.group(1)))
    if not 0 <= (NOW.date() - updated_date).days <= 45:
        raise RuntimeError(f"Volvo ikincil kaynak güncel değil: {updated_date}")
    out = []
    model = ""
    for tr in tree.xpath("//table//tr"):
        group = tr.xpath("./th//a[normalize-space(text())][last()]")
        if group and "grp" in tr.get("class", "").split():
            model = " ".join(group[-1].text_content().split()).removeprefix("Volvo ")
            continue
        cells = tr.xpath("./td")
        if not model or len(cells) != 4:
            continue
        version = " ".join(" ".join(cells[0].xpath("./text() | ./span/text()")).split())
        metadata = " ".join(cells[0].xpath("./small/text()"))
        year = re.search(r"\b(20\d{2})\s+model\b", metadata, re.I)
        listed = re.findall(r"\d{1,3}(?:\.\d{3}){2,}\s*TL", cells[1].text_content(), re.I)
        campaigns = re.findall(r"\d{1,3}(?:\.\d{3}){2,}\s*TL", cells[2].text_content(), re.I)
        dated = re.search(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(20\d{2})", cells[3].text_content())
        if not version or not year or not listed or not dated or dated.group(2).casefold() not in TR_MONTHS:
            continue
        list_date = date(int(dated.group(3)), TR_MONTHS[dated.group(2).casefold()], int(dated.group(1)))
        if not 0 <= (NOW.date() - list_date).days <= 90:
            raise RuntimeError(f"Volvo ikincil fiyat listesi eski: {list_date}")
        lp = price(listed[-1])
        cp = price(campaigns[-1]) if campaigns else None
        if not lp:
            continue
        details = metadata.casefold()
        fuel = ("Elektrik" if "elektrikli" in details else
                "Hibrit" if "hibrit" in details else
                "Dizel" if "dizel" in details else
                "Benzin" if "benzin" in details else "")
        transmission = "Otomatik" if "otomatik" in details else ""
        out.append(record("Volvo", model, version, lp, cp if cp and cp < lp else None,
                          model_year=int(year.group(1)), fuel=fuel, transmission=transmission,
                          source_url=source_url, list_date=list_date,
                          note="Resmî Volvo listesi erişilemedi; tarih kontrollü ikincil Tekerli fiyat listesinden alınmıştır"))
    out = unique(out)
    if len(out) < 40 or len({row.Model for row in out}) < 8:
        raise RuntimeError(f"Volvo ikincil kaynak kapsamı eksik: {len(out)}/40 satır, {len({row.Model for row in out})}/8 model")
    return out


async def collect_volvo_with_secondary(page) -> list[PriceRecord]:
    try:
        return await collect_volvo_browser(page)
    except Exception as official_error:
        try:
            response = await page.goto(VOLVO_DATED_SECONDARY_URL, wait_until="domcontentloaded", timeout=45_000)
            if response and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")
            return parse_volvo_dated_secondary(await page.content(), VOLVO_DATED_SECONDARY_URL)
        except Exception as secondary_error:
            raise RuntimeError(f"Volvo resmî kaynak: {official_error}; tarihli ikincil kaynak: {secondary_error}") from secondary_error


async def collect_chery(page) -> list[PriceRecord]:
    await page.goto(SOURCES["Chery"]["url"], wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(1500)
    return parse_chery_html(await page.content())


async def collect_peugeot(page) -> list[PriceRecord]:
    await page.goto(SOURCES["Peugeot"]["url"], wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2000)
    tables = await page.locator("table[id^='priceListTable_']").evaluate_all("""els => els.map(t => ({
      id:t.id, rows:[...t.rows].map(r => [...r.cells].map(c => c.innerText.trim()))
    }))""")
    out = []
    for table in tables:
        model = table["id"].replace("priceListTable_", "").replace("_", " ").strip()
        for cells in table["rows"]:
            values = [table_price(x) for x in cells]
            pidx = [i for i, x in enumerate(values) if x]
            if not pidx:
                continue
            variant = " ".join(x for x in cells[:pidx[0]] if x)
            if not variant or variant.casefold() == "modeller":
                continue
            fuel = "Elektrik" if re.search(r"E-\d|\bkW\b", variant, re.I) else "Dizel" if "BlueHDi" in variant else "Hibrit" if "Hybrid" in variant else "Benzin"
            transmission = "Otomatik" if re.search(r"EAT|eDCS", variant, re.I) else ""
            power_match = re.search(r"(\d+\s*(?:hp|kW))", variant, re.I)
            out.append(record("Peugeot", model, variant, values[pidx[0]], values[pidx[1]] if len(pidx) > 1 else None,
                              2026, fuel, transmission, power_match.group(1) if power_match else ""))
    return unique(out)


async def collect_dogus_cards(page, brand: str) -> list[PriceRecord]:
    """Read CUPRA/SEAT model cards, including model-specific price-list pages."""
    base_url = SOURCES[brand]["url"]
    await page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    hrefs = await page.locator("a").evaluate_all(
        "els => [...new Set(els.map(a=>a.href).filter(h=>h && h.includes('fiyat-listesi')))]"
    )
    known = ({"CUPRA": ("formentor", "terramar", "leon", "born"),
              "SEAT": ("ibiza", "arona", "leon", "ateca")})[brand]
    root = base_url.rstrip("/")
    urls = [base_url] + [x for x in hrefs if x.startswith("https://")] + [f"{root}/{slug}" for slug in known]
    out = []
    for url in dict.fromkeys(urls):
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(2500)
        body = await page.locator("body").inner_text()
        lines = [re.sub(r"\s+", " ", x).strip() for x in body.splitlines() if x.strip()]
        dm = re.search(r"tarih:\s*(\d{2})/(\d{2})/(20\d{2})", body, re.I)
        list_date = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))) if dm else NOW.date()
        for index, line in enumerate(lines):
            lp = table_price(line)
            if not lp or index < 2:
                continue
            fuel, variant = lines[index - 1], lines[index - 2]
            if not re.search(r"Benzin|Dizel|Elektr|Hibrit", fuel, re.I):
                continue
            model = re.split(r"\s+\d(?:\.|\s)", variant, maxsplit=1)[0].strip()
            out.append(record(brand, model, variant, lp, model_year=2026, fuel=fuel,
                              transmission="Otomatik" if re.search(r"DSG|Otomatik", variant, re.I) else "",
                              source_url=url, list_date=list_date))
    return unique(out)


async def collect_lexus(page) -> list[PriceRecord]:
    url = SOURCES["Lexus"]["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    tables = await page.locator("table").evaluate_all(
        "els => els.map(t => [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim())))"
    )
    out = []
    for rows in tables:
        if len(rows) < 2:
            continue
        header = " ".join(rows[0])
        final_columns = [i for i, cell in enumerate(rows[0]) if "Anahtar Teslim" in cell]
        if not final_columns:
            continue
        for cells in rows[1:]:
            if not cells:
                continue
            lp = next((price(cells[i]) for i in final_columns if i < len(cells) and price(cells[i])), None)
            if not lp:
                continue
            campaign_candidates = [price(cells[i]) for i in final_columns[1:] if i < len(cells) and price(cells[i])]
            campaign = min((x for x in campaign_candidates if x < lp), default=None)
            variant = cells[0]
            model = variant.split()[0]
            year_match = re.search(r"(20\d{2})\s*MY", header)
            out.append(record("Lexus", model, variant, lp, campaign,
                              int(year_match.group(1)) if year_match else 2026,
                              fuel="Hibrit", transmission=cells[1] if len(cells) > 1 else "", source_url=url))
    return unique(out)


async def collect_mg(page) -> list[PriceRecord]:
    url = SOURCES["MG"]["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    tables = await page.locator("table").evaluate_all(
        "els => els.map(t => [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim())))"
    )
    out = []
    for rows in tables:
        if len(rows) < 2 or "Model" not in " ".join(rows[0]):
            continue
        for cells in rows[1:]:
            values = [table_price(x) for x in cells]
            pidx = [i for i, x in enumerate(values) if x]
            if not pidx or not cells[0].startswith("MG"):
                continue
            year = next((int(x) for x in cells if re.fullmatch(r"20\d{2}", x)), None)
            lp = values[pidx[0]]
            campaign = next((values[i] for i in pidx[1:] if values[i] < lp), None)
            model = " ".join(cells[0].split()[:2])
            out.append(record("MG", model, cells[0], lp, campaign, year,
                              cells[1] if len(cells) > 1 else "", source_url=url))
    return unique(out)


def parse_alfa_romeo_html(document: str, url: str) -> list[PriceRecord]:
    tree = lxml_html.fromstring(document)
    rows = []
    for element in tree.xpath("//tr[contains(concat(' ', normalize-space(@class), ' '), ' mobile-disable ')]"):
        rows.append([" ".join(cell.text_content().split()) for cell in element.xpath("./th|./td")])
    body = " ".join(tree.text_content().split())
    published = re.search(r"fiyatlari\s+(\d{2})\.(\d{2})\.(20\d{2})\s+tarihi", body, re.I)
    list_date = (date(int(published.group(3)), int(published.group(2)), int(published.group(1)))
                 if published else NOW.date())
    out = []
    for cells in rows:
        if len(cells) < 6 or not price(cells[5]):
            continue
        model, trim, transmission, fuel = cells[0], cells[2], cells[3], cells[4]
        out.append(record("Alfa Romeo", model, f"{model} {trim}", price(cells[5]), model_year=2026,
                          fuel=fuel, transmission=transmission, source_url=url, list_date=list_date))
    return unique(out)


async def collect_alfa_romeo(page) -> list[PriceRecord]:
    url = "https://arjfiyat.tofas.com.tr/pricelists?brand=alfa-romeo&hidebutton=true"
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(1500)
    out = parse_alfa_romeo_html(await page.content(), url)
    if len({row.Model.casefold() for row in out}) >= MINIMUM_MODEL_COUNTS["Alfa Romeo"]:
        return out

    # GitHub'ın tarayıcı IP'sine zaman zaman boş iskelet HTML dönüyor. Aynı
    # resmi Tofaş kaynağını normal HTTP isteğiyle tekrar okuyarak tek bir geçici
    # sunucu davranışının bütün haftalık çalışmayı bozmasını engelle.
    def direct_fetch() -> str:
        return urlopen(Request(url, headers=HEADERS), timeout=60).read().decode("utf-8", "replace")

    return parse_alfa_romeo_html(await asyncio.to_thread(direct_fetch), url)


async def collect_ds(page) -> list[PriceRecord]:
    """Read every model-specific page exposed by DS Turkey's official selector."""
    landing = SOURCES["DS"]["url"]
    await page.goto(landing, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(1500)
    options = await page.locator("select.price option[data-route]").evaluate_all(
        "els => els.map(o => ({label:o.innerText.trim(), route:o.dataset.route})).filter(x=>x.route)"
    )
    if len(options) != 3:
        raise RuntimeError(f"DS resmî model seçicisi değişti: {len(options)}/3")
    out = []
    for option in options:
        url = f"https://talep.dsautomobiles.com.tr/fiyat-listesi-{option['route']}.html"
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(700)
        body = await page.locator("body").inner_text()
        published = re.search(r"(\d{2})\.(\d{2})\.(20\d{2}) tarihinde yayımlanmıştır", body, re.I)
        list_date = (date(int(published.group(3)), int(published.group(2)), int(published.group(1)))
                     if published else NOW.date())
        year_match = re.search(r"(20\d{2}) İMAL YILI", body, re.I)
        year = int(year_match.group(1)) if year_match else NOW.year
        grid = await page.locator("ul.price-grid").first.inner_text()
        lines = [re.sub(r"\s+", " ", x).strip() for x in grid.splitlines() if x.strip()]
        price_index = next((i for i, x in enumerate(lines) if table_price(x)), None)
        if price_index is None or price_index == 0:
            continue
        variant = lines[price_index - 1]
        lp = table_price(lines[price_index])
        fuel = "Elektrik" if re.search(r"ELEKTRİK|FWD|Long Range", grid, re.I) else "Dizel"
        transmission = "Otomatik" if re.search(r"Otomatik|FWD", variant, re.I) else ""
        out.append(record("DS", option["label"], variant, lp, model_year=year,
                          fuel=fuel, transmission=transmission, source_url=url,
                          list_date=list_date, note="DS Türkiye resmî model fiyat sayfası"))
    if len({r.Model for r in out}) != len(options):
        raise RuntimeError(f"DS resmî model kapsamı eksik: {len({r.Model for r in out})}/{len(options)}")
    return unique(out)


async def collect_togg(page) -> list[PriceRecord]:
    out = []
    urls = SOURCES["Togg"].get("urls") or [SOURCES["Togg"]["url"]]
    for url in urls:
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(2500)
        body = await page.locator("body").inner_text()
        text = body.split("Fiyat Listesi", 1)[-1].split("Opsiyonlar", 1)[0]
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        split = lines.index("Teslim Fiyatları")
        model = next((x.upper() for x in lines[:split] if re.fullmatch(r"T10[XF]", x, re.I)), "")
        if not model:
            model = "T10F" if "t10f" in url.casefold() else "T10X"
        variants = [x for x in lines[:split] if re.match(r"^V[12]\b", x, re.I)]
        prices = [price(x) for x in lines[split + 1:] if price(x)]
        dm = re.search(r"Fiyatlar\s+(\d{2})/(\d{2})/(20\d{2})", body)
        list_date = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))) if dm else NOW.date()
        if len(variants) != len(prices) or len(variants) != 4:
            raise RuntimeError(f"Togg {model} kapsamı değişti: {len(variants)} versiyon/{len(prices)} fiyat")
        out.extend(record("Togg", model, variant, lp, model_year=2026, fuel="Elektrik", transmission="Otomatik",
                          source_url=url, list_date=list_date)
                   for variant, lp in zip(variants, prices))
    if {r.Model for r in out} != {"T10X", "T10F"}:
        raise RuntimeError(f"Togg model kapsamı eksik: {sorted({r.Model for r in out})}")
    return unique(out)


def tesla_tax_inclusive_price(summary: str) -> int | None:
    if "Tahmini fiyatlara ÖTV ve KDV dahildir" not in summary:
        return None
    match = re.search(r"₺\s*(\d{1,3}(?:\.\d{3}){2})", summary)
    return price(match.group(1)) if match else None


async def collect_tesla_official(page) -> list[PriceRecord]:
    url = "https://www.tesla.com/tr_tr/modely/design#overview"
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.locator('label[data-id="Premium-trim-category"]').wait_for(timeout=45_000)
    # Tesla's card prices exclude taxes. The fixed footer is the four-variant
    # tax-inclusive estimate, so never record the card's smaller figure.
    base = page.locator('label.options-group--wrapper').filter(has_text=re.compile(r"^Model\s*Y\s*₺"))
    premium = page.locator('label[data-id="Premium-trim-category"]')
    performance = page.locator('label.options-group--wrapper').filter(has_text=re.compile(r"Model\s*Y\s*Performance"))
    choices = (
        ("Arkadan Çekiş", base, None),
        ("Premium Long Range Arkadan Çekiş", premium, None),
        ("Premium Long Range Dört Çeker", premium, "Long Range Dört Çeker"),
        ("Performance Dört Çeker", performance, None),
    )
    out = []
    for variant, card, subchoice in choices:
        await card.click()
        if subchoice:
            await page.locator("label.tds-form-label").filter(has_text=subchoice).click()
        summary = await page.get_by_role("button", name=re.compile("Tahmini fiyatlara ÖTV ve KDV dahildir")).inner_text(timeout=15_000)
        listed = tesla_tax_inclusive_price(summary)
        if not listed:
            raise RuntimeError(f"Tesla vergiler dâhil tahmini fiyat okunamadı: {variant}")
        out.append(record("Tesla", "Model Y", variant, listed,
                          fuel="Elektrik", transmission="Otomatik", source_url=url,
                          note="Tesla resmî yapılandırıcısının vergiler dâhil tahmini fiyatıdır; seçili standart renk ve donanım geçerlidir. Model yılı kaynakta belirtilmiyor."))
    if len({row.Liste_Fiyati_TL for row in out}) != 4:
        raise RuntimeError("Tesla sürüm seçimleri farklı dört vergili fiyat üretmedi")
    return unique(out)


def _webtekno_month(value: str) -> tuple[int, int] | None:
    normalized = value.casefold()
    year_match = re.search(r"20\d{2}", normalized)
    if not year_match:
        return None
    for month_name, month_number in TR_MONTHS.items():
        if month_name in normalized:
            return int(year_match.group()), month_number
    return None


async def collect_tesla_webtekno(page) -> list[PriceRecord]:
    """Use Webtekno's newest monthly Tesla list only as a dated fallback."""
    await page.goto(WEBTEKNO_TESLA_TOPIC, wait_until="domcontentloaded", timeout=120_000)
    anchors = await page.locator("a").evaluate_all(
        "els => els.map(a => ({text: (a.innerText || a.title || '').trim(), href: a.href || ''}))"
    )
    candidates = []
    for anchor in anchors:
        label = f"{anchor.get('text', '')} {anchor.get('href', '')}"
        period = _webtekno_month(label)
        if period and "tesla" in label.casefold() and "fiyat-listesi" in label.casefold():
            candidates.append((period, anchor["href"]))
    # Konu sayfası yeni aylık yazıyı her zaman listelemiyor (Ekim 2026 örneği).
    # Tarihi bağımsız doğrulanmış bağlantıyı adaylara ekle; daha yeni bağlantı
    # konu sayfasına geldiğinde otomatik olarak onunla ilerle.
    for known_url in WEBTEKNO_TESLA_KNOWN_URLS:
        period = _webtekno_month(known_url)
        if period:
            candidates.append((period, known_url))
    if not candidates:
        raise RuntimeError("Webtekno Tesla aylık fiyat yazısı bulunamadı")
    (year, month), article_url = max(candidates)
    article_date = date(year, month, 1)
    age_days = (NOW.date() - article_date).days
    if age_days < 0 or age_days > 45:
        raise RuntimeError(f"Webtekno Tesla yazısı güncel değil: {year}-{month:02d}")

    await page.goto(article_url, wait_until="domcontentloaded", timeout=120_000)
    body = await page.locator("body").inner_text()
    table_lines = []
    for row_text in await page.locator("table tr").all_inner_texts():
        table_lines.append(" ".join(x.strip() for x in row_text.splitlines() if x.strip()))
    table_body = "\n".join(table_lines) or body
    variant_patterns = (
        ("Premium Long Range Dört Çeker", r"Premium\s+Long\s+Range\s+(?:AWD|Dört\s+Çeker)"),
        ("Premium Long Range Arkadan Çekiş", r"Premium\s+Long\s+Range\s+(?:RWD|Arkadan\s+Çekiş)"),
        ("Performance Dört Çeker", r"Performance(?:\s+AWD|\s+Dört\s+Çeker)?"),
        ("Arkadan Çekiş", r"(?<!Long\sRange\s)(?<!Premium\s)Arkadan\s+Çekiş|\bRWD\b"),
    )
    out = []
    for variant, pattern in variant_patterns:
        match = re.search(r"(?:" + pattern + r")[ \t]{1,20}(?:₺\s*)?(\d{1,3}(?:[.,]\d{3}){2})", table_body, re.I)
        if not match:
            continue
        list_price = price(match.group(1))
        if list_price:
            out.append(record(
                "Tesla", "Model Y", variant, list_price, model_year=year,
                fuel="Elektrik", transmission="Otomatik", source_url=article_url,
                list_date=article_date,
                note="Tesla resmî yapılandırıcısı okunamadığı için tarih kontrollü Webtekno aylık fiyat listesinden alınmıştır",
            ))
    if len(out) < 4:
        raise RuntimeError(f"Webtekno Tesla tablosu eksik okundu: {len(out)}/4")
    return unique(out)


def parse_tesla_dated_secondary(document: str, source_url: str) -> list[PriceRecord]:
    """Parse a dated secondary Tesla snapshot with canonical Model Y variant names."""
    tree = lxml_html.fromstring(document)
    body = " ".join(tree.xpath("//body//text()"))
    updated = re.search(r"Son güncelleme:\s*(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(20\d{2})", body)
    if not updated or updated.group(2).casefold() not in TR_MONTHS:
        raise RuntimeError("Tesla ikincil kaynak güncelleme tarihi yok")
    updated_date = date(int(updated.group(3)), TR_MONTHS[updated.group(2).casefold()], int(updated.group(1)))
    if not 0 <= (NOW.date() - updated_date).days <= 45:
        raise RuntimeError(f"Tesla ikincil kaynak güncel değil: {updated_date}")
    canonical_variants = {
        "arkadan çekiş": "Arkadan Çekiş",
        "long range arkadan çekiş": "Premium Long Range Arkadan Çekiş",
        "premium long range arkadan çekiş": "Premium Long Range Arkadan Çekiş",
        "long range dört çeker": "Premium Long Range Dört Çeker",
        "premium long range dört çeker": "Premium Long Range Dört Çeker",
        "performance dört çeker": "Performance Dört Çeker",
    }
    out = []
    model = ""
    for tr in tree.xpath("//table//tr"):
        group = tr.xpath("./th//a[normalize-space(text())][last()]")
        if group and "grp" in tr.get("class", "").split():
            model = " ".join(group[-1].text_content().split()).removeprefix("Tesla ").strip()
            continue
        cells = tr.xpath("./td")
        if not model or len(cells) != 4:
            continue
        raw_version = " ".join(" ".join(cells[0].xpath("./text() | ./span/text()")).split()).strip()
        version = canonical_variants.get(raw_version.casefold(), raw_version)
        metadata = " ".join(cells[0].xpath("./small/text()"))
        year = re.search(r"\b(20\d{2})\s+model\b", metadata, re.I)
        listed = re.findall(r"\d{1,3}(?:\.\d{3}){2,}\s*TL", cells[1].text_content(), re.I)
        campaigns = re.findall(r"\d{1,3}(?:\.\d{3}){2,}\s*TL", cells[2].text_content(), re.I)
        if not version or not listed:
            continue
        lp = price(listed[-1])
        cp = price(campaigns[-1]) if campaigns else None
        if not lp:
            continue
        out.append(record(
            "Tesla", model, version, lp, cp if cp and cp < lp else None,
            model_year=int(year.group(1)) if year else NOW.year,
            fuel="Elektrik", transmission="Otomatik",
            source_url=source_url, list_date=updated_date,
            note="Tesla resmî yapılandırıcısı okunamadığı için tarih kontrollü ikincil Tekerli fiyat listesinden alınmıştır",
        ))
    out = unique(out)
    if len(out) < 4:
        raise RuntimeError(f"Tesla ikincil kaynak kapsamı eksik: {len(out)}/4 satır")
    return out


async def collect_tesla_dated_secondary(page) -> list[PriceRecord]:
    response = await page.goto(TESLA_DATED_SECONDARY_URL, wait_until="domcontentloaded", timeout=60_000)
    if response and response.status >= 400:
        raise RuntimeError(f"Tesla ikincil kaynak HTTP {response.status}")
    return parse_tesla_dated_secondary(await page.content(), TESLA_DATED_SECONDARY_URL)


async def collect_tesla(page) -> list[PriceRecord]:
    official_error = None
    try:
        rows = await collect_tesla_official(page)
        if len(rows) >= 3:
            return rows
        official_error = f"resmî yapılandırıcı yalnızca {len(rows)} satır verdi"
    except Exception as exc:
        official_error = str(exc)[:200]
    try:
        return await collect_tesla_webtekno(page)
    except Exception as fallback_error:
        try:
            return await collect_tesla_dated_secondary(page)
        except Exception as secondary_error:
            raise RuntimeError(
                f"Tesla resmî kaynak: {official_error}; Webtekno yedeği: {fallback_error}; Tekerli yedeği: {secondary_error}"
            ) from secondary_error


async def collect_volkswagen(page) -> list[PriceRecord]:
    """Read Volkswagen Turkey's official configurator and final-price APIs."""
    source_url = SOURCES["Volkswagen"]["url"]
    global_url = "https://binekarac.vw.com.tr/tr.global-config.json"
    response = await page.request.get(global_url, timeout=120_000)
    if not response.ok:
        raise RuntimeError(f"VW global config HTTP {response.status}")
    config = await response.json()
    spa = config["spaAsyncConfig"]
    trims = spa["showroomNavigationModel"]["config"]["trimConfigs"]
    api_key = spa["oneApiConfiguration"]["apiKey"]
    victor = spa["serviceConfigs"]["oneapi-victor"]
    api_root = victor["urlOrigin"].rstrip("/")
    tenant = victor["tenantPrivate"]
    # OneAPI returns an empty catalogue to non-browser callers unless the
    # official VW Turkey origin is present (notably on GitHub-hosted runners).
    headers = {
        "x-api-key": api_key,
        "Origin": "https://binekarac.vw.com.tr",
        "Referer": "https://binekarac.vw.com.tr/",
        "Accept-Language": "tr-TR,tr;q=0.9",
    }
    seen_trims = set()
    out = []
    for trim in trims.values():
        key = (str(trim.get("carlineId", "")), str(trim.get("salesGroupId", "")), str(trim.get("trimName", "")))
        if not all(key) or key in seen_trims:
            continue
        seen_trims.add(key)
        params = {
            "tenant": tenant, "carlineKey": key[0], "salesgroupKey": key[1],
            "modelFilters": f"EquipmentLine:{key[2]}", "fetchPrices": "true",
            "fetchTechnical": "true", "fetchWltp": "true", "fetchMandatory": "true",
        }
        models_response = await page.request.get(f"{api_root}/viso/catalogue/models", params=params,
                                                 headers=headers, timeout=120_000)
        if not models_response.ok:
            continue
        for model in (await models_response.json()).get("models", []):
            identifier = model.get("pasDataIdentifier")
            if not identifier:
                continue
            final_response = await page.request.get(f"{api_root}/vcso/configPrices/{identifier}",
                                                    params={"tenant": tenant}, headers=headers,
                                                    timeout=120_000)
            if not final_response.ok:
                continue
            final_body = (await final_response.json()).get("body", {})
            lp = price(final_body.get("modelAmount") or final_body.get("amount"))
            if not lp:
                continue
            filters = {str(x.get("type")): str(x.get("text", "")) for x in model.get("modelFilters", [])}
            fuel = filters.get("FuelType", "")
            transmission = filters.get("Gear", "")
            power_bg = filters.get("EnginePower2", "")
            displacement = filters.get("EngineTypeAttribute2", "")
            engine_cc = int(float(displacement)) if re.fullmatch(r"\d+(?:\.\d+)?", displacement) else None
            variant = re.sub(r"\s+", " ", str(model.get("longName") or model.get("name") or key[2])).strip()
            out.append(PriceRecord(
                NOW, NOW.date(), "Volkswagen", str(model.get("carlineName") or model.get("salesgroupName") or "").strip(),
                variant, int(model["year"]) if str(model.get("year", "")).isdigit() else None,
                fuel, transmission, engine_cc, power_bg, lp, None, "TL", source_url, "OK",
                "Resmî Volkswagen Türkiye yapılandırıcı ve anahtar teslim fiyat API'si",
            ))
    out.extend(await collect_volkswagen_commercial(page))
    return unique(out)


async def collect_volkswagen_commercial(page) -> list[PriceRecord]:
    url = "https://ticariarac.vw.com.tr/fiyat-listesi"
    models = ("Caddy", "Transporter", "Caravelle", "Multivan", "ID.Buzz", "Crafter",
              "Amarok", "Grand California")
    out = []
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(3000)
    body_text = await page.locator("body").inner_text(timeout=10_000)
    notice = source_update_notice(body_text)
    if notice:
        raise RuntimeError(f"{SOURCE_UPDATING_PREFIX} Volkswagen Ticari: {notice}")
    if re.search(r"Just a moment|Enable JavaScript and cookies|Attention Required|Güvenlik doğrulaması yapılıyor|bot olmadığınızı doğrularken", body_text, re.I):
        raise RuntimeError(
            f"{SOURCE_ACCESS_PREFIX} Volkswagen Ticari sayfası GitHub veri merkezi isteğine "
            "erişim doğrulaması gösterdi"
        )
    for selected_model in models:
        # activeModel sorgu parametresi sitenin güncel sürümünde güvenilir değil.
        # Resmî sayfadaki gerçek model düğmesini açarak her aileyi ayrı okuyoruz.
        # CDN/görsel optimizasyonu img alt bilgisini kaldırabildiği için yalnız
        # görsel etiketine bağlı kalma. Resmî sayfadaki erişilebilir düğme adı
        # hem görünür metinden hem de görselden üretildiği için daha kararlı.
        button = page.get_by_role(
            "button", name=volkswagen_commercial_button_pattern(selected_model)
        ).first
        if await button.count() == 0:
            button = page.locator(f'button:has(img[alt="{selected_model}"])').first
        if await button.count() == 0:
            continue
        cards = []
        expected = re.compile(re.escape(selected_model).replace(r"ID\.Buzz", r"ID\.?\s*Buzz"), re.I)
        for _ in range(2):
            await button.click()
            await page.wait_for_timeout(2500)
            cards = await page.locator("h4").evaluate_all(r"""nodes => nodes.filter(h => h.offsetParent !== null).map(h => {
              const model = document.evaluate('preceding::h3[1]', h, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue?.innerText || '';
              let box = h.parentElement; while (box && !/Anahtar Teslim Fiyatı/i.test(box.innerText || '') && box.parentElement) box = box.parentElement;
              return {model, variant: h.innerText || '', text: box?.innerText || ''};
            })""")
            if any(expected.search(card["variant"]) for card in cards):
                break
        for card in cards:
            model = re.sub(r"\s+", " ", card["model"]).strip()
            variant = re.sub(r"\s+", " ", card["variant"]).strip()
            if not expected.search(variant):
                continue
            # Bazı kartlarda fiyat başlığından sonra dipnot numarası (örn. 11)
            # yer alıyor; dipnotu fiyat sanmadan asıl TL tutarını yakala.
            lp = volkswagen_commercial_price(card["text"])
            if not model or not variant or not lp:
                continue
            fuel = "Elektrik" if re.search(r"ID\.?Buzz|Elektrik", model + variant, re.I) else "Dizel" if re.search(r"TDI", variant, re.I) else "Benzin"
            transmission = "Otomatik" if re.search(r"Otomatik|DSG", variant, re.I) else "Manuel"
            power_match = re.search(r"(\d+\s*PS)", variant, re.I)
            out.append(record("Volkswagen", model, variant, lp, model_year=2026, fuel=fuel,
                              transmission=transmission, power=power_match.group(1) if power_match else "",
                              source_url=url, note="Resmî Volkswagen Ticari Araç fiyat listesi"))
        print(f"Volkswagen ticari {selected_model}: "
              f"{sum(1 for row in out if expected.search(row.Versiyon_Paket))} satır")
    if len(out) < 30:
        raise RuntimeError(f"Volkswagen ticari fiyat kapsamı eksik: {len(out)}/30")
    return unique(out)


async def collect_kgm(page) -> list[PriceRecord]:
    await page.goto(SOURCES["KGM"]["url"], wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    tables = await page.locator("table").evaluate_all("els => els.map(t => [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim())))")
    out = []
    for rows in tables:
        if len(rows) < 2:
            continue
        model = rows[0][0].strip()
        years = [int(x) for x in re.findall(r"20\d{2}", " ".join(rows[0]))]
        for cells in rows[1:]:
            if not cells or not any(price(x) for x in cells):
                continue
            variant = cells[0]
            value_cells = cells[1:]
            for index, cell in enumerate(value_cells):
                lp = price(cell)
                if not lp:
                    continue
                year = years[index] if index < len(years) else (years[0] if years else None)
                fuel = "Elektrik" if re.search(r"EV|Elektr", model + variant, re.I) else "Dizel" if re.search(r"Dizel|D2\.2", variant, re.I) else "Benzin"
                transmission = "Otomatik" if re.search(r"AT|Otomatik", variant, re.I) else ""
                out.append(record("KGM", model, variant, lp, model_year=year, fuel=fuel,
                                  transmission=transmission, source_url=SOURCES["KGM"]["url"]))
    return unique(out)


async def collect_kia(page) -> list[PriceRecord]:
    url = SOURCES["Kia"]["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    body = await page.locator("body").inner_text()
    dm = re.search(r"(\d{2})/(\d{2})/(20\d{2}) tarihinden", body)
    list_date = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))) if dm else NOW.date()
    tables = await page.locator("table").evaluate_all(r"""tables => tables.map(t => ({
      heading: (() => { const h=document.evaluate('preceding::h2[1]',t,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue; return h?.innerText||'' })(),
      rows: [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim()))
    }))""")
    out = []
    for table in tables:
        rows = table["rows"]
        if len(rows) < 2 or "Anahtar Teslim Satış Fiyatı" not in " ".join(rows[0]):
            continue
        heading = re.sub(r"\s+Fiyat Listesi.*$", "", table["heading"], flags=re.I).strip()
        heading = re.sub(r"^Kia\s+", "", heading, flags=re.I)
        for cells in rows[1:]:
            if len(cells) < 6:
                continue
            lp, campaign = price(cells[3]), price(cells[5])
            if not lp:
                continue
            model_spec, fuel, package = cells[0], cells[1], cells[2]
            model = heading or re.split(r"\s+(?:\d|-)" , model_spec, maxsplit=1)[0]
            variant = " ".join(x for x in (model_spec, package) if x and x != model)
            transmission = "Otomatik" if re.search(r"Otomatik|DCT|AMT", model_spec, re.I) else "Manuel" if re.search(r"Manuel|MT", model_spec, re.I) else ""
            power_match = re.search(r"(\d+(?:[,.]\d+)?\s*(?:PS|kW))", model_spec, re.I)
            out.append(record("Kia", model, variant, lp, campaign, 2026, fuel, transmission,
                              power_match.group(1) if power_match else "", url, list_date))
    return unique(out)


async def collect_ford(page) -> list[PriceRecord]:
    out = []
    for path in ("/fiyat-listesi/otomobil", "/fiyat-listesi/ticari", "/fiyat-listesi/ford-store-araclar"):
        url = "https://www.ford.com.tr" + path
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(4000)
        tables = await page.locator("main table").evaluate_all(r"""tables => tables.map(t => ({
          model: document.evaluate('preceding::h3[contains(@class,"panel-title")][1]',t,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue?.innerText||'',
          header: t.tHead?.innerText||'',
          year: t.querySelector('button[data-year]')?.dataset.year||'',
          rows: [...(t.tBodies[0]?.rows||[])].map(r => [...r.cells].map(c => c.innerText.trim()))
        }))""")
        for table in tables:
            if table["year"] != "2026":
                continue
            campaign_only = "Kampanyalı" in table["header"]
            for cells in table["rows"]:
                if len(cells) < 2:
                    continue
                lp = price(cells[-1])
                if not lp:
                    continue
                variant = cells[0]
                fuel = "Elektrik" if re.search(r"Elektrik", variant, re.I) else "Hibrit" if re.search(r"Hibrit", variant, re.I) else "Dizel" if re.search(r"Dizel", variant, re.I) else "Benzin"
                transmission = "Otomatik" if re.search(r"Otomatik", variant, re.I) else "Manuel" if re.search(r"Manuel", variant, re.I) else ""
                power_match = re.search(r"(\d+\s*(?:PS|KW))", variant, re.I)
                out.append(record("Ford", table["model"], variant, lp, lp if campaign_only else None,
                                  2026, fuel, transmission, power_match.group(1) if power_match else "",
                                  url, note="Resmî Ford Türkiye fiyat tablosu"))
    return unique(out)


async def collect_mini_page(page, url: str, model_year: int) -> list[PriceRecord]:
    await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    frame = page.frame_locator("iframe")
    body = await frame.locator("body").inner_text()
    dm = re.search(r"(\d{2})\.(\d{2})\.(20\d{2}) İtibariyle", body)
    list_date = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))) if dm else NOW.date()
    buttons = frame.get_by_role("button", name="DETAYLARI GÖSTER")
    out = []
    for index in range(await buttons.count()):
        await buttons.nth(index).click()
        await page.wait_for_timeout(250)
        cards = frame.locator('h3:has-text("Azami Anahtar Teslim")')
        for card_index in range(await cards.count()):
            card = cards.nth(card_index)
            text = re.sub(r"\s+", " ", await card.inner_text()).strip()
            lp = price(text)
            if not lp:
                continue
            model_node = card.locator("xpath=preceding::h2[1]")
            model = re.sub(r"\s+", " ", await model_node.inner_text()).strip()
            package = re.sub(r"\s+Tasarım Paketi.*$", "", text, flags=re.I).strip()
            details = card.locator("xpath=following-sibling::ul[1]")
            detail_text = await details.inner_text() if await details.count() else ""
            fuel_match = re.search(r"Yakıt Tipi\s+([^\n]+)", detail_text)
            power_match = re.search(r"Motor Gücü \(KW/BG\)\s+([^\n]+)", detail_text)
            out.append(record("MINI", model, package, lp, model_year=model_year,
                              fuel=fuel_match.group(1) if fuel_match else "",
                              transmission="Otomatik" if "Otomatik" in detail_text else "",
                              power=power_match.group(1) if power_match else "", source_url=url,
                              list_date=list_date))
    return unique(out)


async def collect_mini(page) -> list[PriceRecord]:
    out = []
    for url, year in (
        (SOURCES["MINI"]["url"], 2026),
        ("https://borusanoto.mini.com.tr/satis/fiyat-listesi-2025", 2025),
    ):
        out.extend(await collect_mini_page(page, url, year))
    return unique(out)


async def collect_audi(page) -> list[PriceRecord]:
    base = "https://fiyatlistesi.audi.com.tr/"
    await page.goto(base, wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(3000)
    hrefs = await page.locator(".price_list__box").evaluate_all("els => els.map(x=>x.href)")
    out = []
    for href in hrefs:
        await page.goto(href, wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(1000)
        year_match = re.search(r"/(20\d{2})/", href)
        year = int(year_match.group(1)) if year_match else NOW.year
        cards = page.locator(".price_list__detail_box")
        for ci in range(await cards.count()):
            card = cards.nth(ci)
            model = (await card.locator(".rd_model_name").inner_text()).strip()
            token = await card.locator('input[name="__RequestVerificationToken"]').get_attribute("value")
            options = card.locator(".motor_option_item")
            option_count = await options.count()
            if option_count == 0:
                raise RuntimeError(f"Audi model seçenekleri yüklenmedi: {year} {model}")
            for oi in range(option_count):
                option = options.nth(oi)
                sub_id = await option.get_attribute("data-value")
                variant = (await option.inner_text()).strip()
                lp = None
                for attempt in range(3):
                    try:
                        response = await page.request.post(urljoin(base, "/Home/SubModel"), form={
                            "modelYear": str(year), "classCode": href.rstrip("/").split("/")[-1],
                            "subModelId": sub_id, "__RequestVerificationToken": token,
                        }, timeout=30000)
                        if response.ok:
                            data = await response.json()
                            lp = price(data.get("mrsp"))
                        if lp:
                            break
                    except Exception:
                        pass
                    await page.wait_for_timeout(500 * (attempt + 1))
                if not lp:
                    raise RuntimeError(f"Audi alt model fiyatı üç denemede alınamadı: {year} {model} {variant}")
                fuel = "Elektrik" if "e-tron" in (model + variant).casefold() else "Dizel" if "TDI" in variant else "Benzin"
                power_match = re.search(r"(\d+\s*kW)", variant, re.I)
                out.append(record("Audi", model, variant, lp, model_year=year, fuel=fuel,
                                  transmission="Otomatik", power=power_match.group(1) if power_match else "",
                                  source_url=href))
    return unique(out)


async def collect_mercedes(page) -> list[PriceRecord]:
    out = []
    await page.goto("https://fiyat.mercedes-benz.com.tr/model", wait_until="domcontentloaded", timeout=120_000)
    await page.wait_for_timeout(5000)
    price_urls = await page.locator('a[href*="/model/"][href*="/fiyat/"]').evaluate_all(
        r"els => [...new Set(els.map(x=>x.href).filter(x=>/\/model\/[^/]+\/fiyat\/20\d{2}\/?$/.test(x)))]"
    )
    for price_url in price_urls:
        try:
            await page.goto(price_url, wait_until="domcontentloaded", timeout=120_000)
            await page.locator("app-price").wait_for(timeout=30000)
            text = await page.locator("app-price").inner_text()
        except Exception:
            continue
        dm = re.search(r"Güncellenme tarihi\s*:\s*(\d{2})\.(\d{2})\.(20\d{2})", text)
        list_date = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))) if dm else NOW.date()
        ym = re.search(r"Model Yılı\s*\n\s*(20\d{2})", text)
        year = int(ym.group(1)) if ym else NOW.year
        lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
        buffer = []
        i = 0
        while i < len(lines):
            if lines[i] == "Liste Fiyatı" and i + 1 < len(lines):
                lp = price(lines[i + 1])
                if lp and len(buffer) >= 4:
                    data = [x for x in buffer[-8:] if not re.fullmatch(r"20\d{2}", x)]
                    model = data[0]
                    package = data[1] if len(data) > 1 else ""
                    if re.search(r"Fiyat Listesi$", model, re.I) and package:
                        # The first card on each Mercedes page is preceded by the
                        # page title; the next token is the actual vehicle model.
                        model, package = package, "Standart"
                    fuel = next((x for x in data if x in ("Elektrik", "Benzin", "Dizel", "Hibrit")), "")
                    power = next((x for x in data if re.search(r"\bbg\b", x, re.I)), "")
                    transmission = next((x for x in data if re.search(r"DCT|G-TRONIC|Otomatik", x, re.I)), "")
                    out.append(record("Mercedes-Benz", model, package, lp, model_year=year, fuel=fuel,
                                      transmission=transmission, power=power, source_url=price_url,
                                      list_date=list_date))
                buffer = []
                i += 2
                continue
            if not lines[i].startswith(("CLA Fiyat", "Model Yılı", "Yazdır", "Paylaş", "İndir")):
                buffer.append(lines[i])
            i += 1
    out.extend(await collect_mercedes_commercial(page))
    return unique(out)


async def collect_mercedes_commercial(page) -> list[PriceRecord]:
    hrefs = []
    for slug in ("vito", "sprinter", "esprinter", "eqv", "v-serisi"):
        hub = f"https://htafiyat.mercedes-benz.com.tr/model/{slug}"
        await page.goto(hub, wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(2500)
        hrefs.extend(await page.locator('a[href*="/model/"][href*="/fiyat/2026"]').evaluate_all(
            "els => [...new Set(els.map(x => x.href))]"
        ))
    hrefs = list(dict.fromkeys(hrefs))
    out = []
    for url in hrefs:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            await page.locator("app-price").wait_for(timeout=30000)
            model = re.sub(r"\s+", " ", await page.locator("h1").first.inner_text()).strip()
            text = await page.locator("app-price").inner_text()
        except Exception:
            continue
        dm = re.search(r"Güncellenme tarihi\s*:\s*(\d{2})\.(\d{2})\.(20\d{2})", text)
        list_date = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))) if dm else NOW.date()
        lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
        for index, line in enumerate(lines):
            if line != "Satış Fiyatı" or index < 2 or index + 1 >= len(lines):
                continue
            lp = price(lines[index + 1])
            if not lp:
                continue
            variant = lines[index - 2]
            vehicle_type = lines[index - 1]
            campaign = None
            for campaign_index in range(index + 2, min(index + 8, len(lines) - 1)):
                if lines[campaign_index] == "Kampanyalı Satış Fiyatı (Peşin)":
                    campaign = price(lines[campaign_index + 1])
                    break
            if campaign is not None and campaign >= lp:
                campaign = None
            fuel = "Elektrik" if re.search(r"eSprinter|EQV", model + variant, re.I) else "Dizel"
            out.append(record("Mercedes-Benz", model, f"{variant} {vehicle_type}", lp, campaign,
                              model_year=2026, fuel=fuel, transmission="Otomatik",
                              source_url=url, list_date=list_date,
                              note="Resmî Mercedes-Benz Hafif Ticari güncel satış fiyatı"))
    if len(out) < 10:
        raise RuntimeError(f"Mercedes-Benz hafif ticari fiyat kapsamı eksik: {len(out)}/10; sayfa={len(hrefs)}; modeller={sorted({r.Model for r in out})}")
    return unique(out)


async def collect_browser_brand(page, brand: str) -> list[PriceRecord]:
    if brand == "Volvo": return await collect_volvo_with_secondary(page)
    if brand == "BMW": return await collect_bmw(page)
    if brand == "Honda": return await collect_honda(page)
    if brand == "Toyota": return await collect_toyota_browser(page)
    if brand == "Chery": return await collect_chery(page)
    if brand == "Peugeot": return await collect_peugeot(page)
    if brand in ("CUPRA", "SEAT"): return await collect_dogus_cards(page, brand)
    if brand == "Lexus": return await collect_lexus(page)
    if brand == "MG": return await collect_mg(page)
    if brand == "Alfa Romeo": return await collect_alfa_romeo(page)
    if brand == "DS": return await collect_ds(page)
    if brand == "Togg": return await collect_togg(page)
    if brand == "Tesla": return await collect_tesla(page)
    if brand == "KGM": return await collect_kgm(page)
    if brand == "Audi": return await collect_audi(page)
    if brand == "Mercedes-Benz": return await collect_mercedes(page)
    if brand == "Ford": return await collect_ford(page)
    if brand == "Kia": return await collect_kia(page)
    if brand == "MINI": return await collect_mini(page)
    if brand == "Volkswagen": return await collect_volkswagen(page)
    return await table_rows(page, brand)


async def collect_browser_tables() -> tuple[list[PriceRecord], dict[str, str]]:
    rows, errors = [], {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=os.environ.get("HEADED") != "1")
        context = await browser.new_context(locale="tr-TR", timezone_id="Europe/Istanbul",
                                            user_agent=HEADERS["User-Agent"])
        for brand in ("BYD", "Hyundai", "Nissan", "CUPRA", "Lexus", "Alfa Romeo", "DS", "MG", "SEAT", "BMW", "Honda", "Chery", "Peugeot", "Toyota", "Togg", "Tesla", "KGM", "Audi", "Mercedes-Benz", "Ford", "Kia", "MINI", "Volkswagen", "Volvo"):
            last_error = "fiyat tablosunda satır bulunamadı"
            for attempt in range(2):
                page = await context.new_page()
                try:
                    found = await collect_browser_brand(page, brand)
                    if not found:
                        raise RuntimeError("fiyat tablosunda satır bulunamadı")
                    # Sayfa kısmen yüklenmiş olabilir. Kapsamı ilk denemede
                    # doğrula ki eksik ama sıfır olmayan sonuç yeniden denensin.
                    coverage_errors = (
                        minimum_coverage_errors({brand: len(found)})
                        | minimum_model_errors(found)
                        | semantic_coverage_errors(found)
                    )
                    if brand in coverage_errors:
                        raise RuntimeError(coverage_errors[brand])
                    rows.extend(found)
                    errors.pop(brand, None)
                    break
                except Exception as exc:
                    last_error = str(exc)[:300]
                    try:
                        notice = source_update_notice(await page.locator("body").inner_text(timeout=5_000))
                        if notice:
                            last_error = f"{SOURCE_UPDATING_PREFIX} {notice}"
                    except Exception:
                        pass
                    if attempt == 1:
                        errors[brand] = last_error
                finally:
                    await page.close()
        await browser.close()
    return rows, errors


async def main() -> None:
    all_rows, errors = [], {}
    for brand, fn in (("Citroen", collect_citroen), ("Dacia", collect_dacia), ("Renault", collect_renault),
                      ("Fiat", collect_fiat), ("Opel", collect_opel),
                      ("Skoda", collect_skoda)):
        try:
            rows = fn()
            if not rows:
                raise RuntimeError("fiyat satırı bulunamadı")
            all_rows.extend(rows)
        except Exception as exc:
            errors[brand] = official_source_update_reason(brand) or str(exc)[:300]
    browser_rows, browser_errors = await collect_browser_tables()
    all_rows.extend(browser_rows)
    errors.update(browser_errors)
    all_rows = unique(all_rows)
    counts = {brand: sum(r.Marka == brand for r in all_rows) for brand in SOURCES}
    # Resmî sitede açıkça "fiyatlar güncelleniyor" denmişse bunu genel kapsam
    # hatasıyla ezme: e-posta alıcısı neden güncel veri gelmediğini görmeli.
    source_state_errors = {
        brand: reason for brand, reason in errors.items()
        if reason.startswith((SOURCE_UPDATING_PREFIX, SOURCE_ACCESS_PREFIX))
    }
    for brand_name, err in coverage_errors(all_rows, counts).items():
        errors.setdefault(brand_name, err)
    errors.update(source_state_errors)
    fallbacks = {}
    for brand, reason in list(errors.items()):
        previous, source_date = previous_verified_brand(brand)
        if not previous:
            continue
        all_rows = [row for row in all_rows if row.Marka != brand] + previous
        fallbacks[brand] = {"source_date": source_date, "reason": reason, "rows": len(previous)}
        errors.pop(brand, None)
    all_rows = unique(all_rows)
    counts = {brand: sum(r.Marka == brand for r in all_rows) for brand in SOURCES}
    # A known fallback may have fewer variants than today's guardrail. Keep it
    # visibly marked as stale instead of suppressing the entire Excel delivery.
    errors.update(coverage_errors(all_rows, counts, set(fallbacks)))
    for row in all_rows:
        row.validate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"records": [asdict(x) for x in all_rows], "errors": errors, "fallbacks": fallbacks}, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    print(json.dumps({"total": len(all_rows), "counts": counts, "fallbacks": fallbacks, "errors": errors}, ensure_ascii=False))
    if errors:
        raise RuntimeError("Eksik resmî marka bulundu: " + json.dumps(errors, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
