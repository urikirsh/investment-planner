from __future__ import annotations

"""Focused tests for ``MainWindowWizardMixin`` behavior."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from portfolio_core.use_cases import PlanStep
import ui.main_window_wizard as wizard_mod
from ui.main_window_wizard import MainWindowWizardMixin


class _FakeLabel:
    """Minimal label double with a ``setText`` sink used by assertions."""

    def __init__(self) -> None:
        self.value = ""

    def setText(self, text: str) -> None:
        self.value = text


class _FakeLineEdit:
    """Minimal line-edit double supporting read/write text operations."""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text


class _FakeStack:
    """Minimal stack double capturing the last requested current widget."""

    def __init__(self) -> None:
        self.current_widget: object | None = None

    def setCurrentWidget(self, widget: object) -> None:
        self.current_widget = widget


class _FakeHost(MainWindowWizardMixin):
    """Minimal host implementing dependencies required by the mixin."""

    session: Any
    planning_state: Any
    wizard_state: Any
    stack: Any
    screen_main: Any
    tree: Any
    cash_value_edit: Any
    cash_reserve_edit: Any
    future_tax_edit: Any
    price_edit: Any
    wiz_info: Any
    wiz_result: Any
    _file_context_updates: int
    _future_tax_updates: int

    def __init__(self, *, steps: list[PlanStep], step_index: int = 0, current_portfolio: object | None = object()) -> None:
        self.session = SimpleNamespace(document=SimpleNamespace(current_portfolio=current_portfolio))
        self.planning_state = SimpleNamespace(plan_steps=steps, step_index=step_index)
        self.wizard_state = SimpleNamespace(last_calc=SimpleNamespace(unused=True))
        self.stack = _FakeStack()
        self.screen_main = object()
        self.tree = object()
        self.cash_value_edit = object()
        self.cash_reserve_edit = object()
        self.future_tax_edit = object()
        self.price_edit = _FakeLineEdit()
        self.wiz_info = _FakeLabel()
        self.wiz_result = _FakeLabel()
        self._non_investable_bucket_id = "non_investable_bucket"
        self._non_investable_bucket_title = "Non-investable holdings (excluded from strategy)"
        self._file_context_updates = 0
        self._future_tax_updates = 0

    def _quit_app(self) -> None:
        return None

    def _update_file_context_ui(self) -> None:
        self._file_context_updates += 1

    def _update_future_tax_visual_state(self) -> None:
        self._future_tax_updates += 1


def test_show_current_wizard_step_updates_labels_and_resets_calc(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="125")])
    host.wizard_state.last_calc = SimpleNamespace(units=9)

    host._show_current_wizard_step()

    assert "Step 1/1" in host.wiz_info.value
    assert "Planned BUY value: 125" in host.wiz_info.value
    assert host.price_edit.text() == ""
    assert host.wiz_result.value == "Units: - | Spent/Proceeds: - | Leftover vs plan: -"
    assert host.wizard_state.last_calc is None


def test_wizard_calculate_sets_last_calc_and_result_text(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="-50")])
    host.price_edit = _FakeLineEdit("10")

    fake_calc = SimpleNamespace(units=5, spent=Decimal("50"), leftover=Decimal("0"))
    calls: list[dict[str, Any]] = []

    def fake_calculate_buy_units(*, instrument_id: str, planned_money: Decimal, price_ag: Decimal) -> Any:
        calls.append({"instrument_id": instrument_id, "planned_money": planned_money, "price_ag": price_ag})
        return fake_calc

    monkeypatch.setattr(wizard_mod, "calculate_buy_units", fake_calculate_buy_units)

    host._wizard_calculate()

    assert calls == [{"instrument_id": "ins-1", "planned_money": Decimal("50"), "price_ag": Decimal("10")}]
    assert host.wizard_state.last_calc is fake_calc
    assert host.wiz_result.value == "Units: 5 | Proceeds: 50 | Leftover vs plan: 0"


def test_wizard_save_continue_uses_zero_when_no_last_calc(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="10")])
    host.wizard_state.last_calc = None

    apply_calls: list[dict[str, Any]] = []
    advance_calls = 0

    def fake_apply(session: Any, step: Any, calc_units: int, spent: Decimal) -> bool:
        apply_calls.append({"session": session, "step": step, "calc_units": calc_units, "spent": spent})
        return True

    def fake_advance() -> None:
        nonlocal advance_calls
        advance_calls += 1

    monkeypatch.setattr(wizard_mod, "apply_wizard_step", fake_apply)
    monkeypatch.setattr(host, "_advance_wizard_step", fake_advance)

    host._wizard_save_continue()

    assert len(apply_calls) == 1
    assert apply_calls[0]["session"] is host.session
    assert apply_calls[0]["step"] is host.planning_state.plan_steps[0]
    assert apply_calls[0]["calc_units"] == 0
    assert apply_calls[0]["spent"] == Decimal("0")
    assert host._file_context_updates == 1
    assert advance_calls == 1


def test_advance_wizard_step_shows_next_step_when_more_steps(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="10"), make_plan_step(delta="20")], step_index=0)
    show_calls = 0

    def fake_show() -> None:
        nonlocal show_calls
        show_calls += 1

    monkeypatch.setattr(host, "_show_current_wizard_step", fake_show)

    host._advance_wizard_step()

    assert host.planning_state.step_index == 1
    assert show_calls == 1
    assert host.stack.current_widget is None


def test_advance_wizard_step_returns_to_main_and_populates_editor(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    current_portfolio = object()
    host = _FakeHost(steps=[make_plan_step(delta="10")], step_index=0, current_portfolio=current_portfolio)
    populate_calls: list[dict[str, Any]] = []

    def fake_populate_main_editor_from_portfolio(**kwargs: Any) -> None:
        populate_calls.append(kwargs)

    monkeypatch.setattr(wizard_mod, "populate_main_editor_from_portfolio", fake_populate_main_editor_from_portfolio)

    host._advance_wizard_step()

    assert host.planning_state.step_index == 1
    assert len(populate_calls) == 1
    assert populate_calls[0]["portfolio"] is current_portfolio
    assert host.stack.current_widget is host.screen_main
