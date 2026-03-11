from __future__ import annotations

"""Qt delegate for controlled instrument-exchange editing."""

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QComboBox, QStyleOptionViewItem, QStyledItemDelegate, QWidget

from ui.shared.ui_utils import DEFAULT_EXCHANGE, exchange_choices


class ExchangeDelegate(QStyledItemDelegate):
    """
    Dropdown editor delegate for instrument exchange cells.

    Keeping exchange choices in a delegate prevents free-text drift and keeps
    cell editing aligned with domain validation constraints.
    """

    _choices = exchange_choices()

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
        current = str(index.data() or DEFAULT_EXCHANGE.value)
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
