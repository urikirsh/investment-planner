"""
Typed UI state containers for main window workflow.

These dataclasses centralize mutable state for the planning/summary/wizard
flow so `MainWindow` does not manage scattered ad-hoc attributes.

Why this module exists
----------------------
- Makes UI state explicit and type-checked.
- Avoids dynamic attribute patterns (for example `getattr(..., "_last_calc")`).
- Improves readability by grouping related state into named structures.

Scope
-----
This module stores *UI flow state only*. It does not include widgets,
domain models, persistence logic, or calculation logic.

Lifecycle
---------
- `PlanningState` is updated when a new plan is generated and while navigating
  summary/wizard steps.
- `WizardState` is reset per step and stores only the latest calculation
  relevant to the active step.
- `UnsavedChangesDecision` encodes save/discard/cancel outcomes for
  unsaved-changes confirmation flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from portfolio_core.calc_stock_units import BuyCalculation
from portfolio_core.planning_types import PlanningMode
from portfolio_core.use_cases import PlanStep


class UnsavedChangesDecision(str, Enum):
    """
    Decision outcomes for unsaved-changes confirmation flows.
    """

    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


@dataclass
class PlanningState:
    """
    Planning flow state shared by summary and wizard screens.

    Attributes
    ----------
    plan_steps:
        Instrument-level execution steps produced by the most recent planning run.
    step_index:
        Zero-based index of the active wizard step within `plan_steps`.
    mode:
        Planning mode used to produce `plan_steps` (`INVEST` / `REBALANCE`).

    Notes
    -----
    This dataclass is intentionally mutable. `MainWindow` mutates it in-place
    as the user progresses through the flow.
    """

    plan_steps: list[PlanStep] = field(default_factory=list)
    step_index: int = 0
    mode: PlanningMode = PlanningMode.INVEST


@dataclass
class WizardState:
    """
    Transient state for wizard calculation output.

    Attributes
    ----------
    last_calc:
        Latest units/spend calculation for the current step, or ``None`` when
        no calculation has been performed yet for the active step.

    Notes
    -----
    `last_calc` is step-local transient state and should be reset when moving
    to another wizard step.
    """

    last_calc: BuyCalculation | None = None
