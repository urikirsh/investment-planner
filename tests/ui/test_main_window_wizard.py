from __future__ import annotations

"""Focused tests for ``MainWindowWizardMixin`` behavior."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from portfolio_core.models import Exchange
from portfolio_core.fx_service import UsdIlsRateQuote
from portfolio_core.portfolio_session import CachedUsdIlsQuote
from portfolio_core.use_cases import InsufficientQuantityForSellError, PlanStep
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
        self._placeholder = ""

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text

    def setPlaceholderText(self, text: str) -> None:
        self._placeholder = text

    def placeholderText(self) -> str:
        return self._placeholder


class _FakeButton:
    """Minimal button double exposing enabled-state mutation."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def isEnabled(self) -> bool:
        return self._enabled


class _FakeWizardScreen:
    """Minimal wizard-screen double exposing price-mode behavior."""

    def __init__(self, price_label: _FakeLabel, price_edit: _FakeLineEdit) -> None:
        self._price_label = price_label
        self._price_edit = price_edit
        self.fx_visible = False
        self.fx_info_text = ""
        self.fx_error_text = ""
        self.manual_visible = False
        self.calculate_btn = _FakeButton()
        self.save_continue_btn = _FakeButton(False)

    def set_price_mode(self, exchange: Exchange) -> None:
        if exchange.currency == Exchange.NYSE.currency:
            self._price_label.setText(f"Price ({Exchange.NYSE.currency.value}):")
            self._price_edit.setPlaceholderText(f"Enter unit price in {Exchange.NYSE.currency.value} (e.g. 12.34)")
            return
        self._price_label.setText("Price (Agorot):")
        self._price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")

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
        if manual_visible and manual_value:
            self._price_edit.setText(self._price_edit.text())
        _ = manual_value


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
    screen_wizard: Any
    tree: Any
    cash_value_edit: Any
    cash_reserve_edit: Any
    future_tax_edit: Any
    price_edit: Any
    price_label: Any
    manual_rate_edit: Any
    wiz_info: Any
    wiz_result: Any
    _file_context_updates: int
    _future_tax_updates: int

    def __init__(self, *, steps: list[PlanStep], step_index: int = 0, current_portfolio: object | None = object()) -> None:
        self.session = SimpleNamespace(
            document=SimpleNamespace(current_portfolio=current_portfolio),
            read_cached_usd_ils_quote=lambda: None,
            write_cached_usd_ils_quote=lambda **_kwargs: None,
        )
        self.planning_state = SimpleNamespace(plan_steps=steps, step_index=step_index)
        self.wizard_state = SimpleNamespace(
            last_calc=None,
            usd_ils_rate=None,
            usd_ils_rate_date=None,
            usd_ils_used_last_published=False,
            usd_ils_fetch_attempted=False,
            usd_ils_fetch_error=None,
            manual_override_usd_ils_rate=None,
            usd_ils_fetch_in_progress=False,
            usd_ils_failure_dialog_shown=False,
            usd_ils_rate_from_cache=False,
            usd_ils_rate_cached_at=None,
            usd_ils_fetch_generation=1,
            usd_ils_active_fetch_generation=1,
        )
        self.stack = _FakeStack()
        self.screen_main = object()
        self.tree = object()
        self.cash_value_edit = object()
        self.cash_reserve_edit = object()
        self.future_tax_edit = object()
        self.price_edit = _FakeLineEdit()
        self.manual_rate_edit = _FakeLineEdit()
        self.price_label = _FakeLabel()
        self.screen_wizard = _FakeWizardScreen(self.price_label, self.price_edit)
        self.wiz_info = _FakeLabel()
        self.wiz_result = _FakeLabel()
        self._non_investable_bucket_id = "non_investable_bucket"
        self._non_investable_bucket_title = "Non-investable holdings (excluded from strategy)"
        self._file_context_updates = 0
        self._future_tax_updates = 0
        self._fx_fetch_thread = None
        self._fx_fetch_worker = None

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
    assert "Planned BUY value (ILS): 125" in host.wiz_info.value
    assert host.price_label.value == "Price (Agorot):"
    assert host.price_edit.text() == ""
    assert host.wiz_result.value == "Units: - | Spent/Proceeds (ILS): - | Leftover vs plan (ILS): -"
    assert host.wizard_state.last_calc is None
    assert host.screen_wizard.save_continue_btn.isEnabled() is False


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
    assert host.wiz_result.value == "Units: 5 | Proceeds (ILS): 50 | Leftover vs plan (ILS): 0"
    assert host.screen_wizard.save_continue_btn.isEnabled() is True


def test_wizard_calculate_usd_converts_to_ils_and_shows_conversion_line(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.price_edit = _FakeLineEdit("10")
    host.manual_rate_edit = _FakeLineEdit("")
    host.price_label = _FakeLabel()
    host.screen_wizard = _FakeWizardScreen(host.price_label, host.price_edit)
    host.wizard_state.usd_ils_rate = Decimal("3.1")
    host.wizard_state.usd_ils_rate_date = None

    host._show_current_wizard_step()
    host.price_edit.setText("10")
    host._wizard_calculate()

    assert host.wizard_state.last_calc is not None
    assert host.wizard_state.last_calc.units == 1
    assert host.wizard_state.last_calc.spent == Decimal("31")
    assert host.wizard_state.last_calc.leftover == Decimal("19")
    assert host.price_label.value == "Price (USD):"
    assert "Converted: 10 USD x 3.1 = 31.0 ILS" in host.wiz_result.value
    assert "Units: 1 | Spent (ILS): 31" in host.wiz_result.value


def test_wizard_calculate_usd_uses_manual_override_when_fetch_failed(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.price_edit = _FakeLineEdit("10")
    host.manual_rate_edit = _FakeLineEdit("3.2")
    host.price_label = _FakeLabel()
    host.screen_wizard = _FakeWizardScreen(host.price_label, host.price_edit)
    host.wizard_state.usd_ils_fetch_error = "network"

    host._show_current_wizard_step()
    host.price_edit.setText("10")
    host._wizard_calculate()

    assert host.wizard_state.manual_override_usd_ils_rate == Decimal("3.2")
    assert host.wizard_state.last_calc is not None
    assert host.wizard_state.last_calc.spent == Decimal("32")


def test_wizard_calculate_usd_without_rate_or_override_blocks_calculation(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.price_edit = _FakeLineEdit("10")
    host.manual_rate_edit = _FakeLineEdit("")
    host.wizard_state.usd_ils_fetch_error = "network"
    errors: list[tuple[str, str]] = []

    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: errors.append((t, m)))

    host._wizard_calculate()

    assert host.wizard_state.last_calc is None
    assert host.screen_wizard.save_continue_btn.isEnabled() is False
    assert errors
    assert errors[0][0] == "Calculation failed"
    assert "USD/ILS rate unavailable" in errors[0][1]


def test_wizard_implicit_failure_clears_last_calc_and_disables_save(
    make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="20")])
    host.wizard_state.last_calc = SimpleNamespace(units=2, spent=Decimal("20"), leftover=Decimal("0"))
    host.screen_wizard.save_continue_btn.setEnabled(True)
    host.price_edit.setText("bad-price")

    host._wizard_calculate_implicit()

    assert host.wizard_state.last_calc is None
    assert host.screen_wizard.save_continue_btn.isEnabled() is False
    assert "Calculation not updated:" in host.wiz_result.value


def test_wizard_implicit_empty_input_clears_last_calc_and_disables_save(
    make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="20")])
    host.wizard_state.last_calc = SimpleNamespace(units=2, spent=Decimal("20"), leftover=Decimal("0"))
    host.screen_wizard.save_continue_btn.setEnabled(True)
    host.price_edit.setText("   ")

    host._wizard_calculate_implicit()

    assert host.wizard_state.last_calc is None
    assert host.screen_wizard.save_continue_btn.isEnabled() is False


def test_prepare_wizard_fx_rate_cache_fetches_at_most_once_per_run(
    make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])

    host._on_fx_fetch_finished(
        UsdIlsRateQuote(
            rate=Decimal("3.9"),
            effective_date=datetime.fromisoformat("2026-03-01T00:00:00").date(),
            used_last_published=False,
        ),
        None,
        1,
    )

    assert host.wizard_state.usd_ils_rate == Decimal("3.9")
    assert host.wizard_state.usd_ils_fetch_error is None


def test_prepare_wizard_fx_rate_cache_skips_when_no_usd_steps(
    make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.TASE)])

    host._prepare_wizard_fx_rate_cache()

    assert host.wizard_state.usd_ils_fetch_attempted is False


def test_prepare_wizard_fx_rate_cache_aborts_when_previous_fetch_still_running(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(host, "_cancel_wizard_fx_fetch", lambda **_kwargs: False)
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    host._prepare_wizard_fx_rate_cache()

    assert host.wizard_state.usd_ils_fetch_attempted is False
    assert shown and shown[0][0] == "Please wait"


def test_on_fx_fetch_finished_uses_cached_quote_after_failure(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.session.read_cached_usd_ils_quote = lambda: CachedUsdIlsQuote(
        rate=Decimal("3.8"),
        effective_date=datetime.fromisoformat("2026-03-01T00:00:00").date(),
        used_last_published=False,
        cached_at=datetime.fromisoformat("2026-03-05T12:00:00+00:00"),
    )
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    host._on_fx_fetch_finished(None, "network", 1)

    assert host.wizard_state.usd_ils_rate == Decimal("3.8")
    assert host.wizard_state.usd_ils_rate_from_cache is True
    assert shown and shown[0][0] == "Official USD/ILS fetch failed"
    assert "Using cached USD/ILS rate" in shown[0][1]


def test_on_fx_fetch_finished_requires_manual_when_cache_unreadable(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.session.read_cached_usd_ils_quote = lambda: None
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    host._on_fx_fetch_finished(None, "network", 1)

    assert host.wizard_state.usd_ils_rate is None
    assert host.wizard_state.usd_ils_rate_from_cache is False
    assert shown and shown[0][0] == "Official USD/ILS fetch failed"
    assert "No readable cached rate is available" in shown[0][1]


def test_reset_wizard_fx_state_clears_manual_override_and_input(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.wizard_state.manual_override_usd_ils_rate = Decimal("3.4")
    host.wizard_state.usd_ils_fetch_attempted = True
    host.manual_rate_edit.setText("3.4")

    result = host._reset_wizard_fx_state_for_new_run()

    assert result is True
    assert host.wizard_state.manual_override_usd_ils_rate is None
    assert host.wizard_state.usd_ils_fetch_attempted is False
    assert host.manual_rate_edit.text() == ""


def test_reset_wizard_fx_state_returns_false_when_cancel_fails(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.wizard_state.manual_override_usd_ils_rate = Decimal("3.4")
    host.manual_rate_edit.setText("3.4")
    setattr(host, "_cancel_wizard_fx_fetch", lambda **_kwargs: False)

    result = host._reset_wizard_fx_state_for_new_run()

    assert result is False
    assert host.wizard_state.manual_override_usd_ils_rate == Decimal("3.4")


def test_on_fx_fetch_finished_ignores_stale_generation(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.wizard_state.usd_ils_active_fetch_generation = 2
    host.wizard_state.usd_ils_rate = Decimal("3.7")

    host._on_fx_fetch_finished(
        UsdIlsRateQuote(
            rate=Decimal("3.9"),
            effective_date=datetime.fromisoformat("2026-03-01T00:00:00").date(),
            used_last_published=False,
        ),
        None,
        1,
    )

    assert host.wizard_state.usd_ils_rate == Decimal("3.7")


def test_wizard_save_continue_requires_successful_calculation(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="10")])
    host.wizard_state.last_calc = None

    shown: list[tuple[str, str]] = []
    apply_calls: list[dict[str, Any]] = []
    advance_calls = 0

    def fake_apply(session: Any, step: Any, calc_units: int, spent: Decimal) -> bool:
        apply_calls.append({"session": session, "step": step, "calc_units": calc_units, "spent": spent})
        return True

    def fake_advance() -> None:
        nonlocal advance_calls
        advance_calls += 1

    monkeypatch.setattr(wizard_mod, "apply_wizard_step", fake_apply)
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))
    monkeypatch.setattr(host, "_advance_wizard_step", fake_advance)

    host._wizard_save_continue()

    assert apply_calls == []
    assert shown and shown[0][0] == "Save failed"
    assert "Please calculate units before saving this step." in shown[0][1]
    assert host._file_context_updates == 0
    assert advance_calls == 0


def test_wizard_save_continue_shows_quantity_error_and_advances(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
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
    assert "only 1 units are available" in shown[0][1]
    assert advance_calls == 1


def test_wizard_back_to_portfolio_returns_to_main_and_populates_editor(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    current_portfolio = object()
    host = _FakeHost(steps=[make_plan_step(delta="10")], step_index=0, current_portfolio=current_portfolio)
    populate_calls: list[dict[str, Any]] = []

    def fake_populate_main_editor_from_portfolio(**kwargs: Any) -> None:
        populate_calls.append(kwargs)

    monkeypatch.setattr(wizard_mod, "populate_main_editor_from_portfolio", fake_populate_main_editor_from_portfolio)

    host._wizard_back_to_portfolio()

    assert host.planning_state.step_index == 0
    assert len(populate_calls) == 1
    assert populate_calls[0]["portfolio"] is current_portfolio
    assert host.stack.current_widget is host.screen_main


def test_wizard_back_to_portfolio_blocks_when_cancel_fails(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    host = _FakeHost(steps=[make_plan_step(delta="10")], step_index=0, current_portfolio=object())
    shown: list[tuple[str, str]] = []
    setattr(host, "_cancel_wizard_fx_fetch", lambda **_kwargs: False)
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    host._wizard_back_to_portfolio()

    assert shown and shown[0][0] == "Please wait"
    assert host.stack.current_widget is None


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


def test_advance_wizard_step_blocks_finish_when_cancel_fails(
    monkeypatch: pytest.MonkeyPatch, make_plan_step: Callable[..., PlanStep]
) -> None:
    current_portfolio = object()
    host = _FakeHost(steps=[make_plan_step(delta="10")], step_index=0, current_portfolio=current_portfolio)
    setattr(host, "_cancel_wizard_fx_fetch", lambda **_kwargs: False)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    host._advance_wizard_step()

    assert host.planning_state.step_index == 0
    assert shown and shown[0][0] == "Please wait"
