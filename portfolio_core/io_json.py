import json
from pathlib import Path
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any, Dict, Mapping, Optional

from portfolio_core.domain.models import Cash, AssetGroup, Exchange, Instrument, Portfolio

"""
io_json.py

JSON input/output layer for portfolio persistence.

This module handles loading portfolio data from JSON into in-memory
domain models and serializing those models back to disk. It isolates
file I/O and basic structural validation from the rest of the system.

All monetary values are stored in ILS. No investment logic, calculations,
or UI behavior belongs in this module.
"""

getcontext().prec = 28
D = Decimal


def _parse_exchange(value: Any, field: str) -> Exchange:
    """Parse a required instrument exchange enum."""
    if value is None:
        raise ValueError(f"Missing required field '{field}'")
    try:
        return Exchange(str(value))
    except ValueError:
        raise ValueError(
            f"Field '{field}' must be one of {[exchange.value for exchange in Exchange]}, got: {value!r}"
        )


def _parse_decimal(value: Any, field: str) -> D:
    """
    Parse a value into ``Decimal`` and provide field-aware errors.

    Parameters
    ----------
    value:
        Raw JSON value (number/string/etc.) to parse.
    field:
        Human-readable field path used in error messages.

    Returns
    -------
    Decimal
        Parsed decimal value.

    Raises
    ------
    ValueError
        If ``value`` cannot be interpreted as a number.
    """
    try:
        # Using str() preserves "exactness" of JSON numeric literals better than float()
        return D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Field '{field}' must be a number, got: {value!r}")


def _parse_quantity(value: Any, field: str) -> int:
    """Parse instrument quantity as a required non-negative integer."""
    if value is None:
        raise ValueError(f"Missing required field '{field}'")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Field '{field}' must be a non-negative integer, got: {value!r}")
    if value < 0:
        raise ValueError(
            f"Field '{field}' must be a non-negative integer, got: {value!r}"
        )
    return int(value)


def _parse_required_text(value: Any, field: str) -> str:
    """Parse a required non-empty text field."""
    if value is None:
        raise ValueError(f"Missing required field '{field}'")
    parsed = str(value).strip()
    if not parsed:
        raise ValueError(f"Field '{field}' must be a non-empty string")
    return parsed


def load_portfolio(data: Mapping[str, Any]) -> Portfolio:
    """
    Parse a raw JSON-decoded mapping into a strongly-typed Portfolio model.

    Expects a mapping with:
    - "cash": object with "value", "min_reserve", and "future_tax"
      (all parsed as Decimal, in ILS)
    - "groups": list of asset group objects containing id, name, targetPercentage
    - "instruments": list of instrument objects containing id, ticker, name, value, investable,
      required "exchange" ("TASE"/"NYSE"), group reference ("groupId" or legacy "assetGroupId"), and required
      "targetInGroupPercentage"
    - required instrument "quantity" as a non-negative integer

    This function performs structural/type validation and raises ValueError with a
    precise path (e.g. "instruments[3].value") when a required field is missing or
    malformed. It does not perform strategy validation (e.g. target sums, ID uniqueness,
    in-group target sum checks); those checks belong to the validation layer.

    Parameters
    ----------
    data:
        A mapping produced by json.load()/json.loads().

    Returns
    -------
    Portfolio
        A Portfolio instance containing Cash, AssetGroup, and Instrument objects.

    Raises
    ------
    ValueError
        If required keys are missing, structural types are invalid, or numeric
        fields cannot be parsed.
    """

    # Cash
    cash_raw = data.get("cash")
    if not isinstance(cash_raw, dict):
        raise ValueError("Missing or invalid 'cash' object")

    cash = Cash(
        value=_parse_decimal(cash_raw.get("value"), "cash.value"),
        min_reserve=_parse_decimal(cash_raw.get("min_reserve"), "cash.reserve"),
        future_tax=_parse_decimal(cash_raw.get("future_tax"), "cash.future_tax"),
    )

    # Asset groups
    groups_raw = data.get("groups")
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
                ticker=_parse_required_text(ins.get("ticker"), f"instruments[{i}].ticker"),
                name=str(ins.get("name", "")).strip(),
                value=_parse_decimal(ins.get("value"), f"instruments[{i}].value"),
                exchange=_parse_exchange(ins.get("exchange"), f"instruments[{i}].exchange"),
                investable=bool(ins.get("investable")),
                asset_group_id=asset_group_id,
                target_in_group_pct=_parse_decimal(
                    ins.get("targetInGroupPercentage"),
                    f"instruments[{i}].targetInGroupPercentage",
                ),
                quantity=_parse_quantity(ins.get("quantity"), f"instruments[{i}].quantity"),
            )
        )

    return Portfolio(cash=cash, asset_groups=asset_groups, instruments=instruments)


def load_portfolio_file(path: str | Path) -> Portfolio:
    """
    Load a portfolio from a JSON file path.

    Parameters
    ----------
    path:
        Path-like location of the portfolio JSON file.

    Returns
    -------
    Portfolio
        Parsed portfolio model.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    OSError
        If the file cannot be opened/read due to OS-level errors.
    json.JSONDecodeError
        If file contents are not valid JSON.
    ValueError
        If JSON structure/types are invalid for portfolio parsing.
    """
    path = Path(path)
    # Accept optional UTF-8 BOM to support files saved by some Windows editors.
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return load_portfolio(data)


def dump_portfolio(p: Portfolio) -> Dict[str, Any]:
    """
    Convert a ``Portfolio`` into a JSON-serializable dictionary.

    Output schema notes
    -------------------
    - Uses ``groups`` as the asset-group key.
    - Decimal fields are serialized as strings to preserve precision.
    - Instrument ``quantity`` is serialized as required integer.
    - ``groupId`` is omitted for non-investable instruments.

    Parameters
    ----------
    p:
        Portfolio model to serialize.

    Returns
    -------
    dict[str, Any]
        JSON-ready dictionary suitable for ``json.dump``.
    """
    return {
        "cash": {
            "value": str(p.cash.value),
            "min_reserve": str(p.cash.min_reserve),
            "future_tax": str(p.cash.future_tax),
        },
        "groups": [
            {
                "id": g.id,
                "name": g.name,
                "targetPercentage": str(g.target_pct),
            }
            for g in p.asset_groups
        ],
        "instruments": [
            {
                "id": ins.id,
                "ticker": ins.ticker,
                "name": ins.name,
                "value": str(ins.value),
                "exchange": ins.exchange.value,
                "investable": bool(ins.investable),
                "targetInGroupPercentage": str(ins.target_in_group_pct),
                "quantity": ins.quantity,
                **({"groupId": ins.asset_group_id} if ins.asset_group_id is not None else {}),
            }
            for ins in p.instruments
        ],
    }


def save_portfolio_file(p: Portfolio, path: str | Path) -> None:
    """
    Serialize and write a portfolio JSON file to disk.

    The file is written with UTF-8 encoding, pretty-printed indentation,
    and a trailing newline to keep diffs stable.

    Parameters
    ----------
    p:
        Portfolio model to persist.
    path:
        Destination file path.

    Raises
    ------
    OSError
        If the destination cannot be opened/written.
    TypeError
        If the serialized structure contains non-JSON-serializable values.
    """
    path = Path(path)
    data = dump_portfolio(p)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
