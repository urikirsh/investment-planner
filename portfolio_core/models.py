from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
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


class Currency(StrEnum):
    """Allowed instrument price currencies."""

    ILS = "ILS"
    USD = "USD"


@dataclass(frozen=True)
class Cash:
    """
    Represents uninvested cash held in the investment account.

    Cash is excluded from the investment strategy itself, but contributes
    to total portfolio value. A minimum reserve can be defined to ensure
    sufficient liquidity for fees or operational needs. Future tax is a
    non-investable liability that reduces effective portfolio value.

    Monetary fields are expected in ILS and represented as ``Decimal``.
    """
    value: D
    min_reserve: D
    future_tax: D


@dataclass(frozen=True)
class AssetGroup:
    """
    Represents a logical investment category within the strategy.

    Each asset group has a target percentage allocation.
    Asset groups participate in strategy calculations and drift analysis.

    Invariants (enforced by validation):
    - ``id`` and ``name`` are non-empty
    - ``target_pct`` is positive
    - portfolio-level sum of all group targets is exactly 100
    """
    id: str
    name: str
    target_pct: D  # e.g. Decimal("25.0")


@dataclass(frozen=True)
class Instrument:
    """
    Represents a concrete tradable instrument (e.g. ETF, fund, stock).

    An instrument has a current market value in ILS and may or may not
    participate in the investment strategy. Instruments assigned to an
    asset group are considered investable; others are treated as
    non-investable holdings.

    Invariants (enforced by validation):
    - ``value`` is non-negative
    - ``currency`` is one of ``ILS`` or ``USD``
    - ``target_in_group_pct`` is in [0, 100]
    - ``quantity`` is a non-negative integer
    - investable instruments must reference a valid ``asset_group_id``
    - non-investable instruments must have ``asset_group_id is None``

    Notes
    -----
    ``quantity`` tracks held units. It is required and validated as a
    non-negative integer.
    """
    id: str
    name: str
    value: D  # current market value
    currency: Currency
    investable: bool
    asset_group_id: Optional[str]  # None for non-investable instruments
    target_in_group_pct: D  # must sum to 100 per investable group
    quantity: int = 0  # required non-negative integer


@dataclass(frozen=True)
class Portfolio:
    """
    Aggregate root representing the full investment portfolio.

    A portfolio consists of cash, asset groups defining the strategy,
    and a collection of instruments representing current holdings.
    This model is used as the primary input for validation, planning,
    and investment calculations.

    Ordering notes:
    - ``asset_groups`` order is semantically important and drives plan output order.
    - ``instruments`` order is preserved for stable UI rendering and iteration.
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

    This structure is produced by the planning logic and consumed by the
    investment execution flow. It contains no execution or UI behavior.
    """
    asset_group_id: str
    asset_group_name: str
    target_pct: D
    current_value: D
    planned_delta_money: D              # positive=buy, negative=sell
