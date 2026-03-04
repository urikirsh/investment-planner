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
from datetime import date
from decimal import Decimal
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
    usd_ils_rate:
        Cached BOI USD/ILS rate for the current wizard run, when fetch succeeds.
    usd_ils_rate_date:
        Effective date of `usd_ils_rate`.
    usd_ils_source:
        Source label displayed in wizard FX panel.
    usd_ils_used_last_published:
        Indicates that BOI returned a prior published business-day quote.
    usd_ils_fetch_attempted:
        Guard to ensure BOI fetch is attempted at most once per wizard run.
    usd_ils_fetch_error:
        Captured fetch/parsing error shown to the user when quote retrieval fails.
    manual_override_usd_ils_rate:
        User-entered USD/ILS override reused across USD steps in the same wizard run.

    Notes
    -----
    All fields here are transient UI-only state and are never persisted to
    the portfolio model/JSON.
    """

    last_calc: BuyCalculation | None = None
    usd_ils_rate: Decimal | None = None
    usd_ils_rate_date: date | None = None
    usd_ils_source: str | None = None
    usd_ils_used_last_published: bool = False
    usd_ils_fetch_attempted: bool = False
    usd_ils_fetch_error: str | None = None
    manual_override_usd_ils_rate: Decimal | None = None
