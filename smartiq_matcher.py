from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG = ROOT / "data" / "catalog" / "smartiq_catalog.json"
NOISE_WORDS = {
    "yeni", "new", "suv", "model", "motor", "elektrikli", "electric",
    "otomatik", "automatic", "manuel", "manual", "hybrid", "hibrit", "ehev",
}
MODEL_BODY_WORDS = {
    "yeni", "new", "suv", "sedan", "avant", "sportback", "allstreet",
    "coupe", "cabrio", "touring", "estate", "van", "kamyonet", "minibus",
    "elektrik", "elektrikli", "hybrid", "hibrit", "black", "edition",
}
DRIVE_GROUPS = {
    "awd": {"awd", "4x4", "dortceker"},
    "rwd": {"rwd", "arkadancekis", "arkadan"},
}


def normalize(value: object) -> str:
    text = str(value or "")
    # Bazı resmi sayfalarda Türkçe karakterler U+FFFD olarak geliyor. Yalnız
    # anlamı bağlamdan kesin olan kalıpları onar; belirsiz karakteri tahmin etme.
    repairs = {
        "D�rt": "Dort", "d�rt": "dort", "�eki�": "cekis", "�eker": "ceker",
        "YEN�": "YENI", "Yeni �koda": "Yeni Skoda", "�koda": "Skoda",
        "Coup�": "Coupe", "ELEKTR�KL�": "ELEKTRIKLI",
    }
    for broken, fixed in repairs.items():
        text = text.replace(broken, fixed)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("ı", "i")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def model_key(value: object) -> str:
    return " ".join(token for token in normalize(value).split() if token not in NOISE_WORDS)


def canonical_model(value: object, brand: object = "") -> str:
    """Map official display names to the catalog's model-family convention.

    Only deterministic naming differences are handled here. New/unknown models
    deliberately remain unmatched instead of being forced to a nearby family.
    """
    brand_name = normalize(brand)
    brand_tokens = set(brand_name.split())
    tokens = [x for x in normalize(value).split() if x not in brand_tokens]
    text = " ".join(tokens)

    if brand_name == "bmw":
        compact = text.replace(" ", "")
        found = re.search(r"\b(ix[1-9]|i[457x]|x[1-9]|m[2-8]|[1-8][0-9]{2}[a-z]?)\b", text)
        code = found.group(1) if found else compact
        if code.startswith("ix") or re.fullmatch(r"i(?:4|5|7|x)", code):
            return "i serisi"
        if code.startswith("m") or " competition" in text:
            return "m serisi"
        if code.startswith("x"):
            return code[:2]
        if code and code[0].isdigit():
            return f"{code[0]} serisi"

    if brand_name == "mercedes benz":
        if "maybach" in text:
            return "maybach"
        cleaned = re.sub(r"^mercedes\s+(amg\s+)?", "", text)
        for family in ("amg gt", "eqa", "eqb", "eqe", "eqs", "eqv", "cla", "cle", "gla", "glb", "glc", "gle", "gls", "sprinter", "vito", "v class", "sl"):
            if re.search(rf"\b{re.escape(family)}\b", cleaned):
                return family
        first = cleaned.split()[0] if cleaned.split() else ""
        if first in {"a", "b", "c", "e", "g", "s"}:
            return first

    if brand_name == "audi":
        compact = text.replace(" ", "")
        if "etrongt" in compact:
            return "e tron gt"
        found = re.search(r"\b([aq][2-8])\b", text)
        if found:
            code = found.group(1)
            return f"{code} e tron" if "e tron" in text else code

    cleaned = [x for x in tokens if x not in MODEL_BODY_WORDS]
    compact = "".join(cleaned)
    # e-C4/eC4 and similar electric display prefixes are not part of the
    # catalog family name; fuel compatibility is checked separately.
    if (
        brand_name in {"citroen", "peugeot", "fiat", "opel"}
        and compact.startswith("e")
        and any(char.isdigit() for char in compact[1:])
    ):
        compact = compact[1:]
    aliases = {
        "n4": "no4", "mg7excellence": "mg7",
    }
    return aliases.get(compact, compact)


def similarity(left: object, right: object) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    a_tokens, b_tokens = set(a.split()), set(b.split())
    overlap = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
    # Resmi fiyat listeleri motor/yakıt bilgisini versiyona ekleyebilir; katalog
    # aynı bilgiyi daha kısa yazdığında kapsama oranı karakter oranından daha
    # açıklayıcıdır.
    return max(sequence, overlap)


def same_model_family(left: object, right: object, brand: object = "") -> bool:
    a, b = canonical_model(left, brand), canonical_model(right, brand)
    if not a or not b:
        return False
    # Exact compact equality handles punctuation/spacing variants (C4 X/C4X,
    # e-C3/eC3) without allowing a shorter family such as C4 to match C4 X.
    return a.replace(" ", "") == b.replace(" ", "")


def _classify(text: object, groups: dict[str, set[str]]) -> str | None:
    value = normalize(text)
    compact = value.replace(" ", "")
    for label, markers in groups.items():
        if any(marker in value.split() or marker in compact for marker in markers):
            return label
    return None


def _fuel_classify(text: object, groups: dict[str, set[str]]) -> str | None:
    value = normalize(text)
    words = set(value.split())
    if ({"elektrik", "electric"} & words) and ({"benzin", "petrol"} & words):
        return "hybrid"
    return _classify(text, groups)


def compatible(target: object, candidate: dict) -> bool:
    target_text = SmartIQMatcher._version_text(target)
    candidate_text = " ".join(str(candidate.get(key) or "") for key in ("Versiyon", "Yakit_Tipi", "Sanziman"))
    fuel_groups = {
        "electric": {"elektrik", "electric", "elettrica"},
        "hybrid": {"hybrid", "hibrit", "mhev", "phev", "ehev", "ibrida"},
        "diesel": {"dizel", "diesel", "bluehdi", "multijet", "tdci"},
        "petrol": {"benzin", "petrol"},
    }
    gear_groups = {
        "manual": {"manuel", "manual", "mt5", "mt6"},
        "automatic": {"otomatik", "automatic", "dct", "dsg", "edc", "cvt", "tronic"},
    }
    for groups in (fuel_groups, gear_groups, DRIVE_GROUPS):
        classifier = _fuel_classify if groups is fuel_groups else _classify
        left, right = classifier(target_text, groups), classifier(candidate_text, groups)
        if left and right and left != right:
            return False
    return True


@dataclass(frozen=True)
class MatchResult:
    smartiq_id: int | None
    tsb_kodu: int | str | None
    status: str
    score: float


class SmartIQMatcher:
    def __init__(self, catalog_path: Path = DEFAULT_CATALOG):
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.records = payload.get("records", [])
        self.by_brand: dict[str, list[dict]] = {}
        for row in self.records:
            self.by_brand.setdefault(normalize(row.get("Marka")), []).append(row)

    @staticmethod
    def _version_text(row: object) -> str:
        values = [
            getattr(row, "Versiyon_Paket", ""), getattr(row, "Yakit_Tipi", ""),
            getattr(row, "Sanziman", ""), getattr(row, "Motor_Hacmi_CC", ""),
            getattr(row, "Motor_Gucu_BG", ""),
        ]
        return " ".join(str(value) for value in values if value not in (None, ""))

    def match(self, price_record: object) -> MatchResult:
        candidates = list(self.by_brand.get(normalize(getattr(price_record, "Marka", "")), []))
        year = getattr(price_record, "Model_Yili", None)
        if year is not None:
            candidates = [row for row in candidates if row.get("Model_Yili") == year]
        if not candidates:
            return MatchResult(None, None, "ESLESMEDI", 0.0)

        target_drive = _classify(self._version_text(price_record), DRIVE_GROUPS)
        if target_drive == "awd":
            driven = [row for row in candidates if _classify(row.get("Versiyon"), DRIVE_GROUPS) == "awd"]
            candidates = driven or candidates
        elif target_drive == "rwd":
            candidates = [row for row in candidates if _classify(row.get("Versiyon"), DRIVE_GROUPS) != "awd"]

        target_model = model_key(getattr(price_record, "Model", ""))
        target_version = self._version_text(price_record)
        ranked = []
        for candidate in candidates:
            if not same_model_family(target_model, candidate.get("Model"), getattr(price_record, "Marka", "")):
                continue
            if not compatible(price_record, candidate):
                continue
            m_score = similarity(
                canonical_model(target_model, getattr(price_record, "Marka", "")),
                canonical_model(candidate.get("Model"), getattr(price_record, "Marka", "")),
            )
            v_score = similarity(target_version, candidate.get("Versiyon"))
            total = 0.58 * m_score + 0.42 * v_score
            ranked.append((total, m_score, v_score, candidate))
        if not ranked:
            return MatchResult(None, None, "KONTROL_GEREKLI", 0.0)
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        best = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best[0] - second_score
        # Katalogda aynı teknik aracın gövde açıklaması gibi fiyat listesinde
        # bulunmayan alanlarla çoğaltılmış satırları olabilir. İlk iki aday aynı
        # TSB'yi taşıyorsa bu gerçek bir kimlik çakışması değildir.
        same_tsb = (
            len(ranked) > 1
            and best[3].get("TSB_Kodu") not in (None, "")
            and best[3].get("TSB_Kodu") == ranked[1][3].get("TSB_Kodu")
        )

        # Kimlik ancak model kuvvetli, toplam puan yeterli ve en iyi aday
        # alternatifinden belirgin biçimde ayrışıyorsa atanır.
        if best[1] < 0.78 or best[0] < 0.70 or (margin < 0.035 and not same_tsb):
            return MatchResult(None, None, "KONTROL_GEREKLI", round(best[0], 4))
        row = best[3]
        return MatchResult(row.get("SmartiqId"), row.get("TSB_Kodu"), "ESLESTI", round(best[0], 4))
