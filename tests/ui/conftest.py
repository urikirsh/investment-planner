from __future__ import annotations

"""Pytest configuration and shared fixtures for UI/widget test modules.

This file centralizes Qt test setup so individual tests can focus on widget
behavior rather than process-level initialization details. It also provides
shared helpers/builders (`seed_session_usd_ils_cache`, `make_plan_step`,
`make_buy_calculation`, `add_instrument_row`) for common UI test object setup.
"""

import os
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from portfolio_core.calc_stock_units import BuyCalculation
from portfolio_core.models import Exchange
from portfolio_core.use_cases import PlanStep
from ui.main_window import MainWindow
from ui.shared.ui_utils import add_instrument_item_to_group, set_group_tree_item

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
        ticker: str = "1234567",
        group_id: str = "g-1",
        group_name: str = "Group A",
        instrument_name: str = "ETF A",
        exchange: Exchange = Exchange.TASE,
    ) -> PlanStep:
        return PlanStep(
            asset_group_id=group_id,
            asset_group_name=group_name,
            instrument_id=instrument_id,
            ticker=ticker,
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


@pytest.fixture
def seed_session_usd_ils_cache() -> Callable[[MainWindow], None]:
    """Return helper that seeds session USD/ILS cache for welcome-flow tests."""

    def _seed(window: MainWindow) -> None:
        window.session.cache_usd_ils_quote(
            rate=Decimal("3.75"),
            effective_date=date.fromisoformat("2026-03-10"),
            used_last_published=False,
            cached_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
        )

    return _seed


@pytest.fixture
def window(monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path: Path) -> Iterator[MainWindow]:
    """Return a `MainWindow` with disk/UI side effects neutralized for tests."""
    _ = qapp
    monkeypatch.setattr(MainWindow, "_load_default_document", lambda self: None)
    win = MainWindow(json_path=str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(win, "_cancel_wizard_fx_fetch", lambda **_kwargs: True)
    yield win
    win.close()


@pytest.fixture
def add_instrument_row() -> Callable[..., QTreeWidgetItem]:
    """Return helper that creates one top-level group with one instrument row.

    The helper returns the created instrument child item, so tests can mutate
    the row directly without repeating tree/group bootstrap code.
    """

    def _add_instrument_row(
        *,
        tree: QTreeWidget,
        group_name: str = "Group 1",
        group_target_pct: Decimal | int | str = "100",
        group_id: str = "g1",
        ticker: str = "0000000",
        instrument_name: str = "Instrument 1",
        quantity: int = 1,
        value: str = "100",
        target_in_group_pct: str = "100",
        instrument_id: str = "i1",
        exchange: str = "TASE",
    ) -> QTreeWidgetItem:
        group = QTreeWidgetItem(tree)
        set_group_tree_item(group, group_name, group_target_pct, group_id)
        add_instrument_item_to_group(
            group,
            ticker,
            instrument_name,
            quantity,
            value,
            target_in_group_pct,
            instrument_id,
            exchange,
        )
        child = group.child(group.childCount() - 1)
        assert child is not None
        return child

    return _add_instrument_row
