"""UI behavior tests for the add-instrument wizard dialog."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
import time
from typing import Protocol

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import (
    ExchangeTickerKey,
    ExchangeTickerLocationIndex,
    build_exchange_ticker_key,
)
from portfolio_core.market_data import (
    TickerLookupCommunicationError,
    TickerLookupFound,
    TickerLookupMetadata,
    TickerLookupNotFound,
    TickerLookupResult,
)
from ui.screens.add_instrument_wizard_dialog import AddInstrumentWizardDialog


class WizardDialogFactory(Protocol):
    def __call__(
        self,
        *,
        instrument_group_name: str = "Equity",
        is_non_investable_group: bool = False,
        existing_name_locations: dict[str, str] | None = None,
        existing_ticker_locations: ExchangeTickerLocationIndex | None = None,
    ) -> AddInstrumentWizardDialog: ...


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp: object) -> None:
    """Ensure a QApplication exists for all tests in this module."""
    _ = qapp


@pytest.fixture(autouse=True)
def _mock_ticker_lookup_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default ticker lookup mock for deterministic wizard tests."""
    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        lambda *, exchange, ticker: (
            _lookup_found(exchange=exchange, ticker=ticker, display_name="Resolved Instrument")
            if bool(exchange) and bool(ticker)
            else TickerLookupNotFound()
        ),
    )


@pytest.fixture
def wizard_dialog_factory() -> WizardDialogFactory:
    """Build add-instrument wizard dialogs at step 1 for tests."""

    def _build(
        *,
        instrument_group_name: str = "Equity",
        is_non_investable_group: bool = False,
        existing_name_locations: dict[str, str] | None = None,
        existing_ticker_locations: ExchangeTickerLocationIndex | None = None,
    ) -> AddInstrumentWizardDialog:
        return AddInstrumentWizardDialog(
            instrument_group_name=instrument_group_name,
            is_non_investable_group=is_non_investable_group,
            existing_name_locations=existing_name_locations,
            existing_ticker_locations=existing_ticker_locations,
        )

    return _build


def _open_add_instrument_wizard_step_3(
    wizard_dialog_factory: WizardDialogFactory,
    *,
    instrument_group_name: str = "Equity",
    is_non_investable_group: bool = False,
    exchange: str = "NYSE",
    ticker: str = "AB12",
) -> AddInstrumentWizardDialog:
    """Create wizard dialog and navigate to step 3 with selected exchange/ticker."""
    dialog = wizard_dialog_factory(
        instrument_group_name=instrument_group_name,
        is_non_investable_group=is_non_investable_group,
    )
    dialog.exchange_combo.setCurrentText(exchange)
    dialog.next_step_1_btn.click()
    dialog.ticker_edit.setText(ticker)
    dialog.next_step_2_btn.click()
    _wait_until(lambda: dialog.pages.currentIndex() == 2)
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


def _submit_nyse_step_2(
    dialog: AddInstrumentWizardDialog,
    *,
    ticker: str = "AB12",
) -> None:
    """Navigate to step 2 with NYSE selected and submit ticker lookup."""
    dialog.exchange_combo.setCurrentText("NYSE")
    dialog.next_step_1_btn.click()
    dialog.ticker_edit.setText(ticker)
    dialog.next_step_2_btn.click()


def _open_add_instrument_wizard_step_2(
    wizard_dialog_factory: WizardDialogFactory,
    *,
    exchange: str = "NYSE",
    ticker: str = "AB12",
    existing_ticker_locations: ExchangeTickerLocationIndex | None = None,
) -> AddInstrumentWizardDialog:
    """Create wizard dialog and navigate to step 2 with selected exchange/ticker."""
    dialog = wizard_dialog_factory(existing_ticker_locations=existing_ticker_locations)
    dialog.exchange_combo.setCurrentText(exchange)
    dialog.next_step_1_btn.click()
    dialog.ticker_edit.setText(ticker)
    return dialog


def _ticker_location_index(*pairs: tuple[ExchangeTickerKey, str]) -> ExchangeTickerLocationIndex:
    """Build immutable duplicate-ticker index for wizard setup."""
    return ExchangeTickerLocationIndex.from_pairs(pairs)


def _capture_back_modal_messages(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Patch Back-only error modal helper and return captured `(title, message)` list."""
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.show_error_with_back",
        lambda _parent, title, message: shown.append((title, message)),
    )
    return shown


def _wait_until(predicate: Callable[[], bool], *, timeout_ms: int = 1500) -> None:
    """Pump Qt events until predicate returns true or timeout expires."""
    app = QApplication.instance()
    assert app is not None
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if predicate():
            return
        app.processEvents()
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for async wizard state")


def _lookup_found(*, exchange: Exchange, ticker: str, display_name: str) -> TickerLookupFound:
    """Build found lookup payload with canonical metadata."""
    return TickerLookupFound(
        metadata=TickerLookupMetadata(
            exchange=exchange,
            canonical_ticker=ticker,
            display_name=display_name,
        )
    )


def _assert_step_3_inputs_reset(dialog: AddInstrumentWizardDialog) -> None:
    """Assert step-3 editable fields and add state are reset."""
    assert dialog.name_edit.text() == ""
    assert dialog.target_pct_edit.text() == ""
    assert dialog.units_edit.text() == ""
    assert not dialog.add_step_3_btn.isEnabled()


def test_add_instrument_wizard_builds_expected_controls(wizard_dialog_factory: WizardDialogFactory) -> None:
    dialog = wizard_dialog_factory()

    assert dialog.windowTitle() == "Add Instrument"
    assert dialog.pages.count() == 3
    assert dialog.pages.currentIndex() == 0
    assert dialog.back_step_1_btn.text() == "Return to portfolio"
    assert dialog.next_step_1_btn.text() == "Next"
    assert "Instrument group: Equity" in dialog.context_step_1.text()
    assert "Exchange:" not in dialog.context_step_1.text()


def test_add_instrument_wizard_step_2_validates_ticker_by_exchange(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = wizard_dialog_factory()
    dialog.next_step_1_btn.click()

    dialog.exchange_combo.setCurrentText("TASE")
    dialog.ticker_edit.setText("1234")
    assert not dialog.next_step_2_btn.isEnabled()
    assert "6 or 7 digits" in dialog.ticker_error_label.text()

    dialog.ticker_edit.setText("123456")
    assert dialog.next_step_2_btn.isEnabled()
    dialog.ticker_edit.setText("1234567")
    assert dialog.next_step_2_btn.isEnabled()

    dialog.exchange_combo.setCurrentText("NYSE")
    dialog.ticker_edit.setText("ab12")
    assert dialog.ticker_edit.text() == "AB12"
    assert dialog.next_step_2_btn.isEnabled()

    dialog.ticker_edit.setText("t")
    assert dialog.ticker_edit.text() == "T"
    assert dialog.next_step_2_btn.isEnabled()

    dialog.ticker_edit.setText("brk.b")
    assert dialog.ticker_edit.text() == "BRK.B"
    assert dialog.next_step_2_btn.isEnabled()

    dialog.ticker_edit.setText("BRK..B")
    assert not dialog.next_step_2_btn.isEnabled()


def test_add_instrument_wizard_step_2_ticker_normalization_emits_text_changed_once(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = wizard_dialog_factory()
    dialog.next_step_1_btn.click()
    dialog.exchange_combo.setCurrentText("NYSE")

    spy = QSignalSpy(dialog.ticker_edit.textChanged)
    dialog.ticker_edit.setText("ab12")

    assert dialog.ticker_edit.text() == "AB12"
    assert spy.count() == 1


def test_add_instrument_wizard_step_2_nyse_ticker_limits_length_and_symbol_charset(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = wizard_dialog_factory()
    dialog.next_step_1_btn.click()
    dialog.exchange_combo.setCurrentText("NYSE")

    dialog.ticker_edit.setText("ABCDEFGHIJKLMNO")
    assert dialog.ticker_edit.text() == "ABCDEFGHIJKLMN"
    assert len(dialog.ticker_edit.text()) == 14

    dialog.ticker_edit.setText("AB-12")
    assert dialog.ticker_edit.text() == "AB12"


def test_add_instrument_wizard_step_2_enter_advances_when_next_enabled(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="NYSE",
        ticker="AB12",
    )
    dialog.ticker_edit.setFocus()

    assert dialog.next_step_2_btn.isEnabled() is True
    QTest.keyClick(dialog.ticker_edit, Qt.Key.Key_Return)

    _wait_until(lambda: dialog.pages.currentIndex() == 2)


def test_add_instrument_wizard_step_2_enter_does_not_advance_when_next_disabled(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="TASE",
        ticker="1234",
    )
    dialog.ticker_edit.setFocus()

    assert dialog.next_step_2_btn.isEnabled() is False
    QTest.keyClick(dialog.ticker_edit, Qt.Key.Key_Return)

    assert dialog.pages.currentIndex() == 1


def test_add_instrument_wizard_units_field_rejects_non_digit_input(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_3(wizard_dialog_factory)

    dialog.units_edit.setText("-")
    assert not dialog.units_edit.hasAcceptableInput()

    dialog.units_edit.setText("ab")
    assert not dialog.units_edit.hasAcceptableInput()

    dialog.units_edit.setText("12")
    assert dialog.units_edit.hasAcceptableInput()


def test_add_instrument_wizard_target_pct_field_rejects_non_decimal_input(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_3(wizard_dialog_factory)

    dialog.target_pct_edit.setText("")
    assert dialog.target_pct_edit.hasAcceptableInput()

    dialog.target_pct_edit.setText("-")
    assert not dialog.target_pct_edit.hasAcceptableInput()

    dialog.target_pct_edit.setText("ab")
    assert not dialog.target_pct_edit.hasAcceptableInput()

    dialog.target_pct_edit.setText("12.5")
    assert dialog.target_pct_edit.hasAcceptableInput()


def test_add_instrument_wizard_step_3_enables_add_when_inputs_are_valid(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_3(
        wizard_dialog_factory,
        exchange="TASE",
        ticker="1234567",
    )

    assert not dialog.add_step_3_btn.isEnabled()
    dialog.name_edit.setText("TA-35 ETF")
    dialog.target_pct_edit.setText("101")
    dialog.units_edit.setText("5")
    assert not dialog.add_step_3_btn.isEnabled()
    assert "cannot exceed 100" in dialog.target_pct_error_label.text()

    dialog.target_pct_edit.setText("25")
    assert dialog.add_step_3_btn.isEnabled()


def test_add_instrument_wizard_step_3_context_shows_only_prior_inputs(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_3(wizard_dialog_factory)
    _fill_step_3_details(dialog)

    assert "Instrument group: Equity" in dialog.context_step_3.text()
    assert "Exchange: NYSE" in dialog.context_step_3.text()
    assert "Ticker: AB12" in dialog.context_step_3.text()
    assert "Name:" not in dialog.context_step_3.text()
    assert "Strategy percentage:" not in dialog.context_step_3.text()


def test_add_instrument_wizard_exchange_change_resets_step_2_and_step_3_inputs(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_3(wizard_dialog_factory)
    _fill_step_3_details(dialog)

    dialog.back_step_3_btn.click()
    dialog.back_step_2_btn.click()
    dialog.exchange_combo.setCurrentText("TASE")

    assert dialog.ticker_edit.text() == ""
    _assert_step_3_inputs_reset(dialog)
    assert not dialog.next_step_2_btn.isEnabled()


def test_add_instrument_wizard_ticker_change_resets_step_3_inputs(
    wizard_dialog_factory: WizardDialogFactory,
) -> None:
    dialog = _open_add_instrument_wizard_step_3(wizard_dialog_factory)
    _fill_step_3_details(dialog)

    dialog.back_step_3_btn.click()
    dialog.ticker_edit.setText("CD34")

    _assert_step_3_inputs_reset(dialog)


def test_add_instrument_wizard_blocks_duplicate_name_with_back_only_modal(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = wizard_dialog_factory(
        existing_name_locations={"world etf": "US Equity"},
    )
    shown = _capture_back_modal_messages(monkeypatch)

    _submit_nyse_step_2(dialog)
    _wait_until(lambda: dialog.pages.currentIndex() == 2)
    dialog.name_edit.setText("  World ETF  ")
    dialog.target_pct_edit.setText("25")
    dialog.units_edit.setText("10")
    assert dialog.add_step_3_btn.isEnabled() is False
    assert "already exists in this portfolio" in dialog.name_error_label.text()
    dialog._accept_result()

    assert shown
    assert shown[0][0] == "Duplicate instrument name"
    assert 'named "World ETF"' in shown[0][1]
    assert "under US Equity" in shown[0][1]
    assert dialog.result_data is None


def test_add_instrument_wizard_step_2_blocks_unknown_ticker_with_back_modal(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = wizard_dialog_factory()
    shown = _capture_back_modal_messages(monkeypatch)
    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        lambda *, exchange, ticker: TickerLookupNotFound(),
    )

    _submit_nyse_step_2(dialog)

    _wait_until(lambda: len(shown) == 1)
    assert dialog.pages.currentIndex() == 1
    assert shown[0][0] == "Ticker not found"
    assert "selected exchange" in shown[0][1]


def test_add_instrument_wizard_step_2_blocks_duplicate_exchange_ticker_before_nyse_lookup(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object]] = []
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="NYSE",
        ticker="AB12",
        existing_ticker_locations=_ticker_location_index(
            (build_exchange_ticker_key(exchange=Exchange.NYSE, raw_ticker="AB12"), "US Equity")
        ),
    )
    shown = _capture_back_modal_messages(monkeypatch)

    def _checker(*, exchange: object, ticker: object) -> TickerLookupResult:
        calls.append((exchange, ticker))
        _ = (exchange, ticker)
        assert isinstance(exchange, Exchange)
        assert isinstance(ticker, str)
        return _lookup_found(exchange=exchange, ticker=ticker, display_name="Resolved Instrument")

    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        _checker,
    )

    assert dialog.next_step_2_btn.isEnabled() is False
    assert "already exists for this exchange" in dialog.ticker_error_label.text()
    dialog._go_to_step_3()
    assert dialog.pages.currentIndex() == 1
    assert shown
    assert shown[0][0] == "Duplicate ticker"
    assert 'Ticker "AB12" on NYSE already exists' in shown[0][1]
    assert "under US Equity" in shown[0][1]
    assert calls == []


def test_add_instrument_wizard_step_2_applies_duplicate_exchange_ticker_check_for_tase(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="TASE",
        ticker="1234567",
        existing_ticker_locations=_ticker_location_index(
            (build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker="1234567"), "IL Equity")
        ),
    )
    shown = _capture_back_modal_messages(monkeypatch)

    assert dialog.next_step_2_btn.isEnabled() is False
    assert "already exists for this exchange" in dialog.ticker_error_label.text()
    dialog._go_to_step_3()
    assert dialog.pages.currentIndex() == 1
    assert shown
    assert shown[0][0] == "Duplicate ticker"
    assert 'Ticker "1234567" on TASE already exists' in shown[0][1]
    assert "under IL Equity" in shown[0][1]


def test_add_instrument_wizard_step_2_tase_duplicate_check_normalizes_leading_zeros(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="TASE",
        ticker="0312017",
        existing_ticker_locations=_ticker_location_index(
            (build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker="312017"), "IL Equity")
        ),
    )
    shown = _capture_back_modal_messages(monkeypatch)

    assert dialog.next_step_2_btn.isEnabled() is False
    assert "already exists for this exchange" in dialog.ticker_error_label.text()
    dialog._go_to_step_3()
    assert dialog.pages.currentIndex() == 1
    assert shown
    assert shown[0][0] == "Duplicate ticker"
    assert 'Ticker "312017" on TASE already exists' in shown[0][1]
    assert "under IL Equity" in shown[0][1]


def test_add_instrument_wizard_step_2_allows_same_ticker_on_other_exchange(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="NYSE",
        ticker="1234567",
        existing_ticker_locations=_ticker_location_index(
            (build_exchange_ticker_key(exchange=Exchange.TASE, raw_ticker="1234567"), "IL Equity")
        ),
    )
    shown = _capture_back_modal_messages(monkeypatch)
    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        lambda *, exchange, ticker: (
            _lookup_found(exchange=exchange, ticker=ticker, display_name="Resolved Instrument")
            if bool(exchange) and bool(ticker)
            else TickerLookupNotFound()
        ),
    )

    dialog.next_step_2_btn.click()

    _wait_until(lambda: dialog.pages.currentIndex() == 2)
    assert shown == []


def test_add_instrument_wizard_step_2_prefills_step_3_name_from_successful_lookup(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="NYSE",
        ticker="AAPL",
    )
    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        lambda *, exchange, ticker: (
            _lookup_found(exchange=exchange, ticker=ticker, display_name="Apple Inc.")
            if bool(exchange) and bool(ticker)
            else TickerLookupNotFound()
        ),
    )

    dialog.next_step_2_btn.click()
    _wait_until(lambda: dialog.pages.currentIndex() == 2)

    assert dialog.name_edit.text() == "Apple Inc."
    dialog.name_edit.setText("Custom Name")
    assert dialog.name_edit.text() == "Custom Name"


def test_add_instrument_wizard_step_2_shows_network_error_message_for_communication_failure(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = wizard_dialog_factory()
    shown = _capture_back_modal_messages(monkeypatch)

    def _raise_network(*, exchange: object, ticker: object) -> TickerLookupResult:
        _ = (exchange, ticker)
        raise TickerLookupCommunicationError("offline")

    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        _raise_network,
    )

    _submit_nyse_step_2(dialog)

    _wait_until(lambda: len(shown) == 1)
    assert dialog.pages.currentIndex() == 1
    assert shown[0][0] == "Ticker lookup network error"
    assert "network/communication issue" in shown[0][1]


def test_add_instrument_wizard_step_2_shows_internal_error_message_for_unexpected_lookup_exception(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = wizard_dialog_factory()
    shown = _capture_back_modal_messages(monkeypatch)

    def _raise_internal(*, exchange: object, ticker: object) -> TickerLookupResult:
        _ = (exchange, ticker)
        raise RuntimeError("unexpected")

    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        _raise_internal,
    )

    _submit_nyse_step_2(dialog)

    _wait_until(lambda: len(shown) == 1)
    assert dialog.pages.currentIndex() == 1
    assert shown[0][0] == "Ticker lookup internal error"
    assert "internal error" in shown[0][1].lower()


def test_add_instrument_wizard_step_2_shows_internal_error_for_unexpected_lookup_payload(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = _open_add_instrument_wizard_step_2(
        wizard_dialog_factory,
        exchange="NYSE",
        ticker="AB12",
    )
    shown = _capture_back_modal_messages(monkeypatch)

    dialog._on_ticker_lookup_finished(object())

    assert dialog.pages.currentIndex() == 1
    assert shown[0][0] == "Ticker lookup internal error"
    assert "internal error" in shown[0][1].lower()


def test_add_instrument_wizard_keeps_close_guard_until_lookup_thread_finishes(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = wizard_dialog_factory()
    running = {"value": True}
    monkeypatch.setattr(
        dialog,
        "_is_ticker_lookup_running",
        lambda: running["value"],
    )

    blocked_event = QCloseEvent()
    dialog.closeEvent(blocked_event)
    assert blocked_event.isAccepted() is False

    running["value"] = False
    allowed_event = QCloseEvent()
    dialog.closeEvent(allowed_event)
    assert allowed_event.isAccepted() is True


def test_add_instrument_wizard_step_2_performs_tase_lookup_and_advances(
    wizard_dialog_factory: WizardDialogFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = wizard_dialog_factory()
    calls: list[tuple[object, object]] = []

    def _checker(*, exchange: object, ticker: object) -> TickerLookupResult:
        calls.append((exchange, ticker))
        _ = (exchange, ticker)
        assert isinstance(exchange, Exchange)
        assert isinstance(ticker, str)
        return _lookup_found(exchange=exchange, ticker=ticker, display_name="Resolved Instrument")

    monkeypatch.setattr(
        "ui.screens.add_instrument_wizard_dialog.lookup_ticker_in_exchange",
        _checker,
    )

    dialog.exchange_combo.setCurrentText("TASE")
    dialog.next_step_1_btn.click()
    dialog.ticker_edit.setText("1234567")
    dialog.next_step_2_btn.click()

    _wait_until(lambda: dialog.pages.currentIndex() == 2)
    assert calls == [(Exchange.TASE, "1234567")]


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
