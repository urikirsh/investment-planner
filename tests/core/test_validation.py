from __future__ import annotations

"""
Validation and JSON round-trip tests for the domain layer.

These tests verify portfolio invariants and serialization behavior without
Qt/UI involvement.
"""

from decimal import Decimal
from typing import cast

import pytest

from portfolio_core.io_json import dump_portfolio, load_portfolio
from portfolio_core.models import AssetGroup, Cash, Exchange, Instrument, Portfolio
from portfolio_core.validation import validate_portfolio
from tests.core.helpers import make_valid_data


def test_validate_portfolio_happy_path():
    p = load_portfolio(make_valid_data())
    validate_portfolio(p)


def test_parse_succeeds_with_valid_exchange_values():
    data = make_valid_data(
        instruments=[
            {
                "id": "i1",
                "ticker": "AB12",
                "name": "Inst 1",
                "value": "6000",
                "exchange": "NYSE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i2",
                "ticker": "1234567",
                "name": "Inst 2",
                "value": "4000",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g2",
                "targetInGroupPercentage": "100",
            },
        ],
    )
    p = load_portfolio(data)
    assert p.instruments[0].exchange.value == "NYSE"
    assert p.instruments[1].exchange.value == "TASE"


def test_validation_cash_reserve_must_not_exceed_cash_value():
    p = load_portfolio(make_valid_data(cash_value="100", cash_reserve="101"))
    with pytest.raises(ValueError, match="cash.reserve must be <= cash.value"):
        validate_portfolio(p)


@pytest.mark.parametrize("cash_value", ["0", "-1"])
def test_validation_cash_value_must_be_positive(cash_value: str):
    p = load_portfolio(make_valid_data(cash_value=cash_value))
    with pytest.raises(ValueError, match="cash.value must be positive"):
        validate_portfolio(p)


def test_validation_cash_reserve_cannot_be_negative():
    p = load_portfolio(make_valid_data(cash_reserve="-0.01"))
    with pytest.raises(ValueError, match="cash.reserve cannot be negative"):
        validate_portfolio(p)


def test_validation_percentages_must_sum_to_100_exactly():
    p = load_portfolio(make_valid_data(group_targets=(("g1", "Asset 1", "60.0"), ("g2", "Asset 2", "39.9"))))
    with pytest.raises(ValueError, match="Sum of asset group target percentages must be exactly 100"):
        validate_portfolio(p)


def test_validation_future_tax_cannot_be_negative():
    p = load_portfolio(make_valid_data(cash_future_tax="-0.01"))
    with pytest.raises(ValueError, match="cash.future_tax cannot be negative"):
        validate_portfolio(p)


def test_json_round_trip_preserves_portfolio_structure_and_values():
    data = make_valid_data(
        cash_value="12345.67",
        cash_reserve="2345.67",
        cash_future_tax="123.45",
        group_targets=(("g1", "Asset 1", "55.5"), ("g2", "Asset 2", "44.5")),
        instruments=[
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst 1",
                "quantity": 12,
                "value": "6000.25",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "70",
            },
            {
                "id": "i2",
                "ticker": "AB12",
                "name": "Inst 2",
                "quantity": 0,
                "value": "2575.42",
                "exchange": "NYSE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "30",
            },
            {
                "id": "i3",
                "ticker": "2345678",
                "name": "Inst 3",
                "quantity": 4,
                "value": "3500.00",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g2",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i4",
                "ticker": "3456789",
                "name": "Parking",
                "quantity": 0,
                "value": "1000",
                "exchange": "TASE",
                "investable": False,
                "targetInGroupPercentage": "0",
            },
        ],
    )
    p1 = load_portfolio(data)
    dumped = dump_portfolio(p1)
    p2 = load_portfolio(dumped)

    assert p2 == p1
    assert dumped == {
        "cash": {"value": "12345.67", "min_reserve": "2345.67", "future_tax": "123.45"},
        "groups": [
            {"id": "g1", "name": "Asset 1", "targetPercentage": "55.5"},
            {"id": "g2", "name": "Asset 2", "targetPercentage": "44.5"},
        ],
        "instruments": [
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst 1",
                "quantity": 12,
                "value": "6000.25",
                "exchange": "TASE",
                "investable": True,
                "targetInGroupPercentage": "70",
                "groupId": "g1",
            },
            {
                "id": "i2",
                "ticker": "AB12",
                "name": "Inst 2",
                "quantity": 0,
                "value": "2575.42",
                "exchange": "NYSE",
                "investable": True,
                "targetInGroupPercentage": "30",
                "groupId": "g1",
            },
            {
                "id": "i3",
                "ticker": "2345678",
                "name": "Inst 3",
                "quantity": 4,
                "value": "3500.00",
                "exchange": "TASE",
                "investable": True,
                "targetInGroupPercentage": "100",
                "groupId": "g2",
            },
            {
                "id": "i4",
                "ticker": "3456789",
                "name": "Parking",
                "quantity": 0,
                "value": "1000",
                "exchange": "TASE",
                "investable": False,
                "targetInGroupPercentage": "0",
            },
        ],
    }


def test_parse_fails_when_quantity_is_missing() -> None:
    data = make_valid_data()
    data["instruments"][0].pop("quantity", None)
    with pytest.raises(ValueError, match=r"Missing required field 'instruments\[0\]\.quantity'"):
        load_portfolio(data)


def test_parse_rejects_string_quantity() -> None:
    data = make_valid_data()
    data["instruments"][0]["quantity"] = "12"
    with pytest.raises(ValueError, match=r"instruments\[0\]\.quantity"):
        load_portfolio(data)


def test_parse_rejects_negative_quantity_int() -> None:
    data = make_valid_data()
    data["instruments"][0]["quantity"] = -1
    with pytest.raises(ValueError, match=r"instruments\[0\]\.quantity"):
        load_portfolio(data)


def test_validation_rejects_invalid_negative_quantity() -> None:
    p = load_portfolio(make_valid_data())
    updated_instruments = list(p.instruments)
    updated_instruments[0] = Instrument(
        id=updated_instruments[0].id,
        ticker=updated_instruments[0].ticker,
        name=updated_instruments[0].name,
        value=updated_instruments[0].value,
        exchange=updated_instruments[0].exchange,
        investable=updated_instruments[0].investable,
        asset_group_id=updated_instruments[0].asset_group_id,
        target_in_group_pct=updated_instruments[0].target_in_group_pct,
        quantity=-1,
    )
    invalid = Portfolio(cash=p.cash, asset_groups=p.asset_groups, instruments=updated_instruments)
    with pytest.raises(ValueError, match="quantity must be a non-negative integer"):
        validate_portfolio(invalid)


def test_parse_fails_when_exchange_is_missing():
    data = make_valid_data(
        instruments=[
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst 1",
                "value": "6000",
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
        ],
    )
    data["instruments"][0].pop("exchange", None)
    with pytest.raises(ValueError, match=r"Missing required field 'instruments\[0\]\.exchange'"):
        load_portfolio(data)


def test_parse_fails_when_ticker_is_missing() -> None:
    data = make_valid_data()
    data["instruments"][0].pop("ticker", None)
    with pytest.raises(ValueError, match=r"Missing required field 'instruments\[0\]\.ticker'"):
        load_portfolio(data)


def test_parse_fails_when_exchange_is_invalid():
    data = make_valid_data(
        instruments=[
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Inst 1",
                "value": "6000",
                "exchange": "EUR",
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
        ],
    )
    with pytest.raises(ValueError, match=r"instruments\[0\]\.exchange"):
        load_portfolio(data)


def test_validation_rejects_invalid_tase_ticker_format() -> None:
    data = make_valid_data()
    data["instruments"][0]["exchange"] = "TASE"
    data["instruments"][0]["ticker"] = "12AB567"
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="ticker for TASE must be 6 or 7 digits"):
        validate_portfolio(p)


def test_validation_allows_6_digit_tase_ticker() -> None:
    data = make_valid_data()
    data["instruments"][0]["exchange"] = "TASE"
    data["instruments"][0]["ticker"] = "123456"
    p = load_portfolio(data)
    validate_portfolio(p)


def test_validation_allows_nyse_uppercase_alphanumeric_ticker() -> None:
    data = make_valid_data()
    data["instruments"][0]["exchange"] = "NYSE"
    data["instruments"][0]["ticker"] = "3DSB"
    p = load_portfolio(data)
    validate_portfolio(p)


@pytest.mark.parametrize("ticker", ["T", "BRK.B", "ABCDEFGHIJKLMN"])
def test_validation_allows_extended_nyse_ticker_shapes(ticker: str) -> None:
    data = make_valid_data()
    data["instruments"][0]["exchange"] = "NYSE"
    data["instruments"][0]["ticker"] = ticker
    p = load_portfolio(data)
    validate_portfolio(p)


@pytest.mark.parametrize("ticker", ["BRK..B", ".BRKB", "ABCDEFGHIJKLMNO"])
def test_validation_rejects_invalid_nyse_ticker_shapes(ticker: str) -> None:
    data = make_valid_data()
    data["instruments"][0]["exchange"] = "NYSE"
    data["instruments"][0]["ticker"] = ticker
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="ticker for NYSE must be 1 to 14 uppercase letters/digits, optionally one dot"):
        validate_portfolio(p)


def test_validation_value_cannot_be_negative():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "0", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "Inst 2", "value": "-4000", "investable": True, "groupId": "g2"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(ValueError, match="Instrument 'Inst 2' value cannot be negative"):
        validate_portfolio(p)


def test_validation_instrument_names_must_be_unique():
    instruments = [
        {"id": "i1", "name": "DUP", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "DUP", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(
        ValueError,
        match=r"Duplicate instrument name 'DUP' across multiple locations .*Rename one of them to a unique name",
    ):
        validate_portfolio(p)


def test_validation_instrument_names_duplicate_within_same_group_has_detailed_error():
    instruments = [
        {"id": "i1", "name": "DUP", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "DUP", "value": "4000", "investable": True, "groupId": "g1"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(
        ValueError,
        match=r"Duplicate instrument name 'DUP' in asset group 'Asset 1'.*Rename one of the instruments in this group",
    ):
        validate_portfolio(p)


def test_validation_investable_instrument_must_have_group():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True},
        {"id": "i2", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(ValueError, match="must have an assetGroupId/groupId"):
        validate_portfolio(p)


def test_validation_group_must_exist():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g3"},
        {"id": "i2", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(ValueError, match="Instrument 'Inst 1' references unknown asset group id 'g3'"):
        validate_portfolio(p)


def test_validation_non_investable_instrument_must_not_have_group():
    instruments = [
        {"id": "i1", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "i2", "name": "Parking", "value": "4000", "investable": False, "groupId": "g2"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(ValueError, match="Non-investable instrument .* must not have"):
        validate_portfolio(p)


def test_validation_requires_at_least_one_asset_group():
    data = make_valid_data(
        group_targets=(),
        instruments=[{"id": "i1", "name": "Parking", "value": "1000", "investable": False, "targetInGroupPercentage": "0"}],
    )
    p = load_portfolio(data)
    with pytest.raises(ValueError, match="At least one asset group is required"):
        validate_portfolio(p)


def test_validation_requires_at_least_one_instrument():
    p = load_portfolio(make_valid_data(instruments=[]))
    with pytest.raises(ValueError, match="At least one instrument is required"):
        validate_portfolio(p)


def test_validation_group_ids_must_be_unique():
    p = load_portfolio(make_valid_data(group_targets=(("dup", "Asset 1", "50"), ("dup", "Asset 2", "50"))))
    with pytest.raises(ValueError, match="Duplicate asset_group.id found"):
        validate_portfolio(p)


def test_validation_instrument_ids_must_be_unique():
    instruments = [
        {"id": "dup", "name": "Inst 1", "value": "6000", "investable": True, "groupId": "g1"},
        {"id": "dup", "name": "Inst 2", "value": "4000", "investable": True, "groupId": "g2"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(ValueError, match="Duplicate instrument.id found"):
        validate_portfolio(p)


def test_validation_instrument_names_duplicate_in_non_investable_bucket_has_detailed_error():
    instruments = [
        {"id": "i1", "name": "DUP", "value": "6000", "investable": False, "targetInGroupPercentage": "0"},
        {"id": "i2", "name": "DUP", "value": "4000", "investable": False, "targetInGroupPercentage": "0"},
    ]
    p = load_portfolio(make_valid_data(instruments=instruments))
    with pytest.raises(
        ValueError,
        match=r"Duplicate instrument name 'DUP' in the non-investable bucket.*Rename one of the instruments to a unique name",
    ):
        validate_portfolio(p)


def test_validation_rejects_non_enum_exchange() -> None:
    p = Portfolio(
        cash=Cash(value=Decimal("1000"), min_reserve=Decimal("0"), future_tax=Decimal("0")),
        asset_groups=[AssetGroup(id="g1", name="Asset 1", target_pct=Decimal("100"))],
        instruments=[
            Instrument(
                id="i1",
                ticker="1234567",
                name="Inst 1",
                value=Decimal("1000"),
                exchange=cast(Exchange, "EUR"),
                investable=True,
                asset_group_id="g1",
                target_in_group_pct=Decimal("100"),
            )
        ],
    )
    with pytest.raises(ValueError, match="exchange must be one of"):
        validate_portfolio(p)
