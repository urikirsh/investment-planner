from __future__ import annotations

"""Pytest configuration and shared fixtures for UI/widget test modules.

This file centralizes Qt test setup so individual tests can focus on widget
behavior rather than process-level initialization details. It also provides
shared helpers/builders (`seed_session_usd_ils_cache`, `make_plan_step`,
`make_buy_calculation`, `add_instrument_row`, `make_cached_lookup`,
`stub_cached_prices_for_portfolio`,
`make_wizard_host`) for common UI test object setup.
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
from portfolio_core.domain.models import Currency, Exchange, Portfolio
from portfolio_core.market_data import TickerLookupFound, TickerLookupMetadata
from portfolio_core.workflows import PlanStep
import ui.controllers.main_window_metrics as metrics_mod
from ui.plan_execution_wizard import MainWindowPlanExecutionMixin
from ui.main_window import MainWindow
from ui.shared.portfolio_tree_row import PortfolioTreeRow
from ui.shared.ui_types import Col
from ui.shared.ui_utils import fmt_decimal_grouped, fmt_non_negative_integer_grouped
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
def stub_cached_prices_for_portfolio() -> Callable[[pytest.MonkeyPatch, MainWindow, Portfolio], None]:
    """Return helper that stubs metrics price resolution for a portfolio."""

    def _seed(monkeypatch: pytest.MonkeyPatch, window: MainWindow, portfolio: Portfolio) -> None:
        cached_quote = window.session.cached_usd_ils_quote
        prices_by_key: dict[tuple[Exchange, str], Decimal] = {}
        for instrument in portfolio.instruments:
            quantity = instrument.quantity
            if quantity == 0:
                native_price = Decimal("0")
            else:
                native_price = instrument.value / quantity
                if instrument.exchange.currency is Currency.USD and cached_quote is not None:
                    native_price /= cached_quote.rate
            prices_by_key[(instrument.exchange, instrument.ticker)] = native_price

        monkeypatch.setattr(
            metrics_mod,
            "resolve_cached_instrument_price_ils",
            lambda *, exchange, ticker, instrument_name, usd_ils_rate=None: prices_by_key[(exchange, ticker)]
            if (exchange, ticker) in prices_by_key
            else (_ for _ in ()).throw(
                ValueError(f"Cached price unavailable for '{instrument_name}'. Return to the welcome screen and try again.")
            ),
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
            target_in_group_pct,
            instrument_id,
            exchange,
        )
        child = group.child(group.childCount() - 1)
        assert child is not None
        PortfolioTreeRow(child).set_total_value(Decimal(value))
        return child

    return _add_instrument_row


def assert_portfolio_tree_managed_cells_consistent(tree: QTreeWidget) -> None:
    """Assert managed quantity/total cells stay synchronized with raw row state."""

    def _assert_item(item: QTreeWidgetItem) -> None:
        row = PortfolioTreeRow(item)
        if item.childCount() > 0:
            assert item.text(Col.QUANTITY.value) == ""
            assert row.quantity() == 0
        else:
            assert item.text(Col.QUANTITY.value) == fmt_non_negative_integer_grouped(row.quantity())
        assert item.text(Col.TOT_VALUE.value) == fmt_decimal_grouped(row.total_value())
        for idx in range(item.childCount()):
            child = item.child(idx)
            assert child is not None
            _assert_item(child)

    for idx in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(idx)
        assert item is not None
        _assert_item(item)


class _FakeLabel:
    """Small label double for wizard tests that need text/visibility assertions."""

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
    """Small integer-spinner double that enforces the configured maximum."""

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


class _FakeButton:
    """Small button double exposing only enabled-state mutation."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def isEnabled(self) -> bool:
        return self._enabled


class _FakeWizardScreen:
    """Presentation-only wizard screen double for mixin-focused tests."""

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
    ) -> None:
        self.fx_visible = visible
        self.fx_info_text = info_text
        self.fx_error_text = error_text

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
    """Minimal stacked-widget double capturing the last requested screen."""

    def __init__(self) -> None:
        self.current_widget: object | None = None

    def setCurrentWidget(self, widget: object) -> None:
        self.current_widget = widget


class _FakeWizardHost(MainWindowPlanExecutionMixin):
    """Small host object for testing wizard mixin behavior without Qt widgets."""

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
