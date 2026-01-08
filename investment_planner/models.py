from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


D = Decimal


@dataclass(frozen=True)
class Cash:
    value: D
    reserve: D   # TODO - call this min_reserve


@dataclass(frozen=True)
class AssetGroup:
    id: str
    name: str
    target_pct: D  # e.g. Decimal("25.0")
    preferred_instrument_id: str


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    value: D  # current market value
    investable: bool
    asset_group_id: Optional[str]  # None for non-investable instruments


@dataclass(frozen=True)
class Portfolio:
    cash: Cash
    asset_groups: list[AssetGroup]       # ordered (drives planning order)
    instruments: list[Instrument]        # ordered (drives UI order; not required for planning)


@dataclass(frozen=True)
class AssetGroupPlanRow:
    asset_group_id: str
    asset_group_name: str
    target_pct: D
    current_value: D
    planned_delta_money: D              # positive=buy, negative=sell
    preferred_instrument_id: str