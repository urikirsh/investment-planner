from __future__ import annotations

"""Add-instrument modal wizard used from the main editor.

The dialog is intentionally self-contained and keeps a 3-step flow:
1. choose exchange
2. enter ticker with exchange-specific live validation/normalization
3. enter name + strategy percentage + units and confirm add

Step 2 blocks duplicate `(exchange, ticker)` combinations already present in
the portfolio with inline validation before `Next` can run verification. The
final step similarly blocks duplicate instrument names (case-insensitive)
inline before `Add` can be used. Both keep a Back-only modal as a defensive
guard when submit handlers are invoked directly.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from PySide6.QtCore import QObject, QRegularExpression, QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QRegularExpressionValidator
from collections.abc import Callable
from enum import IntEnum

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from portfolio_core.models import Exchange
from portfolio_core.ticker_rules import (
    NYSE_TICKER_ERROR,
    NYSE_TICKER_INPUT_PATTERN,
    NYSE_TICKER_MAX_LENGTH,
    NYSE_TICKER_PLACEHOLDER,
    TASE_TICKER_ERROR,
    TASE_TICKER_INPUT_PATTERN,
    TASE_TICKER_MAX_LENGTH,
    TASE_TICKER_PLACEHOLDER,
    is_complete_nyse_ticker,
    is_complete_tase_ticker,
    normalize_ticker_for_exchange,
)
from portfolio_core.ticker_lookup_service import (
    TickerLookupCommunicationError,
    TickerLookupResult,
    lookup_ticker_in_exchange,
)
from ui.dialogs import confirm_discard_changes, show_error_with_back
from ui.shared.decimal_input_delegate import build_decimal_validator, build_non_negative_integer_validator
from ui.shared.loading_overlay import LoadingOverlay
from ui.shared.ui_utils import (
    DEFAULT_EXCHANGE,
    exchange_choices,
    normalize_and_validate_non_negative_integer_text,
)

_ExchangeTickerKey = tuple[Exchange, str]


@dataclass(frozen=True)
class _TickerRule:
    """Exchange-specific ticker input/validation behavior."""

    max_length: int
    validator_pattern: str
    placeholder: str
    error_text: str
    is_complete: Callable[[str], bool]


_TICKER_RULES: dict[Exchange, _TickerRule] = {
    Exchange.TASE: _TickerRule(
        max_length=TASE_TICKER_MAX_LENGTH,
        validator_pattern=TASE_TICKER_INPUT_PATTERN,
        placeholder=TASE_TICKER_PLACEHOLDER,
        error_text=TASE_TICKER_ERROR,
        is_complete=is_complete_tase_ticker,
    ),
    Exchange.NYSE: _TickerRule(
        max_length=NYSE_TICKER_MAX_LENGTH,
        validator_pattern=NYSE_TICKER_INPUT_PATTERN,
        placeholder=NYSE_TICKER_PLACEHOLDER,
        error_text=NYSE_TICKER_ERROR,
        is_complete=is_complete_nyse_ticker,
    ),
}


class _WizardPage(IntEnum):
    """Stacked-page indices for the 3-step add-instrument wizard."""

    EXCHANGE = 0
    TICKER = 1
    DETAILS = 2


@dataclass(frozen=True)
class AddInstrumentWizardResult:
    """Collected instrument values returned when the wizard is accepted."""

    exchange: Exchange
    ticker: str
    name: str
    target_in_group_pct: Decimal | None
    units: int


@dataclass(frozen=True)
class _ValidatedStep3Payload:
    """Validated step-3 values with non-optional units for accept flow."""

    name: str
    target_in_group_pct: Decimal | None
    units: int


@dataclass(frozen=True)
class _Step3ValidationOutcome:
    """Step-3 validation output containing both UI errors and payload."""

    name_error: str
    target_error: str
    units_error: str
    payload: _ValidatedStep3Payload | None

    @property
    def is_valid(self) -> bool:
        """Return whether step-3 validation produced an accepted payload."""
        return self.payload is not None


@dataclass(frozen=True)
class _AppliedStep3Outcome:
    """Step-3 UI-applied outcome reused by submit flow without recomputation."""

    payload: _ValidatedStep3Payload | None
    candidate_name: str
    duplicate_name_location: str | None


@dataclass(frozen=True)
class _TargetValidationResult:
    """Validation output for strategy-percentage input."""

    error: str
    target_in_group_pct: Decimal | None


@dataclass(frozen=True)
class _UnitsValidationResult:
    """Validation output for units input."""

    error: str
    units: int | None


@dataclass(frozen=True)
class _WizardDisplayContext:
    """Normalized values used for step-context label rendering."""

    instrument_group_name: str
    exchange_text: str
    ticker_text: str


@dataclass(frozen=True)
class _TickerLookupSuccessOutcome:
    """Successful step-2 ticker verification payload."""

    instrument_name: str


@dataclass(frozen=True)
class _TickerLookupErrorOutcome:
    """Failed step-2 ticker verification payload."""

    message_title: str
    message_text: str


_TickerLookupOutcome = _TickerLookupSuccessOutcome | _TickerLookupErrorOutcome


class _TickerLookupChecker(Protocol):
    """Typed callable contract for ticker lookup workers."""

    def __call__(self, *, exchange: Exchange, ticker: str) -> TickerLookupResult: ...


class _TickerLookupWorker(QObject):
    """Background worker that verifies ticker existence on selected exchange."""

    finished = Signal(object)

    def __init__(
        self,
        *,
        exchange: Exchange,
        ticker: str,
        checker: _TickerLookupChecker,
    ) -> None:
        """Store lookup inputs and callable used for background verification."""
        super().__init__()
        self._exchange = exchange
        self._ticker = ticker
        self._checker = checker

    @staticmethod
    def _error_outcome(*, message_title: str, message_text: str) -> _TickerLookupOutcome:
        """Build standardized failure outcome payload."""
        return _TickerLookupErrorOutcome(
            message_title=message_title,
            message_text=message_text,
        )

    @staticmethod
    def _network_error_outcome() -> _TickerLookupOutcome:
        """Build outcome payload for network/communication lookup failures."""
        return _TickerLookupWorker._error_outcome(
            message_title="Ticker lookup network error",
            message_text=(
                "Could not verify this ticker due to a network/communication issue. "
                "Please check your connection and try again."
            ),
        )

    @staticmethod
    def _internal_error_outcome() -> _TickerLookupOutcome:
        """Build outcome payload for unexpected internal lookup failures."""
        return _TickerLookupWorker._error_outcome(
            message_title="Ticker lookup internal error",
            message_text=(
                "Could not verify this ticker due to an internal error. "
                "Please try again or restart the app."
            ),
        )

    @staticmethod
    def _not_found_outcome() -> _TickerLookupOutcome:
        """Build outcome payload for missing symbol on selected exchange."""
        return _TickerLookupWorker._error_outcome(
            message_title="Ticker not found",
            message_text="Ticker was not found on the selected exchange. Please review and try again.",
        )

    @staticmethod
    def _success_outcome(*, instrument_name: str) -> _TickerLookupOutcome:
        """Build outcome payload for successful ticker verification."""
        return _TickerLookupSuccessOutcome(
            instrument_name=instrument_name,
        )

    @Slot()
    def run(self) -> None:
        """Run blocking ticker lookup and emit typed outcome for UI thread handling."""
        try:
            result = self._checker(exchange=self._exchange, ticker=self._ticker)
        except TickerLookupCommunicationError:
            self.finished.emit(self._network_error_outcome())
            return
        except Exception:
            self.finished.emit(self._internal_error_outcome())
            return

        if result.exists:
            self.finished.emit(self._success_outcome(instrument_name=result.instrument_name))
            return
        self.finished.emit(self._not_found_outcome())


class AddInstrumentWizardDialog(QDialog):
    """Modal 3-step dialog used to add a new instrument row."""

    def __init__(
        self,
        *,
        instrument_group_name: str,
        is_non_investable_group: bool,
        existing_name_locations: dict[str, str] | None = None,
        existing_ticker_locations: dict[_ExchangeTickerKey, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the modal wizard and wire all step UI/validation state."""
        super().__init__(parent)
        self._instrument_group_name = instrument_group_name
        self._is_non_investable_group = is_non_investable_group
        self._existing_name_locations = existing_name_locations or {}
        self._existing_ticker_locations = existing_ticker_locations or {}
        self._result_data: AddInstrumentWizardResult | None = None
        self._ticker_lookup_thread: QThread | None = None
        self._ticker_lookup_worker: _TickerLookupWorker | None = None
        self.setWindowTitle("Add Instrument")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.resize(560, 320)
        self._build()
        self._ticker_lookup_overlay = LoadingOverlay(self)
        self._ticker_lookup_overlay.set_status_text("reading data")
        self._last_exchange = self._current_exchange()
        self._last_ticker = self.ticker_edit.text().strip()
        self._sync_exchange_ticker_validator()
        self._sync_target_pct_validator()
        self._sync_units_validator()
        self._refresh_context_labels()
        self._update_step_2_validity()
        self._update_step_3_validity()

    @property
    def result_data(self) -> AddInstrumentWizardResult | None:
        """Return accepted wizard data, or ``None`` when canceled."""
        return self._result_data

    def closeEvent(self, event: QCloseEvent) -> None:
        """Prevent dialog teardown while background ticker verification is running."""
        if self._ticker_lookup_thread is not None:
            event.ignore()
            return
        super().closeEvent(event)

    def _build(self) -> None:
        """Build top-level layout and register all step pages."""
        root = QVBoxLayout(self)
        title = QLabel("Add Instrument Wizard")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        self.pages = QStackedWidget(self)
        self.pages.addWidget(self._build_step_1())
        self.pages.addWidget(self._build_step_2())
        self.pages.addWidget(self._build_step_3())
        root.addWidget(self.pages)

    def _build_step_1(self) -> QWidget:
        """Build step 1 page (`exchange` selection)."""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 1/3 - Choose exchange"))

        self.context_step_1 = QLabel("")
        self.context_step_1.setWordWrap(True)
        self.context_step_1.setStyleSheet("color: #4a4a4a;")
        layout.addWidget(self.context_step_1)

        form = QFormLayout()
        self.exchange_combo = QComboBox(page)
        self.exchange_combo.addItems(exchange_choices())
        self.exchange_combo.setCurrentText(DEFAULT_EXCHANGE.value)
        self.exchange_combo.currentTextChanged.connect(self._on_exchange_changed)
        form.addRow("Exchange:", self.exchange_combo)
        layout.addLayout(form)
        layout.addStretch(1)

        self.back_step_1_btn = QPushButton("Return to portfolio")
        self.next_step_1_btn = QPushButton("Next")
        self._wire_button(self.back_step_1_btn, self._request_cancel)
        self._wire_button(self.next_step_1_btn, lambda: self._set_page(_WizardPage.TICKER))
        layout.addLayout(
            self._build_actions_row(
                left_buttons=(self.back_step_1_btn,),
                right_buttons=(self.next_step_1_btn,),
            )
        )
        return page

    def _build_step_2(self) -> QWidget:
        """Build step 2 page (`ticker` input + validation feedback)."""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 2/3 - Enter ticker"))

        self.context_step_2 = QLabel("")
        self.context_step_2.setWordWrap(True)
        self.context_step_2.setStyleSheet("color: #4a4a4a;")
        layout.addWidget(self.context_step_2)

        form = QFormLayout()
        self.ticker_edit = QLineEdit(page)
        self.ticker_edit.textChanged.connect(self._on_ticker_changed)
        self.ticker_edit.returnPressed.connect(self._on_step_2_ticker_return_pressed)
        form.addRow("Ticker:", self.ticker_edit)
        layout.addLayout(form)

        self.ticker_error_label = QLabel("")
        self.ticker_error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.ticker_error_label)
        layout.addStretch(1)

        self.back_step_2_btn = QPushButton("Back")
        self.next_step_2_btn = QPushButton("Next")
        self.return_step_2_btn = QPushButton("Return to portfolio")
        self._wire_button(self.back_step_2_btn, lambda: self._set_page(_WizardPage.EXCHANGE))
        self._wire_button(self.next_step_2_btn, self._go_to_step_3)
        self._wire_button(self.return_step_2_btn, self._request_cancel)
        layout.addLayout(
            self._build_actions_row(
                left_buttons=(self.back_step_2_btn, self.return_step_2_btn),
                right_buttons=(self.next_step_2_btn,),
            )
        )
        return page

    def _build_step_3(self) -> QWidget:
        """Build step 3 page (`name`/`strategy %`/`units` + final add action)."""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 3/3 - Instrument details"))

        self.context_step_3 = QLabel("")
        self.context_step_3.setWordWrap(True)
        self.context_step_3.setStyleSheet("color: #4a4a4a;")
        layout.addWidget(self.context_step_3)

        form = QFormLayout()
        self.name_edit = QLineEdit(page)
        self.name_edit.textChanged.connect(self._update_step_3_validity)
        form.addRow("Name:", self.name_edit)

        self.target_pct_edit = QLineEdit(page)
        self.target_pct_edit.setPlaceholderText("0 to 100")
        self.target_pct_edit.textChanged.connect(self._update_step_3_validity)
        form.addRow("Strategy percentage:", self.target_pct_edit)

        self.units_edit = QLineEdit(page)
        self.units_edit.setPlaceholderText("Non-negative integer")
        self.units_edit.textChanged.connect(self._update_step_3_validity)
        form.addRow("Units:", self.units_edit)
        layout.addLayout(form)

        self.name_error_label = QLabel("")
        self.name_error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.name_error_label)
        self.target_pct_error_label = QLabel("")
        self.target_pct_error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.target_pct_error_label)
        self.units_error_label = QLabel("")
        self.units_error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.units_error_label)

        if self._is_non_investable_group:
            self.target_pct_edit.setEnabled(False)
            self.target_pct_edit.setPlaceholderText("Not applicable in non-investable bucket")
            self.target_pct_edit.setText("")

        layout.addStretch(1)

        self.back_step_3_btn = QPushButton("Back")
        self.add_step_3_btn = QPushButton("Add")
        self.return_step_3_btn = QPushButton("Return to portfolio")
        self._wire_button(self.back_step_3_btn, lambda: self._set_page(_WizardPage.TICKER))
        self._wire_button(self.add_step_3_btn, self._accept_result)
        self._wire_button(self.return_step_3_btn, self._request_cancel)
        layout.addLayout(
            self._build_actions_row(
                left_buttons=(self.back_step_3_btn, self.return_step_3_btn),
                right_buttons=(self.add_step_3_btn,),
            )
        )
        return page

    @staticmethod
    def _wire_button(button: QPushButton, callback: Callable[[], None]) -> None:
        """Connect one action button click to its callback."""
        button.clicked.connect(callback)

    @staticmethod
    def _build_actions_row(
        *,
        left_buttons: tuple[QPushButton, ...],
        right_buttons: tuple[QPushButton, ...],
    ) -> QHBoxLayout:
        """Build a standard wizard actions row with split left/right button groups."""
        actions = QHBoxLayout()
        for button in left_buttons:
            actions.addWidget(button)
        actions.addStretch(1)
        for button in right_buttons:
            actions.addWidget(button)
        return actions

    def _go_to_step_3(self) -> None:
        """Block duplicate exchange+ticker first, then run optional network verification."""
        duplicate_location = self._find_duplicate_ticker_location()
        if duplicate_location is not None:
            self._show_duplicate_ticker_error(duplicate_location)
            return
        self._start_step_2_verification_flow()

    def _find_duplicate_ticker_location(self) -> str | None:
        """Return location for duplicate `(exchange, ticker)` in portfolio, if present."""
        return self._validate_duplicate_ticker(
            key=self._current_step_2_key(),
            existing_ticker_locations=self._existing_ticker_locations,
        )

    @staticmethod
    def _validate_duplicate_ticker(
        *,
        key: _ExchangeTickerKey,
        existing_ticker_locations: dict[_ExchangeTickerKey, str],
    ) -> str | None:
        """Return duplicate location when `(exchange, ticker)` key already exists."""
        return existing_ticker_locations.get(key)

    def _show_duplicate_ticker_error(self, duplicate_location: str) -> None:
        """Show step-2 Back-only error modal for duplicate `(exchange, ticker)` input."""
        title, message = self._format_duplicate_ticker_error(duplicate_location)
        show_error_with_back(self, title, message)

    def _format_duplicate_ticker_error(self, duplicate_location: str) -> tuple[str, str]:
        """Build `(title, message)` shown when `(exchange, ticker)` already exists."""
        exchange, ticker_text = self._current_step_2_key()
        exchange_text = exchange.value
        return (
            "Duplicate ticker",
            (
                f'Ticker "{ticker_text}" on {exchange_text} already exists in this portfolio '
                f"(under {duplicate_location}). Please choose a different ticker."
            ),
        )

    @staticmethod
    def _format_duplicate_ticker_inline_error(duplicate_location: str) -> str:
        """Build inline step-2 error message for duplicate `(exchange, ticker)` input."""
        return (
            "Ticker already exists for this exchange in your portfolio "
            f"(under {duplicate_location})."
        )

    def _current_step_2_key(self) -> _ExchangeTickerKey:
        """Return current step-2 `(exchange, ticker)` key used for duplicate checks."""
        return (self._current_exchange(), self.ticker_edit.text().strip())

    def _start_step_2_verification_flow(self) -> None:
        """Run NYSE lookup when required; otherwise advance directly to details step."""
        if self._current_exchange() is Exchange.NYSE:
            if self._ticker_lookup_thread is not None:
                return
            self._begin_ticker_lookup()
            return
        self._advance_to_step_3()

    def _advance_to_step_3(self) -> None:
        """Advance wizard to step 3 and refresh dependent context/validation state."""
        self._set_page(_WizardPage.DETAILS)
        self._refresh_context_labels()
        self._update_step_3_validity()

    def _prefill_step_3_name_if_empty(self, instrument_name: str) -> None:
        """Pre-fill step-3 name only when empty so user edits are never overwritten."""
        if not instrument_name.strip():
            return
        if self.name_edit.text().strip():
            return
        with QSignalBlocker(self.name_edit):
            self.name_edit.setText(instrument_name)

    def _begin_ticker_lookup(self) -> None:
        """Create and start async ticker-lookup worker/thread wiring for step 2."""
        self._set_step_2_actions_enabled(False)
        self._ticker_lookup_overlay.show_overlay()
        worker = _TickerLookupWorker(
            exchange=self._current_exchange(),
            ticker=self.ticker_edit.text().strip(),
            checker=lookup_ticker_in_exchange,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ticker_lookup_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._ticker_lookup_worker = worker
        self._ticker_lookup_thread = thread
        thread.start()

    def _teardown_ticker_lookup(self) -> None:
        """Restore UI/action state and clear worker/thread references after lookup completion."""
        self._ticker_lookup_overlay.hide_overlay()
        self._set_step_2_actions_enabled(True)
        self._ticker_lookup_worker = None
        self._ticker_lookup_thread = None

    def _set_page(self, page: _WizardPage) -> None:
        """Switch stacked wizard content to a typed page identifier."""
        self.pages.setCurrentIndex(int(page))

    @Slot(object)
    def _on_ticker_lookup_finished(self, payload: object) -> None:
        """Handle async ticker check result and continue/block wizard flow."""
        outcome = cast(_TickerLookupOutcome, payload)
        self._teardown_ticker_lookup()
        if isinstance(outcome, _TickerLookupSuccessOutcome):
            self._prefill_step_3_name_if_empty(outcome.instrument_name)
            self._advance_to_step_3()
            return
        self._set_page(_WizardPage.TICKER)
        show_error_with_back(self, outcome.message_title, outcome.message_text)

    def _set_step_2_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable all step-2 actions during ticker verification."""
        self.back_step_2_btn.setEnabled(enabled)
        self.next_step_2_btn.setEnabled(enabled)
        self.return_step_2_btn.setEnabled(enabled)

    def _on_exchange_changed(self, _value: str) -> None:
        """React to exchange selection changes and recompute ticker rules."""
        current_exchange = self._current_exchange()
        if current_exchange != self._last_exchange:
            self._reset_inputs_after_step_1_change()
            self._last_exchange = current_exchange
        self._sync_exchange_ticker_validator()
        self._refresh_context_labels()
        self._update_step_2_validity()

    def _on_ticker_changed(self, _value: str) -> None:
        """Normalize ticker text as user types and revalidate step 2."""
        raw = self.ticker_edit.text()
        normalized = normalize_ticker_for_exchange(exchange=self._current_exchange(), raw=raw)
        if normalized != raw:
            cursor = self.ticker_edit.cursorPosition()
            # Prevent recursive textChanged while preserving cursor position.
            with QSignalBlocker(self.ticker_edit):
                self.ticker_edit.setText(normalized)
                self.ticker_edit.setCursorPosition(min(cursor, len(normalized)))
        current_ticker = self.ticker_edit.text().strip()
        if current_ticker != self._last_ticker:
            self._reset_inputs_after_step_2_change()
            self._last_ticker = current_ticker
        self._refresh_context_labels()
        self._update_step_2_validity()

    def _on_step_2_ticker_return_pressed(self) -> None:
        """Advance from step 2 on Enter when ticker is valid and Next is enabled."""
        if not self.next_step_2_btn.isEnabled():
            return
        self._go_to_step_3()

    def _sync_exchange_ticker_validator(self) -> None:
        """Swap ticker regex/placeholder/max-length based on selected exchange."""
        rule = self._current_ticker_rule()
        pattern = QRegularExpression(rule.validator_pattern)
        self.ticker_edit.setMaxLength(rule.max_length)
        self.ticker_edit.setPlaceholderText(rule.placeholder)
        self.ticker_edit.setValidator(QRegularExpressionValidator(pattern, self.ticker_edit))

    def _sync_units_validator(self) -> None:
        """Restrict units input to digits only while allowing temporary empty text."""
        self.units_edit.setValidator(
            build_non_negative_integer_validator(allow_empty=True, parent=self.units_edit)
        )

    def _sync_target_pct_validator(self) -> None:
        """Restrict target-percentage input to unsigned decimal syntax."""
        self.target_pct_edit.setValidator(
            build_decimal_validator(allow_empty=True, parent=self.target_pct_edit)
        )

    def _update_step_2_validity(self) -> None:
        """Validate ticker using exchange rules and gate step-advance action."""
        if self._ticker_lookup_thread is not None:
            return
        ticker = self.ticker_edit.text().strip()
        rule = self._current_ticker_rule()

        is_valid = rule.is_complete(ticker)
        duplicate_location = self._find_duplicate_ticker_location() if is_valid else None
        if not ticker:
            error_text = "Ticker is required."
        elif not is_valid:
            error_text = rule.error_text
        elif duplicate_location is not None:
            error_text = self._format_duplicate_ticker_inline_error(duplicate_location)
            is_valid = False
        else:
            error_text = ""
        self.ticker_error_label.setText(error_text)
        self.next_step_2_btn.setEnabled(is_valid)

    def _update_step_3_validity(self) -> None:
        """Validate name/strategy fields and gate final `Add` action."""
        _ = self._compute_and_apply_step_3_outcome()

    def _compute_and_apply_step_3_outcome(self) -> _AppliedStep3Outcome:
        """Compute step-3 validation, apply UI state, and return submit-ready outcome."""
        outcome = self._validate_step_3(
            name_text=self.name_edit.text(),
            target_text=self.target_pct_edit.text(),
            units_text=self.units_edit.text(),
            is_non_investable_group=self._is_non_investable_group,
        )
        candidate_name = (
            outcome.payload.name
            if outcome.payload is not None
            else self.name_edit.text().strip()
        )
        duplicate_name_location = self._find_duplicate_name_location(candidate_name) if candidate_name else None
        name_error = outcome.name_error
        is_valid = outcome.is_valid
        payload = outcome.payload
        if duplicate_name_location is not None:
            if payload is not None:
                name_error = self._format_duplicate_name_inline_error(duplicate_name_location)
                is_valid = False
                payload = None

        self.name_error_label.setText(name_error)
        self.target_pct_error_label.setText(outcome.target_error)
        self.units_error_label.setText(outcome.units_error)
        self.add_step_3_btn.setEnabled(is_valid)
        return _AppliedStep3Outcome(
            payload=payload,
            candidate_name=candidate_name,
            duplicate_name_location=duplicate_name_location,
        )

    @staticmethod
    def _validate_step_3(
        *,
        name_text: str,
        target_text: str,
        units_text: str,
        is_non_investable_group: bool,
    ) -> _Step3ValidationOutcome:
        """Return pure step-3 validation outcome from raw text input."""
        name = name_text.strip()
        name_error = "" if name else "Name is required."
        target_validation = AddInstrumentWizardDialog._validate_target_input(
            target_text=target_text,
            is_non_investable_group=is_non_investable_group,
        )
        units_validation = AddInstrumentWizardDialog._validate_units_input(units_text)

        payload = (
            _ValidatedStep3Payload(
                name=name,
                target_in_group_pct=target_validation.target_in_group_pct,
                units=units_validation.units,
            )
            if name_error == "" and target_validation.error == "" and units_validation.error == "" and units_validation.units is not None
            else None
        )

        return _Step3ValidationOutcome(
            name_error=name_error,
            target_error=target_validation.error,
            units_error=units_validation.error,
            payload=payload,
        )

    @staticmethod
    def _validate_target_input(*, target_text: str, is_non_investable_group: bool) -> _TargetValidationResult:
        """Validate strategy percentage for the selected group type."""
        if is_non_investable_group:
            return _TargetValidationResult(error="", target_in_group_pct=None)

        normalized_target = target_text.strip()
        if not normalized_target:
            return _TargetValidationResult(error="Strategy percentage is required.", target_in_group_pct=None)
        try:
            parsed_target = Decimal(normalized_target)
        except (InvalidOperation, ValueError):
            return _TargetValidationResult(error="Strategy percentage must be a number.", target_in_group_pct=None)
        if parsed_target < Decimal("0"):
            return _TargetValidationResult(error="Strategy percentage cannot be negative.", target_in_group_pct=None)
        if parsed_target > Decimal("100"):
            return _TargetValidationResult(error="Strategy percentage cannot exceed 100.", target_in_group_pct=None)
        return _TargetValidationResult(error="", target_in_group_pct=parsed_target)

    @staticmethod
    def _validate_units_input(units_text: str) -> _UnitsValidationResult:
        """Validate units as a required non-negative integer."""
        _normalized_text, units, error = normalize_and_validate_non_negative_integer_text(
            units_text,
            field_label="Units",
            required=True,
        )
        return _UnitsValidationResult(error=error, units=units)

    @staticmethod
    def _validate_duplicate_name(*, normalized_name: str, existing_name_locations: dict[str, str]) -> str | None:
        """Return duplicate location for normalized name if already present."""
        return existing_name_locations.get(normalized_name)

    def _find_duplicate_name_location(self, candidate_name: str) -> str | None:
        """Return duplicate-name location in portfolio for candidate instrument name."""
        return self._validate_duplicate_name(
            normalized_name=candidate_name.casefold(),
            existing_name_locations=self._existing_name_locations,
        )

    @staticmethod
    def _format_duplicate_name_inline_error(duplicate_location: str) -> str:
        """Build inline step-3 error for duplicate instrument name."""
        return f"Instrument name already exists in this portfolio (under {duplicate_location})."

    @staticmethod
    def _format_duplicate_name_error(candidate_name: str, existing_location: str) -> tuple[str, str]:
        """Build `(title, message)` shown when instrument name already exists."""
        return (
            "Duplicate instrument name",
            (
                f'An instrument named "{candidate_name}" already exists in this portfolio '
                f"(under {existing_location}). Please choose a different name."
            ),
        )

    def _show_duplicate_name_error(self, *, candidate_name: str, existing_location: str) -> None:
        """Show Back-only duplicate-name error modal."""
        title, message = self._format_duplicate_name_error(candidate_name, existing_location)
        show_error_with_back(self, title, message)

    def _accept_result(self) -> None:
        """Accept wizard only when step 3 is valid and name is not duplicate."""
        applied_outcome = self._compute_and_apply_step_3_outcome()
        if applied_outcome.duplicate_name_location is not None:
            self._show_duplicate_name_error(
                candidate_name=applied_outcome.candidate_name,
                existing_location=applied_outcome.duplicate_name_location,
            )
            return
        if applied_outcome.payload is None:
            return
        validated = applied_outcome.payload
        self._result_data = AddInstrumentWizardResult(
            exchange=self._current_exchange(),
            ticker=self.ticker_edit.text().strip(),
            name=validated.name,
            target_in_group_pct=validated.target_in_group_pct,
            units=validated.units,
        )
        self.accept()

    def _current_exchange(self) -> Exchange:
        """Return currently selected exchange value from the combo box."""
        return Exchange(self.exchange_combo.currentText())

    def _current_ticker_rule(self) -> _TickerRule:
        """Return the active ticker behavior bundle for current exchange."""
        return _TICKER_RULES[self._current_exchange()]

    def _request_cancel(self) -> None:
        """Reject wizard, guarding against accidental loss of in-progress input."""
        if self._is_dirty() and not confirm_discard_changes(self, noun="instrument wizard edits"):
            return
        self.reject()

    def _reset_inputs_after_step_1_change(self) -> None:
        """Reset all fields from steps 2 and 3 after exchange changes."""
        with QSignalBlocker(self.ticker_edit):
            self.ticker_edit.setText("")
        self._last_ticker = ""
        self._reset_inputs_after_step_2_change()

    def _reset_inputs_after_step_2_change(self) -> None:
        """Reset step-3 inputs and errors after ticker changes."""
        with QSignalBlocker(self.name_edit):
            self.name_edit.setText("")
        if not self._is_non_investable_group:
            with QSignalBlocker(self.target_pct_edit):
                self.target_pct_edit.setText("")
        with QSignalBlocker(self.units_edit):
            self.units_edit.setText("")
        self._clear_step_3_state()

    def _clear_step_3_state(self) -> None:
        """Clear step-3 validation UI state after upstream input changes."""
        self.name_error_label.setText("")
        self.target_pct_error_label.setText("")
        self.units_error_label.setText("")
        self.add_step_3_btn.setEnabled(False)

    def _is_dirty(self) -> bool:
        """Return whether any wizard field diverged from initial defaults."""
        if self.exchange_combo.currentText() != DEFAULT_EXCHANGE.value:
            return True
        if self.ticker_edit.text().strip():
            return True
        if self.name_edit.text().strip():
            return True
        if not self._is_non_investable_group and self.target_pct_edit.text().strip():
            return True
        if self.units_edit.text().strip():
            return True
        return False

    def _refresh_context_labels(self) -> None:
        """Render previous-step context text shown above current input fields."""
        context = self._build_display_context(
            instrument_group_name=self._instrument_group_name,
            exchange_text=self.exchange_combo.currentText(),
            ticker_text=self.ticker_edit.text(),
        )
        self.context_step_1.setText(self._format_step_1_context(context))
        self.context_step_2.setText(self._format_step_2_context(context))
        self.context_step_3.setText(self._format_step_3_context(context))

    @staticmethod
    def _build_display_context(
        *,
        instrument_group_name: str,
        exchange_text: str,
        ticker_text: str,
    ) -> _WizardDisplayContext:
        """Build normalized display context from raw input values."""
        return _WizardDisplayContext(
            instrument_group_name=instrument_group_name,
            exchange_text=exchange_text.strip() or "-",
            ticker_text=ticker_text.strip() or "-",
        )

    @staticmethod
    def _format_step_1_context(context: _WizardDisplayContext) -> str:
        """Format context string for step 1."""
        return AddInstrumentWizardDialog._format_context_lines(
            [("Instrument group", context.instrument_group_name)]
        )

    @staticmethod
    def _format_step_2_context(context: _WizardDisplayContext) -> str:
        """Format context string for step 2."""
        return AddInstrumentWizardDialog._format_context_lines(
            [
                ("Instrument group", context.instrument_group_name),
                ("Exchange", context.exchange_text),
            ]
        )

    @staticmethod
    def _format_step_3_context(context: _WizardDisplayContext) -> str:
        """Format context string for step 3."""
        return AddInstrumentWizardDialog._format_context_lines(
            [
                ("Instrument group", context.instrument_group_name),
                ("Exchange", context.exchange_text),
                ("Ticker", context.ticker_text),
            ]
        )

    @staticmethod
    def _format_context_lines(lines: list[tuple[str, str]]) -> str:
        """Join ordered `(label, value)` pairs into multiline `label: value` text."""
        return "\n".join(f"{label}: {value}" for label, value in lines)
