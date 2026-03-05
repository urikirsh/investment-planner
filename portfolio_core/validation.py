from __future__ import annotations

from decimal import Decimal
from typing import Dict

from portfolio_core.models import Currency, Portfolio

"""
validation.py

Validation logic for ensuring portfolio and strategy correctness.

This module contains checks that verify the internal consistency of a
portfolio and its investment strategy, such as target allocation rules,
structural integrity, and reference validity. Validation is performed
before saving or executing an investment plan.

No UI, persistence, or calculation logic belongs in this module.
"""

D = Decimal


def _allowed_currency_values_text() -> str:
    """Return allowed currency codes as a comma-separated string."""
    return ", ".join(currency.value for currency in Currency)


def _format_instrument_location(p: Portfolio, idx: int, instrument_name: str, group_id: str | None) -> str:
    """
    Build a user-facing location label for duplicate-name error messages.

    The function intentionally hides positional/index details to keep
    validation messages stable and easy to read.
    """
    del idx  # index is intentionally hidden from user-facing messages
    del instrument_name
    group_by_id = {g.id: g.name for g in p.asset_groups}
    if group_id is None:
        return "non-investable bucket"
    group_name = group_by_id.get(group_id, "<unknown group>")
    return f"asset group '{group_name}'"


def validate_portfolio(p: Portfolio) -> None:
    """
    Run the full portfolio validation pipeline.

    Validation order:
    1. cash constraints
    2. asset-group constraints
    3. instrument constraints

    Raises
    ------
    ValueError
        On the first violated rule encountered.
    """
    _validate_cash(p)
    _validate_asset_groups(p)
    _validate_instruments(p)

def _validate_cash(p: Portfolio) -> None:
    """Validate cash-level numeric and relationship constraints."""
    if p.cash.value <= 0:
        raise ValueError("cash.value must be positive")
    if p.cash.min_reserve < 0:
        raise ValueError("cash.reserve cannot be negative")
    if p.cash.future_tax < 0:
        raise ValueError("cash.future_tax cannot be negative")
    if p.cash.min_reserve > p.cash.value:
        raise ValueError("cash.reserve must be <= cash.value")

def _validate_asset_groups(p: Portfolio) -> None:
    """
    Validate asset-group identity and target-allocation rules.

    Enforces that group targets are positive and sum exactly to 100.
    """
    if not p.asset_groups:
        raise ValueError("At least one asset group is required")

    group_ids = [g.id for g in p.asset_groups]
    if any(not gid for gid in group_ids):
        raise ValueError("All asset groups must have a non-empty 'id'")
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("Duplicate asset_group.id found")

    if any(not g.name for g in p.asset_groups):
        raise ValueError("All asset groups must have a non-empty 'name'")

    for g in p.asset_groups:
        if g.target_pct <= 0:
            raise ValueError(f"Asset group '{g.name}' targetPercentage must be positive")

    pct_sum = sum((g.target_pct for g in p.asset_groups), D("0"))
    if pct_sum != D("100"):
        raise ValueError(f"Sum of asset group target percentages must be exactly 100, got {pct_sum}")

def _validate_instruments(p: Portfolio) -> None:
    """
    Validate instrument set by delegating to focused helper checks.

    Includes identity, name uniqueness, value/range constraints, mapping
    consistency, and per-group in-group percentage totals.
    """
    if not p.instruments:
        raise ValueError("At least one instrument is required")

    _validate_instrument_identity(p)
    _validate_instrument_name_uniqueness(p)
    group_pct_sum = _validate_instrument_values_and_group_mapping(p)
    _validate_group_instrument_pct_sums(p, group_pct_sum)


def _validate_instrument_identity(p: Portfolio) -> None:
    """Validate that instrument ids are present and globally unique."""
    ins_ids = [ins.id for ins in p.instruments]
    if any(not iid for iid in ins_ids):
        raise ValueError("All instruments must have a non-empty 'id'")
    if len(set(ins_ids)) != len(ins_ids):
        raise ValueError("Duplicate instrument.id found")


def _validate_instrument_name_uniqueness(p: Portfolio) -> None:
    """
    Validate global uniqueness of instrument names with actionable messages.

    Error text includes human-readable location(s) to simplify correction in UI.
    """
    ins_names = [ins.name for ins in p.instruments]
    if any(not n for n in ins_names):
        raise ValueError("All instruments must have a non-empty 'name'")

    # Detect duplicate names and fail fast on the first duplicate for clear feedback.
    first_seen_index_by_name: Dict[str, int] = {}
    for idx, ins in enumerate(p.instruments):
        prior_idx = first_seen_index_by_name.get(ins.name)
        if prior_idx is None:
            first_seen_index_by_name[ins.name] = idx
            continue

        first_ins = p.instruments[prior_idx]
        first_loc = _format_instrument_location(p, prior_idx, first_ins.name, first_ins.asset_group_id)
        dup_loc = _format_instrument_location(p, idx, ins.name, ins.asset_group_id)

        if first_ins.asset_group_id == ins.asset_group_id:
            if ins.asset_group_id is None:
                raise ValueError(
                    f"Duplicate instrument name '{ins.name}' in the non-investable bucket. "
                    "Rename one of the instruments to a unique name."
                )
            raise ValueError(
                f"Duplicate instrument name '{ins.name}' in {dup_loc}. "
                "Rename one of the instruments in this group to a unique name."
            )

        raise ValueError(
            f"Duplicate instrument name '{ins.name}' across multiple locations "
            f"({first_loc} and {dup_loc}). Rename one of them to a unique name."
        )


def _validate_instrument_values_and_group_mapping(p: Portfolio) -> Dict[str, D]:
    """
    Validate per-instrument value/range/mapping rules and accumulate group pct sums.

    Returns
    -------
    dict[str, Decimal]
        Running sum of ``target_in_group_pct`` for each asset group.
    """
    group_id_set = {g.id for g in p.asset_groups}
    group_pct_sum: Dict[str, D] = {g.id: D("0") for g in p.asset_groups}

    for ins in p.instruments:
        if ins.value < 0:
            raise ValueError(f"Instrument '{ins.name}' value cannot be negative")

        if not isinstance(ins.currency, Currency):
            allowed = _allowed_currency_values_text()
            raise ValueError(f"Instrument '{ins.name}' currency must be one of {allowed}")

        if ins.target_in_group_pct < 0 or ins.target_in_group_pct > D("100"):
            raise ValueError(
                f"Instrument '{ins.name}' targetInGroupPercentage must be between 0 and 100"
            )

        if ins.investable:
            # investable instruments must belong to a group
            if not ins.asset_group_id:
                raise ValueError(f"Investable instrument '{ins.name}' must have an assetGroupId/groupId")
            if ins.asset_group_id not in group_id_set:
                raise ValueError(
                    f"Instrument '{ins.name}' references unknown asset group id '{ins.asset_group_id}'"
                )
            group_pct_sum[ins.asset_group_id] += ins.target_in_group_pct
        else:
            # non-investable instruments must not belong to a group
            if ins.asset_group_id is not None:
                raise ValueError(f"Non-investable instrument '{ins.name}' must not have assetGroupId/groupId")
            if ins.target_in_group_pct != D("0"):
                raise ValueError(
                    f"Non-investable instrument '{ins.name}' targetInGroupPercentage must be 0"
                )

    return group_pct_sum


def _validate_group_instrument_pct_sums(p: Portfolio, group_pct_sum: Dict[str, D]) -> None:
    """Validate that each group's instrument target percentages sum exactly to 100."""
    for g in p.asset_groups:
        pct_sum = group_pct_sum[g.id]
        if pct_sum != D("100"):
            raise ValueError(
                f"Sum of targetInGroupPercentage for group '{g.name}' must be exactly 100, got {pct_sum}"
            )
