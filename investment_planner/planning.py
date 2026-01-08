from __future__ import annotations

from decimal import Decimal, getcontext
from typing import Dict, List

from investment_planner.models import Portfolio, AssetGroupPlanRow
from investment_planner.validation import validate_portfolio

getcontext().prec = 28
D = Decimal


def compute_invest_budget(p: Portfolio) -> D:
    """
    Cash is excluded from thev strategy universe.
    Budget is simply cash.value - cash.reserve, floored at 0.
    """
    budget = p.cash.value - p.cash.reserve
    return budget if budget > 0 else D("0")


def _asset_group_current_values(p: Portfolio) -> Dict[str, D]:
    """
    Current exposure per asset group = sum(value) of investable instruments in that group.
    """
    cur: Dict[str, D] = {g.id: D("0") for g in p.asset_groups}
    for ins in p.instruments:
        if ins.investable and ins.asset_group_id:
            cur[ins.asset_group_id] += ins.value
    return cur


def plan_invest_no_sell(p: Portfolio) -> List[AssetGroupPlanRow]:
    """
    No selling allowed.

    If some asset groups are overweight (negative delta), they are excluded,
    and their target percentages are redistributed among remaining groups.
    Preserves asset group order.
    """
    validate_portfolio(p)
    budget = compute_invest_budget(p)
    if budget == 0:
        return []

    cur = _asset_group_current_values(p)

    active_ids = [g.id for g in p.asset_groups]
    active_pct = {g.id: g.target_pct for g in p.asset_groups}

    while True:
        pct_total = sum((active_pct[gid] for gid in active_ids), D("0"))
        if pct_total <= 0:
            return []

        sum_active_current = sum((cur[gid] for gid in active_ids), D("0"))
        active_total_after = sum_active_current + budget

        deltas: Dict[str, D] = {}
        negative_ids: List[str] = []

        for gid in active_ids:
            wanted = (active_total_after * active_pct[gid]) / pct_total
            delta = wanted - cur[gid]
            deltas[gid] = delta
            if delta < 0:
                negative_ids.append(gid)

        if not negative_ids:
            rows: List[AssetGroupPlanRow] = []
            for g in p.asset_groups:
                if g.id in active_ids:
                    dmoney = deltas[g.id]
                    if dmoney < 0:
                        dmoney = D("0")
                    rows.append(
                        AssetGroupPlanRow(
                            asset_group_id=g.id,
                            asset_group_name=g.name,
                            target_pct=g.target_pct,
                            current_value=cur[g.id],
                            planned_delta_money=dmoney,
                            preferred_instrument_id=g.preferred_instrument_id,
                        )
                    )
            return rows

        neg_set = set(negative_ids)
        active_ids = [gid for gid in active_ids if gid not in neg_set]


def plan_rebalance(p: Portfolio) -> List[AssetGroupPlanRow]:
    """
    Selling allowed.

    Compute deltas directly against the original 100% targets across all asset groups.
    Positive=buy, Negative=sell. Preserves asset group order.
    """
    validate_portfolio(p)
    budget = compute_invest_budget(p)

    cur = _asset_group_current_values(p)
    current_total = sum((cur[g.id] for g in p.asset_groups), D("0"))
    total_after = current_total + budget

    rows: List[AssetGroupPlanRow] = []
    for g in p.asset_groups:
        wanted = (total_after * g.target_pct) / D("100")
        delta = wanted - cur[g.id]
        rows.append(
            AssetGroupPlanRow(
                asset_group_id=g.id,
                asset_group_name=g.name,
                target_pct=g.target_pct,
                current_value=cur[g.id],
                planned_delta_money=delta,
                preferred_instrument_id=g.preferred_instrument_id,
            )
        )
    return rows


def map_asset_group_buys_to_instruments(plan: List[AssetGroupPlanRow]) -> Dict[str, D]:
    """
    Map positive asset-group deltas to the preferred instrument (buys only).
    Sells remain at the asset-group level (you'll decide later how to sell across instruments).
    """
    instrument_buys: Dict[str, D] = {}
    for row in plan:
        if row.planned_delta_money > 0:
            instrument_buys[row.preferred_instrument_id] = (
                instrument_buys.get(row.preferred_instrument_id, D("0")) + row.planned_delta_money
            )
    return instrument_buys