from __future__ import annotations

"""Qt delegate for constrained ticker-symbol text editing."""

from PySide6.QtCore import QPersistentModelIndex, QRegularExpression, QModelIndex, QObject
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit, QStyleOptionViewItem, QStyledItemDelegate, QWidget


class TickerInputDelegate(QStyledItemDelegate):
    """
    Delegate that restricts ticker input to ASCII letters and digits.

    The editor allows empty input while typing; required/exact-format validation
    still runs in the save/planning validation pipeline.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._validator = QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9]*$"))

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
