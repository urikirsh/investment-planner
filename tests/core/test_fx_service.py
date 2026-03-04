from __future__ import annotations

import json
from datetime import datetime

from portfolio_core.fx_service import fetch_latest_usd_ils_rate


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)
        return None


def test_fetch_latest_usd_ils_rate_marks_last_published_when_date_is_before_today(monkeypatch) -> None:
    payload = {
        "exchangeRates": [
            {
                "key": "USD",
                "currentExchangeRate": "3.55",
                "lastUpdate": "2026-03-03T12:00:00Z",
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(
        "portfolio_core.fx_service.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(body),
    )

    quote = fetch_latest_usd_ils_rate(now=datetime.fromisoformat("2026-03-04T12:00:00+02:00"))

    assert str(quote.rate) == "3.55"
    assert str(quote.effective_date) == "2026-03-03"
    assert quote.used_last_published is True
    assert "Bank of Israel" in quote.source
