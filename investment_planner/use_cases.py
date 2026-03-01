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

D = Decimal


@dataclass(frozen=True)
class PlanStep:
    """Per-instrument execution step derived from portfolio planning output."""

    asset_group_id: str
    asset_group_name: str
    instrument_id: str
    instrument_name: str
    planned_delta_money: D


@dataclass(frozen=True)
class PlanBuildResult:
    """Planning output consumed by the UI summary and wizard screens."""

    portfolio: Portfolio
    budget: D
    rows: List[AssetGroupPlanRow]
    steps: List[PlanStep]
    mode: PlanningMode


def parse_portfolio_data(data: Dict[str, Any]) -> Portfolio:
    """Parse raw JSON-like portfolio data into the strongly-typed model."""
    return load_portfolio(data)


def load_document(session: PortfolioSession, path: Path) -> Portfolio:
    """Load portfolio from disk and update session document state."""
    return session.load_document_from_path(path)


def create_new_default_document(session: PortfolioSession) -> Portfolio:
    """Create a fresh default in-memory portfolio and reset file association."""
    portfolio = build_default_portfolio()
    session.mark_new_document(portfolio)
    return portfolio


def save_document_from_data(session: PortfolioSession, data: Dict[str, Any], target_path: Path) -> Portfolio:
    """Validate and persist editor data to a target path via session/document APIs."""
    portfolio = parse_portfolio_data(data)
    validate_portfolio(portfolio)
    session.document.set_current(portfolio)
    session.save_document_to_path(target_path)
    return portfolio


def sync_document_from_data(session: PortfolioSession, data: Dict[str, Any]) -> Portfolio:
    """Parse current editor state and update session current portfolio only."""
    portfolio = parse_portfolio_data(data)
    session.document.set_current(portfolio)
    return portfolio


def build_plan_for_current_document(session: PortfolioSession, mode: PlanningMode) -> PlanBuildResult:
    """Build group plan rows and instrument execution steps for current document."""
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
    Apply a wizard step to the current document and persist immediately.

    Returns ``True`` only when a trade was applied and saved.
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
