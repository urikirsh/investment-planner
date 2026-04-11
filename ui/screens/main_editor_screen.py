"""
Main editor screen UI.

This module defines `MainEditorScreen`, the presentational widget for screen 2
of the application flow. It is responsible for:
- building the editable portfolio UI (cash row, tree, controls, actions)
- exposing key child widgets as attributes for external signal wiring
- applying static UI setup (column headers, delegates, tooltips)

Main tree note:
- includes required instrument `Ticker` column (exchange-specific format rules)
- includes an instrument `Quantity` column for user tracking convenience
  (required non-negative integer).

The class intentionally contains no business logic, persistence logic, or
navigation flow control. Those concerns stay in
`ui.main_window.MainWindow`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ui.shared.decimal_input_delegate import (
    NonNegativeIntegerInputDelegate,
    PercentInputDelegate,
)
from ui.shared.formatted_numeric_line_edit import FormattedDecimalLineEdit
from ui.tree_widget import InvestmentTreeWidget
from ui.shared.ui_types import Col
from ui.shared.ui_utils import (
    BASE_CURRENCY_SUFFIX,
    DEFAULT_CURRENCY,
    exchange_choices,
)


class MainEditorScreen(QWidget):
    """
    Main editor UI (screen 2).

    This widget owns the main editor controls and exposes child widgets
    so the coordinator can connect behavior and orchestrate workflow.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Insert data here")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        layout.addWidget(self._build_file_toolbar())
        layout.addWidget(self._build_cash_row())
        self.tree = self._build_tree()
        layout.addWidget(self.tree, 1)
        layout.addWidget(self._build_controls_row())
        layout.addWidget(self._build_totals_row())
        layout.addWidget(self._build_actions_row())

    def _build_file_toolbar(self) -> QToolBar:
        toolbar = QToolBar("File actions", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(toolbar.iconSize())
        toolbar.setStyleSheet(
            "QToolBar { background: #f5f7fa; border: 1px solid #d8dde6; border-radius: 6px; spacing: 6px; padding: 4px; }"
        )

        self.new_btn = QPushButton("New")
        toolbar.addWidget(self.new_btn)

        self.open_btn = QPushButton("Open")
        toolbar.addWidget(self.open_btn)

        self.save_btn = QPushButton("Save")
        toolbar.addWidget(self.save_btn)

        self.save_as_btn = QPushButton("Save As")
        toolbar.addWidget(self.save_as_btn)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        return toolbar

    def _build_cash_row(self) -> QWidget:
        cash_box = QWidget(self)
        cash_layout = QHBoxLayout(cash_box)
        cash_layout.setContentsMargins(0, 0, 0, 0)

        cash_layout.addWidget(QLabel(f"Cash value {BASE_CURRENCY_SUFFIX}:"))
        self.cash_value_edit = FormattedDecimalLineEdit(cash_box)
        self.cash_value_edit.setPlaceholderText("e.g. 1000")
        cash_layout.addWidget(self.cash_value_edit)

        cash_layout.addWidget(QLabel(f"Minimal cash reserve {BASE_CURRENCY_SUFFIX}:"))
        self.cash_reserve_edit = FormattedDecimalLineEdit(cash_box)
        self.cash_reserve_edit.setPlaceholderText("e.g. 20000")
        cash_layout.addWidget(self.cash_reserve_edit)

        cash_layout.addWidget(QLabel(f"Future tax {BASE_CURRENCY_SUFFIX}:"))
        self.future_tax_edit = FormattedDecimalLineEdit(cash_box)
        self.future_tax_edit.setPlaceholderText("e.g. 0")
        self.future_tax_edit.setText("0")
        cash_layout.addWidget(self.future_tax_edit)

        self.investable_balance_label = QLabel(f"Investable balance {BASE_CURRENCY_SUFFIX}: 0")
        cash_layout.addWidget(self.investable_balance_label)

        cash_layout.addStretch(1)
        return cash_box

    def _build_tree(self) -> InvestmentTreeWidget:
        tree = InvestmentTreeWidget(self)
        tree.setColumnCount(len(Col))
        tree.setHeaderLabels(
            [
                "Name",
                "Ticker",
                "Quantity",
                "Total value",
                "Portfolio %",
                "Target %",
                "Strategy %",
                "Drift (pp)",
                "Exchange",
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
            elif col == Col.TICKER:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.Fixed)
            elif col == Col.QUANTITY:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.Fixed)
            elif col == Col.EXCHANGE:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.Fixed)
            elif col == Col.DRIFT_PP:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.Fixed)
            else:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeMode.ResizeToContents)

        tree.setColumnWidth(Col.TICKER.value, 110)
        tree.setColumnWidth(Col.QUANTITY.value, 84)
        tree.setColumnWidth(Col.EXCHANGE.value, 84)
        tree.setColumnWidth(Col.DRIFT_PP.value, 78)
        tree.headerItem().setTextAlignment(Col.TICKER.value, Qt.AlignmentFlag.AlignLeft)
        tree.headerItem().setTextAlignment(Col.DRIFT_PP.value, Qt.AlignmentFlag.AlignCenter)
        tree.headerItem().setTextAlignment(Col.QUANTITY.value, Qt.AlignmentFlag.AlignCenter)
        tree.headerItem().setTextAlignment(Col.EXCHANGE.value, Qt.AlignmentFlag.AlignCenter)
        tree.setItemDelegateForColumn(
            Col.TARGET_PCT.value,
            PercentInputDelegate(allow_empty=False, parent=tree),
        )
        tree.setItemDelegateForColumn(
            Col.QUANTITY.value,
            NonNegativeIntegerInputDelegate(allow_empty=True, parent=tree),
        )
        self._set_tree_header_tooltips(tree)
        return tree

    def _set_tree_header_tooltips(self, tree: InvestmentTreeWidget) -> None:
        header_item = tree.headerItem()
        header_item.setToolTip(
            Col.TICKER.value,
            "Instrument ticker symbol (required).\n"
            "TASE: 6 or 7 digits.\n"
            "NYSE: exactly 4 uppercase letters or digits.",
        )
        header_item.setToolTip(
            Col.NAME.value,
            "A user-defined display name for your convenience.",
        )
        header_item.setToolTip(
            Col.QUANTITY.value,
            "Required holdings field for instrument units.\n"
            "Allowed values: non-negative integers.\n"
            "Empty input is normalized to 0.",
        )
        header_item.setToolTip(
            Col.TOT_VALUE.value,
            f"Current value for this row in {DEFAULT_CURRENCY.value}.\n"
            "For an instrument: computed from the current price and quantity.\n"
            "For an asset group: sum of its instruments.\n"
            "This column is read-only.",
        )
        header_item.setToolTip(
            Col.EXCHANGE.value,
            "Instrument trading exchange used by the wizard "
            f"(allowed: {', '.join(exchange_choices())}; default: TASE).\n"
            f"TASE uses ILS prices; NYSE uses USD prices. Portfolio value and totals remain in {DEFAULT_CURRENCY.value}.",
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
        controls_layout.setContentsMargins(0, 0, 0, 0)

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
        totals_layout.setContentsMargins(0, 0, 0, 0)
        self.total_label = QLabel(f"Total portfolio {BASE_CURRENCY_SUFFIX}: -")
        totals_layout.addWidget(self.total_label)
        totals_layout.addStretch(1)
        return totals

    def _build_actions_row(self) -> QWidget:
        actions = QWidget(self)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self.quit_btn = QPushButton("Quit")
        actions_layout.addWidget(self.quit_btn)

        actions_layout.addStretch(1)

        self.refresh_market_data_btn = QPushButton("Refresh Market Data")
        self.refresh_market_data_btn.setToolTip(
            "Fetch the latest portfolio prices without saving."
        )
        self.refresh_market_data_btn.setStyleSheet("padding: 6px 10px;")
        actions_layout.addWidget(self.refresh_market_data_btn)

        self.rebalance_btn = QPushButton("Invest & Rebalance")
        self.rebalance_btn.setStyleSheet("padding: 6px 10px;")
        actions_layout.addWidget(self.rebalance_btn)

        self.invest_btn = QPushButton("Invest")
        self.invest_btn.setStyleSheet(
            "QPushButton { background: #2f6fed; color: white; border: 1px solid #275dca; "
            "border-radius: 6px; padding: 6px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #285fcc; }"
            "QPushButton:pressed { background: #214ea8; }"
            "QPushButton:disabled { background: #9eb7ea; border-color: #9eb7ea; color: #eef3ff; }"
        )
        actions_layout.addWidget(self.invest_btn)
        return actions
