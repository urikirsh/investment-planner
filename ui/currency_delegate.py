from __future__ import annotations

"""Qt delegate for controlled instrument-currency editing."""

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QComboBox, QStyleOptionViewItem, QStyledItemDelegate, QWidget


class CurrencyDelegate(QStyledItemDelegate):
    """
    Dropdown editor delegate for instrument currency cells.

    Keeping currency choices in a delegate prevents free-text drift and keeps
    cell editing aligned with domain validation constraints.
    """

    _choices = ("ILS", "USD")

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        _ = option
        _ = index
        editor = QComboBox(parent)
        editor.addItems(list(self._choices))
        return editor

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        if not isinstance(editor, QComboBox):
            return
        current = str(index.data() or "ILS")
        pos = editor.findText(current)
        editor.setCurrentIndex(pos if pos >= 0 else 0)

    def setModelData(
        self,
        editor: QWidget,
        model: QAbstractItemModel,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not isinstance(editor, QComboBox):
            return
        model.setData(index, editor.currentText())
