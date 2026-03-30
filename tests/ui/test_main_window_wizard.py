from __future__ import annotations

"""Focused tests for `MainWindowWizardMixin` behavior."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from portfolio_core.domain.models import Exchange, Portfolio
from portfolio_core.market_data import TickerLookupFound, TickerLookupMetadata
from portfolio_core.use_cases import InsufficientQuantityForSellError, PlanStep
import ui.main_window_wizard as wizard_mod
from ui.main_window_wizard import MainWindowWizardMixin


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


class _FakeHost(MainWindowWizardMixin):
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


def _cached_lookup(*, exchange: Exchange, ticker: str, price: Decimal) -> TickerLookupFound:
    return TickerLookupFound(
        metadata=TickerLookupMetadata(
            exchange=exchange,
            canonical_ticker=ticker,
            display_name=ticker,
            last_traded_price=price,
        )
    )


def test_show_current_wizard_step_prefills_buy_units_from_cached_price(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="125")])
    monkeypatch.setattr(
        wizard_mod,
        "get_cached_ticker_lookup_in_exchange",
        lambda *, exchange, ticker: _cached_lookup(exchange=exchange, ticker=ticker, price=Decimal("12.5")),
    )

    host._show_current_wizard_step()

    assert host.screen_wizard.step_progress.value == "Step 1/1"
    assert host.units_label.value == "Units bought:"
    assert host.units_edit.value() == 10
    assert host.units_edit.maximum() == 10
    assert host.screen_wizard.wiz_summary.value == "Planned: 125 ILS | Price: 12.5 ILS/unit | Recommended: 10 units"
    assert host.wiz_result.value == "Total spend: 125 ILS | Leftover: 0 ILS"
    assert host.screen_wizard.save_continue_btn.isEnabled() is True


def test_show_current_wizard_step_prefills_sell_units_from_cached_price(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="-125")])
    monkeypatch.setattr(
        wizard_mod,
        "get_cached_ticker_lookup_in_exchange",
        lambda *, exchange, ticker: _cached_lookup(exchange=exchange, ticker=ticker, price=Decimal("25")),
    )

    host._show_current_wizard_step()

    assert host.units_label.value == "Units sold:"
    assert host.units_edit.value() == 5
    assert host.units_edit.maximum() == 5
    assert host.screen_wizard.wiz_summary.value == "Planned: 125 ILS | Price: 25 ILS/unit | Recommended: 5 units"
    assert host.wiz_result.value == "Total proceeds: 125 ILS | Leftover: 0 ILS"


def test_show_current_wizard_step_uses_cached_usd_price_and_fx_rate(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.wizard_state.usd_ils_rate = Decimal("3.1")
    monkeypatch.setattr(
        wizard_mod,
        "get_cached_ticker_lookup_in_exchange",
        lambda *, exchange, ticker: _cached_lookup(exchange=exchange, ticker=ticker, price=Decimal("10")),
    )

    host._show_current_wizard_step()

    assert host.units_edit.value() == 1
    assert host.units_edit.maximum() == 1
    assert host.screen_wizard.wiz_summary.value == "Planned: 50 ILS | Price: 31 ILS/unit | Recommended: 1 units"
    assert host.wiz_result.value == "Total spend: 31 ILS | Leftover: 19 ILS"


def test_wizard_units_change_clamps_to_recommended_limit(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50")])
    monkeypatch.setattr(
        wizard_mod,
        "get_cached_ticker_lookup_in_exchange",
        lambda *, exchange, ticker: _cached_lookup(exchange=exchange, ticker=ticker, price=Decimal("20")),
    )

    host._show_current_wizard_step()
    host.units_edit.setValue(3)

    assert host.units_edit.value() == 2
    assert host.wizard_state.last_calc is not None
    assert host.wizard_state.last_calc.units == 2
    assert host.screen_wizard.save_continue_btn.isEnabled() is True
    assert host.screen_wizard.units_error_label.value == ""


def test_wizard_units_change_allows_zero_units(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50")])
    monkeypatch.setattr(
        wizard_mod,
        "get_cached_ticker_lookup_in_exchange",
        lambda *, exchange, ticker: _cached_lookup(exchange=exchange, ticker=ticker, price=Decimal("20")),
    )

    host._show_current_wizard_step()
    host.units_edit.setValue(0)
    host._wizard_units_changed(0)

    assert host.wizard_state.last_calc is not None
    assert host.wizard_state.last_calc.units == 0
    assert host.wizard_state.last_calc.spent == Decimal("0")
    assert host.screen_wizard.save_continue_btn.isEnabled() is True


def test_show_current_wizard_step_requires_cached_price(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50")])
    monkeypatch.setattr(
        wizard_mod,
        "get_cached_ticker_lookup_in_exchange",
        lambda *, exchange, ticker: None,
    )

    host._show_current_wizard_step()

    assert host.screen_wizard.save_continue_btn.isEnabled() is False
    assert "Cached price unavailable" in host.screen_wizard.units_error_label.value


def test_wizard_save_continue_requires_valid_units(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="10")])
    shown: list[tuple[str, str]] = []

    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    host._wizard_save_continue()

    assert shown and shown[0][0] == "Save failed"
    assert "Please enter a valid units value" in shown[0][1]


def test_wizard_save_continue_applies_zero_unit_step_as_no_op_and_advances(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="10")])
    host.wizard_state.last_calc = SimpleNamespace(units=0, spent=Decimal("0"))
    apply_calls: list[dict[str, Any]] = []
    advance_calls = 0

    def fake_apply(session: Any, step: Any, calc_units: int, spent: Decimal) -> bool:
        apply_calls.append({"session": session, "step": step, "calc_units": calc_units, "spent": spent})
        return False

    def fake_advance() -> None:
        nonlocal advance_calls
        advance_calls += 1

    monkeypatch.setattr(wizard_mod, "apply_wizard_step", fake_apply)
    monkeypatch.setattr(host, "_advance_wizard_step", fake_advance)

    host._wizard_save_continue()

    assert apply_calls == [{"session": host.session, "step": host._current_step(), "calc_units": 0, "spent": Decimal("0")}]
    assert host._file_context_updates == 0
    assert advance_calls == 1


def test_wizard_save_continue_shows_quantity_error_and_advances(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="-50")])
    host.wizard_state.last_calc = SimpleNamespace(units=3, spent=Decimal("150"))
    shown: list[tuple[str, str]] = []
    advance_calls = 0

    def fake_apply(_session: Any, _step: Any, _calc_units: int, _spent: Decimal) -> bool:
        raise InsufficientQuantityForSellError(
            instrument_name="ETF A",
            available_units=1,
            requested_units=3,
        )

    def fake_advance() -> None:
        nonlocal advance_calls
        advance_calls += 1

    monkeypatch.setattr(wizard_mod, "apply_wizard_step", fake_apply)
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))
    monkeypatch.setattr(host, "_advance_wizard_step", fake_advance)

    host._wizard_save_continue()

    assert shown and shown[0][0] == "Cannot complete sell step"
    assert "tried to sell 3 units" in shown[0][1]
    assert advance_calls == 1


def test_wizard_back_to_portfolio_returns_to_main_and_populates_editor(
    make_plan_step: Callable[..., PlanStep]
) -> None:
    current_portfolio = object()
    host = _FakeHost(steps=[make_plan_step(delta="10")], step_index=0, current_portfolio=current_portfolio)

    host._wizard_back_to_portfolio()

    assert len(host._render_main_editor_calls) == 1
    assert host._render_main_editor_calls[0]["portfolio"] is current_portfolio
    assert host._render_main_editor_calls[0]["switch_to_main"] is True
    assert host.stack.current_widget is host.screen_main
