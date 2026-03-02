from __future__ import annotations

"""
Unit tests for `ui.ui_state`.

These tests lock down the intended defaults and mutability characteristics of
`PlanningState` and `WizardState`, so future refactors do not accidentally
reintroduce implicit/dynamic state behavior.
"""

from decimal import Decimal

from investment_planner.calc_stock_units import BuyCalculation
from investment_planner.planning_types import PlanningMode
from investment_planner.use_cases import PlanStep
from ui.ui_state import PlanningState, WizardState

D = Decimal


def test_planning_state_defaults() -> None:
    """`PlanningState` starts with an empty plan at step 0 in INVEST mode."""
    state = PlanningState()

    assert state.plan_steps == []
    assert state.step_index == 0
    assert state.mode == PlanningMode.INVEST


def test_planning_state_list_default_is_not_shared() -> None:
    """Each state instance should get its own `plan_steps` list."""
    first = PlanningState()
    second = PlanningState()

    first.plan_steps.append(
        PlanStep(
            asset_group_id="g1",
            asset_group_name="Group 1",
            instrument_id="i1",
            instrument_name="Instrument 1",
            planned_delta_money=D("100"),
        )
    )

    assert len(first.plan_steps) == 1
    assert second.plan_steps == []


def test_wizard_state_defaults() -> None:
    """`WizardState` has no prior calculation by default."""
    state = WizardState()
    assert state.last_calc is None


def test_wizard_state_stores_last_calc() -> None:
    """`WizardState` can hold and expose the latest `BuyCalculation`."""
    calc = BuyCalculation(
        instrument_id="i1",
        price=D("10"),
        planned_money=D("100"),
        units=10,
        spent=D("100"),
        leftover=D("0"),
    )
    state = WizardState(last_calc=calc)

    assert state.last_calc is calc
