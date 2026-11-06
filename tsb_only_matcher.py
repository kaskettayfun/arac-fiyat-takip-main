from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re

from smartiq_matcher import normalize


ROOT = Path(__file__).resolve().parent
DEFAULT_MAPPINGS = ROOT / "data" / "catalog" / "confirmed_tsb_only_mappings.json"
NO_TSB_STATUS = "TSB_KATALOGUNDA_YOK"


@dataclass(frozen=True)
class TSBMatch:
    tsb_kodu: int | None
    status: str
    model: str
    model_yili: int | None


def canonical_identity(record) -> tuple[str, int | None]:
    model = record.Model
    year = record.Model_Yili
    if record.Marka in {"Nissan", "BYD"} and year is None:
        year = datetime.now().year
    if record.Marka == "Nissan" and (
        re.search(r"\bL[12]\b", record.Versiyon_Paket, re.I)
        or re.match(r"^EV\s+(?:Designpack|Platinum)", record.Versiyon_Paket, re.I)
    ):
        model = "Townstar"
    return model, year


def canonical_version(model: str, version: str) -> str:
    """Excel'deki `Model - Versiyon` ile kaynaktaki ham versiyonu aynı kimliğe indirger."""
    model_key = normalize(model)
    version_key = normalize(version)
    if model_key and version_key.startswith(model_key):
        version_key = version_key[len(model_key):].strip()
    return version_key


class TSBOnlyMatcher:
    def __init__(self, mapping_path: Path = DEFAULT_MAPPINGS):
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        self.by_key = {}
        self.by_identity = {}
        for row in payload.get("records", []):
            if row.get("Karar") != "KESİN":
                continue
            key = (
                normalize(row["Marka"]), normalize(row["Model"]), canonical_version(row["Model"], row["Versiyon"]),
                row["Model_Yili"], row.get("Kaynak_URL", ""),
            )
            if key in self.by_key:
                raise RuntimeError(f"Mükerrer TSB eşleşme anahtarı: {key}")
            self.by_key[key] = int(row["TSB_Kodu"])
            identity = key[:4]
            previous = self.by_identity.get(identity)
            if previous is not None and previous != int(row["TSB_Kodu"]):
                raise RuntimeError(f"Çelişkili TSB eşleşme kimliği: {identity}")
            self.by_identity[identity] = int(row["TSB_Kodu"])

    def match(self, record) -> TSBMatch:
        model, year = canonical_identity(record)
        key = (normalize(record.Marka), normalize(model), canonical_version(model, record.Versiyon_Paket), year, record.Kaynak_URL)
        tsb = self.by_key.get(key) or self.by_identity.get(key[:4])
        return TSBMatch(tsb, "KESİN" if tsb else NO_TSB_STATUS, model, year)
