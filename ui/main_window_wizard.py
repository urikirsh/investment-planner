from __future__ import annotations

"""Wizard-screen flow extracted from the main window controller.

This mixin encapsulates wizard screen wiring plus step calculation/save/advance
behavior so `MainWindow` can remain focused on high-level orchestration.

Wizard-run-scoped FX handling for USD-priced instruments is delegated to
`ui.wizard_fx_coordinator.WizardFxCoordinator` via thin wrapper methods in
this mixin.
"""

from decimal import Decimal
from typing import cast

from PySide6.QtWidgets import QLabel, QLineEdit, QStackedWidget, QTreeWidget, QWidget

from portfolio_core.calc_stock_units import calculate_buy_units, calculate_buy_units_from_ils_price
from portfolio_core.models import Currency
from portfolio_core.portfolio_session import PortfolioSession
from portfolio_core.use_cases import InsufficientQuantityForSellError, PlanStep, apply_wizard_step
from ui.dialogs import show_error
from ui.portfolio_editor_adapter import populate_main_editor_from_portfolio
from ui.screens.wizard_screen import WizardScreen
from ui.ui_state import PlanningState, WizardState
from ui.shared.ui_utils import BASE_CURRENCY_SUFFIX, DEFAULT_CURRENCY, d_from_text
from ui.wizard_fx_coordinator import WizardFxCoordinator

D = Decimal


class MainWindowWizardMixin:
    """Mixin containing wizard screen setup and per-step execution flow.

    Host methods declared with ``...`` are intentional interface stubs that
    the concrete ``MainWindow`` provides.
    """

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
    price_label: QLabel
    price_edit: QLineEdit
    manual_rate_edit: QLineEdit
    wiz_result: QLabel
    _non_investable_bucket_id: str
    _non_investable_bucket_title: str
    _wizard_fx: WizardFxCoordinator

    def _quit_app(self) -> None:
        """Quit the Qt application from wizard controls."""
        ...

    def _update_file_context_ui(self) -> None:
        """Refresh file-related UI context after wizard save side effects."""
        ...

    def _update_future_tax_visual_state(self) -> None:
        """Apply visual cues when the editor is repopulated after wizard completion."""
        ...

    def _refresh_data(self) -> None:
        """Recompute and rerender derived values on the main screen."""
        ...

    def _init_wizard_screen(self) -> None:
        """Build screen-4 wizard widget and wire wizard actions."""
        self.screen_wizard = WizardScreen(cast(QWidget, self))
        self.wiz_info = self.screen_wizard.wiz_info
        self.price_label = self.screen_wizard.price_label
        self.price_edit = self.screen_wizard.price_edit
        self.manual_rate_edit = self.screen_wizard.manual_rate_edit
        self.wiz_result = self.screen_wizard.wiz_result
        self.screen_wizard.calculate_btn.clicked.connect(self._wizard_calculate)
        self.price_edit.editingFinished.connect(self._wizard_calculate_implicit)
        self.screen_wizard.quit_btn.clicked.connect(self._quit_app)
        self.screen_wizard.back_to_portfolio_btn.clicked.connect(self._wizard_back_to_portfolio)
        self.screen_wizard.save_continue_btn.clicked.connect(self._wizard_save_continue)
        self.screen_wizard.continue_without_save_btn.clicked.connect(self._wizard_continue_without_saving)
        self._invalidate_current_calc(reset_result=False, sync_widths=False)
        self._wizard_fx = WizardFxCoordinator(self, show_error_fn=show_error)

    def _show_current_wizard_step(self) -> None:
        """Render current wizard step details and reset last calculation state."""
        s = self._current_step()
        idx = self.planning_state.step_index + 1
        total = len(self.planning_state.plan_steps)

        action = "BUY" if s.planned_delta_money > 0 else "SELL"
        planned_amount_text = f"{abs(s.planned_delta_money)} {BASE_CURRENCY_SUFFIX}"
        self.screen_wizard.set_step_context(
            step_index=idx,
            total_steps=total,
            asset_group_name=s.asset_group_name,
            ticker=s.ticker,
            exchange=s.exchange.value,
            instrument_name=s.instrument_name,
            action=action,
            planned_amount_text=planned_amount_text,
        )
        self.screen_wizard.set_price_mode(s.exchange)
        self._render_fx_panel_for_current_step()
        self.price_edit.setText("")
        self._invalidate_current_calc(reset_result=True, sync_widths=True)

    def _wizard_calculate(self) -> None:
        """Calculate units/spend for the current wizard step from entered price."""
        self._wizard_calculate_impl(show_error_dialog=True)

    def _wizard_calculate_implicit(self) -> None:
        """Calculate on price edit commit (Enter/focus-out) without modal errors.

        Empty/whitespace input clears any previous calculation and restores the
        step-aware placeholder so stale values cannot be committed.
        """
        if not self.price_edit.text().strip():
            self._invalidate_current_calc(reset_result=True, sync_widths=True)
            return
        self._wizard_calculate_impl(show_error_dialog=False)

    def _wizard_calculate_impl(self, *, show_error_dialog: bool) -> None:
        """Shared calculation logic for explicit and implicit wizard triggers.

        Explicit failures are shown in a modal dialog. Implicit failures update
        the result row inline with a shortened single-line message so layout
        remains stable during typing/focus navigation.
        """
        try:
            s = self._current_step()
            entered_price = d_from_text(self.price_edit.text(), "price")

            planned = abs(s.planned_delta_money)
            conversion_info = ""
            if s.exchange.currency == Currency.USD:
                usd_ils_rate = self._get_effective_usd_ils_rate()
                price_ils = entered_price * usd_ils_rate
                calc = calculate_buy_units_from_ils_price(
                    instrument_id=s.instrument_id,
                    planned_money=planned,
                    price_ils=price_ils,
                )
                conversion_info = (
                    f"Converted: {entered_price} {s.exchange.currency.value} x {usd_ils_rate} = "
                    f"{price_ils} {DEFAULT_CURRENCY.value} | "
                )
            else:
                calc = calculate_buy_units(
                    instrument_id=s.instrument_id,
                    planned_money=planned,
                    price_ag=entered_price,
                )
            self.wizard_state.last_calc = calc
            self._set_save_continue_enabled(True)

            label_money = (
                f"Spent {BASE_CURRENCY_SUFFIX}"
                if s.planned_delta_money > 0
                else f"Proceeds {BASE_CURRENCY_SUFFIX}"
            )
            self.wiz_result.setText(
                self._format_wizard_result_text(
                    units=calc.units,
                    money_label=label_money,
                    money_value=calc.spent,
                    leftover_value=calc.leftover,
                    conversion_info=conversion_info,
                )
            )
            self._sync_wizard_focus_row_widths()
        except Exception as e:
            self._invalidate_current_calc(reset_result=False, sync_widths=False)
            if show_error_dialog:
                show_error(cast(QWidget, self), "Calculation failed", str(e))
                return
            inline_error = str(e).strip().splitlines()[0]
            if len(inline_error) > 60:
                inline_error = f"{inline_error[:57]}..."
            self.wiz_result.setText(f"Calculation not updated: {inline_error}")
            self._sync_wizard_focus_row_widths()

    def _get_effective_usd_ils_rate(self) -> D:
        """Return USD/ILS rate for current wizard run, with override fallback."""
        if self.wizard_state.usd_ils_rate is not None:
            return self.wizard_state.usd_ils_rate
        if self.wizard_state.usd_ils_fetch_in_progress:
            raise ValueError("Still fetching official USD/ILS rate (can take up to 10 seconds). Please wait.")
        if self.wizard_state.manual_override_usd_ils_rate is not None:
            return self.wizard_state.manual_override_usd_ils_rate

        raw = self.manual_rate_edit.text().strip()
        if raw:
            rate = d_from_text(raw, "manual USD/ILS rate")
            if rate <= 0:
                raise ValueError("manual USD/ILS rate must be positive")
            self.wizard_state.manual_override_usd_ils_rate = rate
            self._render_fx_panel_for_current_step()
            return rate

        raise ValueError(
            "USD/ILS rate unavailable. Could not fetch from Bank of Israel. "
            "Enter a manual USD/ILS rate to continue."
        )

    def _wizard_has_usd_steps(self) -> bool:
        """Return whether current plan includes at least one USD-priced step."""
        return any(step.exchange.currency == Currency.USD for step in self.planning_state.plan_steps)

    def _prepare_wizard_fx_rate_cache(self) -> None:
        """Begin BOI USD/ILS fetch asynchronously once per wizard run when needed."""
        self._wizard_fx_coordinator().prepare_wizard_fx_rate_cache()

    def _on_fx_fetch_finished(self, quote_obj: object, error_obj: object, generation: int) -> None:
        """Handle completion of asynchronous BOI fetch."""
        self._wizard_fx_coordinator().on_fx_fetch_finished(quote_obj, error_obj, generation)

    def _reset_wizard_fx_state_for_new_run(self) -> bool:
        """Reset transient USD/ILS state and clear manual FX input for a new run."""
        return self._wizard_fx_coordinator().reset_wizard_fx_state_for_new_run()

    def _cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = 1000) -> bool:
        """Stop and detach the in-flight FX fetch thread, if any."""
        return self._wizard_fx_coordinator().cancel_wizard_fx_fetch(wait_timeout_ms=wait_timeout_ms)

    def _render_fx_panel_for_current_step(self) -> None:
        """Render FX quote/fallback/override status for the active step."""
        self._wizard_fx_coordinator().render_fx_panel_for_current_step()

    def _wizard_fx_coordinator(self) -> WizardFxCoordinator:
        """Lazily create coordinator for tests that bypass widget initialization."""
        if not hasattr(self, "_wizard_fx"):
            self._wizard_fx = WizardFxCoordinator(self, show_error_fn=show_error)
        return self._wizard_fx

    def _wizard_save_continue(self) -> None:
        """Apply current step trade, persist if applied, then advance.

        Behavior:
        - Requires a successful current-step calculation before applying.
        - On successful apply, refreshes file-context UI (because autosave happened).
        - If sell units exceed tracked quantity, shows a clear error prompt and
          advances to the next step without saving this step.
        """
        try:
            self._require_current_portfolio()

            s = self._current_step()
            if self.wizard_state.last_calc is None:
                raise ValueError("Please calculate units before saving this step.")
            calc_units = self.wizard_state.last_calc.units
            spent = self.wizard_state.last_calc.spent

            applied = apply_wizard_step(self.session, s, calc_units, spent)
            if applied:
                self._update_file_context_ui()

            self._advance_wizard_step()
        except InsufficientQuantityForSellError as e:
            show_error(
                cast(QWidget, self),
                "Cannot complete sell step",
                (
                    f"{e.instrument_name}: tried to sell {e.requested_units} units, "
                    f"but only {e.available_units} units are available.\n\n"
                    "This step was skipped. Update the instrument quantity in the main screen if needed."
                ),
            )
            self._advance_wizard_step()
        except Exception as e:
            show_error(cast(QWidget, self), "Save failed", str(e))

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

    def _wizard_money_label(self, planned_delta_money: D) -> str:
        """Return action-specific money label for the active step."""
        if planned_delta_money > 0:
            return f"Spent {BASE_CURRENCY_SUFFIX}"
        return f"Proceeds {BASE_CURRENCY_SUFFIX}"

    def _format_wizard_result_text(
        self,
        *,
        units: object,
        money_label: str,
        money_value: object,
        leftover_value: object,
        conversion_info: str = "",
    ) -> str:
        """Build one canonical wizard result-line format.

        Used for both placeholder and calculated states so wording/order/units
        remain consistent across step refreshes and recalculations.
        """
        return (
            f"{conversion_info}"
            f"Units: {units} | "
            f"{money_label}: {money_value} | "
            f"Leftover vs plan {BASE_CURRENCY_SUFFIX}: {leftover_value}"
        )

    def _set_wizard_result_placeholder_for_current_step(self) -> None:
        """Render action-specific placeholder text before calculation."""
        planned_delta_money = self._current_step().planned_delta_money
        self.wiz_result.setText(
            self._format_wizard_result_text(
                units="-",
                money_label=self._wizard_money_label(planned_delta_money),
                money_value="-",
                leftover_value="-",
            )
        )

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
        except Exception as e:
            show_error(cast(QWidget, self), "Continue failed", str(e))

    def _wizard_back_to_portfolio(self) -> None:
        """Exit wizard early and return to main editor without applying the active step.

        This path is intentionally non-mutating for the active step; only
        previously saved wizard steps are reflected when repopulating editor UI.
        """
        try:
            self._require_current_portfolio()
            if not self._cancel_wizard_fx_fetch():
                show_error(
                    cast(QWidget, self),
                    "Please wait",
                    "Still finishing background USD/ILS fetch. Try again in a few seconds.",
                )
                return
            self.wizard_state.usd_ils_fetch_in_progress = False
            self.wizard_state.usd_ils_active_fetch_generation = None
            self._return_to_main_editor_from_current_portfolio()
        except Exception as e:
            show_error(cast(QWidget, self), "Back failed", str(e))

    def _return_to_main_editor_from_current_portfolio(self) -> None:
        """Populate main editor from current portfolio and switch to screen 2.

        Shared by full wizard completion and explicit "Exit Wizard" exit
        to keep main-screen refresh behavior identical across both transitions.
        """
        current = self.session.document.current_portfolio
        assert current is not None
        populate_main_editor_from_portfolio(
            tree=self.tree,
            cash_value_edit=self.cash_value_edit,
            cash_reserve_edit=self.cash_reserve_edit,
            future_tax_edit=self.future_tax_edit,
            portfolio=current,
            non_investable_bucket_id=self._non_investable_bucket_id,
            non_investable_bucket_title=self._non_investable_bucket_title,
            on_future_tax_value_set=self._update_future_tax_visual_state,
        )
        self._refresh_data()
        self.stack.setCurrentWidget(self.screen_main)

    def _advance_wizard_step(self) -> None:
        """Move to next step, or repopulate main editor and return when complete.

        Final-step transition is guarded by FX-thread cancellation; if cleanup
        cannot complete yet, the method keeps the current step active and
        informs the user to retry shortly.
        """
        self.planning_state.step_index += 1
        if self.planning_state.step_index >= len(self.planning_state.plan_steps):
            if not self._cancel_wizard_fx_fetch():
                self.planning_state.step_index -= 1
                show_error(
                    cast(QWidget, self),
                    "Please wait",
                    "Still finishing background USD/ILS fetch. Try again in a few seconds.",
                )
                return
            self.wizard_state.usd_ils_fetch_in_progress = False
            self.wizard_state.usd_ils_active_fetch_generation = None
            self._return_to_main_editor_from_current_portfolio()
        else:
            self._show_current_wizard_step()
