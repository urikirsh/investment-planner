from __future__ import annotations

from typing import Callable

from portfolio_core.domain.planning_types import PlanningMode
from portfolio_core.io_json import load_portfolio
from portfolio_core.workflows import PlanStep
from ui.controllers.main_window_summary import MainWindowSummaryController


def test_build_summary_header_lines_formats_grouped_values() -> None:
    portfolio = load_portfolio(
        {
            "cash": {"value": "20000", "min_reserve": "5000", "future_tax": "12345.67"},
            "groups": [],
            "instruments": [],
        }
    )

    lines = MainWindowSummaryController._build_summary_header_lines(portfolio, PlanningMode.INVEST)

    assert lines == [
        "Mode: invest",
        "Future tax (non-investable): 12,345.67",
        "Invest budget (cash - minimal reserve - future tax): 2,654.33",
        "",
    ]


def test_build_summary_action_lines_formats_grouped_trade_amounts(
    make_plan_step: Callable[..., PlanStep],
) -> None:
    steps = [
        make_plan_step(
            delta="12345.67",
            group_name="Equity",
            instrument_name="World ETF",
        )
    ]

    lines = MainWindowSummaryController._build_summary_action_lines(steps)

    assert lines == [
        "Planned actions (split per instrument by in-group target percentages):",
        "- BUY 12,345.67 in [Equity] via [World ETF]",
    ]
