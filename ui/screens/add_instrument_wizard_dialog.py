from __future__ import annotations

"""Add-instrument modal wizard used from the main editor.

The dialog is intentionally self-contained and keeps a 3-step flow:
1. choose exchange
2. enter ticker with exchange-specific live validation/normalization
3. enter name + strategy percentage and confirm add

The final step also protects against duplicate instrument names in the current
portfolio (case-insensitive), showing a Back-only modal so the user can keep
editing without closing the wizard.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
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
from ui.dialogs import confirm_discard_changes, show_error_with_back
from ui.shared.ui_utils import DEFAULT_EXCHANGE, exchange_choices


@dataclass(frozen=True)
class _TickerRule:
    """Exchange-specific ticker input/validation behavior."""

    max_length: int
    validator_pattern: str
    placeholder: str
    error_text: str


_TICKER_RULES: dict[Exchange, _TickerRule] = {
    Exchange.TASE: _TickerRule(
        max_length=7,
        validator_pattern=r"^\d{0,7}$",
        placeholder="7 digits (e.g. 1234567)",
        error_text="Ticker for TASE must be exactly 7 digits.",
    ),
    Exchange.NYSE: _TickerRule(
        max_length=4,
        validator_pattern=r"^[A-Za-z0-9]{0,4}$",
        placeholder="4 uppercase letters or digits (e.g. AB12)",
        error_text="Ticker for NYSE must be exactly 4 uppercase letters or digits.",
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


@dataclass(frozen=True)
class _Step3ValidationResult:
    """Pure step-3 validation result independent from widget state."""

    name: str
    name_error: str
    target_error: str
    target_in_group_pct: Decimal | None

    @property
    def is_valid(self) -> bool:
        return self.name_error == "" and self.target_error == ""


class AddInstrumentWizardDialog(QDialog):
    """Modal 3-step dialog used to add a new instrument row."""

    def __init__(
        self,
        *,
        instrument_group_name: str,
        is_non_investable_group: bool,
        existing_name_locations: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._instrument_group_name = instrument_group_name
        self._is_non_investable_group = is_non_investable_group
        self._existing_name_locations = existing_name_locations or {}
        self._result_data: AddInstrumentWizardResult | None = None
        self.setWindowTitle("Add Instrument")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.resize(560, 320)
        self._build()
        self._sync_exchange_ticker_validator()
        self._refresh_context_labels()
        self._update_step_2_validity()
        self._update_step_3_validity()

    @property
    def result_data(self) -> AddInstrumentWizardResult | None:
        """Return accepted wizard data, or ``None`` when canceled."""
        return self._result_data

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
        """Build step 3 page (`name`/`strategy %` + final add action)."""
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
        layout.addLayout(form)

        self.name_error_label = QLabel("")
        self.name_error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.name_error_label)
        self.target_pct_error_label = QLabel("")
        self.target_pct_error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.target_pct_error_label)

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
        """Advance from step 2 to step 3 and refresh derived UI state."""
        self._set_page(_WizardPage.DETAILS)
        self._refresh_context_labels()
        self._update_step_3_validity()

    def _set_page(self, page: _WizardPage) -> None:
        """Switch stacked wizard content to a typed page identifier."""
        self.pages.setCurrentIndex(int(page))

    def _on_exchange_changed(self, _value: str) -> None:
        """React to exchange selection changes and recompute ticker rules."""
        self._sync_exchange_ticker_validator()
        self._refresh_context_labels()
        self._update_step_2_validity()

    def _on_ticker_changed(self, _value: str) -> None:
        """Normalize ticker text as user types and revalidate step 2."""
        exchange = Exchange(self.exchange_combo.currentText())
        raw = self.ticker_edit.text()
        normalized = self._normalize_ticker(raw, exchange)
        if normalized != raw:
            cursor = self.ticker_edit.cursorPosition()
            # Prevent recursive textChanged while preserving cursor position.
            self.ticker_edit.blockSignals(True)
            self.ticker_edit.setText(normalized)
            self.ticker_edit.setCursorPosition(min(cursor, len(normalized)))
            self.ticker_edit.blockSignals(False)
        self._refresh_context_labels()
        self._update_step_2_validity()

    def _sync_exchange_ticker_validator(self) -> None:
        """Swap ticker regex/placeholder/max-length based on selected exchange."""
        exchange = Exchange(self.exchange_combo.currentText())
        rule = _TICKER_RULES[exchange]
        pattern = QRegularExpression(rule.validator_pattern)
        self.ticker_edit.setMaxLength(rule.max_length)
        self.ticker_edit.setPlaceholderText(rule.placeholder)
        self.ticker_edit.setValidator(QRegularExpressionValidator(pattern, self.ticker_edit))

    def _update_step_2_validity(self) -> None:
        """Validate ticker using exchange rules and gate step-advance action."""
        ticker = self.ticker_edit.text().strip()
        exchange = Exchange(self.exchange_combo.currentText())
        rule = _TICKER_RULES[exchange]

        is_valid = self._is_ticker_complete_for_exchange(ticker, exchange)
        self.ticker_error_label.setText("" if is_valid or not ticker else rule.error_text)

        if not ticker:
            self.ticker_error_label.setText("Ticker is required.")
        self.next_step_2_btn.setEnabled(is_valid)

    @staticmethod
    def _normalize_ticker(raw: str, exchange: Exchange) -> str:
        """Normalize raw ticker text to exchange-specific allowed character set."""
        if exchange == Exchange.TASE:
            return "".join(ch for ch in raw if ch.isdigit())
        return "".join(ch for ch in raw if ch.isascii() and ch.isalnum()).upper()

    @staticmethod
    def _is_ticker_complete_for_exchange(ticker: str, exchange: Exchange) -> bool:
        """Return whether ticker satisfies complete exchange-specific format rules."""
        if exchange == Exchange.TASE:
            return len(ticker) == 7 and ticker.isdigit()
        return len(ticker) == 4 and all(ch.isdigit() or ("A" <= ch <= "Z") for ch in ticker)

    def _update_step_3_validity(self) -> None:
        """Validate name/strategy fields and gate final `Add` action."""
        result = self._validate_step_3_inputs(
            name_text=self.name_edit.text(),
            target_text=self.target_pct_edit.text(),
            is_non_investable_group=self._is_non_investable_group,
        )
        self.name_error_label.setText(result.name_error)
        self.target_pct_error_label.setText(result.target_error)
        self.add_step_3_btn.setEnabled(result.is_valid)
        self._refresh_context_labels()

    @staticmethod
    def _validate_step_3_inputs(
        *,
        name_text: str,
        target_text: str,
        is_non_investable_group: bool,
    ) -> _Step3ValidationResult:
        """Return pure step-3 validation outcome from raw text input."""
        name = name_text.strip()
        if not name:
            return _Step3ValidationResult(
                name="",
                name_error="Name is required.",
                target_error="" if is_non_investable_group else "Strategy percentage is required." if not target_text.strip() else "",
                target_in_group_pct=None,
            )

        if is_non_investable_group:
            return _Step3ValidationResult(
                name=name,
                name_error="",
                target_error="",
                target_in_group_pct=None,
            )

        normalized_target = target_text.strip()
        if not normalized_target:
            return _Step3ValidationResult(
                name=name,
                name_error="",
                target_error="Strategy percentage is required.",
                target_in_group_pct=None,
            )
        try:
            target_in_group_pct = Decimal(normalized_target)
        except (InvalidOperation, ValueError):
            return _Step3ValidationResult(
                name=name,
                name_error="",
                target_error="Strategy percentage must be a number.",
                target_in_group_pct=None,
            )
        if target_in_group_pct < Decimal("0"):
            return _Step3ValidationResult(
                name=name,
                name_error="",
                target_error="Strategy percentage cannot be negative.",
                target_in_group_pct=None,
            )
        if target_in_group_pct > Decimal("100"):
            return _Step3ValidationResult(
                name=name,
                name_error="",
                target_error="Strategy percentage cannot exceed 100.",
                target_in_group_pct=None,
            )
        return _Step3ValidationResult(
            name=name,
            name_error="",
            target_error="",
            target_in_group_pct=target_in_group_pct,
        )

    def _accept_result(self) -> None:
        """Accept wizard only when step 3 is valid and name is not duplicate."""
        if not self.add_step_3_btn.isEnabled():
            return
        validation_result = self._validate_step_3_inputs(
            name_text=self.name_edit.text(),
            target_text=self.target_pct_edit.text(),
            is_non_investable_group=self._is_non_investable_group,
        )
        if not validation_result.is_valid:
            self._update_step_3_validity()
            return
        candidate_name = validation_result.name
        normalized_name = candidate_name.casefold()
        existing_location = self._existing_name_locations.get(normalized_name)
        if existing_location is not None:
            show_error_with_back(
                self,
                "Duplicate instrument name",
                (
                    f'An instrument named "{candidate_name}" already exists in this portfolio '
                    f"(under {existing_location}). Please choose a different name."
                ),
            )
            return
        self._result_data = AddInstrumentWizardResult(
            exchange=Exchange(self.exchange_combo.currentText()),
            ticker=self.ticker_edit.text().strip(),
            name=candidate_name,
            target_in_group_pct=validation_result.target_in_group_pct,
        )
        self.accept()

    def _request_cancel(self) -> None:
        """Reject wizard, guarding against accidental loss of in-progress input."""
        if self._is_dirty() and not confirm_discard_changes(self, noun="instrument wizard edits"):
            return
        self.reject()

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
        return False

    def _refresh_context_labels(self) -> None:
        """Render previous-step context text shown above current input fields."""
        exchange_text = self.exchange_combo.currentText() or "-"
        ticker_text = self.ticker_edit.text().strip() or "-"

        self.context_step_1.setText(
            f"Instrument group: {self._instrument_group_name}"
        )
        self.context_step_2.setText(
            f"Instrument group: {self._instrument_group_name}\n"
            f"Exchange: {exchange_text}"
        )
        self.context_step_3.setText(
            f"Instrument group: {self._instrument_group_name}\n"
            f"Exchange: {exchange_text}\n"
            f"Ticker: {ticker_text}"
        )
