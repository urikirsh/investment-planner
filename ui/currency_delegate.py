from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QComboBox, QStyleOptionViewItem, QStyledItemDelegate, QWidget


class CurrencyDelegate(QStyledItemDelegate):
    """Dropdown editor delegate for instrument currency cells."""

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
        model: object,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not isinstance(editor, QComboBox):
            return
        # Qt model has setData; keep typed loosely to avoid importing Qt model classes.
        if hasattr(model, "setData"):
            model.setData(index, editor.currentText())  # type: ignore[attr-defined]
