from __future__ import annotations

from enum import StrEnum


class PlanningMode(StrEnum):
    """Supported planning strategies for portfolio adjustment flows."""

    INVEST = "invest"
    REBALANCE = "rebalance"
