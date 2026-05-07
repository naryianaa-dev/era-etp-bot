"""Валидация пользовательского ввода."""

from __future__ import annotations

import re
from datetime import date

import validators as _v


CURRENT_YEAR = date.today().year
_INT_RE = re.compile(r"[^\d]")


def parse_int(text: str) -> int | None:
    """Выдернуть целое число из строки. Принимает '12 500', '12,500', '12500km' и т.п."""
    if text is None:
        return None
    cleaned = _INT_RE.sub("", text)
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_year(text: str) -> int | None:
    n = parse_int(text)
    if n is None:
        return None
    # разумные рамки: 1950..текущий+1
    if 1950 <= n <= CURRENT_YEAR + 1:
        return n
    return None


def parse_mileage(text: str) -> int | None:
    n = parse_int(text)
    if n is None:
        return None
    if 0 <= n <= 2_000_000:
        return n
    return None


def parse_money_usd(text: str) -> int | None:
    n = parse_int(text)
    if n is None:
        return None
    if 1 <= n <= 10_000_000:
        return n
    return None


def is_valid_url(text: str) -> bool:
    if not text:
        return False
    # validators возвращает bool | ValidationError
    return bool(_v.url(text.strip()))


_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$", re.IGNORECASE)


def is_valid_vin(text: str) -> bool:
    if not text:
        return False
    return bool(_VIN_RE.match(text.strip().replace(" ", "")))
