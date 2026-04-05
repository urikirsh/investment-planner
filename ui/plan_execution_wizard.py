from __future__ import annotations

"""Wizard-screen flow extracted from the main window controller.

This mixin owns the per-step execution flow after planning summary review:
- render current step context,
- resolve startup-cached instrument prices into an ILS unit price,
- prefill and validate whole-unit counts,
- apply or skip the current step,
- return to the main editor when the wizard ends.

Wizard FX handling for USD-priced instruments is delegated to
`ui.wizard_fx_coordinator.WizardFxCoordinator`, which reads startup-cached
USD/ILS state and renders wizard FX panel context.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import cast

from contextlib import AbstractContextManager, nullcontext

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtWidgets import QLabel, QLineEdit, QSpinBox, QStackedWidget, QTreeWidget, QWidget

from portfolio_core.domain.models import Currency, Portfolio
from portfolio_core.planning.calc_stock_units import BuyCalculation, calculate_buy_units_from_ils_price
from portfolio_core.session.portfolio_session import PortfolioSession
from portfolio_core.workflows import InsufficientQuantityForSellError, PlanStep, apply_wizard_step
from ui.dialogs import show_error
from ui.screens.wizard_screen import WizardScreen
from ui.shared.cached_instrument_pricing import resolve_cached_instrument_price_ils
from ui.shared.constants import DEFAULT_CLEANUP_WAIT_MS
from ui.shared.ui_utils import BASE_CURRENCY_SUFFIX, DEFAULT_CURRENCY, fmt_decimal_grouped
from ui.ui_state import PlanningState, WizardState
from ui.wizard_fx_coordinator import WizardFxCoordinator

D = Decimal
_DISPLAY_PRICE_PRECISION = D("0.01")


@dataclass(frozen=True)
class _WizardCalculationContext:
    """Immutable current-step pricing/label context reused across recalculation."""

    step: PlanStep
    price_ils: D
    recommended_units: int
    total_label: str


class MainWindowPlanExecutionMixin:
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
    units_edit: QSpinBox
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
        self.wiz_result = self.screen_wizard.wiz_result
        self.units_edit.valueChanged.connect(self._wizard_units_changed)
        self.screen_wizard.quit_btn.clicked.connect(self._quit_app)
        self.screen_wizard.back_to_portfolio_btn.clicked.connect(self._exit_plan_execution_to_portfolio)
        self.screen_wizard.save_continue_btn.clicked.connect(self._save_and_continue_plan_execution_step)
        self.screen_wizard.continue_without_save_btn.clicked.connect(self._skip_plan_execution_step)
        self._invalidate_current_calc(reset_result=False, sync_widths=False)
        self._wizard_fx = WizardFxCoordinator(self)

    def _show_current_plan_execution_step(self) -> None:
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
            self.units_edit.setValue(0)
            self.screen_wizard.set_units_limit(value=0)
        self._invalidate_current_calc(reset_result=True, sync_widths=False)
        self._prefill_units_from_cached_price()

    def _wizard_units_changed(self, _value: int) -> None:
        """Recalculate wizard totals whenever the entered units change."""
        self._recalculate_current_step_from_units()

    def _prefill_units_from_cached_price(self) -> None:
        """Populate the spinner from the cached price-derived recommended units.

        The UI caps the spinner to the recommendation, so the user can reduce
        the trade amount (including to zero) but cannot increase it above the
        startup-planned whole-unit quantity.
        """
        try:
            context = self._current_wizard_calculation_context()
            with self._signal_blocker(self.units_edit):
                self.screen_wizard.set_units_limit(value=context.recommended_units)
                self.units_edit.setValue(context.recommended_units)
            self._apply_current_units(context.recommended_units)
        except Exception as exc:
            self._invalidate_current_calc(reset_result=True, sync_widths=True)
            self.screen_wizard.set_units_error(str(exc))

    def _recalculate_current_step_from_units(self) -> None:
        """Validate units input and update calculation/validation UI."""
        self._apply_current_units(self.units_edit.value())

    def _apply_current_units(self, units: int) -> None:
        """Apply current units input to wizard calculation and save-button state."""
        try:
            context = self._current_wizard_calculation_context()
            calc = self._build_current_calc_for_units(context=context, units=units)
            validation_error = self._validate_calc_within_plan(calc)
            self._render_calculation_state(
                context=context,
                calc=calc,
                validation_error=validation_error,
            )
        except Exception as exc:
            self._invalidate_current_calc(reset_result=True, sync_widths=True)
            self.screen_wizard.set_units_error(str(exc))

    def _render_calculation_state(
        self,
        *,
        context: _WizardCalculationContext,
        calc: BuyCalculation,
        validation_error: str,
    ) -> None:
        """Render summary/result rows plus save availability for one units value."""
        has_error = bool(validation_error)
        self.wizard_state.last_calc = None if has_error else calc
        self._set_save_continue_enabled(not has_error)
        self.screen_wizard.set_units_error(validation_error)
        self.screen_wizard.set_wizard_summary(self._format_wizard_summary_text(context=context, calc=calc))
        self.wiz_result.setText(self._format_wizard_result_text(calc=calc, total_label=context.total_label))
        self._sync_wizard_focus_row_widths()

    def _build_current_calc_for_units(self, *, context: _WizardCalculationContext, units: int) -> BuyCalculation:
        """Build calculation state for the current step and explicit units input."""
        planned_money = abs(context.step.planned_delta_money)
        spent = context.price_ils * D(units)
        leftover = planned_money - spent
        return BuyCalculation(
            instrument_id=context.step.instrument_id,
            price=context.price_ils,
            planned_money=planned_money,
            units=units,
            spent=spent,
            leftover=leftover,
        )

    def _validate_calc_within_plan(self, calc: BuyCalculation) -> str:
        """Return inline validation error when entered units exceed the planned amount."""
        if calc.spent <= calc.planned_money:
            return ""
        action_word = "cost" if self._current_step().planned_delta_money > 0 else "proceeds"
        return (
            f"Total {action_word} exceeds planned amount: "
            f"{self._format_decimal_for_display(calc.spent)} {DEFAULT_CURRENCY.value} > "
            f"{self._format_decimal_for_display(calc.planned_money)} {DEFAULT_CURRENCY.value}."
        )

    def _current_step_cached_price_ils(self, step: PlanStep) -> D:
        """Return startup-cached per-unit price for the active wizard step.

        TASE prices are already stored in ILS. NYSE prices are converted to ILS
        using the wizard's startup-cached USD/ILS rate so unit calculations stay
        in one currency.
        """
        usd_ils_rate = self._get_effective_usd_ils_rate() if step.exchange.currency == Currency.USD else None
        return resolve_cached_instrument_price_ils(
            exchange=step.exchange,
            ticker=step.ticker,
            instrument_name=step.instrument_name,
            usd_ils_rate=usd_ils_rate,
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

    def _save_and_continue_plan_execution_step(self) -> None:
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

            self._advance_plan_execution_step()
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
            self._advance_plan_execution_step()
        except Exception as exc:
            show_error(cast(QWidget, self), "Save failed", str(exc))

    def _set_save_continue_enabled(self, enabled: bool) -> None:
        """Enable/disable step commit action based on calculation validity."""
        self.screen_wizard.save_continue_btn.setEnabled(enabled)

    def _invalidate_current_calc(self, *, reset_result: bool, sync_widths: bool) -> None:
        """Clear cached calculation and disable save for the current step."""
        self.wizard_state.last_calc = None
        self._set_save_continue_enabled(False)
        self.screen_wizard.set_units_error("")
        if reset_result:
            self._set_wizard_result_placeholder_for_current_step()
        if sync_widths:
            self._sync_wizard_focus_row_widths()

    def _wizard_step_direction_labels(self, planned_delta_money: D) -> tuple[str, str]:
        """Return `(action_label, money_label)` for step direction."""
        if planned_delta_money > 0:
            return ("BUY", f"Spent {BASE_CURRENCY_SUFFIX}")
        return ("SELL", f"Proceeds {BASE_CURRENCY_SUFFIX}")

    def _format_wizard_summary_text(self, *, context: _WizardCalculationContext, calc: BuyCalculation) -> str:
        """Build the top summary line above the units input."""
        return (
            f"Planned: {self._format_decimal_for_display(calc.planned_money)} {DEFAULT_CURRENCY.value} | "
            f"Price: {self._format_decimal_for_display(context.price_ils)} {DEFAULT_CURRENCY.value}/unit | "
            f"Recommended: {context.recommended_units} units"
        )

    def _format_wizard_result_text(self, *, calc: BuyCalculation, total_label: str) -> str:
        """Build the totals line shown below the units input."""
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

    def _skip_plan_execution_step(self) -> None:
        """Skip current step without mutating portfolio and move forward."""
        try:
            self._require_current_portfolio()
            self._advance_plan_execution_step()
        except Exception as exc:
            show_error(cast(QWidget, self), "Continue failed", str(exc))

    def _exit_plan_execution_to_portfolio(self) -> None:
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

    def _advance_plan_execution_step(self) -> None:
        """Move to next step, or repopulate main editor and return when complete."""
        self.planning_state.step_index += 1
        if self.planning_state.step_index >= len(self.planning_state.plan_steps):
            if not self._try_finish_wizard_fx_cleanup():
                self.planning_state.step_index -= 1
                return
            self._return_to_main_editor_from_current_portfolio()
        else:
            self._show_current_plan_execution_step()

    @staticmethod
    def _format_decimal_for_display(value: D) -> str:
        """Format numeric display values with up to two decimal places."""
        quantized = value.quantize(_DISPLAY_PRICE_PRECISION, rounding=ROUND_HALF_UP)
        return fmt_decimal_grouped(quantized, trim_trailing_zeros=True)

    def _current_wizard_calculation_context(self) -> _WizardCalculationContext:
        """Return reusable current-step calculation/render context.

        The recommended units value is the whole-unit result derived from the
        planned step amount and cached unit price. The UI uses it both as the
        initial spinner value and as the spinner's upper bound.
        """
        step = self._current_step()
        price_ils = self._current_step_cached_price_ils(step)
        recommended_calc = calculate_buy_units_from_ils_price(
            instrument_id=step.instrument_id,
            planned_money=abs(step.planned_delta_money),
            price_ils=price_ils,
        )
        _, money_label = self._wizard_step_direction_labels(step.planned_delta_money)
        return _WizardCalculationContext(
            step=step,
            price_ils=price_ils,
            recommended_units=recommended_calc.units,
            total_label="Total spend" if money_label.startswith("Spent") else "Total proceeds",
        )

    @staticmethod
    def _signal_blocker(widget: object) -> AbstractContextManager[object]:
        """Return a signal blocker context when available, otherwise a no-op."""
        if isinstance(widget, QObject):
            return QSignalBlocker(widget)
        return nullcontext()
