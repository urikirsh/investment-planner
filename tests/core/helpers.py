from __future__ import annotations

"""
Shared builders for core/domain tests.

This module centralizes fixture-like payload builders so core tests can
focus on behavior assertions instead of repeating portfolio JSON setup.
"""

from decimal import Decimal
from typing import Any

from portfolio_core.io_json import load_portfolio

D = Decimal


def make_valid_data(
    *,
    cash_value: str = "12000",
    cash_reserve: str = "2000",
    cash_future_tax: str = "0",
    group_targets: tuple[tuple[str, str, str], ...] = (("g1", "Asset 1", "60.0"), ("g2", "Asset 2", "40.0")),
    instruments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build a valid JSON-like portfolio payload for tests.

    Callers can override cash/group/instrument parts to target specific
    validation or planning scenarios while preserving required defaults.
    """
    if instruments is None:
        instruments = [
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst 1",
                "value": "6000",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i2",
                "ticker": "2345678",
                "name": "Inst 2",
                "value": "4000",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g2",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i3",
                "ticker": "3456789",
                "name": "Parking",
                "value": "1000",
                "exchange": "TASE",
                "investable": False,
                "targetInGroupPercentage": "0",
            },
        ]

    seen_by_group: dict[str, bool] = {}
    for ins in instruments:
        ins.setdefault("exchange", "TASE")
        exchange = str(ins["exchange"]).strip().upper()
        if exchange == "TASE":
            ins.setdefault("ticker", "1234567")
        elif exchange == "NYSE":
            ins.setdefault("ticker", "AB12")
        else:
            ins.setdefault("ticker", "UNKNOWN")
        ins.setdefault("quantity", 0)
        if "targetInGroupPercentage" in ins:
            continue
        if ins.get("investable") and ins.get("groupId"):
            gid = ins["groupId"]
            if gid not in seen_by_group:
                ins["targetInGroupPercentage"] = "100"
                seen_by_group[gid] = True
            else:
                ins["targetInGroupPercentage"] = "0"
        else:
            ins["targetInGroupPercentage"] = "0"

    groups = [{"id": gid, "name": name, "targetPercentage": pct} for gid, name, pct in group_targets]
    return {
        "cash": {"value": cash_value, "min_reserve": cash_reserve, "future_tax": cash_future_tax},
        "groups": groups,
        "instruments": instruments,
    }


def make_portfolio():
    """Build a compact one-group/one-instrument portfolio for stock-unit tests."""
    data = {
        "cash": {"value": "1000", "min_reserve": "100", "future_tax": "0"},
        "groups": [{"id": "g1", "name": "Asset", "targetPercentage": "100"}],
        "instruments": [
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst",
                "quantity": 0,
                "value": "500",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            }
        ],
    }
    return load_portfolio(data)
