from __future__ import annotations

from decimal import Decimal, getcontext
from typing import Dict, List

from portfolio_core.domain.models import AssetGroupPlanRow, Instrument, Portfolio
from portfolio_core.domain.validation import validate_portfolio

"""
planning.py

Investment planning logic for translating a target allocation strategy
into concrete buy and sell decisions.

This module computes how each asset group should change in value in order
to move the portfolio toward its target percentages, based on current
holdings and available funds. It produces planning results that are later
consumed by the execution and UI layers.

No persistence or UI logic belongs in this module.
"""

getcontext().prec = 28
D = Decimal


def compute_invest_budget(p: Portfolio) -> D:
    """
    Compute investable cash budget for planning.

    Formula
    -------
    ``cash.value - cash.min_reserve - cash.future_tax``, floored at ``0``.

    Returns
    -------
    Decimal
        Non-negative amount available for strategy allocation.
    """
    budget = p.cash.value - p.cash.min_reserve - p.cash.future_tax
    return budget if budget > 0 else D("0")


def _asset_group_current_values(p: Portfolio) -> Dict[str, D]:
    """
    Aggregate current investable exposure per asset group.

    Returns
    -------
    dict[str, Decimal]
        Mapping of ``asset_group_id -> current value`` including all investable
        instruments assigned to that group.
    """
    cur: Dict[str, D] = {g.id: D("0") for g in p.asset_groups}
    for ins in p.instruments:
        if ins.investable and ins.asset_group_id:
            cur[ins.asset_group_id] += ins.value
    return cur


def plan_invest_no_sell(p: Portfolio) -> List[AssetGroupPlanRow]:
    """
    No selling allowed.

    If some asset groups are overweight (negative delta), they are excluded
    from the active set and target percentages are re-normalized among the
    remaining groups. This repeats until all active groups have non-negative
    deltas.

    Returns
    -------
    list[AssetGroupPlanRow]
        Planned non-negative buy deltas by group, preserving original
        ``p.asset_groups`` order.
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
                        )
                    )
            return rows

        neg_set = set(negative_ids)
        active_ids = [gid for gid in active_ids if gid not in neg_set]


def plan_rebalance(p: Portfolio) -> List[AssetGroupPlanRow]:
    """
    Selling allowed.

    Compute deltas directly against original group targets across all groups.

    Returns
    -------
    list[AssetGroupPlanRow]
        Per-group deltas where positive means buy and negative means sell.
        Output order follows ``p.asset_groups``.
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
            )
        )
    return rows


def map_asset_group_deltas_to_instruments(
    p: Portfolio, plan: List[AssetGroupPlanRow]
) -> List[tuple[str, str, str, D]]:
    """
    Split each planned asset-group delta into per-instrument deltas.

    The split targets desired post-investment in-group percentages
    (``target_in_group_pct``), while preserving no-sell behavior for positive
    group deltas.

    Important behavior:
    - Only instruments with target_in_group_pct > 0 are considered.
    - For positive group deltas (buying), we do not force sells inside the group.
      Overweight instruments can be frozen at delta=0, while the remaining active
      instruments absorb the buy amount.
    - For zero/negative group deltas, we solve directly to post-target values
      (which can yield negative deltas per instrument).

    Returns
    -------
    list[tuple[str, str, str, Decimal]]
        Ordered tuples:
        ``(asset_group_id, asset_group_name, instrument_id, planned_delta_money)``.
        Zero deltas are omitted.
    """
    instruments_by_group: Dict[str, list[Instrument]] = {g.id: [] for g in p.asset_groups}
    for ins in p.instruments:
        if ins.investable and ins.asset_group_id:
            instruments_by_group[ins.asset_group_id].append(ins)

    def _split_positive_delta_no_sell(group_instruments: list[Instrument], group_delta: D) -> Dict[str, D]:
        """
        Allocate a positive group delta across instruments while forbidding per-instrument sells.

        This mirrors the no-sell logic at asset-group level:
        - Compute wanted post-invest values from in-group percentages.
        - If some instruments would require negative delta (sell), exclude them from the active set.
        - Renormalize percentages over the remaining active instruments and iterate.
        - Return deltas for all instruments (inactive ones get 0).
        """
        cur = {ins.id: ins.value for ins in group_instruments}
        pct = {ins.id: ins.target_in_group_pct for ins in group_instruments}
        active_ids = [ins.id for ins in group_instruments]

        while True:
            # Active percentages are renormalized by dividing by pct_total.
            pct_total = sum((pct[iid] for iid in active_ids), D("0"))
            if pct_total <= 0:
                return {ins.id: D("0") for ins in group_instruments}

            sum_active_current = sum((cur[iid] for iid in active_ids), D("0"))
            active_total_after = sum_active_current + group_delta

            deltas: Dict[str, D] = {}
            negative_ids: list[str] = []
            for iid in active_ids:
                wanted = (active_total_after * pct[iid]) / pct_total
                delta = wanted - cur[iid]
                deltas[iid] = delta
                if delta < 0:
                    negative_ids.append(iid)

            if not negative_ids:
                # Stable allocation: all active deltas are non-negative.
                result = {ins.id: D("0") for ins in group_instruments}
                for iid in active_ids:
                    result[iid] = deltas[iid]
                return result

            # Freeze instruments that would need a sell and retry with the rest.
            neg_set = set(negative_ids)
            active_ids = [iid for iid in active_ids if iid not in neg_set]
            if not active_ids:
                return {ins.id: D("0") for ins in group_instruments}

    def _split_by_post_target(group_instruments: list[Instrument], group_delta: D) -> Dict[str, D]:
        """
        Solve directly for per-instrument deltas from desired post-investment percentages.

        For each instrument:
            wanted_after = (group_total_after * target_pct / 100)
            delta = wanted_after - current_value
        """
        current_total = sum((ins.value for ins in group_instruments), D("0"))
        total_after = current_total + group_delta
        deltas: Dict[str, D] = {}
        for ins in group_instruments:
            wanted = (total_after * ins.target_in_group_pct) / D("100")
            deltas[ins.id] = wanted - ins.value
        return deltas

    steps: List[tuple[str, str, str, D]] = []
    for row in plan:
        # Ignore instruments with 0% in-group target: they should not receive future investments.
        group_instruments = [
            ins for ins in instruments_by_group.get(row.asset_group_id, []) if ins.target_in_group_pct > 0
        ]
        if not group_instruments:
            continue

        # Positive group delta -> buy-only split (no per-instrument sells).
        # Non-positive group delta -> exact post-target solve.
        if row.planned_delta_money > 0:
            split_deltas = _split_positive_delta_no_sell(group_instruments, row.planned_delta_money)
        else:
            split_deltas = _split_by_post_target(group_instruments, row.planned_delta_money)

        # Keep output compact: only emit actionable (non-zero) instrument deltas.
        for ins in group_instruments:
            delta = split_deltas.get(ins.id, D("0"))
            if delta != 0:
                steps.append((row.asset_group_id, row.asset_group_name, ins.id, delta))

    return steps
