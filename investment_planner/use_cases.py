from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from investment_planner.calc_stock_units import commit_buy, commit_sell
from investment_planner.io_json import load_portfolio
from investment_planner.models import AssetGroupPlanRow, Portfolio
from investment_planner.planning_types import PlanningMode
from investment_planner.planning import (
    compute_invest_budget,
    map_asset_group_deltas_to_instruments,
    plan_invest_no_sell,
    plan_rebalance,
)
from investment_planner.portfolio_session import PortfolioSession, build_default_portfolio
from investment_planner.validation import validate_portfolio

"""
use_cases.py

Application-level portfolio workflows ("use-cases").

This module is the orchestration layer between UI and domain logic.
It coordinates parsing, validation, planning, and persistence through
`PortfolioSession` and domain services, while keeping GUI code free from
business-flow details.

Design intent:
- UI gathers user input and handles presentation.
- Use-cases execute workflow steps and return domain-friendly outputs.
- Domain modules remain focused on pure calculations and invariants.
"""

D = Decimal


@dataclass(frozen=True)
class PlanStep:
    """
    One actionable instrument-level step in the planning wizard.

    A `PlanStep` is generated from group-level plan rows and tells the caller
    which instrument should be bought or sold and by how much planned value.
    """

    asset_group_id: str
    asset_group_name: str
    instrument_id: str
    instrument_name: str
    planned_delta_money: D


@dataclass(frozen=True)
class PlanBuildResult:
    """
    Aggregate planning result consumed by summary and wizard screens.

    Attributes
    ----------
    portfolio:
        Portfolio used for planning.
    budget:
        Computed investable cash budget (floored at zero by planning logic).
    rows:
        Asset-group level plan rows.
    steps:
        Instrument-level actionable steps derived from `rows`.
    mode:
        Planning strategy used to produce this result.
    """

    portfolio: Portfolio
    budget: D
    rows: List[AssetGroupPlanRow]
    steps: List[PlanStep]
    mode: PlanningMode


def parse_portfolio_data(data: Dict[str, Any]) -> Portfolio:
    """
    Parse raw JSON-like payload into a `Portfolio`.

    This function performs schema-level parsing only; business-rule validation
    is intentionally handled separately by `validate_portfolio`.
    """
    return load_portfolio(data)


def load_document(session: PortfolioSession, path: Path) -> Portfolio:
    """
    Load a portfolio file and update session document state.

    Side effects
    ------------
    - Updates `session.document` current/snapshot/active path.
    - Persists active path through session config behavior.
    """
    return session.load_document_from_path(path)


def create_new_default_document(session: PortfolioSession) -> Portfolio:
    """
    Create a new default portfolio and mark it as an unsaved document.

    Side effects
    ------------
    - Sets current and saved snapshot to default portfolio.
    - Clears active file path in session and persisted config.
    """
    portfolio = build_default_portfolio()
    session.mark_new_document(portfolio)
    return portfolio


def save_document_from_data(session: PortfolioSession, data: Dict[str, Any], target_path: Path) -> Portfolio:
    """
    Parse, validate, and persist editor data to `target_path`.

    Workflow
    --------
    1. Parse UI payload into `Portfolio`.
    2. Validate business invariants.
    3. Set parsed portfolio as current document.
    4. Save document and update active path via session.

    Returns
    -------
    Portfolio
        The validated portfolio that was saved.
    """
    portfolio = parse_portfolio_data(data)
    validate_portfolio(portfolio)
    session.document.set_current(portfolio)
    session.save_document_to_path(target_path)
    return portfolio


def sync_document_from_data(session: PortfolioSession, data: Dict[str, Any]) -> Portfolio:
    """
    Parse UI payload and update only the in-memory current document.

    This use-case does not validate or persist. It is useful for dirty-state
    checks where the UI needs a current parsed snapshot without saving.
    """
    portfolio = parse_portfolio_data(data)
    session.document.set_current(portfolio)
    return portfolio


def build_plan_for_current_document(session: PortfolioSession, mode: PlanningMode) -> PlanBuildResult:
    """
    Build planning output for the current document and selected strategy.

    Parameters
    ----------
    session:
        Session holding the current document to plan.
    mode:
        Planning strategy (`INVEST` or `REBALANCE`).

    Returns
    -------
    PlanBuildResult
        Includes budget, asset-group rows, and instrument-level steps.
        If budget is non-positive, `rows` and `steps` are returned empty.

    Raises
    ------
    ValueError
        If no current portfolio is loaded, or if an instrument referenced by
        the split plan cannot be found.
    """
    portfolio = session.document.current_portfolio
    if portfolio is None:
        raise ValueError("No portfolio loaded")

    budget = compute_invest_budget(portfolio)
    if budget <= 0:
        return PlanBuildResult(
            portfolio=portfolio,
            budget=budget,
            rows=[],
            steps=[],
            mode=mode,
        )

    rows = plan_invest_no_sell(portfolio) if mode == PlanningMode.INVEST else plan_rebalance(portfolio)
    instrument_steps = map_asset_group_deltas_to_instruments(portfolio, rows)
    instruments_by_id = {ins.id: ins for ins in portfolio.instruments}

    steps: List[PlanStep] = []
    for group_id, group_name, instrument_id, planned_delta in instrument_steps:
        if planned_delta == 0:
            continue
        instrument = instruments_by_id.get(instrument_id)
        if instrument is None:
            raise ValueError(f"Instrument not found: {instrument_id}")
        steps.append(
            PlanStep(
                asset_group_id=group_id,
                asset_group_name=group_name,
                instrument_id=instrument_id,
                instrument_name=instrument.name,
                planned_delta_money=planned_delta,
            )
        )

    return PlanBuildResult(
        portfolio=portfolio,
        budget=budget,
        rows=rows,
        steps=steps,
        mode=mode,
    )


def apply_wizard_step(
    session: PortfolioSession,
    step: PlanStep,
    calc_units: int,
    spent: D,
    *,
    min_buy_trade_ils: D = D("100"),
    min_sell_trade_ils: D = D("1"),
    min_apply_spent_ils: D = D("1"),
) -> bool:
    """
    Apply one wizard step trade and persist immediately when actionable.

    Actionability rules
    -------------------
    A step is applied only when:
    - `calc_units > 0`
    - `spent >= min_apply_spent_ils`

    If not actionable, this function returns `False` and performs no changes.

    Persistence behavior
    --------------------
    For actionable steps:
    - Applies buy/sell to current portfolio.
    - Updates current document in session.
    - Saves to the currently active file path.

    Returns
    -------
    bool
        `True` when trade was applied and saved, otherwise `False`.

    Raises
    ------
    ValueError
        If no portfolio is loaded or there is no active save path.
    """
    portfolio = session.document.current_portfolio
    if portfolio is None:
        raise ValueError("No portfolio loaded")

    if calc_units <= 0 or spent < min_apply_spent_ils:
        return False

    if step.planned_delta_money > 0:
        updated = commit_buy(
            p=portfolio,
            instrument_id=step.instrument_id,
            spent=spent,
            min_trade_ils=min_buy_trade_ils,
        )
    else:
        updated = commit_sell(
            p=portfolio,
            instrument_id=step.instrument_id,
            proceeds=spent,
            min_trade_ils=min_sell_trade_ils,
        )

    session.document.set_current(updated)
    target_path = session.current_file_path
    if target_path is None:
        raise ValueError("No target file selected. Save the portfolio before continuing.")
    session.save_document_to_path(target_path)
    return True
