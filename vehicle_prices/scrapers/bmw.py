import re
import unicodedata
from datetime import date, datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html as lxml_html

from vehicle_prices.schema import PriceRecord


class BMWPriceScraper:
    """Borusan BMW yetkili satıcısındaki güncel azami fiyat listesini okur."""

    SOURCE_URL = "https://teknikoto.bmw.com.tr/fiyat-listesi"
    TIMEOUT_SECONDS = 45
    USER_AGENT = (
        "Mozilla/5.0 (compatible; WeeklyVehiclePriceTracker/1.0; "
        "+https://github.com/)"
    )

    def fetch(self) -> list[PriceRecord]:
        request = Request(self.SOURCE_URL, headers={"User-Agent": self.USER_AGENT})
        with urlopen(request, timeout=self.TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
        return self.parse(body)

    def parse(self, html: str) -> list[PriceRecord]:
        document = lxml_html.fromstring(html)
        full_text = self._clean(" ".join(document.itertext()))
        list_date = self._extract_list_date(full_text)
        captured_at = datetime.now(ZoneInfo("Europe/Istanbul")).replace(
            microsecond=0, tzinfo=None
        )
        records: list[PriceRecord] = []

        for table in document.xpath("//table"):
            headers = [self._clean(" ".join(cell.itertext())) for cell in table.xpath(".//th")]
            normalized = [self._normalize_header(value) for value in headers]
            if not self._is_price_table(normalized):
                continue

            indexes = self._column_indexes(normalized)
            last_model = ""
            for row in table.xpath(".//tr"):
                cells = row.xpath("./td|./th")
                values = [self._clean(" ".join(cell.itertext())) for cell in cells]
                if not values or len(values) <= indexes["price"]:
                    continue
                if any("azami anahtar teslim" in self._normalize_header(value) for value in values):
                    continue

                raw_price = values[indexes["price"]]
                price = self._parse_money(raw_price)
                if price is None:
                    continue

                model = self._clean_model(values[indexes["model"]])
                if model:
                    last_model = model
                model = model or last_model
                if not model:
                    continue

                record = PriceRecord(
                    Kayit_Tarihi=captured_at,
                    Liste_Tarihi=list_date,
                    Marka="BMW",
                    Model=model,
                    Versiyon_Paket=self._value(values, indexes.get("package")),
                    Model_Yili=list_date.year if list_date else captured_at.year,
                    Yakit_Tipi=self._value(values, indexes.get("fuel")),
                    Sanziman=self._value(values, indexes.get("transmission")),
                    Motor_Hacmi_CC=self._parse_engine_cc(
                        self._value(values, indexes.get("engine_cc"))
                    ),
                    Motor_Gucu_BG=self._value(values, indexes.get("power")),
                    Liste_Fiyati_TL=price,
                    Kampanyali_Fiyat_TL=None,
                    Para_Birimi="TL",
                    Kaynak_URL=self.SOURCE_URL,
                    Veri_Durumu="OK",
                    Aciklama="BMW Türkiye yetkili satıcısı azami anahtar teslim fiyat listesi",
                )
                record.validate()
                records.append(record)

        # Yetkili satıcı sayfası masaüstünde tabloyu div bileşenleriyle kuruyor.
        for detail in document.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' Detail ')]"):
            header_nodes = detail.xpath(
                ".//div[contains(concat(' ', normalize-space(@class), ' '), ' TableTittle ')]"
            )
            headers = [self._clean(" ".join(node.itertext())) for node in header_nodes]
            normalized = [self._normalize_header(value) for value in headers]
            if not self._is_price_table(normalized):
                continue
            indexes = self._column_indexes(normalized)
            last_model = ""
            rows = detail.xpath(
                "./div[contains(concat(' ', normalize-space(@class), ' '), ' DetailTable ')]"
            )
            for row in rows:
                cells = row.xpath(
                    "./div[contains(concat(' ', normalize-space(@class), ' '), ' tableWrap ')]"
                )
                values = [self._clean(" ".join(cell.xpath("./p//text()"))) for cell in cells]
                if not values or len(values) <= indexes["price"]:
                    continue
                price = self._parse_money(values[indexes["price"]])
                if price is None:
                    continue
                model = self._clean_model(values[indexes["model"]])
                if model:
                    last_model = model
                model = model or last_model
                if not model:
                    continue
                record = PriceRecord(
                    Kayit_Tarihi=captured_at,
                    Liste_Tarihi=list_date,
                    Marka="BMW",
                    Model=model,
                    Versiyon_Paket=self._value(values, indexes.get("package")),
                    Model_Yili=list_date.year if list_date else captured_at.year,
                    Yakit_Tipi=self._value(values, indexes.get("fuel")),
                    Sanziman=self._value(values, indexes.get("transmission")),
                    Motor_Hacmi_CC=self._parse_engine_cc(
                        self._value(values, indexes.get("engine_cc"))
                    ),
                    Motor_Gucu_BG=self._value(values, indexes.get("power")),
                    Liste_Fiyati_TL=price,
                    Kampanyali_Fiyat_TL=None,
                    Para_Birimi="TL",
                    Kaynak_URL=self.SOURCE_URL,
                    Veri_Durumu="OK",
                    Aciklama="BMW Türkiye yetkili satıcısı azami anahtar teslim fiyat listesi",
                )
                record.validate()
                records.append(record)

        return self._deduplicate(records)

    @staticmethod
    def _extract_list_date(text: str) -> date | None:
        match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+[İI]tibarıyla", text, re.IGNORECASE)
        if not match:
            return None
        day, month, year = map(int, match.groups())
        return date(year, month, day)

    @staticmethod
    def _normalize_header(value: str) -> str:
        value = value.casefold().replace("ı", "i")
        value = "".join(
            character
            for character in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(character)
        )
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def _is_price_table(cls, headers: list[str]) -> bool:
        joined = " | ".join(headers)
        return "model" in joined and "azami anahtar teslim" in joined

    @classmethod
    def _column_indexes(cls, headers: list[str]) -> dict[str, int]:
        aliases = {
            "model": ("model",),
            "package": ("tasarim paketi",),
            "transmission": ("sanziman",),
            "fuel": ("yakit tipi",),
            "engine_cc": ("motor hacmi",),
            "power": ("motor gucu",),
            "price": ("azami anahtar teslim",),
        }
        result: dict[str, int] = {}
        for key, candidates in aliases.items():
            for index, header in enumerate(headers):
                if any(candidate in header for candidate in candidates):
                    result[key] = index
                    break
        if "model" not in result or "price" not in result:
            raise ValueError("BMW tablosunun zorunlu kolonları bulunamadı")
        return result

    @staticmethod
    def _value(values: list[str], index: int | None) -> str:
        return values[index].strip() if index is not None and index < len(values) else ""

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def _clean_model(cls, value: str) -> str:
        value = re.sub(r"\b(?:Online rezerve edin|DONANIMI KEŞFEDİN)\b", "", value, flags=re.IGNORECASE)
        return cls._clean(value)

    @staticmethod
    def _parse_money(value: str) -> int | None:
        digits = re.sub(r"\D", "", value)
        if not digits:
            return None
        number = int(digits)
        return number if number >= 100_000 else None

    @staticmethod
    def _parse_integer(value: str) -> int | None:
        digits = re.sub(r"\D", "", value)
        return int(digits) if digits else None

    @classmethod
    def _parse_engine_cc(cls, value: str) -> int | None:
        number = cls._parse_integer(value)
        # BMW'nin bazı M/elektrikli satırlarında aynı konumda kW gücü bulunuyor.
        # 1.000 altındaki değerleri motor hacmi olarak kabul etmiyoruz.
        return number if number is not None and number >= 1_000 else None

    @staticmethod
    def _deduplicate(records: list[PriceRecord]) -> list[PriceRecord]:
        unique: dict[tuple[object, ...], PriceRecord] = {}
        for record in records:
            unique[record.dedupe_key()] = record
        return list(unique.values())
