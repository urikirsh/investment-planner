"""
Main editor screen UI.

This module defines `MainEditorScreen`, the presentational widget for screen 1
of the application flow. It is responsible for:
- building the editable portfolio UI (cash row, tree, controls, actions)
- exposing key child widgets as attributes for external signal wiring
- applying static UI setup (column headers, delegates, tooltips)

The class intentionally contains no business logic, persistence logic, or
navigation flow control. Those concerns stay in
`ui.main_window_controller.MainWindow`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.decimal_input_delegate import DecimalInputDelegate
from ui.tree_widget import InvestmentTreeWidget
from ui.ui_types import Col


class MainEditorScreen(QWidget):
    """
    Main editor UI (screen 1).

    This widget owns the main editor controls and exposes child widgets
    so the coordinator can connect behavior and orchestrate workflow.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Insert data here")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        layout.addWidget(self._build_cash_row())
        self.tree = self._build_tree()
        layout.addWidget(self.tree, 1)
        layout.addWidget(self._build_controls_row())
        layout.addWidget(self._build_totals_row())
        layout.addWidget(self._build_actions_row())

    def _build_cash_row(self) -> QWidget:
        cash_box = QWidget(self)
        cash_layout = QHBoxLayout(cash_box)

        cash_layout.addWidget(QLabel("Cash value:"))
        self.cash_value_edit = QLineEdit()
        self.cash_value_edit.setPlaceholderText("e.g. 1000")
        cash_layout.addWidget(self.cash_value_edit)

        cash_layout.addWidget(QLabel("Minimal cash reserve:"))
        self.cash_reserve_edit = QLineEdit()
        self.cash_reserve_edit.setPlaceholderText("e.g. 20000")
        cash_layout.addWidget(self.cash_reserve_edit)

        cash_layout.addWidget(QLabel("Future tax:"))
        self.future_tax_edit = QLineEdit()
        self.future_tax_edit.setPlaceholderText("e.g. 0")
        self.future_tax_edit.setText("0")
        cash_layout.addWidget(self.future_tax_edit)

        self.investable_balance_label = QLabel("Investable balance: 0")
        cash_layout.addWidget(self.investable_balance_label)

        cash_layout.addStretch(1)
        return cash_box

    def _build_tree(self) -> InvestmentTreeWidget:
        tree = InvestmentTreeWidget(self)
        tree.setColumnCount(len(Col))
        tree.setHeaderLabels(
            [
                "Name",
                "Total value",
                "Portfolio %",
                "Target %",
                "Strategy %",
                "Drift (pp)",
            ]
        )
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        tree.setIndentation(22)

        header = tree.header()
        header.setStretchLastSection(False)
        for col in Col:
            if col == Col.NAME:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.Stretch)
            elif col == Col.DRIFT_PP:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.Fixed)
            else:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.ResizeToContents)

        tree.setColumnWidth(Col.DRIFT_PP.value, 78)
        tree.headerItem().setTextAlignment(Col.DRIFT_PP.value, Qt.AlignmentFlag.AlignCenter)
        tree.setItemDelegateForColumn(
            Col.TOT_VALUE.value,
            DecimalInputDelegate(allow_empty=False, parent=tree),
        )
        tree.setItemDelegateForColumn(
            Col.TARGET_PCT.value,
            DecimalInputDelegate(allow_empty=False, parent=tree),
        )
        self._set_tree_header_tooltips(tree)
        return tree

    def _set_tree_header_tooltips(self, tree: InvestmentTreeWidget) -> None:
        header_item = tree.headerItem()
        header_item.setToolTip(
            Col.NAME.value,
            "The asset group or instrument name shown in this row.",
        )
        header_item.setToolTip(
            Col.TOT_VALUE.value,
            "Current value for this row.\n"
            "For an asset group: sum of its instruments.\n"
            "For an instrument: the instrument's own value.",
        )
        header_item.setToolTip(
            Col.PORTFOLIO_PCT.value,
            "Share of your full portfolio value (including cash and all instruments).",
        )
        header_item.setToolTip(
            Col.TARGET_PCT.value,
            "This is your goal for this row.\n"
            "For an asset group: part of your whole investment plan.\n"
            "For an instrument: part of its asset group.",
        )
        header_item.setToolTip(
            Col.STRATEGY_PCT.value,
            "This is where you are now.\n"
            "For an asset group: its current share of your invested portfolio.\n"
            "For an instrument: its current share inside its asset group.",
        )
        header_item.setToolTip(
            Col.DRIFT_PP.value,
            "How far you are from your goal for this row.\n"
            "Positive means above goal. Negative means below goal.",
        )

    def _build_controls_row(self) -> QWidget:
        controls = QWidget(self)
        controls_layout = QHBoxLayout(controls)

        self.add_group_btn = QPushButton("Add Asset Group")
        controls_layout.addWidget(self.add_group_btn)

        self.add_instrument_btn = QPushButton("Add Instrument")
        controls_layout.addWidget(self.add_instrument_btn)

        self.delete_row_btn = QPushButton("Delete Selected")
        controls_layout.addWidget(self.delete_row_btn)

        controls_layout.addStretch(1)
        return controls

    def _build_totals_row(self) -> QWidget:
        totals = QWidget(self)
        totals_layout = QHBoxLayout(totals)
        self.total_label = QLabel("Total portfolio value: -")
        totals_layout.addWidget(self.total_label)
        totals_layout.addStretch(1)
        return totals

    def _build_actions_row(self) -> QWidget:
        actions = QWidget(self)
        actions_layout = QHBoxLayout(actions)

        self.quit_btn = QPushButton("Quit")
        actions_layout.addWidget(self.quit_btn)

        self.invest_btn = QPushButton("Invest")
        actions_layout.addWidget(self.invest_btn)

        self.rebalance_btn = QPushButton("Invest & Rebalance")
        actions_layout.addWidget(self.rebalance_btn)

        self.save_btn = QPushButton("Save")
        actions_layout.addWidget(self.save_btn)

        self.save_as_btn = QPushButton("Save As")
        actions_layout.addWidget(self.save_as_btn)

        self.open_btn = QPushButton("Open")
        actions_layout.addWidget(self.open_btn)

        self.new_btn = QPushButton("New")
        actions_layout.addWidget(self.new_btn)

        actions_layout.addStretch(1)
        return actions
