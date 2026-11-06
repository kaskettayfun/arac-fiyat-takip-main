"""Compare two verified exports without treating fallback prices as new observations."""
from __future__ import annotations

from smartiq_matcher import normalize
from tsb_only_matcher import NO_TSB_STATUS, canonical_version


def identity(row: list | tuple) -> tuple:
    return (normalize(row[1]), normalize(row[2]), canonical_version(str(row[2]), str(row[3])), row[4])


def label(row: list | tuple) -> str:
    version = str(row[3] or "").strip()
    model = str(row[2] or "").strip()
    if normalize(version).startswith(normalize(model) + " "):
        return f"{row[1]} {version} ({row[4]})"
    return f"{row[1]} {model} {version} ({row[4]})".strip()


def compare(previous: list, current: list, fallback_brands: set[str]) -> dict:
    def index(rows):
        result, duplicates = {}, set()
        for row in rows:
            key = identity(row)
            if key in result:
                duplicates.add(key)
            else:
                result[key] = row
        for key in duplicates:
            result.pop(key, None)
        return result, duplicates

    old, old_duplicates = index(previous)
    new, new_duplicates = index(current)
    ambiguous = old_duplicates | new_duplicates
    excluded_brands = {normalize(brand) for brand in fallback_brands}
    comparable = lambda key: key not in ambiguous and key[0] not in excluded_brands
    common = {key for key in old.keys() & new.keys() if comparable(key)}
    changes = []
    campaigns_entered = campaigns_exited = 0
    tsb_changes = []
    for key in common:
        before, after = old[key], new[key]
        if isinstance(before[5], (int, float)) and isinstance(after[5], (int, float)) and before[5] > 0 and after[5] > 0 and before[5] != after[5]:
            delta = int(after[5] - before[5])
            changes.append((abs(delta / before[5]), label(after), int(before[5]), int(after[5]), delta))
        campaigns_entered += int(before[6] is None and after[6] is not None)
        campaigns_exited += int(before[6] is not None and after[6] is None)
        if len(before) > 8 and len(after) > 8 and before[7] != after[7]:
            tsb_changes.append((label(after), before[7], after[7]))
    added = sorted(label(new[key]) for key in new.keys() - old.keys() if comparable(key))
    removed = sorted(label(old[key]) for key in old.keys() - new.keys() if comparable(key))
    old_missing = {key for key, row in old.items() if len(row) > 8 and row[8] == NO_TSB_STATUS}
    new_missing = {key for key, row in new.items() if len(row) > 8 and row[8] == NO_TSB_STATUS}
    newly_missing = sorted(label(new[key]) for key in new_missing - old_missing if comparable(key))
    return {
        "price_changes": sorted(changes, reverse=True),
        "tsb_changes": sorted(tsb_changes),
        "new_versions": added, "removed_versions": removed,
        "campaigns_entered": campaigns_entered, "campaigns_exited": campaigns_exited,
        "newly_missing_tsb": newly_missing, "total_missing_tsb": len(new_missing),
        "excluded_fallback_brands": sorted(fallback_brands), "ambiguous_keys": len(ambiguous),
    }
