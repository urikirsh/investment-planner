from __future__ import annotations

"""Wizard-screen flow extracted from the main window controller.

This mixin encapsulates wizard screen wiring plus step calculation/save/advance
behavior so `MainWindow` can remain focused on high-level orchestration.

Wizard FX handling for USD-priced instruments is delegated to
`ui.wizard_fx_coordinator.WizardFxCoordinator`, which reads startup-cached
USD/ILS state and renders wizard FX panel context.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import cast

from contextlib import AbstractContextManager, nullcontext

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtWidgets import QLabel, QLineEdit, QStackedWidget, QTreeWidget, QWidget

from portfolio_core.domain.models import Currency, Portfolio
from portfolio_core.market_data import TickerLookupFound, get_cached_ticker_lookup_in_exchange
from portfolio_core.planning.calc_stock_units import BuyCalculation, calculate_buy_units_from_ils_price
from portfolio_core.session.portfolio_session import PortfolioSession
from portfolio_core.use_cases import InsufficientQuantityForSellError, PlanStep, apply_wizard_step
from ui.dialogs import show_error
from ui.screens.wizard_screen import WizardScreen
from ui.shared.constants import DEFAULT_CLEANUP_WAIT_MS
from ui.shared.ui_utils import BASE_CURRENCY_SUFFIX, DEFAULT_CURRENCY, normalize_and_validate_non_negative_integer_text
from ui.ui_state import PlanningState, WizardState
from ui.wizard_fx_coordinator import WizardFxCoordinator

D = Decimal
_DISPLAY_PRICE_PRECISION = D("0.01")


@dataclass(frozen=True)
class _CachedStepPrice:
    """Cached pricing context used to derive wizard trade calculations."""

    native_price: D
    native_currency: str
    price_ils: D
    display_text: str
    calculation_text: str


class MainWindowWizardMixin:
    """Mixin containing wizard screen setup and per-step execution flow."""

    session: PortfolioSession
    planning_state: PlanningState
    wizard_state: WizardState
    stack: QStackedWidget
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    screen_main: QWidget
    screen_wizard: WizardScreen
    wiz_info: QLabel
    units_label: QLabel
    units_edit: QLineEdit
    manual_rate_edit: QLineEdit
    wiz_result: QLabel
    _non_investable_bucket_id: str
    _non_investable_bucket_title: str
    _wizard_fx: WizardFxCoordinator

    def _quit_app(self) -> None:
        ...

    def _update_file_context_ui(self) -> None:
        ...

    def _update_future_tax_visual_state(self) -> None:
        ...

    def _render_main_editor_from_portfolio(self, portfolio: Portfolio, *, switch_to_main: bool) -> None:
        ...

    def _init_wizard_screen(self) -> None:
        """Build screen-4 wizard widget and wire wizard actions."""
        self.screen_wizard = WizardScreen(cast(QWidget, self))
        self.wiz_info = self.screen_wizard.wiz_info
        self.units_label = self.screen_wizard.units_label
        self.units_edit = self.screen_wizard.units_edit
        self.manual_rate_edit = self.screen_wizard.manual_rate_edit
        self.wiz_result = self.screen_wizard.wiz_result
        self.units_edit.textChanged.connect(self._wizard_units_changed)
        self.screen_wizard.quit_btn.clicked.connect(self._quit_app)
        self.screen_wizard.back_to_portfolio_btn.clicked.connect(self._wizard_back_to_portfolio)
        self.screen_wizard.save_continue_btn.clicked.connect(self._wizard_save_continue)
        self.screen_wizard.continue_without_save_btn.clicked.connect(self._wizard_continue_without_saving)
        self._invalidate_current_calc(reset_result=False, sync_widths=False)
        self._wizard_fx = WizardFxCoordinator(self)

    def _show_current_wizard_step(self) -> None:
        """Render current wizard step details and prefill units from cached price."""
        s = self._current_step()
        idx = self.planning_state.step_index + 1
        total = len(self.planning_state.plan_steps)

        action, _ = self._wizard_step_direction_labels(s.planned_delta_money)
        planned_amount_text = f"{abs(s.planned_delta_money)} {BASE_CURRENCY_SUFFIX}"
        self.screen_wizard.set_step_context(
            step_index=idx,
            total_steps=total,
            asset_group_name=s.asset_group_name,
            ticker=s.ticker,
            exchange=s.exchange,
            instrument_name=s.instrument_name,
            action=action,
            planned_amount_text=planned_amount_text,
        )
        self.screen_wizard.set_trade_mode(action=action)
        self._render_fx_panel_for_current_step()
        with self._signal_blocker(self.units_edit):
            self.units_edit.setText("")
        self._invalidate_current_calc(reset_result=True, sync_widths=False)
        self._prefill_units_from_cached_price()

    def _wizard_units_changed(self, _text: str) -> None:
        """Recalculate wizard totals whenever the entered units change."""
        self._recalculate_current_step_from_units()

    def _prefill_units_from_cached_price(self) -> None:
        """Populate the units field from the cached startup lookup price."""
        try:
            price = self._current_step_cached_price()
            s = self._current_step()
            default_calc = calculate_buy_units_from_ils_price(
                instrument_id=s.instrument_id,
                planned_money=abs(s.planned_delta_money),
                price_ils=price.price_ils,
            )
            with self._signal_blocker(self.units_edit):
                self.units_edit.setText(str(default_calc.units))
            self._apply_current_units(default_calc.units)
        except Exception as exc:
            self._invalidate_current_calc(reset_result=True, sync_widths=True)
            self.screen_wizard.set_units_error(str(exc))

    def _recalculate_current_step_from_units(self) -> None:
        """Validate units input and update calculation/validation UI."""
        raw_units = self.units_edit.text()
        _, units, error = normalize_and_validate_non_negative_integer_text(
            raw_units,
            field_label=self.units_label.text().rstrip(":"),
            required=True,
        )
        if error:
            self._invalidate_current_calc(reset_result=True, sync_widths=True)
            self.screen_wizard.set_units_error(error)
            return
        if units is None:
            self._invalidate_current_calc(reset_result=True, sync_widths=True)
            self.screen_wizard.set_units_error("Units are required.")
            return
        self._apply_current_units(units)

    def _apply_current_units(self, units: int) -> None:
        """Apply current units input to wizard calculation and save-button state."""
        try:
            calc = self._build_current_calc_for_units(units)
            validation_error = self._validate_calc_within_plan(calc)
            if validation_error:
                self.wizard_state.last_calc = None
                self._set_save_continue_enabled(False)
                self.screen_wizard.set_units_error(validation_error)
            else:
                self.wizard_state.last_calc = calc
                self._set_save_continue_enabled(True)
                self.screen_wizard.set_units_error("")
            self.screen_wizard.set_wizard_summary(self._format_wizard_summary_text(calc=calc))
            self.wiz_result.setText(self._format_wizard_result_text(calc=calc))
            self._sync_wizard_focus_row_widths()
        except Exception as exc:
            self._invalidate_current_calc(reset_result=True, sync_widths=True)
            self.screen_wizard.set_units_error(str(exc))

    def _build_current_calc_for_units(self, units: int) -> BuyCalculation:
        """Build calculation state for the current step and explicit units input."""
        price = self._current_step_cached_price()
        s = self._current_step()
        planned_money = abs(s.planned_delta_money)
        spent = price.price_ils * D(units)
        leftover = planned_money - spent
        return BuyCalculation(
            instrument_id=s.instrument_id,
            price=price.price_ils,
            planned_money=planned_money,
            units=units,
            spent=spent,
            leftover=leftover,
        )

    def _validate_calc_within_plan(self, calc: BuyCalculation) -> str:
        """Return inline validation error when entered units exceed the planned amount."""
        if calc.spent <= calc.planned_money:
            return ""
        _, money_label = self._wizard_step_direction_labels(self._current_step().planned_delta_money)
        action_word = "cost" if money_label.startswith("Spent") else "proceeds"
        return (
            f"Total {action_word} exceeds planned amount: "
            f"{calc.spent} {DEFAULT_CURRENCY.value} > {calc.planned_money} {DEFAULT_CURRENCY.value}."
        )

    def _current_step_cached_price(self) -> _CachedStepPrice:
        """Return cached startup lookup price for the active wizard step."""
        s = self._current_step()
        result = get_cached_ticker_lookup_in_exchange(exchange=s.exchange, ticker=s.ticker)
        if not isinstance(result, TickerLookupFound):
            raise ValueError(
                f"Cached price unavailable for {s.instrument_name}. Return to the welcome screen and try again."
            )
        native_price = result.metadata.last_traded_price
        if native_price is None:
            raise ValueError(
                f"Cached price unavailable for {s.instrument_name}. Return to the welcome screen and try again."
            )
        if s.exchange.currency == Currency.USD:
            usd_ils_rate = self._get_effective_usd_ils_rate()
            price_ils = native_price * usd_ils_rate
            return _CachedStepPrice(
                native_price=native_price,
                native_currency=s.exchange.currency.value,
                price_ils=price_ils,
                display_text=f"{self._format_decimal_for_display(native_price)} {s.exchange.currency.value}",
                calculation_text=(
                    f"{self._format_decimal_for_display(native_price)} {s.exchange.currency.value} x "
                    f"{self._format_decimal_for_display(usd_ils_rate)} = "
                    f"{self._format_decimal_for_display(price_ils)} {DEFAULT_CURRENCY.value}"
                ),
            )
        return _CachedStepPrice(
            native_price=native_price,
            native_currency=DEFAULT_CURRENCY.value,
            price_ils=native_price,
            display_text=f"{self._format_decimal_for_display(native_price)} {DEFAULT_CURRENCY.value}",
            calculation_text=f"{self._format_decimal_for_display(native_price)} {DEFAULT_CURRENCY.value}",
        )

    def _get_effective_usd_ils_rate(self) -> D:
        """Return startup-cached USD/ILS rate for current wizard run."""
        if self.wizard_state.usd_ils_rate is not None:
            return self.wizard_state.usd_ils_rate
        raise ValueError("USD/ILS rate unavailable. Return to the welcome screen and try again.")

    def _reset_wizard_fx_state_for_new_run(self) -> bool:
        """Reset transient USD/ILS state for a new run."""
        return self._wizard_fx_coordinator().reset_wizard_fx_state_for_new_run()

    def _cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Run wizard FX cleanup seam (currently a no-op compatibility call)."""
        return self._wizard_fx_coordinator().cancel_wizard_fx_fetch(wait_timeout_ms=wait_timeout_ms)

    def _render_fx_panel_for_current_step(self) -> None:
        """Render FX cached-rate status for the active step."""
        self._wizard_fx_coordinator().render_fx_panel_for_current_step()

    def _wizard_fx_coordinator(self) -> WizardFxCoordinator:
        """Lazily create coordinator for tests that bypass widget initialization."""
        if not hasattr(self, "_wizard_fx"):
            self._wizard_fx = WizardFxCoordinator(self)
        return self._wizard_fx

    def _try_finish_wizard_fx_cleanup(self) -> bool:
        """Run wizard FX cleanup guard before leaving wizard flow."""
        if self._cancel_wizard_fx_fetch():
            return True
        show_error(
            cast(QWidget, self),
            "Please wait",
            "Still finishing cleanup tasks. Try again in a few seconds.",
        )
        return False

    def _wizard_save_continue(self) -> None:
        """Apply current step trade, persist if applied, then advance."""
        try:
            self._require_current_portfolio()

            s = self._current_step()
            if self.wizard_state.last_calc is None:
                raise ValueError("Please enter a valid units value before saving this step.")
            calc_units = self.wizard_state.last_calc.units
            spent = self.wizard_state.last_calc.spent

            applied = apply_wizard_step(self.session, s, calc_units, spent)
            if applied:
                self._update_file_context_ui()

            self._advance_wizard_step()
        except InsufficientQuantityForSellError as exc:
            show_error(
                cast(QWidget, self),
                "Cannot complete sell step",
                (
                    f"{exc.instrument_name}: tried to sell {exc.requested_units} units, "
                    f"but only {exc.available_units} units are available.\n\n"
                    "This step was skipped. Update the instrument quantity in the main screen if needed."
                ),
            )
            self._advance_wizard_step()
        except Exception as exc:
            show_error(cast(QWidget, self), "Save failed", str(exc))

    def _set_save_continue_enabled(self, enabled: bool) -> None:
        """Enable/disable step commit action based on calculation validity."""
        self.screen_wizard.save_continue_btn.setEnabled(enabled)

    def _invalidate_current_calc(self, *, reset_result: bool, sync_widths: bool) -> None:
        """Clear cached calculation and disable save for the current step."""
        self.wizard_state.last_calc = None
        self._set_save_continue_enabled(False)
        if reset_result:
            self._set_wizard_result_placeholder_for_current_step()
        if sync_widths:
            self._sync_wizard_focus_row_widths()

    def _wizard_step_direction_labels(self, planned_delta_money: D) -> tuple[str, str]:
        """Return `(action_label, money_label)` for step direction."""
        if planned_delta_money > 0:
            return ("BUY", f"Spent {BASE_CURRENCY_SUFFIX}")
        return ("SELL", f"Proceeds {BASE_CURRENCY_SUFFIX}")

    def _format_wizard_summary_text(self, *, calc: BuyCalculation) -> str:
        """Build the top summary line above the units input."""
        price = self._current_step_cached_price()
        return (
            f"Planned: {self._format_decimal_for_display(calc.planned_money)} {DEFAULT_CURRENCY.value} | "
            f"Price: {self._format_decimal_for_display(price.price_ils)} {DEFAULT_CURRENCY.value}/unit | "
            f"Recommended: {self._recommended_units_for_current_step()} units"
        )

    def _format_wizard_result_text(self, *, calc: BuyCalculation) -> str:
        """Build the totals line shown below the units input."""
        _, money_label = self._wizard_step_direction_labels(self._current_step().planned_delta_money)
        total_label = "Total spend" if money_label.startswith("Spent") else "Total proceeds"
        return (
            f"{total_label}: {self._format_decimal_for_display(calc.spent)} {DEFAULT_CURRENCY.value} | "
            f"Leftover: {self._format_decimal_for_display(calc.leftover)} {DEFAULT_CURRENCY.value}"
        )

    def _set_wizard_result_placeholder_for_current_step(self) -> None:
        """Render action-specific placeholder text before calculation."""
        self.screen_wizard.set_wizard_summary("Planned: - ILS | Price: - ILS/unit | Recommended: - units")
        self.wiz_result.setText("Total spend/proceeds: - ILS | Leftover: - ILS")

    def _sync_wizard_focus_row_widths(self) -> None:
        """Refresh optional focus-row width alignment on wizard result changes."""
        self.screen_wizard.sync_focus_row_widths()

    def _current_step(self) -> PlanStep:
        """Return the active wizard step from planning state."""
        return self.planning_state.plan_steps[self.planning_state.step_index]

    def _require_current_portfolio(self) -> None:
        """Validate that wizard flow has a loaded current portfolio."""
        if self.session.document.current_portfolio is None:
            raise ValueError("No portfolio loaded")

    def _wizard_continue_without_saving(self) -> None:
        """Skip current step without mutating portfolio and move forward."""
        try:
            self._require_current_portfolio()
            self._advance_wizard_step()
        except Exception as exc:
            show_error(cast(QWidget, self), "Continue failed", str(exc))

    def _wizard_back_to_portfolio(self) -> None:
        """Exit wizard early and return to main editor without applying the active step."""
        try:
            self._require_current_portfolio()
            if not self._try_finish_wizard_fx_cleanup():
                return
            self._return_to_main_editor_from_current_portfolio()
        except Exception as exc:
            show_error(cast(QWidget, self), "Back failed", str(exc))

    def _return_to_main_editor_from_current_portfolio(self) -> None:
        """Populate main editor from current portfolio and switch to screen 2."""
        self._require_current_portfolio()
        current = self.session.document.current_portfolio
        if current is None:
            return
        self._render_main_editor_from_portfolio(current, switch_to_main=True)

    def _advance_wizard_step(self) -> None:
        """Move to next step, or repopulate main editor and return when complete."""
        self.planning_state.step_index += 1
        if self.planning_state.step_index >= len(self.planning_state.plan_steps):
            if not self._try_finish_wizard_fx_cleanup():
                self.planning_state.step_index -= 1
                return
            self._return_to_main_editor_from_current_portfolio()
        else:
            self._show_current_wizard_step()

    @staticmethod
    def _format_decimal_for_display(value: D) -> str:
        """Format numeric display values with up to two decimal places."""
        quantized = value.quantize(_DISPLAY_PRICE_PRECISION, rounding=ROUND_HALF_UP)
        normalized = format(quantized, "f")
        if "." not in normalized:
            return normalized
        return normalized.rstrip("0").rstrip(".")

    def _recommended_units_for_current_step(self) -> int:
        """Return the recommended whole-unit count from the cached unit price."""
        price = self._current_step_cached_price()
        s = self._current_step()
        default_calc = calculate_buy_units_from_ils_price(
            instrument_id=s.instrument_id,
            planned_money=abs(s.planned_delta_money),
            price_ils=price.price_ils,
        )
        return default_calc.units

    @staticmethod
    def _signal_blocker(widget: object) -> AbstractContextManager[object]:
        """Return a signal blocker context when available, otherwise a no-op."""
        if isinstance(widget, QObject):
            return QSignalBlocker(widget)
        return nullcontext()
