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
- `WizardState` is reset per wizard run and stores:
  - step-local transient calculation output, and
  - run-scoped USD/ILS display state populated from startup cache.
- `UnsavedChangesDecision` encodes save/discard/cancel outcomes for
  unsaved-changes confirmation flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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
        Cached USD/ILS rate for the current wizard run, loaded from startup cache.
    usd_ils_rate_date:
        Effective date of `usd_ils_rate`.
    usd_ils_used_last_published:
        Indicates that BOI returned a prior published business-day quote.
    usd_ils_fetch_attempted:
        Legacy guard kept for compatibility with coordinator seams.
    usd_ils_fetch_error:
        Optional FX-state error surfaced in wizard UI when cache is unavailable.
    manual_override_usd_ils_rate:
        Legacy field retained for compatibility; manual override is no longer used.
    usd_ils_fetch_in_progress:
        Legacy field retained for compatibility with old async-fetch paths.
    usd_ils_failure_dialog_shown:
        Guard to show loud fetch-failure modal at most once per wizard run.
    usd_ils_rate_from_cache:
        True when the effective rate currently comes from local cache.
    usd_ils_rate_cached_at:
        Timestamp when the cached rate was stored locally.
    usd_ils_fetch_generation:
        Monotonic generation id incremented for each started async fetch.
    usd_ils_active_fetch_generation:
        Generation id of the currently active fetch, if any.

    Notes
    -----
    All fields here are transient UI-only state and are never persisted to
    the portfolio model/JSON.
    """

    last_calc: BuyCalculation | None = None
    usd_ils_rate: Decimal | None = None
    usd_ils_rate_date: date | None = None
    usd_ils_used_last_published: bool = False
    usd_ils_fetch_attempted: bool = False
    usd_ils_fetch_error: str | None = None
    manual_override_usd_ils_rate: Decimal | None = None
    usd_ils_fetch_in_progress: bool = False
    usd_ils_failure_dialog_shown: bool = False
    usd_ils_rate_from_cache: bool = False
    usd_ils_rate_cached_at: datetime | None = None
    usd_ils_fetch_generation: int = 0
    usd_ils_active_fetch_generation: int | None = None
