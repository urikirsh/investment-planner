from __future__ import annotations

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QLineEdit, QStyleOptionViewItem, QWidget

from ui.delegates.ticker_input_delegate import TickerInputDelegate


def test_ticker_delegate_accepts_ascii_alnum_and_rejects_symbols(qapp) -> None:
    _ = qapp
    delegate = TickerInputDelegate()
    parent = QWidget()
    editor = delegate.createEditor(parent, QStyleOptionViewItem(), QModelIndex())
    assert isinstance(editor, QLineEdit)
    assert editor.validator() is not None

    editor.setText("Ab12")
    assert editor.hasAcceptableInput()

    editor.setText("AB-12")
    assert not editor.hasAcceptableInput()

    editor.setText("AB 12")
    assert not editor.hasAcceptableInput()
