from PySide6.QtWidgets import QStyledItemDelegate, QLineEdit, QWidget
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression, QModelIndex, QPersistentModelIndex

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
        super().__init__(parent)
        # Simple numeric syntax: digits with optional single dot and digits after it.
        # Allows "12", "12.3", "0.0". (No sign)
        self._validator = QRegularExpressionValidator(
            QRegularExpression(r"^\d+(\.\d+)?$" if not allow_empty else r"^(\d+(\.\d+)?)?$")
        )

    def createEditor(self, parent: QWidget, option, index: QModelIndex | QPersistentModelIndex):
        """
        Create a ``QLineEdit`` editor with the configured decimal validator.

        Notes
        -----
        This delegate validates input *format* only; business/range validation is
        intentionally handled in higher-level validation layers.
        """
        editor = QLineEdit(parent)
        editor.setValidator(self._validator)
        return editor
