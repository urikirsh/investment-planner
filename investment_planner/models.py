from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

"""
models.py

Core domain models for the investment planner.

This module defines the immutable data structures that represent
the portfolio, including cash, asset groups, and instruments.
These models are independent of UI, persistence, and calculation logic
and are used throughout the application as the source of truth.
"""

D = Decimal


@dataclass(frozen=True)
class Cash:
    """
    Represents uninvested cash held in the investment account.

    Cash is excluded from the investment strategy itself, but contributes
    to total portfolio value. A minimum reserve can be defined to ensure
    sufficient liquidity for fees or operational needs.
    """
    value: D
    min_reserve: D


@dataclass(frozen=True)
class AssetGroup:
    """
    Represents a logical investment category within the strategy.

    Each asset group has a target percentage allocation and may designate
    a preferred instrument to be used when allocating new funds.
    Asset groups participate in strategy calculations and drift analysis.
    """
    id: str
    name: str
    target_pct: D  # e.g. Decimal("25.0")
    preferred_instrument_id: str


@dataclass(frozen=True)
class Instrument:
    """
    Represents a concrete tradable instrument (e.g. ETF, fund, stock).

    An instrument has a current market value in ILS and may or may not
    participate in the investment strategy. Instruments assigned to an
    asset group are considered investable; others are treated as
    non-investable holdings.
    """
    id: str
    name: str
    value: D  # current market value
    investable: bool
    asset_group_id: Optional[str]  # None for non-investable instruments


@dataclass(frozen=True)
class Portfolio:
    """
    Aggregate root representing the full investment portfolio.

    A portfolio consists of cash, asset groups defining the strategy,
    and a collection of instruments representing current holdings.
    This model is used as the primary input for validation, planning,
    and investment calculations.
    """
    cash: Cash
    asset_groups: list[AssetGroup]       # ordered (drives planning order)
    instruments: list[Instrument]        # ordered (drives UI order; not required for planning)


@dataclass(frozen=True)
class AssetGroupPlanRow:
    """
    Planning-time representation of an asset group's allocation adjustment.

    This model describes how a single asset group should change in order to
    move the portfolio toward its target allocation, based on current values
    and available funds.

    Fields:
    - asset_group_id:
        Identifier of the asset group.
    - asset_group_name:
        Human-readable name of the asset group.
    - target_pct:
        Target allocation percentage defined by the strategy.
    - current_value:
        Current total value of the asset group (ILS).
    - planned_delta_money:
        Planned change in value (ILS) required to reach the target.
        Positive values indicate buying; negative values indicate selling.
    - preferred_instrument_id:
        Identifier of the instrument preferred for executing purchases
        for this asset group.

    This structure is produced by the planning logic and consumed by the
    investment execution flow. It contains no execution or UI behavior.
    """
    asset_group_id: str
    asset_group_name: str
    target_pct: D
    current_value: D
    planned_delta_money: D              # positive=buy, negative=sell
    preferred_instrument_id: str