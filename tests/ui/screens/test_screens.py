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

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel
from portfolio_core.models import Exchange
from portfolio_core.app_metadata import get_app_version
from ui.delegates.exchange_delegate import ExchangeDelegate
from ui.delegates.decimal_input_delegate import DecimalInputDelegate
from ui.delegates.ticker_input_delegate import TickerInputDelegate
from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.summary_screen import SummaryScreen
from ui.screens.welcome_screen import WelcomeScreen
from ui.screens.wizard_screen import WizardScreen
from ui.shared.ui_types import Col
from ui.shared.ui_utils import DEFAULT_CURRENCY, exchange_choices


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
    assert isinstance(screen.tree.itemDelegateForColumn(Col.TICKER.value), TickerInputDelegate)
    assert isinstance(screen.tree.itemDelegateForColumn(Col.EXCHANGE.value), ExchangeDelegate)
    assert isinstance(screen.tree.itemDelegateForColumn(Col.TARGET_PCT.value), DecimalInputDelegate)

    assert screen.add_group_btn.text() == "Add Asset Group"
    assert screen.add_instrument_btn.text() == "Add Instrument"
    assert screen.delete_row_btn.text() == "Delete Selected"
    assert screen.total_label.text() == "Total portfolio (ILS): -"
    assert screen.rebalance_btn.text() == "Invest & Rebalance"


def test_welcome_screen_builds_expected_controls(qapp) -> None:
    _ = qapp
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


def test_welcome_screen_hides_version_label_when_app_version_is_unavailable(qapp) -> None:
    _ = qapp
    screen = WelcomeScreen(app_version=None)

    assert screen.version_label.isHidden()
    assert screen.version_label.text() == ""


def test_welcome_screen_set_app_version_updates_visibility_and_text(qapp) -> None:
    _ = qapp
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

    labels = [label.text() for label in screen.findChildren(QLabel)]
    assert "Execute Plan Step" in labels
    assert "Step -/-" in labels
    assert "font-size: 15px" in screen.step_progress.styleSheet()
    assert screen.wiz_info.text() == "-"
    assert screen.wiz_info.wordWrap()
    assert "font-size: 15px" in screen.wiz_info.styleSheet()
    assert screen.price_edit.placeholderText() == "Enter unit price (e.g. 123.45)"
    assert screen.price_edit.maxLength() == 11
    assert screen.calculate_btn.text() == "Calculate"
    assert screen.calculate_btn.parentWidget() is screen.price_edit.parentWidget()
    assert "font-size: 15px" in screen.price_label.styleSheet()
    assert "font-size: 15px" in screen.price_edit.styleSheet()
    assert "font-size: 15px" in screen.calculate_btn.styleSheet()
    assert screen.wiz_result.text() == "Units: - | Spent/Proceeds (ILS): - | Leftover vs plan (ILS): -"
    assert not screen.wiz_result.wordWrap()
    assert "font-size: 15px" in screen.wiz_result.styleSheet()
    assert screen.quit_btn.text() == "Quit"
    assert screen.back_to_portfolio_btn.text() == "Exit Wizard"
    assert screen.save_continue_btn.text() == "Save and continue"
    assert "font-size: 15px" in screen.save_continue_btn.styleSheet()
    assert screen.continue_without_save_btn.text() == "Skip Step"
    assert screen.save_continue_btn.parentWidget() is screen.wiz_result.parentWidget()
    btns_parent = screen.quit_btn.parentWidget()
    assert btns_parent is not None
    btns_layout = btns_parent.layout()
    assert btns_layout is not None
    assert btns_layout.indexOf(screen.quit_btn) < btns_layout.indexOf(screen.back_to_portfolio_btn)
    assert btns_layout.indexOf(screen.back_to_portfolio_btn) < btns_layout.indexOf(screen.continue_without_save_btn)
    assert btns_layout.indexOf(screen.save_continue_btn) == -1
    price_row_parent = screen.price_label.parentWidget()
    result_row_parent = screen.wiz_result.parentWidget()
    assert price_row_parent is not None
    assert result_row_parent is not None
    assert price_row_parent.width() == result_row_parent.width()
    min_input_width = QFontMetrics(screen.price_edit.font()).horizontalAdvance("0" * 11) + 24
    assert screen.price_edit.minimumWidth() >= min_input_width


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
