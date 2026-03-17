from PySide6.QtCore import QPersistentModelIndex, QRegularExpression, QModelIndex, QObject
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit, QStyleOptionViewItem, QStyledItemDelegate, QWidget

"""
decimal_input_delegate.py

Qt item delegate for validating decimal numeric input in editable cells.

This module provides a QStyledItemDelegate that restricts user input
to valid decimal number syntax while editing table or tree cells.
It is used to prevent malformed numeric input before commit-time
business validation occurs.

The delegate enforces input format only; range and strategy validation
are handled elsewhere.
"""


class _ValidatorInputDelegate(QStyledItemDelegate):
    """Base delegate that applies a preconfigured validator to line editors."""

    def __init__(self, validator: QRegularExpressionValidator, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._validator = validator

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        _ = option
        _ = index
        editor = QLineEdit(parent)
        editor.setValidator(self._validator)
        return editor


# Validator builders
def build_decimal_validator(
    *,
    allow_empty: bool,
    parent: QObject | None = None,
) -> QRegularExpressionValidator:
    """Build validator for unsigned decimal input."""
    pattern = r"^\d+(\.\d+)?$" if not allow_empty else r"^(\d+(\.\d+)?)?$"
    return QRegularExpressionValidator(QRegularExpression(pattern), parent)


class DecimalInputDelegate(_ValidatorInputDelegate):
    def __init__(self, allow_empty: bool, parent: QObject | None = None) -> None:
        """
        Create a delegate that constrains editor input to unsigned decimal syntax.

        Parameters
        ----------
        allow_empty:
            If ``True``, an empty string is accepted during editing.
            If ``False``, at least one digit is required.
        parent:
            Optional Qt parent object.
        """
        validator = build_decimal_validator(allow_empty=allow_empty, parent=parent)
        # Simple numeric syntax: digits with optional single dot and digits after it.
        # Allows "12", "12.3", "0.0". (No sign)
        super().__init__(validator=validator, parent=parent)


def build_non_negative_integer_validator(
    *,
    allow_empty: bool,
    parent: QObject | None = None,
) -> QRegularExpressionValidator:
    """Build validator for non-negative integer input."""
    pattern = r"^\d*$" if allow_empty else r"^\d+$"
    return QRegularExpressionValidator(QRegularExpression(pattern), parent)


class NonNegativeIntegerInputDelegate(_ValidatorInputDelegate):
    """Delegate that restricts editor input to non-negative integers."""

    def __init__(self, allow_empty: bool, parent: QObject | None = None) -> None:
        super().__init__(
            validator=build_non_negative_integer_validator(allow_empty=allow_empty, parent=parent),
            parent=parent,
        )
