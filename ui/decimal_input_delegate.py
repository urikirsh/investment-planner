from PySide6.QtWidgets import QStyledItemDelegate, QLineEdit
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression

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

class DecimalInputDelegate(QStyledItemDelegate):
    def __init__(self, allow_empty: bool, parent=None):
        super().__init__(parent)
        # Simple numeric syntax: digits with optional single dot and digits after it.
        # Allows "12", "12.3", "0.0". (No sign)
        self._validator = QRegularExpressionValidator(
            QRegularExpression(r"^\d+(\.\d+)?$" if not allow_empty else r"^(\d+(\.\d+)?)?$")
        )

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setValidator(self._validator)
        return editor