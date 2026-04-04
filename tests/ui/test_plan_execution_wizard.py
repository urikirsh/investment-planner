from __future__ import annotations

"""Focused tests for `MainWindowPlanExecutionMixin` behavior."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from portfolio_core.domain.models import Exchange
from portfolio_core.workflows import InsufficientQuantityForSellError, PlanStep
import ui.plan_execution_wizard as wizard_mod


def test_show_current_plan_execution_step_prefills_buy_units_from_cached_price(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="125")])
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("12.5"),
    )

    host._show_current_plan_execution_step()

    assert host.screen_wizard.step_progress.value == "Step 1/1"
    assert host.units_label.value == "Units bought:"
    assert host.units_edit.value() == 10
    assert host.units_edit.maximum() == 10
    assert host.screen_wizard.wiz_summary.value == "Planned: 125 ILS | Price: 12.5 ILS/unit | Recommended: 10 units"
    assert host.wiz_result.value == "Total spend: 125 ILS | Leftover: 0 ILS"
    assert host.screen_wizard.save_continue_btn.isEnabled() is True


def test_show_current_plan_execution_step_prefills_sell_units_from_cached_price(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="-125")])
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("25"),
    )

    host._show_current_plan_execution_step()

    assert host.units_label.value == "Units sold:"
    assert host.units_edit.value() == 5
    assert host.units_edit.maximum() == 5
    assert host.screen_wizard.wiz_summary.value == "Planned: 125 ILS | Price: 25 ILS/unit | Recommended: 5 units"
    assert host.wiz_result.value == "Total proceeds: 125 ILS | Leftover: 0 ILS"


def test_show_current_plan_execution_step_uses_cached_usd_price_and_fx_rate(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.wizard_state.usd_ils_rate = Decimal("3.1")
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("31"),
    )

    host._show_current_plan_execution_step()

    assert host.units_edit.value() == 1
    assert host.units_edit.maximum() == 1
    assert host.screen_wizard.wiz_summary.value == "Planned: 50 ILS | Price: 31 ILS/unit | Recommended: 1 units"
    assert host.wiz_result.value == "Total spend: 31 ILS | Leftover: 19 ILS"


def test_wizard_units_change_clamps_to_recommended_limit(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="50")])
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("20"),
    )

    host._show_current_plan_execution_step()
    host.units_edit.setValue(3)

    assert host.units_edit.value() == 2
    assert host.wizard_state.last_calc is not None
    assert host.wizard_state.last_calc.units == 2
    assert host.screen_wizard.save_continue_btn.isEnabled() is True
    assert host.screen_wizard.units_error_label.value == ""


def test_wizard_units_change_allows_zero_units(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="50")])
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("20"),
    )

    host._show_current_plan_execution_step()
    host.units_edit.setValue(0)
    host._wizard_units_changed(0)

    assert host.wizard_state.last_calc is not None
    assert host.wizard_state.last_calc.units == 0
    assert host.wizard_state.last_calc.spent == Decimal("0")
    assert host.screen_wizard.save_continue_btn.isEnabled() is True


def test_show_current_plan_execution_step_requires_cached_price(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="50")])
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("Cached price unavailable for 'ETF A'. Return to the welcome screen and try again.")),
    )

    host._show_current_plan_execution_step()

    assert host.screen_wizard.save_continue_btn.isEnabled() is False
    assert "Cached price unavailable" in host.screen_wizard.units_error_label.value


def test_save_and_continue_plan_execution_step_requires_valid_units(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="10")])
    shown: list[tuple[str, str]] = []

    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    host._save_and_continue_plan_execution_step()

    assert shown and shown[0][0] == "Save failed"
    assert "Please enter a valid units value" in shown[0][1]


def test_save_and_continue_plan_execution_step_applies_zero_unit_step_as_no_op_and_advances(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="10")])
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
    monkeypatch.setattr(host, "_advance_plan_execution_step", fake_advance)

    host._save_and_continue_plan_execution_step()

    assert apply_calls == [{"session": host.session, "step": host._current_step(), "calc_units": 0, "spent": Decimal("0")}]
    assert host._file_context_updates == 0
    assert advance_calls == 1


def test_save_and_continue_plan_execution_step_shows_quantity_error_and_advances(
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    host = make_wizard_host(steps=[make_plan_step(delta="-50")])
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
    monkeypatch.setattr(host, "_advance_plan_execution_step", fake_advance)

    host._save_and_continue_plan_execution_step()

    assert shown and shown[0][0] == "Cannot complete sell step"
    assert "tried to sell 3 units" in shown[0][1]
    assert advance_calls == 1


def test_exit_plan_execution_to_portfolio_returns_to_main_and_populates_editor(
    make_plan_step: Callable[..., PlanStep],
    make_wizard_host: Callable[..., Any],
) -> None:
    current_portfolio = object()
    host = make_wizard_host(steps=[make_plan_step(delta="10")], step_index=0, current_portfolio=current_portfolio)

    host._exit_plan_execution_to_portfolio()

    assert len(host._render_main_editor_calls) == 1
    assert host._render_main_editor_calls[0]["portfolio"] is current_portfolio
    assert host._render_main_editor_calls[0]["switch_to_main"] is True
    assert host.stack.current_widget is host.screen_main
