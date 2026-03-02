"""
UI construction tests for extracted screen widgets.

These tests verify that each screen module builds the expected controls,
defaults, and static configuration. They intentionally focus on structure
and wiring surfaces, not full interaction workflows (which are covered via
MainWindow integration behavior).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ui.decimal_input_delegate import DecimalInputDelegate
from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.summary_screen import SummaryScreen
from ui.screens.wizard_screen import WizardScreen
from ui.ui_types import Col


@pytest.fixture(scope="module")
def qapp():
    """Provide a shared QApplication instance for widget construction tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_editor_screen_builds_expected_controls(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()

    assert screen.cash_value_edit.placeholderText() == "e.g. 1000"
    assert screen.cash_reserve_edit.placeholderText() == "e.g. 20000"
    assert screen.future_tax_edit.text() == "0"
    assert screen.investable_balance_label.text() == "Investable balance: 0"

    assert screen.tree.columnCount() == len(Col)
    assert screen.tree.headerItem().text(Col.NAME.value) == "Name"
    assert screen.tree.headerItem().text(Col.DRIFT_PP.value) == "Drift (pp)"
    assert screen.tree.columnWidth(Col.DRIFT_PP.value) == 78

    assert isinstance(screen.tree.itemDelegateForColumn(Col.TOT_VALUE.value), DecimalInputDelegate)
    assert isinstance(screen.tree.itemDelegateForColumn(Col.TARGET_PCT.value), DecimalInputDelegate)

    assert screen.add_group_btn.text() == "Add Asset Group"
    assert screen.add_instrument_btn.text() == "Add Instrument"
    assert screen.delete_row_btn.text() == "Delete Selected"
    assert screen.total_label.text() == "Total portfolio value: -"
    assert screen.rebalance_btn.text() == "Invest & Rebalance"


def test_main_editor_screen_sets_header_tooltips(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()

    assert "asset group or instrument name" in screen.tree.headerItem().toolTip(Col.NAME.value).lower()
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
