"""
UI construction tests for screen widgets.

These tests verify that each screen module builds the expected controls,
defaults, and static configuration. They intentionally focus on structure
and wiring surfaces, not full interaction workflows (which are covered via
MainWindow integration behavior).
"""

from __future__ import annotations

from portfolio_core.models import Exchange
from ui.exchange_delegate import ExchangeDelegate
from ui.decimal_input_delegate import DecimalInputDelegate
from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.summary_screen import SummaryScreen
from ui.screens.wizard_screen import WizardScreen
from ui.ui_types import Col
from ui.ui_utils import DEFAULT_CURRENCY, exchange_choices


def test_main_editor_screen_builds_expected_controls(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()

    assert screen.cash_value_edit.placeholderText() == "e.g. 1000"
    assert screen.cash_reserve_edit.placeholderText() == "e.g. 20000"
    assert screen.future_tax_edit.text() == "0"
    assert screen.investable_balance_label.text() == "Investable balance (ILS): 0"

    assert screen.tree.columnCount() == len(Col)
    assert screen.tree.headerItem().text(Col.TICKER.value) == "Ticker"
    assert screen.tree.headerItem().text(Col.NAME.value) == "Name"
    assert screen.tree.headerItem().text(Col.QUANTITY.value) == "Quantity"
    assert screen.tree.headerItem().text(Col.EXCHANGE.value) == "Exchange"
    assert screen.tree.headerItem().text(Col.DRIFT_PP.value) == "Drift (pp)"
    assert screen.tree.columnWidth(Col.DRIFT_PP.value) == 78

    assert isinstance(screen.tree.itemDelegateForColumn(Col.TOT_VALUE.value), DecimalInputDelegate)
    assert isinstance(screen.tree.itemDelegateForColumn(Col.EXCHANGE.value), ExchangeDelegate)
    assert isinstance(screen.tree.itemDelegateForColumn(Col.TARGET_PCT.value), DecimalInputDelegate)

    assert screen.add_group_btn.text() == "Add Asset Group"
    assert screen.add_instrument_btn.text() == "Add Instrument"
    assert screen.delete_row_btn.text() == "Delete Selected"
    assert screen.total_label.text() == "Total portfolio (ILS): -"
    assert screen.rebalance_btn.text() == "Invest & Rebalance"


def test_main_editor_screen_sets_header_tooltips(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()

    assert "ticker symbol" in screen.tree.headerItem().toolTip(Col.TICKER.value).lower()
    assert "user-defined display name for your convenience" in screen.tree.headerItem().toolTip(Col.NAME.value).lower()
    assert "non-negative integer" in screen.tree.headerItem().toolTip(Col.QUANTITY.value).lower()
    total_value_tooltip = screen.tree.headerItem().toolTip(Col.TOT_VALUE.value)
    assert DEFAULT_CURRENCY.value in total_value_tooltip
    exchange_tooltip = screen.tree.headerItem().toolTip(Col.EXCHANGE.value)
    assert "wizard" in exchange_tooltip.lower()
    for exchange_code in exchange_choices():
        assert exchange_code in exchange_tooltip
    assert "default: TASE" in exchange_tooltip
    assert "full portfolio value" in screen.tree.headerItem().toolTip(Col.PORTFOLIO_PCT.value).lower()
    assert "how far you are from your goal" in screen.tree.headerItem().toolTip(Col.DRIFT_PP.value).lower()


def test_summary_screen_builds_expected_controls(qapp) -> None:
    _ = qapp
    screen = SummaryScreen()

    assert screen.summary_text.isReadOnly()
    assert screen.quit_btn.text() == "Quit"
    assert screen.back_btn.text() == "Back"
    assert screen.next_btn.text() == "Next"


def test_wizard_screen_builds_expected_controls(qapp) -> None:
    _ = qapp
    screen = WizardScreen()

    assert screen.wiz_info.text() == "-"
    assert screen.wiz_info.wordWrap()
    assert screen.price_edit.placeholderText() == "Enter unit price (e.g. 123.45)"
    assert screen.calculate_btn.text() == "Calculate"
    assert screen.wiz_result.text() == "Units: - | Spent: - | Leftover vs plan: -"
    assert screen.quit_btn.text() == "Quit"
    assert screen.save_continue_btn.text() == "Save and continue"
    assert screen.continue_without_save_btn.text() == "Continue without saving"


def test_wizard_screen_set_fx_panel_clears_stale_manual_rate_when_visible_without_value(qapp) -> None:
    _ = qapp
    screen = WizardScreen()
    screen.manual_rate_edit.setText("3.77")

    screen.set_fx_panel(
        visible=True,
        info_text="",
        error_text="fetch failed",
        manual_visible=True,
        manual_value="",
    )

    assert screen.manual_rate_edit.text() == ""


def test_exchange_delegate_choices_follow_exchange_enum_values() -> None:
    assert ExchangeDelegate._choices == tuple(exchange.value for exchange in Exchange)
