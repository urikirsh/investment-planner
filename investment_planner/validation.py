from __future__ import annotations

from decimal import Decimal
from typing import Dict

from investment_planner.models import Portfolio

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


def validate_portfolio(p: Portfolio) -> None:
    _validate_cash(p)
    _validate_asset_groups(p)
    _validate_instruments(p)

def _validate_cash(p: Portfolio) -> None:
    if p.cash.value <= 0:
        raise ValueError("cash.value must be positive")
    if p.cash.min_reserve < 0:
        raise ValueError("cash.reserve cannot be negative")
    if p.cash.min_reserve > p.cash.value:
        raise ValueError("cash.reserve must be <= cash.value")

def _validate_asset_groups(p: Portfolio) -> None:
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
    if not p.instruments:
        raise ValueError("At least one instrument is required")

    ins_ids = [ins.id for ins in p.instruments]
    if any(not iid for iid in ins_ids):
        raise ValueError("All instruments must have a non-empty 'id'")
    if len(set(ins_ids)) != len(ins_ids):
        raise ValueError("Duplicate instrument.id found")

    ins_names = [ins.name for ins in p.instruments]
    if any(not n for n in ins_names):
        raise ValueError("All instruments must have a non-empty 'name'")
    if len(set(ins_names)) != len(ins_names):
        raise ValueError("Duplicate instrument.name found (names must be unique)")

    group_id_set = {g.id for g in p.asset_groups}
    group_pct_sum: Dict[str, D] = {g.id: D("0") for g in p.asset_groups}

    for ins in p.instruments:
        if ins.value < 0:
            raise ValueError(f"Instrument '{ins.name}' value cannot be negative")

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

    for g in p.asset_groups:
        pct_sum = group_pct_sum[g.id]
        if pct_sum != D("100"):
            raise ValueError(
                f"Sum of targetInGroupPercentage for group '{g.name}' must be exactly 100, got {pct_sum}"
            )
