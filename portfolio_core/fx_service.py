from __future__ import annotations

"""
Bank of Israel FX service helpers.

This module provides a narrow boundary for fetching and parsing the latest
representative USD/ILS quote from the BOI public API.

Design notes
------------
- Keeps HTTP/parsing concerns out of UI and planning modules.
- Returns a typed quote object (`UsdIlsRateQuote`) for downstream use.
- Treats BOI's latest published quote as authoritative; callers can decide
  how to display "last published day" behavior in UX.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import urlopen
from zoneinfo import ZoneInfo


BOI_EXCHANGE_RATES_URL = "https://boi.org.il/PublicApi/GetExchangeRates"
BOI_SOURCE_LABEL = "Bank of Israel (representative)"
try:
    _JERUSALEM_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:
    # Fallback for environments without IANA tzdata (e.g., bare Windows Python).
    _JERUSALEM_TZ = timezone(timedelta(hours=2), name="UTC+02")


@dataclass(frozen=True)
class UsdIlsRateQuote:
    """USD/ILS quote fetched from the Bank of Israel public API."""

    rate: Decimal
    effective_date: date
    source: str
    used_last_published: bool


def _parse_last_update(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("BOI payload missing USD lastUpdate")
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid BOI lastUpdate value: {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_JERUSALEM_TZ)


def _parse_rate(raw: object) -> Decimal:
    try:
        rate = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid BOI USD rate value: {raw!r}") from exc
    if rate <= 0:
        raise ValueError(f"Invalid BOI USD rate value: {raw!r}")
    return rate


def fetch_latest_usd_ils_rate(*, timeout_seconds: float = 10.0, now: datetime | None = None) -> UsdIlsRateQuote:
    """
    Fetch latest BOI representative USD/ILS rate.

    If BOI has not published a rate for today (Israel time), the returned quote
    represents the latest published business-day rate.

    Parameters
    ----------
    timeout_seconds:
        HTTP timeout passed to `urlopen`.
    now:
        Optional injection point used by tests to control "today" comparison.

    Raises
    ------
    ValueError
        If BOI payload is missing expected fields or has invalid values.
    """

    with urlopen(BOI_EXCHANGE_RATES_URL, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))

    rates = payload.get("exchangeRates")
    if not isinstance(rates, list):
        raise ValueError("BOI payload missing exchangeRates")

    usd_entry: dict[str, object] | None = None
    for row in rates:
        if isinstance(row, dict) and row.get("key") == "USD":
            usd_entry = row
            break
    if usd_entry is None:
        raise ValueError("BOI payload missing USD rate")

    rate = _parse_rate(usd_entry.get("currentExchangeRate"))
    updated_at = _parse_last_update(usd_entry.get("lastUpdate"))
    effective_date = updated_at.date()

    now_local = (now or datetime.now(_JERUSALEM_TZ)).astimezone(_JERUSALEM_TZ)
    used_last_published = effective_date < now_local.date()

    return UsdIlsRateQuote(
        rate=rate,
        effective_date=effective_date,
        source=BOI_SOURCE_LABEL,
        used_last_published=used_last_published,
    )
