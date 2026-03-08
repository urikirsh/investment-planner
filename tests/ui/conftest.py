from __future__ import annotations

"""Pytest configuration and shared fixtures for UI/widget test modules.

This file centralizes Qt test setup so individual tests can focus on widget
behavior rather than process-level initialization details. It also provides
shared builders (`make_plan_step`, `make_buy_calculation`) for common UI test
object setup.
"""

import os
from collections.abc import Callable
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication

from portfolio_core.calc_stock_units import BuyCalculation
from portfolio_core.use_cases import PlanStep

# Qt requires a platform plugin. `offscreen` allows QApplication startup in
# headless environments (e.g., CI runners without an active display server).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return a module-scoped ``QApplication`` instance for widget tests.

    Qt allows only one QApplication per process. Reusing the existing instance
    keeps tests deterministic and avoids setup overhead across test functions in
    the same module.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture
def make_plan_step() -> Callable[..., PlanStep]:
    """Return a helper that builds ``PlanStep`` objects with sane defaults."""

    def _make_plan_step(
        *,
        delta: str,
        instrument_id: str = "ins-1",
        group_id: str = "g-1",
        group_name: str = "Group A",
        instrument_name: str = "ETF A",
        exchange: str = "TASE",
    ) -> PlanStep:
        return PlanStep(
            asset_group_id=group_id,
            asset_group_name=group_name,
            instrument_id=instrument_id,
            instrument_name=instrument_name,
            exchange=exchange,
            planned_delta_money=Decimal(delta),
        )

    return _make_plan_step


@pytest.fixture
def make_buy_calculation() -> Callable[..., BuyCalculation]:
    """Return a helper that builds ``BuyCalculation`` objects with sane defaults."""

    def _make_buy_calculation(
        *,
        instrument_id: str = "i1",
        price: str = "10",
        planned_money: str = "100",
        units: int = 10,
        spent: str = "100",
        leftover: str = "0",
    ) -> BuyCalculation:
        return BuyCalculation(
            instrument_id=instrument_id,
            price=Decimal(price),
            planned_money=Decimal(planned_money),
            units=units,
            spent=Decimal(spent),
            leftover=Decimal(leftover),
        )

    return _make_buy_calculation
