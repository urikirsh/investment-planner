from __future__ import annotations

from typing import Callable

from portfolio_core.domain.planning_types import PlanningMode
from portfolio_core.io_json import load_portfolio
from portfolio_core.workflows import PlanStep
from ui.controllers.main_window_summary import MainWindowSummaryController


def test_planning_action_label_matches_main_editor_button_wording() -> None:
    assert MainWindowSummaryController._planning_action_label(PlanningMode.INVEST) == "Invest Cash"
    assert MainWindowSummaryController._planning_action_label(PlanningMode.REBALANCE) == "Rebalance Portfolio"


def test_available_to_allocate_text_formats_grouped_values() -> None:
    portfolio = load_portfolio(
        {
            "cash": {"value": "20000", "min_reserve": "5000", "future_tax": "12345.67"},
            "groups": [],
            "instruments": [],
        }
    )

    text = MainWindowSummaryController._available_to_allocate_text(portfolio)

    assert text == "2,654.33 ILS"


def test_format_planned_action_formats_grouped_trade_amounts(
    make_plan_step: Callable[..., PlanStep],
) -> None:
    step = make_plan_step(
        delta="12345.67",
        group_name="Equity",
        instrument_name="World ETF",
    )

    text = MainWindowSummaryController._format_planned_action(step, index=1)

    assert text == "1. BUY 12,345.67 ILS in [Equity] via [World ETF]"


def test_format_planned_action_trim_trailing_zeros_for_display(
    make_plan_step: Callable[..., PlanStep],
) -> None:
    step = make_plan_step(
        delta="12345.00",
        group_name="Equity",
        instrument_name="World ETF",
    )

    text = MainWindowSummaryController._format_planned_action(step, index=1)

    assert text == "1. BUY 12,345 ILS in [Equity] via [World ETF]"


def test_format_planned_action_limits_display_to_two_decimals(
    make_plan_step: Callable[..., PlanStep],
) -> None:
    step = make_plan_step(
        delta="12345.6789",
        group_name="Equity",
        instrument_name="World ETF",
    )

    text = MainWindowSummaryController._format_planned_action(step, index=1)

    assert text == "1. BUY 12,345.68 ILS in [Equity] via [World ETF]"


def test_build_planned_actions_text_joins_multiple_formatted_lines(
    make_plan_step: Callable[..., PlanStep],
) -> None:
    steps = [
        make_plan_step(delta="12345.67", group_name="Equity", instrument_name="World ETF"),
        make_plan_step(delta="-5000", group_name="Bonds", instrument_name="Bond ETF"),
    ]

    text = MainWindowSummaryController._build_planned_actions_text(steps)

    assert text == (
        "1. BUY 12,345.67 ILS in [Equity] via [World ETF]\n"
        "2. SELL 5,000 ILS in [Bonds] via [Bond ETF]"
    )
