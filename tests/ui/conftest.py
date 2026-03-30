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
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from portfolio_core.planning.calc_stock_units import BuyCalculation
from portfolio_core.domain.models import Exchange, Portfolio
from portfolio_core.market_data import TickerLookupFound, TickerLookupMetadata
from portfolio_core.use_cases import PlanStep
from ui.main_window_wizard import MainWindowWizardMixin
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
    win = MainWindow(
        json_path=str(tmp_path / "portfolio.json"),
        config_path=tmp_path / "config.json",
    )
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


class _FakeLabel:
    def __init__(self) -> None:
        self.value = ""
        self.visible = True

    def setText(self, text: str) -> None:
        self.value = text

    def text(self) -> str:
        return self.value

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


class _FakeSpinBox:
    def __init__(self, value: int = 0) -> None:
        self._value = value
        self._maximum = 0

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = min(value, self._maximum)

    def setMaximum(self, value: int) -> None:
        self._maximum = value
        if self._value > self._maximum:
            self._value = self._maximum

    def maximum(self) -> int:
        return self._maximum


class _FakeLineEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text


class _FakeButton:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def isEnabled(self) -> bool:
        return self._enabled


class _FakeWizardScreen:
    def __init__(self, units_label: _FakeLabel, units_edit: _FakeSpinBox) -> None:
        self.units_label = units_label
        self.units_edit = units_edit
        self.step_progress = _FakeLabel()
        self.wiz_info = _FakeLabel()
        self.wiz_summary = _FakeLabel()
        self.wiz_result = _FakeLabel()
        self.units_error_label = _FakeLabel()
        self.fx_visible = False
        self.fx_info_text = ""
        self.fx_error_text = ""
        self.manual_visible = False
        self.save_continue_btn = _FakeButton(False)
        self.quit_btn = SimpleNamespace(clicked=SimpleNamespace(connect=lambda _cb: None))
        self.back_to_portfolio_btn = SimpleNamespace(clicked=SimpleNamespace(connect=lambda _cb: None))
        self.continue_without_save_btn = SimpleNamespace(clicked=SimpleNamespace(connect=lambda _cb: None))

    def set_trade_mode(self, *, action: str) -> None:
        self.units_label.setText("Units sold:" if action == "SELL" else "Units bought:")

    def set_fx_panel(
        self,
        *,
        visible: bool,
        info_text: str,
        error_text: str,
        manual_visible: bool,
        manual_value: str = "",
    ) -> None:
        self.fx_visible = visible
        self.fx_info_text = info_text
        self.fx_error_text = error_text
        self.manual_visible = manual_visible
        _ = manual_value

    def set_step_context(
        self,
        *,
        step_index: int,
        total_steps: int,
        asset_group_name: str,
        ticker: str,
        exchange: Exchange,
        instrument_name: str,
        action: str,
        planned_amount_text: str,
    ) -> None:
        self.step_progress.setText(f"Step {step_index}/{total_steps}")
        self.wiz_info.setText(
            f"Instrument: {instrument_name}\n"
            f"Ticker: {ticker}\n"
            f"Exchange: {exchange.value}\n"
            f"Asset group: {asset_group_name}\n"
            f"Action: {action} {planned_amount_text}"
        )

    def set_units_error(self, text: str) -> None:
        self.units_error_label.setText(text)
        self.units_error_label.setVisible(bool(text))

    def set_wizard_summary(self, text: str) -> None:
        self.wiz_summary.setText(text)

    def set_units_limit(self, *, value: int) -> None:
        self.units_edit.setMaximum(value)

    def sync_focus_row_widths(self) -> None:
        return None


class _FakeStack:
    def __init__(self) -> None:
        self.current_widget: object | None = None

    def setCurrentWidget(self, widget: object) -> None:
        self.current_widget = widget


class _FakeWizardHost(MainWindowWizardMixin):
    session: Any
    planning_state: Any
    wizard_state: Any
    stack: Any
    screen_main: Any
    screen_wizard: Any
    tree: Any
    cash_value_edit: Any
    cash_reserve_edit: Any
    future_tax_edit: Any
    units_edit: Any
    units_label: Any
    manual_rate_edit: Any
    wiz_info: Any
    wiz_result: Any
    _file_context_updates: int
    _refresh_data_calls: int
    _render_main_editor_calls: list[dict[str, object]]

    def __init__(self, *, steps: list[PlanStep], step_index: int = 0, current_portfolio: object | None = object()) -> None:
        self.session = SimpleNamespace(
            document=SimpleNamespace(current_portfolio=current_portfolio),
            cached_usd_ils_quote=None,
        )
        self.planning_state = SimpleNamespace(plan_steps=steps, step_index=step_index)
        self.wizard_state = SimpleNamespace(
            last_calc=None,
            usd_ils_rate=None,
            usd_ils_rate_date=None,
            usd_ils_used_last_published=False,
            usd_ils_rate_from_cache=False,
            usd_ils_rate_cached_at=None,
        )
        self.stack = _FakeStack()
        self.screen_main = object()
        self.tree = object()
        self.cash_value_edit = object()
        self.cash_reserve_edit = object()
        self.future_tax_edit = object()
        self.units_edit = _FakeSpinBox()
        self.units_label = _FakeLabel()
        self.manual_rate_edit = _FakeLineEdit()
        self.screen_wizard = _FakeWizardScreen(self.units_label, self.units_edit)
        self.wiz_info = self.screen_wizard.wiz_info
        self.wiz_result = self.screen_wizard.wiz_result
        self._non_investable_bucket_id = "non_investable_bucket"
        self._non_investable_bucket_title = "Non-investable holdings (excluded from strategy)"
        self._file_context_updates = 0
        self._refresh_data_calls = 0
        self._render_main_editor_calls = []

    def _quit_app(self) -> None:
        return None

    def _update_file_context_ui(self) -> None:
        self._file_context_updates += 1

    def _update_future_tax_visual_state(self) -> None:
        return None

    def _refresh_data(self) -> None:
        self._refresh_data_calls += 1

    def _render_main_editor_from_portfolio(self, portfolio: Portfolio, *, switch_to_main: bool) -> None:
        self._render_main_editor_calls.append({"portfolio": portfolio, "switch_to_main": switch_to_main})
        self._refresh_data()
        if switch_to_main:
            self.stack.setCurrentWidget(self.screen_main)


@pytest.fixture
def make_cached_lookup() -> Callable[..., TickerLookupFound]:
    """Return helper that builds cached ticker lookup results for wizard tests."""

    def _make_cached_lookup(*, exchange: Exchange, ticker: str, price: Decimal) -> TickerLookupFound:
        return TickerLookupFound(
            metadata=TickerLookupMetadata(
                exchange=exchange,
                canonical_ticker=ticker,
                display_name=ticker,
                last_traded_price=price,
            )
        )

    return _make_cached_lookup


@pytest.fixture
def make_wizard_host() -> Callable[..., _FakeWizardHost]:
    """Return helper that builds a lightweight wizard host with shared fake widgets."""

    def _make_wizard_host(
        *,
        steps: list[PlanStep],
        step_index: int = 0,
        current_portfolio: object | None = object(),
    ) -> _FakeWizardHost:
        return _FakeWizardHost(
            steps=steps,
            step_index=step_index,
            current_portfolio=current_portfolio,
        )

    return _make_wizard_host
