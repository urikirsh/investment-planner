"""
Typed UI state containers for main window workflow.

These dataclasses hold mutable UI flow state that was previously tracked as
independent attributes on `MainWindow`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from investment_planner.calc_stock_units import BuyCalculation
from investment_planner.planning_types import PlanningMode
from investment_planner.use_cases import PlanStep


@dataclass
class PlanningState:
    """State for planning results and wizard navigation position."""

    plan_steps: list[PlanStep] = field(default_factory=list)
    step_index: int = 0
    mode: PlanningMode = PlanningMode.INVEST


@dataclass
class WizardState:
    """State for the current wizard step's latest unit calculation."""

    last_calc: BuyCalculation | None = None

