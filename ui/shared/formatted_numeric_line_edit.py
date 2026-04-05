from __future__ import annotations

from decimal import Decimal

from PySide6.QtGui import QFocusEvent, QValidator
from PySide6.QtWidgets import QLineEdit, QWidget

from ui.shared.decimal_input_delegate import build_decimal_validator, build_non_negative_integer_validator
from ui.shared.ui_utils import (
    fmt_decimal_grouped,
    fmt_non_negative_integer_grouped,
    get_decimal_line_edit_raw_text,
    set_decimal_line_edit_raw_text,
    try_parse_grouped_non_negative_integer_display,
)

_RAW_INTEGER_TEXT_PROPERTY = "_raw_integer_text"


class _FormattedNumericLineEdit(QLineEdit):
    """Base line edit that edits raw numeric text and renders formatted display text when idle."""

    def __init__(self, *, validator: QValidator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setValidator(validator)
        self._updating_display = False
        self._initialize_raw_text()
        self.textChanged.connect(self._sync_raw_text_from_editor)
        self.editingFinished.connect(self._format_for_display)

    def setText(self, text: str | None) -> None:
        """Render programmatic values using the non-editing display format."""
        normalized = "" if text is None else text.strip()
        self._set_raw_text(normalized)
        self._set_display_text(self._format_raw_text(normalized))

    def focusInEvent(self, event: QFocusEvent) -> None:
        """Show raw numeric text while the user edits the field."""
        self._set_display_text(self._get_raw_text())
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        """Restore formatted display text after editing ends."""
        self._format_for_display()
        super().focusOutEvent(event)

    def _set_display_text(self, text: str) -> None:
        self._updating_display = True
        try:
            super().setText(text)
        finally:
            self._updating_display = False

    def _sync_raw_text_from_editor(self, text: str) -> None:
        """Keep raw text synchronized while the user edits the field."""
        if self._updating_display:
            return
        self._set_raw_text(text.strip())

    def _format_for_display(self) -> None:
        """Apply formatted display text from the current raw value."""
        formatted = self._format_raw_text(self._get_raw_text())
        if formatted != self.text():
            self._set_display_text(formatted)

    def _initialize_raw_text(self) -> None:
        """Initialize raw widget state when the control is created."""
        raise NotImplementedError

    def _get_raw_text(self) -> str:
        """Return the current raw numeric text."""
        raise NotImplementedError

    def _set_raw_text(self, text: str) -> None:
        """Store the current raw numeric text."""
        raise NotImplementedError

    @staticmethod
    def _format_raw_text(raw_text: str) -> str:
        """Return idle display text for one raw numeric value."""
        raise NotImplementedError


class FormattedDecimalLineEdit(_FormattedNumericLineEdit):
    """Line edit that shows grouped decimal values when not actively being edited."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(validator=build_decimal_validator(allow_empty=True, parent=parent), parent=parent)

    def _initialize_raw_text(self) -> None:
        set_decimal_line_edit_raw_text(self, "")

    def _get_raw_text(self) -> str:
        return get_decimal_line_edit_raw_text(self)

    def _set_raw_text(self, text: str) -> None:
        set_decimal_line_edit_raw_text(self, text)

    @staticmethod
    def _format_raw_text(raw_text: str) -> str:
        if not raw_text:
            return ""
        return fmt_decimal_grouped(Decimal(raw_text))


class FormattedIntegerLineEdit(_FormattedNumericLineEdit):
    """Line edit that shows grouped integer values when not actively being edited."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            validator=build_non_negative_integer_validator(allow_empty=True, parent=parent),
            parent=parent,
        )

    def _initialize_raw_text(self) -> None:
        self.setProperty(_RAW_INTEGER_TEXT_PROPERTY, "")

    def _get_raw_text(self) -> str:
        raw = self.property(_RAW_INTEGER_TEXT_PROPERTY)
        return raw if isinstance(raw, str) else ""

    def _set_raw_text(self, text: str) -> None:
        self.setProperty(_RAW_INTEGER_TEXT_PROPERTY, text)

    @staticmethod
    def _format_raw_text(raw_text: str) -> str:
        if not raw_text:
            return ""
        if try_parse_grouped_non_negative_integer_display(raw_text) is not None:
            return raw_text
        if not raw_text.isdigit():
            return raw_text
        return fmt_non_negative_integer_grouped(int(raw_text))
