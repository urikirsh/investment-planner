"""UI behavior tests for the add-instrument wizard dialog."""

from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtTest import QSignalSpy
from ui.screens.add_instrument_wizard_dialog import AddInstrumentWizardDialog


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp: object) -> None:
    """Ensure a QApplication exists for all tests in this module."""
    _ = qapp


def _open_add_instrument_wizard_step_3(
    *,
    instrument_group_name: str = "Equity",
    is_non_investable_group: bool = False,
    exchange: str = "NYSE",
    ticker: str = "AB12",
) -> AddInstrumentWizardDialog:
    """Create wizard dialog and navigate to step 3 with selected exchange/ticker."""
    dialog = AddInstrumentWizardDialog(
        instrument_group_name=instrument_group_name,
        is_non_investable_group=is_non_investable_group,
    )
    dialog.exchange_combo.setCurrentText(exchange)
    dialog.next_step_1_btn.click()
    dialog.ticker_edit.setText(ticker)
    dialog.next_step_2_btn.click()
    return dialog


def _fill_step_3_details(
    dialog: AddInstrumentWizardDialog,
    *,
    name: str = "World ETF",
    target_pct: str = "25",
    units: str = "10",
) -> None:
    """Populate wizard step-3 editable fields."""
    dialog.name_edit.setText(name)
    dialog.target_pct_edit.setText(target_pct)
    dialog.units_edit.setText(units)


def _assert_step_3_inputs_reset(dialog: AddInstrumentWizardDialog) -> None:
    """Assert step-3 editable fields and add state are reset."""
    assert dialog.name_edit.text() == ""
    assert dialog.target_pct_edit.text() == ""
    assert dialog.units_edit.text() == ""
    assert not dialog.add_step_3_btn.isEnabled()


def test_add_instrument_wizard_builds_expected_controls() -> None:
    dialog = AddInstrumentWizardDialog(
        instrument_group_name="Equity",
        is_non_investable_group=False,
    )

    assert dialog.windowTitle() == "Add Instrument"
    assert dialog.pages.count() == 3
    assert dialog.pages.currentIndex() == 0
    assert dialog.back_step_1_btn.text() == "Return to portfolio"
    assert dialog.next_step_1_btn.text() == "Next"
    assert "Instrument group: Equity" in dialog.context_step_1.text()
    assert "Exchange:" not in dialog.context_step_1.text()


def test_add_instrument_wizard_step_2_validates_ticker_by_exchange() -> None:
    dialog = AddInstrumentWizardDialog(
        instrument_group_name="Equity",
        is_non_investable_group=False,
    )
    dialog.next_step_1_btn.click()

    dialog.exchange_combo.setCurrentText("TASE")
    dialog.ticker_edit.setText("1234")
    assert not dialog.next_step_2_btn.isEnabled()
    assert "exactly 7 digits" in dialog.ticker_error_label.text()

    dialog.ticker_edit.setText("1234567")
    assert dialog.next_step_2_btn.isEnabled()

    dialog.exchange_combo.setCurrentText("NYSE")
    dialog.ticker_edit.setText("ab12")
    assert dialog.ticker_edit.text() == "AB12"
    assert dialog.next_step_2_btn.isEnabled()


def test_add_instrument_wizard_step_2_ticker_normalization_emits_text_changed_once() -> None:
    dialog = AddInstrumentWizardDialog(
        instrument_group_name="Equity",
        is_non_investable_group=False,
    )
    dialog.next_step_1_btn.click()
    dialog.exchange_combo.setCurrentText("NYSE")

    spy = QSignalSpy(dialog.ticker_edit.textChanged)
    dialog.ticker_edit.setText("ab12")

    assert dialog.ticker_edit.text() == "AB12"
    assert spy.count() == 1


def test_add_instrument_wizard_units_field_rejects_non_digit_input() -> None:
    dialog = _open_add_instrument_wizard_step_3()

    dialog.units_edit.setText("-")
    assert not dialog.units_edit.hasAcceptableInput()

    dialog.units_edit.setText("ab")
    assert not dialog.units_edit.hasAcceptableInput()

    dialog.units_edit.setText("12")
    assert dialog.units_edit.hasAcceptableInput()


def test_add_instrument_wizard_step_3_enables_add_when_inputs_are_valid() -> None:
    dialog = _open_add_instrument_wizard_step_3(exchange="TASE", ticker="1234567")

    assert not dialog.add_step_3_btn.isEnabled()
    dialog.name_edit.setText("TA-35 ETF")
    dialog.target_pct_edit.setText("101")
    dialog.units_edit.setText("5")
    assert not dialog.add_step_3_btn.isEnabled()
    assert "cannot exceed 100" in dialog.target_pct_error_label.text()

    dialog.target_pct_edit.setText("25")
    assert dialog.add_step_3_btn.isEnabled()


def test_add_instrument_wizard_step_3_context_shows_only_prior_inputs() -> None:
    dialog = _open_add_instrument_wizard_step_3()
    _fill_step_3_details(dialog)

    assert "Instrument group: Equity" in dialog.context_step_3.text()
    assert "Exchange: NYSE" in dialog.context_step_3.text()
    assert "Ticker: AB12" in dialog.context_step_3.text()
    assert "Name:" not in dialog.context_step_3.text()
    assert "Strategy percentage:" not in dialog.context_step_3.text()


def test_add_instrument_wizard_exchange_change_resets_step_2_and_step_3_inputs() -> None:
    dialog = _open_add_instrument_wizard_step_3()
    _fill_step_3_details(dialog)

    dialog.back_step_3_btn.click()
    dialog.back_step_2_btn.click()
    dialog.exchange_combo.setCurrentText("TASE")

    assert dialog.ticker_edit.text() == ""
    _assert_step_3_inputs_reset(dialog)
    assert not dialog.next_step_2_btn.isEnabled()


def test_add_instrument_wizard_ticker_change_resets_step_3_inputs() -> None:
    dialog = _open_add_instrument_wizard_step_3()
    _fill_step_3_details(dialog)

    dialog.back_step_3_btn.click()
    dialog.ticker_edit.setText("CD34")

    _assert_step_3_inputs_reset(dialog)


def test_add_instrument_wizard_blocks_duplicate_name_with_back_only_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = AddInstrumentWizardDialog(
        instrument_group_name="Equity",
        is_non_investable_group=False,
        existing_name_locations={"world etf": "US Equity"},
    )
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.show_error_with_back",
        lambda _parent, title, message: shown.append((title, message)),
    )

    dialog.exchange_combo.setCurrentText("NYSE")
    dialog.next_step_1_btn.click()
    dialog.ticker_edit.setText("AB12")
    dialog.next_step_2_btn.click()
    dialog.name_edit.setText("  World ETF  ")
    dialog.target_pct_edit.setText("25")
    dialog.units_edit.setText("10")
    dialog.add_step_3_btn.click()

    assert shown
    assert shown[0][0] == "Duplicate instrument name"
    assert 'named "World ETF"' in shown[0][1]
    assert "under US Equity" in shown[0][1]
    assert dialog.result_data is None


def test_add_instrument_wizard_validate_step_3_inputs_requires_name() -> None:
    result = AddInstrumentWizardDialog._validate_step_3(
        name_text="   ",
        target_text="25",
        units_text="10",
        is_non_investable_group=False,
    )

    assert result.is_valid is False
    assert result.name_error == "Name is required."
    assert result.target_error == ""
    assert result.units_error == ""
    assert result.payload is None


def test_add_instrument_wizard_validate_step_3_inputs_validates_target_range() -> None:
    result = AddInstrumentWizardDialog._validate_step_3(
        name_text="ETF A",
        target_text="101",
        units_text="10",
        is_non_investable_group=False,
    )

    assert result.is_valid is False
    assert result.name_error == ""
    assert result.target_error == "Strategy percentage cannot exceed 100."
    assert result.units_error == ""
    assert result.payload is None


def test_add_instrument_wizard_validate_step_3_inputs_returns_typed_result_for_valid_data() -> None:
    result = AddInstrumentWizardDialog._validate_step_3(
        name_text="  ETF A  ",
        target_text="25",
        units_text="10",
        is_non_investable_group=False,
    )

    assert result.is_valid is True
    assert result.name_error == ""
    assert result.target_error == ""
    assert result.units_error == ""
    assert result.payload is not None
    assert result.payload.name == "ETF A"
    assert result.payload.target_in_group_pct == Decimal("25")
    assert result.payload.units == 10


def test_add_instrument_wizard_validate_step_3_inputs_non_investable_ignores_target() -> None:
    result = AddInstrumentWizardDialog._validate_step_3(
        name_text="Legacy Holding",
        target_text="",
        units_text="7",
        is_non_investable_group=True,
    )

    assert result.is_valid is True
    assert result.name_error == ""
    assert result.target_error == ""
    assert result.units_error == ""
    assert result.payload is not None
    assert result.payload.name == "Legacy Holding"
    assert result.payload.target_in_group_pct is None
    assert result.payload.units == 7


def test_add_instrument_wizard_validate_step_3_inputs_requires_units() -> None:
    result = AddInstrumentWizardDialog._validate_step_3(
        name_text="ETF A",
        target_text="25",
        units_text="",
        is_non_investable_group=False,
    )

    assert result.is_valid is False
    assert result.units_error == "Units is required."
    assert result.payload is None


def test_add_instrument_wizard_validate_step_3_inputs_rejects_non_integer_units() -> None:
    result = AddInstrumentWizardDialog._validate_step_3(
        name_text="ETF A",
        target_text="25",
        units_text="2.5",
        is_non_investable_group=False,
    )

    assert result.is_valid is False
    assert result.units_error == "Units must be a non-negative integer."
    assert result.payload is None


def test_add_instrument_wizard_build_display_context_normalizes_empty_exchange_and_ticker() -> None:
    context = AddInstrumentWizardDialog._build_display_context(
        instrument_group_name="Equity",
        exchange_text="   ",
        ticker_text="",
    )

    assert context.instrument_group_name == "Equity"
    assert context.exchange_text == "-"
    assert context.ticker_text == "-"


def test_add_instrument_wizard_step_context_formatters_render_expected_lines() -> None:
    context = AddInstrumentWizardDialog._build_display_context(
        instrument_group_name="US Equity",
        exchange_text="NYSE",
        ticker_text="AB12",
    )

    assert AddInstrumentWizardDialog._format_step_1_context(context) == "Instrument group: US Equity"
    assert AddInstrumentWizardDialog._format_step_2_context(context) == "Instrument group: US Equity\nExchange: NYSE"
    assert (
        AddInstrumentWizardDialog._format_step_3_context(context)
        == "Instrument group: US Equity\nExchange: NYSE\nTicker: AB12"
    )


def test_add_instrument_wizard_format_context_lines_joins_ordered_pairs() -> None:
    text = AddInstrumentWizardDialog._format_context_lines(
        [("Instrument group", "US Equity"), ("Exchange", "NYSE"), ("Ticker", "AB12")]
    )

    assert text == "Instrument group: US Equity\nExchange: NYSE\nTicker: AB12"
