import json
from pathlib import Path
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any, Dict, Optional

from investment_planner.models import Cash, AssetGroup, Instrument, Portfolio

getcontext().prec = 28
D = Decimal


def _parse_decimal(value: Any, field: str) -> D:
    try:
        # Using str() preserves "exactness" of JSON numeric literals better than float()
        return D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Field '{field}' must be a number, got: {value!r}")


def load_portfolio(data: Dict[str, Any]) -> Portfolio:
    # Cash
    cash_raw = data.get("cash")
    if not isinstance(cash_raw, dict):
        raise ValueError("Missing or invalid 'cash' object")

    cash = Cash(
        amount=_parse_decimal(cash_raw.get("amount"), "cash.amount"),
        reserve=_parse_decimal(cash_raw.get("reserve"), "cash.reserve"),
    )

    # Asset groups
    groups_raw = data.get("groups") or data.get("assetGroups")
    if not isinstance(groups_raw, list):
        raise ValueError("Missing or invalid 'groups' list")

    asset_groups: list[AssetGroup] = []
    for i, g in enumerate(groups_raw):
        if not isinstance(g, dict):
            raise ValueError(f"groups[{i}] must be an object")

        asset_groups.append(
            AssetGroup(
                id=str(g.get("id", "")).strip(),
                name=str(g.get("name", "")).strip(),
                target_pct=_parse_decimal(g.get("targetPercentage"), f"groups[{i}].targetPercentage"),
                preferred_instrument_id=str(g.get("preferredInstrumentId", "")).strip(),
            )
        )

    # Instruments
    instruments_raw = data.get("instruments")
    if not isinstance(instruments_raw, list):
        raise ValueError("Missing or invalid 'instruments' list")

    instruments: list[Instrument] = []
    for i, ins in enumerate(instruments_raw):
        if not isinstance(ins, dict):
            raise ValueError(f"instruments[{i}] must be an object")

        asset_group_id: Optional[str] = ins.get("groupId", ins.get("assetGroupId", None))
        if asset_group_id is not None:
            asset_group_id = str(asset_group_id).strip() or None

        instruments.append(
            Instrument(
                id=str(ins.get("id", "")).strip(),
                name=str(ins.get("name", "")).strip(),
                amount=_parse_decimal(ins.get("amount"), f"instruments[{i}].amount"),
                investable=bool(ins.get("investable")),
                asset_group_id=asset_group_id,
            )
        )

    return Portfolio(cash=cash, asset_groups=asset_groups, instruments=instruments)


def load_portfolio_file(path: str | Path) -> Portfolio:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return load_portfolio(data)


def dump_portfolio(p: Portfolio) -> Dict[str, Any]:
    """
    Convert Portfolio back to a JSON-serializable dict.
    Uses the 'groups' key (not 'assetGroups') to keep it simple.
    """
    return {
        "cash": {
            "amount": str(p.cash.amount),
            "reserve": str(p.cash.reserve),
        },
        "groups": [
            {
                "id": g.id,
                "name": g.name,
                "targetPercentage": str(g.target_pct),
                "preferredInstrumentId": g.preferred_instrument_id,
            }
            for g in p.asset_groups
        ],
        "instruments": [
            {
                "id": ins.id,
                "name": ins.name,
                "amount": str(ins.amount),
                "investable": bool(ins.investable),
                **({"groupId": ins.asset_group_id} if ins.asset_group_id is not None else {}),
            }
            for ins in p.instruments
        ],
    }


def save_portfolio_file(p: Portfolio, path: str | Path) -> None:
    path = Path(path)
    data = dump_portfolio(p)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

