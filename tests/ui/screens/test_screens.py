"""
UI construction tests for screen widgets.

These tests verify that each screen module builds the expected controls,
defaults, and static configuration. They intentionally focus on structure
and wiring surfaces, not full interaction workflows (which are covered via
MainWindow integration behavior).
"""

from __future__ import annotations

from pathlib import Path
import tomllib

import pytest
from PySide6.QtGui import QFontMetrics
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QLabel, QLineEdit, QSpinBox, QStyleOptionViewItem, QToolBar, QTreeWidgetItem
from portfolio_core.domain.models import Exchange
from portfolio_core.app_metadata import get_app_version
from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.summary_screen import SummaryScreen
from ui.screens.welcome_screen import WelcomeScreen
from ui.screens.wizard_screen import WizardScreen
from ui.shared.button_styles import (
    BUTTON_STYLE_SIZE_PROPERTY,
    BUTTON_STYLE_ROLE_PROPERTY,
    COMPACT_BUTTON_STYLE_SIZE,
    PRIMARY_BUTTON_STYLE_ROLE,
    REGULAR_BUTTON_STYLE_SIZE,
    SECONDARY_BUTTON_STYLE_ROLE,
)
from ui.shared.decimal_input_delegate import DecimalInputDelegate, NonNegativeIntegerInputDelegate, PercentInputDelegate
from ui.shared.portfolio_tree_row import PortfolioTreeRow
from ui.shared.ui_types import Col
from ui.shared.ui_utils import DEFAULT_CURRENCY, exchange_choices, get_decimal_line_edit_raw_text


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp: object) -> None:
    """Ensure a QApplication exists for all tests in this module."""
    _ = qapp

def test_main_editor_screen_builds_expected_controls() -> None:
    screen = MainEditorScreen()

    layout = screen.layout()
    assert layout is not None
    toolbar = screen.findChild(QToolBar)
    assert toolbar is not None
    title_label = next(label for label in screen.findChildren(QLabel) if label.text() == "Insert data here")
    assert layout.indexOf(toolbar) < layout.indexOf(title_label)
    assert screen.new_btn.text() == "New"
    assert screen.open_btn.text() == "Open"
    assert screen.save_btn.text() == "Save"
    assert screen.save_as_btn.text() == "Save As"

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

    assert isinstance(screen.tree.itemDelegateForColumn(Col.TARGET_PCT.value), PercentInputDelegate)
    assert isinstance(screen.tree.itemDelegateForColumn(Col.QUANTITY.value), NonNegativeIntegerInputDelegate)

    assert screen.add_group_btn.text() == "Add Asset Group"
    assert screen.add_instrument_btn.text() == "Add Instrument"
    assert screen.delete_row_btn.text() == "Delete Selected"
    assert screen.total_label.text() == "Total portfolio (ILS): -"
    assert screen.refresh_market_data_btn.text() == "Refresh Market Data"
    assert screen.invest_btn.text() == "Invest Cash"
    assert screen.invest_btn.toolTip() == "Allocate available cash without selling holdings."
    assert screen.rebalance_btn.text() == "Rebalance Portfolio"
    assert screen.rebalance_btn.toolTip() == "Adjust holdings, including sells, to restore targets."
    actions_parent = screen.quit_btn.parentWidget()
    assert actions_parent is not None
    actions_layout = actions_parent.layout()
    assert actions_layout is not None
    assert actions_layout.indexOf(screen.quit_btn) < actions_layout.indexOf(screen.refresh_market_data_btn)
    assert actions_layout.indexOf(screen.refresh_market_data_btn) < actions_layout.indexOf(screen.rebalance_btn)
    assert actions_layout.indexOf(screen.rebalance_btn) < actions_layout.indexOf(screen.invest_btn)
    assert screen.refresh_market_data_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == SECONDARY_BUTTON_STYLE_ROLE
    assert screen.refresh_market_data_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == COMPACT_BUTTON_STYLE_SIZE
    assert screen.rebalance_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == SECONDARY_BUTTON_STYLE_ROLE
    assert screen.rebalance_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == COMPACT_BUTTON_STYLE_SIZE
    assert screen.invest_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == PRIMARY_BUTTON_STYLE_ROLE
    assert screen.invest_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == COMPACT_BUTTON_STYLE_SIZE


def test_welcome_screen_builds_expected_controls() -> None:
    app_version = get_app_version()
    screen = WelcomeScreen(app_version=app_version)

    title_label = screen.findChild(QLabel, "welcome_title")
    assert title_label is not None
    assert title_label.text() == "Welcome"
    assert app_version is not None
    assert screen.version_label.text() == f"Version {app_version}"
    assert not screen.version_label.isHidden()
    assert screen.open_last_btn.text() == "Open Last Portfolio"
    assert screen.load_different_btn.text() == "Load Portfolio..."
    assert screen.start_new_btn.text() == "Start New File"
    assert screen.quit_btn.text() == "Quit"
    assert screen.open_last_btn.minimumHeight() == 36
    assert screen.load_different_btn.minimumHeight() == 36
    assert screen.start_new_btn.minimumHeight() == 36
    assert screen.quit_btn.minimumHeight() == 36
    assert screen.open_last_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == PRIMARY_BUTTON_STYLE_ROLE
    assert screen.open_last_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == COMPACT_BUTTON_STYLE_SIZE
    assert screen.load_different_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == SECONDARY_BUTTON_STYLE_ROLE
    assert screen.load_different_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == COMPACT_BUTTON_STYLE_SIZE
    assert screen.start_new_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == SECONDARY_BUTTON_STYLE_ROLE
    assert screen.start_new_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == COMPACT_BUTTON_STYLE_SIZE
    assert screen.quit_btn.property(BUTTON_STYLE_ROLE_PROPERTY) is None
    assert screen.quit_btn.property(BUTTON_STYLE_SIZE_PROPERTY) is None
    layout = screen.layout()
    assert layout is not None
    assert layout.indexOf(screen.last_path_label) == layout.indexOf(screen.open_last_btn) + 1

    screen.set_last_portfolio_status(
        button_enabled=False,
        path_text="Last portfolio: C:/missing.json (Not found)",
        path_tooltip="C:/missing.json",
        missing_path=True,
    )
    assert not screen.open_last_btn.isEnabled()
    assert "Not found" in screen.last_path_label.text()
    assert screen.last_path_label.toolTip() == "C:/missing.json"


def test_welcome_screen_hides_version_label_when_app_version_is_unavailable() -> None:
    screen = WelcomeScreen(app_version=None)

    assert screen.version_label.isHidden()
    assert screen.version_label.text() == ""


def test_welcome_screen_set_app_version_updates_visibility_and_text() -> None:
    screen = WelcomeScreen(app_version=None)

    screen.set_app_version("9.9.9")
    assert not screen.version_label.isHidden()
    assert screen.version_label.text() == "Version 9.9.9"

    screen.set_app_version(None)
    assert screen.version_label.isHidden()
    assert screen.version_label.text() == ""


def test_app_version_is_loaded_from_pyproject() -> None:
    pyproject_path = Path(__file__).resolve().parents[3] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = pyproject.get("project")
    assert isinstance(project, dict)
    version = project.get("version")
    assert isinstance(version, str)
    assert get_app_version() == version


def test_main_editor_screen_sets_header_tooltips() -> None:
    screen = MainEditorScreen()

    assert "ticker symbol" in screen.tree.headerItem().toolTip(Col.TICKER.value).lower()
    assert "user-defined display name for your convenience" in screen.tree.headerItem().toolTip(Col.NAME.value).lower()
    assert "non-negative integer" in screen.tree.headerItem().toolTip(Col.QUANTITY.value).lower()
    total_value_tooltip = screen.tree.headerItem().toolTip(Col.TOT_VALUE.value)
    assert DEFAULT_CURRENCY.value in total_value_tooltip
    assert "read-only" in total_value_tooltip.lower()
    assert "cache" not in total_value_tooltip.lower()
    exchange_tooltip = screen.tree.headerItem().toolTip(Col.EXCHANGE.value)
    assert "wizard" in exchange_tooltip.lower()
    for exchange_code in exchange_choices():
        assert exchange_code in exchange_tooltip
    assert "default: TASE" in exchange_tooltip
    assert "full portfolio value" in screen.tree.headerItem().toolTip(Col.PORTFOLIO_PCT.value).lower()
    assert "how far you are from your goal" in screen.tree.headerItem().toolTip(Col.DRIFT_PP.value).lower()


def test_summary_screen_builds_expected_controls() -> None:
    screen = SummaryScreen()

    assert screen.quit_btn.text() == "Quit"
    assert screen.back_btn.text() == "Back"
    assert screen.start_execution_btn.text() == "Start Execution"
    assert screen.planning_action_label.text() == "Planning action: -"
    assert screen.available_to_allocate_label.text() == "Available to allocate: -"
    assert screen.planned_actions_label.text() == "No actions required."
    assert screen.back_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == SECONDARY_BUTTON_STYLE_ROLE
    assert screen.back_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == REGULAR_BUTTON_STYLE_SIZE
    assert screen.start_execution_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == PRIMARY_BUTTON_STYLE_ROLE
    assert screen.start_execution_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == REGULAR_BUTTON_STYLE_SIZE
    btns_parent = screen.quit_btn.parentWidget()
    assert btns_parent is not None
    btns_layout = btns_parent.layout()
    assert btns_layout is not None
    assert btns_layout.indexOf(screen.quit_btn) < btns_layout.indexOf(screen.back_btn)
    assert btns_layout.indexOf(screen.back_btn) < btns_layout.indexOf(screen.start_execution_btn)


def test_wizard_screen_builds_expected_controls() -> None:
    screen = WizardScreen()

    labels = [label.text() for label in screen.findChildren(QLabel)]
    assert "Execute Plan Step" in labels
    assert "Step -/-" in labels
    assert screen.wiz_info.text() == "-"
    assert screen.wiz_info.wordWrap()
    assert screen.units_label.text() == "Units bought:"
    assert isinstance(screen.units_edit, QSpinBox)
    assert screen.units_edit.minimum() == 0
    assert screen.units_edit.maximum() == 0
    assert screen.units_edit.singleStep() == 1
    assert screen.wiz_summary.text() == "Planned: - ILS | Price: - ILS/unit | Recommended: - units"
    assert not screen.wiz_summary.wordWrap()
    assert screen.wiz_result.text() == "Total spend/proceeds: - ILS | Leftover: - ILS"
    assert not screen.wiz_result.wordWrap()
    assert screen.quit_btn.text() == "Quit"
    assert screen.back_to_portfolio_btn.text() == "Exit Wizard"
    assert screen.save_continue_btn.text() == "Save and continue"
    assert not screen.save_continue_btn.isEnabled()
    assert screen.continue_without_save_btn.text() == "Skip Step"
    assert screen.back_to_portfolio_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == SECONDARY_BUTTON_STYLE_ROLE
    assert screen.back_to_portfolio_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == REGULAR_BUTTON_STYLE_SIZE
    assert screen.continue_without_save_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == SECONDARY_BUTTON_STYLE_ROLE
    assert screen.continue_without_save_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == REGULAR_BUTTON_STYLE_SIZE
    assert screen.save_continue_btn.property(BUTTON_STYLE_ROLE_PROPERTY) == PRIMARY_BUTTON_STYLE_ROLE
    assert screen.save_continue_btn.property(BUTTON_STYLE_SIZE_PROPERTY) == REGULAR_BUTTON_STYLE_SIZE
    assert screen.save_continue_btn.parentWidget() is screen.wiz_result.parentWidget()
    btns_parent = screen.quit_btn.parentWidget()
    assert btns_parent is not None
    btns_layout = btns_parent.layout()
    assert btns_layout is not None
    assert btns_layout.indexOf(screen.quit_btn) < btns_layout.indexOf(screen.back_to_portfolio_btn)
    assert btns_layout.indexOf(screen.back_to_portfolio_btn) < btns_layout.indexOf(screen.continue_without_save_btn)
    assert btns_layout.indexOf(screen.save_continue_btn) == -1
    summary_row_parent = screen.wiz_summary.parentWidget()
    units_row_parent = screen.units_label.parentWidget()
    result_row_parent = screen.wiz_result.parentWidget()
    info_card_parent = screen.step_progress.parentWidget()
    assert summary_row_parent is not None
    assert units_row_parent is not None
    assert result_row_parent is not None
    assert info_card_parent is not None
    assert screen.step_progress.parentWidget() is info_card_parent
    assert screen.wiz_info.parentWidget() is info_card_parent
    assert summary_row_parent.width() == result_row_parent.width()
    assert units_row_parent.width() == result_row_parent.width()
    min_input_width = QFontMetrics(screen.units_edit.font()).horizontalAdvance("0" * 11) + 24
    assert screen.units_edit.minimumWidth() >= min_input_width


def test_wizard_screen_set_step_context_includes_ticker_and_exchange() -> None:
    screen = WizardScreen()

    screen.set_step_context(
        step_index=2,
        total_steps=4,
        asset_group_name="US Equity",
        ticker="AB12",
        exchange=Exchange.NYSE,
        instrument_name="ETF A",
        action="BUY",
        planned_amount_text="500 (ILS)",
    )

    assert screen.step_progress.text() == "Step 2/4"
    assert "Instrument: ETF A" in screen.wiz_info.text()
    assert "Ticker: AB12" in screen.wiz_info.text()
    assert "Exchange: NYSE" in screen.wiz_info.text()
    assert "Asset group: US Equity" in screen.wiz_info.text()
    assert "Action: BUY 500 (ILS)" in screen.wiz_info.text()


def test_wizard_screen_set_fx_panel_updates_labels_without_override_inputs() -> None:
    screen = WizardScreen()

    screen.set_fx_panel(
        visible=True,
        info_text="USD/ILS rate: 3.77",
        error_text="fetch failed",
    )

    assert screen.fx_info_label.text() == "USD/ILS rate: 3.77"
    assert screen.fx_error_label.text() == "fetch failed"


def test_main_editor_quantity_delegate_rejects_non_digit_input() -> None:
    screen = MainEditorScreen()
    delegate = screen.tree.itemDelegateForColumn(Col.QUANTITY.value)
    assert isinstance(delegate, NonNegativeIntegerInputDelegate)

    editor = delegate.createEditor(screen.tree, QStyleOptionViewItem(), QModelIndex())
    assert isinstance(editor, QLineEdit)

    editor.setText("-")
    assert not editor.hasAcceptableInput()

    editor.setText("ab")
    assert not editor.hasAcceptableInput()

    editor.setText("10")
    assert editor.hasAcceptableInput()


def test_main_editor_quantity_formats_with_grouping_after_edit_commit() -> None:
    screen = MainEditorScreen()
    group = screen.tree.invisibleRootItem()
    child = QTreeWidgetItem(group)
    PortfolioTreeRow(child).set_quantity(12345)
    delegate = screen.tree.itemDelegateForColumn(Col.QUANTITY.value)
    assert isinstance(delegate, NonNegativeIntegerInputDelegate)

    editor = delegate.createEditor(screen.tree, QStyleOptionViewItem(), screen.tree.model().index(0, Col.QUANTITY.value))
    assert isinstance(editor, QLineEdit)
    delegate.setEditorData(editor, screen.tree.model().index(0, Col.QUANTITY.value))
    assert editor.text() == "12345"

    editor.setText("12345")
    delegate.setModelData(editor, screen.tree.model(), screen.tree.model().index(0, Col.QUANTITY.value))
    assert child.text(Col.QUANTITY.value) == "12,345"


def test_main_editor_target_percent_delegate_edits_plain_numeric_text() -> None:
    screen = MainEditorScreen()
    group = screen.tree.invisibleRootItem()
    child = QTreeWidgetItem(group)
    PortfolioTreeRow(child).set_target_pct_text("12.5")
    delegate = screen.tree.itemDelegateForColumn(Col.TARGET_PCT.value)
    assert isinstance(delegate, PercentInputDelegate)

    editor = delegate.createEditor(screen.tree, QStyleOptionViewItem(), screen.tree.model().index(0, Col.TARGET_PCT.value))
    assert isinstance(editor, QLineEdit)
    delegate.setEditorData(editor, screen.tree.model().index(0, Col.TARGET_PCT.value))
    assert editor.text() == "12.5"


def test_main_editor_cash_inputs_reject_commas_and_letters() -> None:
    screen = MainEditorScreen()
    screen.show()

    for editor in (screen.cash_value_edit, screen.cash_reserve_edit, screen.future_tax_edit):
        editor.clear()
        editor.insert("1,000")
        assert "," not in editor.text()

        editor.clear()
        editor.insert("abc")
        assert editor.text() == ""

        editor.clear()
        editor.insert("1000.25")
        assert editor.hasAcceptableInput()


def test_main_editor_cash_inputs_format_with_grouping_after_editing_finishes() -> None:
    screen = MainEditorScreen()
    screen.show()

    screen.cash_value_edit.clear()
    screen.cash_value_edit.insert("12345.67")
    assert screen.cash_value_edit.text() == "12345.67"
    screen.cash_value_edit.editingFinished.emit()

    assert screen.cash_value_edit.text() == "12,345.67"
    assert get_decimal_line_edit_raw_text(screen.cash_value_edit) == "12345.67"
    assert screen.cash_value_edit.hasAcceptableInput() is False
