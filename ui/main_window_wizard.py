from __future__ import annotations

"""Wizard-screen flow extracted from the main window controller.

This mixin encapsulates wizard screen wiring plus step calculation/save/advance
behavior so `MainWindow` can remain focused on high-level orchestration.
"""

from decimal import Decimal
from typing import cast

from PySide6.QtWidgets import QLabel, QLineEdit, QStackedWidget, QTreeWidget, QWidget

from portfolio_core.calc_stock_units import calculate_buy_units
from portfolio_core.portfolio_session import PortfolioSession
from portfolio_core.use_cases import apply_wizard_step
from ui.dialogs import show_error
from ui.portfolio_editor_adapter import populate_main_editor_from_portfolio
from ui.screens.wizard_screen import WizardScreen
from ui.ui_state import PlanningState, WizardState
from ui.ui_utils import d_from_text

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
    price_edit: QLineEdit
    wiz_result: QLabel
    _non_investable_bucket_id: str
    _non_investable_bucket_title: str

    def _quit_app(self) -> None:
        """Quit the Qt application from wizard controls."""
        ...

    def _update_file_context_ui(self) -> None:
        """Refresh file-related UI context after wizard save side effects."""
        ...

    def _update_future_tax_visual_state(self) -> None:
        """Apply visual cues when the editor is repopulated after wizard completion."""
        ...

    def _init_wizard_screen(self) -> None:
        """Build screen-3 widget and wire wizard actions."""
        self.screen_wizard = WizardScreen(cast(QWidget, self))
        self.wiz_info = self.screen_wizard.wiz_info
        self.price_edit = self.screen_wizard.price_edit
        self.wiz_result = self.screen_wizard.wiz_result
        self.screen_wizard.calculate_btn.clicked.connect(self._wizard_calculate)
        self.screen_wizard.quit_btn.clicked.connect(self._quit_app)
        self.screen_wizard.save_continue_btn.clicked.connect(self._wizard_save_continue)
        self.screen_wizard.continue_without_save_btn.clicked.connect(self._wizard_continue_without_saving)

    def _show_current_wizard_step(self) -> None:
        """Render current wizard step details and reset last calculation state."""
        s = self.planning_state.plan_steps[self.planning_state.step_index]
        idx = self.planning_state.step_index + 1
        total = len(self.planning_state.plan_steps)

        action = "BUY" if s.planned_delta_money > 0 else "SELL"
        self.wiz_info.setText(
            f"Step {idx}/{total}\n"
            f"Asset group: {s.asset_group_name}\n"
            f"Instrument: {s.instrument_name}\n"
            f"Planned {action} value: {abs(s.planned_delta_money)}"
        )
        self.price_edit.setText("")
        self.wiz_result.setText("Units: - | Spent/Proceeds: - | Leftover vs plan: -")

        self.wizard_state.last_calc = None

    def _wizard_calculate(self) -> None:
        """Calculate units/spend for the current wizard step from entered price."""
        try:
            s = self.planning_state.plan_steps[self.planning_state.step_index]
            price = d_from_text(self.price_edit.text(), "price")

            planned = abs(s.planned_delta_money)
            calc = calculate_buy_units(
                instrument_id=s.instrument_id,
                planned_money=planned,
                price_ag=price,
            )
            self.wizard_state.last_calc = calc

            label_money = "Spent" if s.planned_delta_money > 0 else "Proceeds"
            self.wiz_result.setText(
                f"Units: {calc.units} | {label_money}: {calc.spent} | Leftover vs plan: {calc.leftover}"
            )
        except Exception as e:
            show_error(cast(QWidget, self), "Calculation failed", str(e))

    def _wizard_save_continue(self) -> None:
        """Apply current step trade (if valid), persist, and move to next step."""
        try:
            if self.session.document.current_portfolio is None:
                raise ValueError("No portfolio loaded")

            s = self.planning_state.plan_steps[self.planning_state.step_index]

            if self.wizard_state.last_calc is None:
                calc_units = 0
                spent = D("0")
            else:
                calc_units = self.wizard_state.last_calc.units
                spent = self.wizard_state.last_calc.spent

            applied = apply_wizard_step(self.session, s, calc_units, spent)
            if applied:
                self._update_file_context_ui()

            self._advance_wizard_step()
        except Exception as e:
            show_error(cast(QWidget, self), "Save failed", str(e))

    def _wizard_continue_without_saving(self) -> None:
        """Skip current step without mutating portfolio and move forward."""
        try:
            if self.session.document.current_portfolio is None:
                raise ValueError("No portfolio loaded")
            self._advance_wizard_step()
        except Exception as e:
            show_error(cast(QWidget, self), "Continue failed", str(e))

    def _advance_wizard_step(self) -> None:
        """Move to next step, or repopulate main editor and return when complete."""
        self.planning_state.step_index += 1
        if self.planning_state.step_index >= len(self.planning_state.plan_steps):
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
            self.stack.setCurrentWidget(self.screen_main)
        else:
            self._show_current_wizard_step()
