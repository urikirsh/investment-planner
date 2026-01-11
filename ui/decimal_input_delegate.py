from PySide6.QtWidgets import QStyledItemDelegate, QLineEdit
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression

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