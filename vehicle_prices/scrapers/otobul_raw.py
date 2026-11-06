import json
import re
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class OtoBulRawScraper:
    SOURCE_URL = "https://www.otobul.tr/araclar"
    TARGET_BRANDS = {
        "Audi", "BMW", "BYD", "Chery", "Citroen", "Dacia", "Fiat", "Ford",
        "Honda", "Hyundai", "KGM", "Kia", "Mercedes-Benz", "MINI", "Nissan",
        "Opel", "Peugeot", "Renault", "Skoda", "Tesla", "Togg", "Toyota",
        "Volkswagen", "Volvo",
    }

    def fetch(self) -> list[dict]:
        request = Request(self.SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=60) as response:
            page = response.read().decode("utf-8", errors="replace")
        return self.parse(page)

    def parse(self, page: str) -> list[dict]:
        chunks: list[str] = []
        pattern = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.DOTALL)
        for match in pattern.finditer(page):
            try:
                value = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if len(value) > 1 and isinstance(value[1], str):
                chunks.append(value[1])
        payloads = ["".join(chunks)]
        decoded_page = page
        for _ in range(3):
            decoded_page = decoded_page.replace('\\"', '"')
            payloads.append(decoded_page)

        decoder = json.JSONDecoder()
        vehicles: dict[int, dict] = {}
        decode_errors: list[str] = []
        for payload in payloads:
            for match in re.finditer(r'\{"id":\d+,"marka_id":', payload):
                try:
                    obj, _ = decoder.raw_decode(payload[match.start():])
                except json.JSONDecodeError as exc:
                    if len(decode_errors) < 3:
                        decode_errors.append(str(exc))
                    continue
                if not isinstance(obj, dict) or "model_adi" not in obj:
                    continue
                brand = self._brand_name(obj)
                if brand not in self.TARGET_BRANDS:
                    continue
                obj["_kaynak_url"] = self.SOURCE_URL
                obj["_kaynak_turu"] = "IKINCIL_KATALOG"
                obj["_cekilme_zamani"] = datetime.now(ZoneInfo("Europe/Istanbul")).isoformat()
                vehicles[int(obj["id"])] = obj
        if not vehicles:
            payload = payloads[0]
            starts = list(re.finditer(r'\{"id":\d+,"marka_id":', payload))
            for index, start in enumerate(starts):
                end = starts[index + 1].start() if index + 1 < len(starts) else len(payload)
                fragment = payload[start.start():end]
                model = self._string_field(fragment, "model_adi")
                brand = self._string_field(fragment, "marka_adi")
                if not model or brand not in self.TARGET_BRANDS:
                    continue
                vehicle_id = self._number_field(fragment, "id")
                obj = {
                    "id": vehicle_id,
                    "marka_adi": brand,
                    "model_adi": model,
                    "donanim_paketi": self._string_field(fragment, "donanim_paketi"),
                    "motor_gucu": self._string_field(fragment, "motor_gucu"),
                    "yakit_tipi": self._string_field(fragment, "yakit_tipi"),
                    "vites_tipi": self._string_field(fragment, "vites_tipi"),
                    "liste_2026_08": self._number_field(fragment, "liste_2026_08"),
                    "kampanya_2026_08": self._number_field(fragment, "kampanya_2026_08"),
                    "guncelleme_tarihi": self._string_field(fragment, "guncelleme_tarihi"),
                    "_ham_parca": fragment[:4000],
                    "_kaynak_url": self.SOURCE_URL,
                    "_kaynak_turu": "IKINCIL_KATALOG",
                    "_cekilme_zamani": datetime.now(ZoneInfo("Europe/Istanbul")).isoformat(),
                }
                if vehicle_id is not None:
                    vehicles[int(vehicle_id)] = obj
        if not vehicles:
            raise ValueError(
                "Gömülü veri çözülemedi: "
                f"next_push={page.count('self.__next_f.push')}, "
                f"escaped_model={page.count(r'\"model_adi\"')}, "
                f"plain_model={page.count(chr(34) + 'model_adi' + chr(34))}, "
                f"decoded_objects={[p.count(chr(123) + chr(34) + 'id' + chr(34)) for p in payloads]}, "
                f"chunks={len(chunks)}, errors={decode_errors}"
            )
        return list(vehicles.values())

    @staticmethod
    def _brand_name(obj: dict) -> str:
        for key in ("marka", "brands"):
            nested = obj.get(key)
            if isinstance(nested, dict):
                for name_key in ("marka_adi", "ad", "name"):
                    if nested.get(name_key):
                        return str(nested[name_key])
        return str(obj.get("marka_adi") or "")

    @staticmethod
    def _string_field(fragment: str, name: str) -> str:
        match = re.search(rf'"{re.escape(name)}":"([^"\\]*(?:\\.[^"\\]*)*)"', fragment)
        if not match:
            return ""
        return match.group(1).replace(r'\"', '"').replace(r'\\', '\\')

    @staticmethod
    def _number_field(fragment: str, name: str) -> int | None:
        match = re.search(rf'"{re.escape(name)}":(\d+|null)', fragment)
        return int(match.group(1)) if match and match.group(1) != "null" else None
