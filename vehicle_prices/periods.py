import re
from datetime import date


PRICE_KEY = re.compile(r"^(liste|kampanya)_(\d{4})_(\d{2})$")


def available_periods(row: dict) -> list[tuple[int, int]]:
    periods = set()
    for key in row:
        match = PRICE_KEY.match(key)
        if match and 1 <= int(match.group(3)) <= 12:
            periods.add((int(match.group(2)), int(match.group(3))))
    return sorted(periods)


def choose_period(row: dict, today: date | None = None) -> tuple[int, int] | None:
    periods = available_periods(row)
    if not periods:
        return None
    reference = today or date.today()
    current = reference.year, reference.month
    eligible = [period for period in periods if period <= current]
    return eligible[-1] if eligible else periods[-1]


def price_for(row: dict, kind: str, today: date | None = None) -> int | None:
    period = choose_period(row, today)
    if period is None:
        return None
    value = row.get(f"{kind}_{period[0]:04d}_{period[1]:02d}")
    return int(value) if isinstance(value, (int, float)) and value > 0 else None
