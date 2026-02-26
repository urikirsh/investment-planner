from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget, QHeaderView,
)

from investment_planner.io_json import load_portfolio_file, load_portfolio, save_portfolio_file
from investment_planner.validation import validate_portfolio
from investment_planner.planning import (
    compute_invest_budget,
    plan_invest_no_sell,
    plan_rebalance,
    map_asset_group_deltas_to_instruments,
)
from investment_planner.calc_stock_units import calculate_buy_units, commit_buy, commit_sell

from ui.ui_types import RowKind, Col, WizardStep, ROLE_PREV_TEXT
from ui.ui_utils import d_from_text, set_item_meta, get_item_kind, get_item_id, new_id, \
    set_group_tree_item, add_instrument_item_to_group, parse_value_cell
from ui.ui_utils import safe_pct, fmt_pct, fmt_pp, apply_drift_color, NON_INVESTABLE_BUCKET_ID, _is_cell_editable

from ui.tree_widget import InvestmentTreeWidget

from ui.decimal_input_delegate import DecimalInputDelegate

"""
main_window.py

Primary GUI implementation for the investment planner application.

This module defines the main application window and coordinates all
user interaction, including portfolio editing, validation feedback,
navigation through the investment workflow, and triggering planning
and execution logic.

The main window acts as an orchestrator between the UI components and
the underlying domain logic, while keeping calculation, validation,
and persistence responsibilities in their respective modules.
"""

D = Decimal

NON_INVESTABLE_BUCKET_TITLE = "Non-investable holdings (excluded from strategy)"

class MainWindow(QMainWindow):
    """
    3-screen flow:
      1) main editor
      2) summary
      3) per-instrument wizard
    """

    def __init__(self, json_path: str = "portfolio.json"):
        super().__init__()
        self.setWindowTitle("Investment Planner")

        self.json_path = Path(json_path)
        self.current_portfolio = None  # type: ignore[assignment]
        self.current_plan_steps: List[WizardStep] = []
        self.current_step_index: int = 0
        self.current_mode: str = "invest"  # "invest" or "rebalance"

        # Screens
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.screen_main = self._build_main_screen()
        self.screen_summary = self._build_summary_screen()
        self.screen_wizard = self._build_wizard_screen()

        self.stack.addWidget(self.screen_main)
        self.stack.addWidget(self.screen_summary)
        self.stack.addWidget(self.screen_wizard)
        self.stack.setCurrentWidget(self.screen_main)

        self._load_or_init()

        self._suppress_item_changed = False
        self.tree.itemChanged.connect(self._on_item_changed_guard_and_recalc)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        self._refresh_data()

    # -------------------------
    # Screen 1 (Main)
    # -------------------------

    def _on_item_changed_guard_and_recalc(self, item, column: int):
        if self._suppress_item_changed:
            return

        # Only business-rule validate relevant cells
        if get_item_kind(item) == RowKind.GROUP.name and column == Col.TARGET_PCT.value:
            if not self._validate_target_pct_cell_or_revert(item):
                self._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT.name and column == Col.TARGET_PCT.value:
            if not self._validate_instrument_target_pct_cell_or_revert(item):
                self._refresh_data()
                return

        self._refresh_data()

    def _generate_cash_box(self) -> QWidget:
        # Cash block (fixed)
        cash_box = QWidget()
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

        cash_layout.addStretch(1)
        return cash_box

    def _init_group_and_instruments_tree(self) -> None:
        # Tree: Groups as top-level, instruments as children
        self.tree = InvestmentTreeWidget()
        self.tree.setColumnCount(len(Col))
        self.tree.setHeaderLabels(
            [
                "Name",
                "Total value",
                "Portfolio %",
                "Target %",
                "Strategy %",
                "Drift (pp)",
            ]
        )
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.tree.setIndentation(22)

        # Set column widths and drag behaviors
        header = self.tree.header()
        header.setStretchLastSection(False)

        for col in Col:
            if col == Col.NAME:
                header.setSectionResizeMode(col.value, QHeaderView.Stretch)
            elif col == Col.DRIFT_PP:
                header.setSectionResizeMode(col.value, QHeaderView.Fixed)
            else:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeToContents)

        self.tree.setColumnWidth(Col.DRIFT_PP.value, 78)
        self.tree.headerItem().setTextAlignment(Col.DRIFT_PP.value, Qt.AlignCenter)

        self.tree.items_reordered.connect(self._after_tree_reorder)

        self.tree.setItemDelegateForColumn(Col.TOT_VALUE.value,
                                           DecimalInputDelegate(allow_empty=False, parent=self.tree))
        self.tree.setItemDelegateForColumn(Col.TARGET_PCT.value,
                                           DecimalInputDelegate(allow_empty=False, parent=self.tree))
        self._set_tree_header_tooltips()

    def _set_tree_header_tooltips(self) -> None:
        header_item = self.tree.headerItem()
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

    def _generate_controls_widget(self) -> QWidget:
        # Controls row: add/remove
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)

        add_group = QPushButton("Add Asset Group")
        add_group.clicked.connect(self._add_asset_group)
        controls_layout.addWidget(add_group)

        add_instrument = QPushButton("Add Instrument")
        add_instrument.clicked.connect(self._add_instrument)
        controls_layout.addWidget(add_instrument)

        delete_row = QPushButton("Delete Selected")
        delete_row.clicked.connect(self._delete_selected_row)
        controls_layout.addWidget(delete_row)

        controls_layout.addStretch(1)
        return controls

    def _generate_total_portfolio_value_widget(self) -> QWidget:
        totals = QWidget()
        totals_layout = QHBoxLayout(totals)
        self.total_label = QLabel("Total portfolio value: -")
        totals_layout.addWidget(self.total_label)
        totals_layout.addStretch(1)
        return totals

    def _generate_bottom_buttons_widget(self) -> QWidget:
        btns = QWidget()
        btns_layout = QHBoxLayout(btns)

        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(self._on_main_quit_clicked)
        btns_layout.addWidget(quit_btn)

        invest_btn = QPushButton("Invest")
        invest_btn.clicked.connect(self._on_invest_clicked)
        btns_layout.addWidget(invest_btn)

        rebalance_btn = QPushButton("Invest & Rebalance")
        rebalance_btn.clicked.connect(self._on_rebalance_clicked)
        btns_layout.addWidget(rebalance_btn)

        update_btn = QPushButton("Update")
        update_btn.clicked.connect(self._on_update_clicked)
        btns_layout.addWidget(update_btn)

        btns_layout.addStretch(1)
        return btns

    def _build_main_screen(self) -> QWidget:
        main_screen_widget = QWidget()
        layout = QVBoxLayout(main_screen_widget)

        title = QLabel("Insert data here")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(self._generate_cash_box())

        self._init_group_and_instruments_tree()
        layout.addWidget(self.tree, 1)

        layout.addWidget(self._generate_controls_widget())
        layout.addWidget(self._generate_total_portfolio_value_widget())
        layout.addWidget(self._generate_bottom_buttons_widget())

        # Live total refresh
        self.tree.itemChanged.connect(self._refresh_total_portfolio)
        self.cash_value_edit.textChanged.connect(self._refresh_total_portfolio)
        self.cash_reserve_edit.textChanged.connect(self._refresh_total_portfolio)
        self.future_tax_edit.textChanged.connect(self._refresh_total_portfolio)
        self.cash_value_edit.textChanged.connect(self._recalc_totals_and_pcts)
        self.future_tax_edit.textChanged.connect(self._recalc_totals_and_pcts)
        self.future_tax_edit.textChanged.connect(self._update_future_tax_visual_state)
        self.future_tax_edit.editingFinished.connect(self._normalize_future_tax_input)

        return main_screen_widget

    def _add_asset_group(self):
        # gid = _new_id("grp")
        gitem = QTreeWidgetItem(self.tree)

        set_group_tree_item(gitem, "New Asset Group", 0)

        self.tree.expandAll()
        self._refresh_data()

    def _add_instrument(self):
        sel = self.tree.currentItem()
        if sel is None:
            QMessageBox.warning(self, "Add instrument", "Select a group (or an instrument under a group) first.")
            return

        # If instrument selected, use its parent group
        parent = sel.parent() or sel

        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET.name:
            default_in_group_pct = ""
        else:
            default_in_group_pct = "100" if parent.childCount() == 0 else "0"

        add_instrument_item_to_group(parent, "New Instrument", "1", default_in_group_pct)

        self.tree.expandAll()
        self._refresh_data()

    def _delete_selected_row(self):
        sel = self.tree.currentItem()
        if sel is None:
            return

        if get_item_kind(sel) == RowKind.NON_INVESTABLE_BUCKET.name:
            QMessageBox.warning(self, "Not allowed", "The non-investable bucket cannot be deleted.")
            return

        parent = sel.parent()
        if parent is None:
            idx = self.tree.indexOfTopLevelItem(sel)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(sel)
        self._refresh_data()

    def _load_or_init(self):
        if self.json_path.exists():
            try:
                p = load_portfolio_file(self.json_path)
            except Exception as e:
                QMessageBox.critical(self, "Load failed", f"Failed loading JSON:\n{e}")
                p = None
        else:
            # Minimal default portfolio
            data = {
                "cash": {"value": "12000", "min_reserve": "2000", "future_tax": "0"},
                "groups": [
                    {"id": "sp500", "name": "S&P 500", "targetPercentage": "100"}
                ],
                "instruments": [
                    {
                        "id": "spx_a",
                        "name": "SPX 500",
                        "value": "1",
                        "investable": True,
                        "groupId": "sp500",
                        "targetInGroupPercentage": "100",
                    }
                ],
            }
            p = load_portfolio(data)

        self.current_portfolio = p
        self._populate_main_from_portfolio(p)
        self._refresh_data()

    def _populate_main_from_portfolio(self, p):
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self.cash_value_edit.setText(str(p.cash.value))
            self.cash_reserve_edit.setText(str(p.cash.min_reserve))
            self.future_tax_edit.setText(str(p.cash.future_tax))
            self._update_future_tax_visual_state()

            # group -> list instruments (keep input order as stored)
            ins_by_group: Dict[str, List[Dict[str, Any]]] = {}
            non_investable: List[Dict[str, Any]] = []

            for ins in p.instruments:
                row = {
                    "id": ins.id,
                    "name": ins.name,
                    "value": str(ins.value),
                    "investable": ins.investable,
                    "groupId": ins.asset_group_id,
                    "targetInGroupPercentage": str(ins.target_in_group_pct),
                }
                if ins.investable and ins.asset_group_id:
                    ins_by_group.setdefault(ins.asset_group_id, []).append(row)
                else:
                    non_investable.append(row)

            for g in p.asset_groups:
                gitem = QTreeWidgetItem(self.tree)
                set_group_tree_item(gitem, g.name, g.target_pct, g.id)

                for ins in ins_by_group.get(g.id, []):
                    add_instrument_item_to_group(
                        gitem,
                        ins["name"],
                        ins["value"],
                        ins["targetInGroupPercentage"],
                        ins["id"],
                    )

            # Non-investable section is always present and always added, even if it is empty.
            # It does not exist in the JSON, it is purely in the UI
            non_investable_bucket = QTreeWidgetItem(self.tree)
            set_group_tree_item(
                non_investable_bucket,
                NON_INVESTABLE_BUCKET_TITLE,
                0,
                NON_INVESTABLE_BUCKET_ID,
            )

            for ins in non_investable:
                add_instrument_item_to_group(
                    non_investable_bucket,
                    ins["name"],
                    ins["value"],
                    "",
                    ins["id"],
                )

            self.tree.expandAll()
        finally:
            self.tree.blockSignals(False)

    def _refresh_data(self):
        self._refresh_total_portfolio()
        self._recalc_totals_and_pcts()

    def _refresh_total_portfolio(self):
        try:
            data = self._build_data_from_main_ui(allow_partial=True)
            # Total portfolio = cash + all instruments values
            cash_amt = D(str(data["cash"]["value"]))
            future_tax = D(str(data["cash"]["future_tax"]))
            total = cash_amt
            for ins in data.get("instruments", []):
                total += D(str(ins["value"]))
            total -= future_tax
            self.total_label.setText(f"Total portfolio: {total}")
        except Exception:
            self.total_label.setText("Total portfolio: -")


    def _build_data_from_main_ui(self, allow_partial: bool = False)\
            -> Dict[str, Any]:
        cash_value = self.cash_value_edit.text().strip()
        cash_reserve = self.cash_reserve_edit.text().strip()
        future_tax = self.future_tax_edit.text().strip()

        if not allow_partial:
            if not cash_value or not cash_reserve:
                raise ValueError("Cash value and reserve must be filled")

        # In allow_partial, default to "0" if empty for total display
        cash_value = cash_value or "0"
        cash_reserve = cash_reserve or "0"
        future_tax = future_tax or "0"

        groups: List[Dict[str, Any]] = []
        instruments: List[Dict[str, Any]] = []

        top_count = self.tree.topLevelItemCount()
        for i in range(top_count):
            gitem = self.tree.topLevelItem(i)

            kind = get_item_kind(gitem)
            if kind == RowKind.INSTRUMENT.name:
                continue

            gid = get_item_id(gitem) or new_id("grp")

            gname = gitem.text(Col.NAME.value).strip()
            target_pct = gitem.text(Col.TARGET_PCT.value).strip() or "0"

            # This top-level bucket exists only in UI and is not serialized as a strategy group.
            is_non_investable_bucket = kind == RowKind.NON_INVESTABLE_BUCKET.name

            if not is_non_investable_bucket:
                groups.append(
                    {
                        "id": gid,
                        "name": gname,
                        "targetPercentage": target_pct,
                    }
                )

            # children instruments
            for j in range(gitem.childCount()):
                ins = gitem.child(j)

                if ins.parent() is None:  # not an instrument
                    continue

                iid = get_item_id(ins)
                if not iid:
                    iid = new_id("ins")
                    set_item_meta(ins, RowKind.INSTRUMENT.name, iid)

                iname = ins.text(Col.NAME.value).strip()
                tot_value = ins.text(Col.TOT_VALUE.value).strip() or "0"

                if is_non_investable_bucket:
                    investable = False
                    group_id = None
                    target_in_group_pct = "0"
                else:
                    investable = True
                    group_id = gid
                    target_in_group_pct = ins.text(Col.TARGET_PCT.value).strip() or "0"

                instruments.append(
                    {
                        "id": iid,
                        "name": iname,
                        "value": tot_value,
                        "investable": investable,
                        "targetInGroupPercentage": target_in_group_pct,
                        **({"groupId": group_id} if group_id is not None else {}),
                    }
                )

        return {
            "cash": {"value": cash_value, "min_reserve": cash_reserve, "future_tax": future_tax},
            "groups": groups,
            "instruments": instruments,
        }

    def _save_from_main_ui(self) -> None:
        data = self._build_data_from_main_ui(allow_partial=False)
        p = load_portfolio(data)  # parses Decimals
        validate_portfolio(p)
        save_portfolio_file(p, self.json_path)
        self.current_portfolio = p

    def _on_update_clicked(self):
        try:
            self._save_from_main_ui()
            QMessageBox.information(self, "Saved", "Portfolio saved.")
        except Exception as e:
            QMessageBox.critical(self, "Validation / Save failed", str(e))

    def _on_invest_clicked(self):
        self._run_planning(mode="invest")

    def _on_rebalance_clicked(self):
        self._run_planning(mode="rebalance")

    def _on_main_quit_clicked(self):
        if not self._has_unsaved_main_changes():
            QApplication.instance().quit()
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText("Your current changes are not saved.")
        box.setInformativeText("Do you want to save before quitting?")
        save_btn = box.addButton("Save", QMessageBox.AcceptRole)
        dont_save_btn = box.addButton("Don't Save", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked == save_btn:
            try:
                self._save_from_main_ui()
                QApplication.instance().quit()
            except Exception as e:
                QMessageBox.critical(self, "Validation / Save failed", str(e))
            return
        if clicked == dont_save_btn:
            QApplication.instance().quit()
            return
        if clicked == cancel_btn:
            return

    def _has_unsaved_main_changes(self) -> bool:
        # If current UI state cannot be parsed, treat it as unsaved changes.
        try:
            current_data = self._build_data_from_main_ui(allow_partial=True)
            current_portfolio = load_portfolio(current_data)
        except Exception:
            return True

        if not self.json_path.exists():
            return True

        try:
            saved_portfolio = load_portfolio_file(self.json_path)
        except Exception:
            return True

        return current_portfolio != saved_portfolio

    def _run_planning(self, mode: str):
        try:
            self._save_from_main_ui()
            p = self.current_portfolio
            assert p is not None

            budget = compute_invest_budget(p)
            if budget <= 0:
                QMessageBox.information(self, "No budget", "No investable cash")
                return

            if mode == "invest":
                rows = plan_invest_no_sell(p)
            else:
                rows = plan_rebalance(p)

            # Build wizard steps in group order, split by instrument target % within each group.
            ins_by_id = {ins.id: ins for ins in p.instruments}
            instrument_steps = map_asset_group_deltas_to_instruments(p, rows)

            steps: List[WizardStep] = []
            for group_id, group_name, instrument_id, planned_delta in instrument_steps:
                if planned_delta == 0:
                    continue
                ins = ins_by_id.get(instrument_id)
                if ins is None:
                    raise ValueError(f"Instrument not found: {instrument_id}")

                steps.append(
                    WizardStep(
                        asset_group_id=group_id,
                        asset_group_name=group_name,
                        instrument_id=ins.id,
                        instrument_name=ins.name,
                        planned_delta_money=planned_delta,
                    )
                )

            self.current_plan_steps = steps
            self.current_step_index = 0
            self.current_mode = mode

            self._populate_summary(p, steps, mode)
            self.stack.setCurrentWidget(self.screen_summary)
        except Exception as e:
            QMessageBox.critical(self, "Plan failed", str(e))

    # -------------------------
    # Screen 2 (Summary)
    # -------------------------

    def _build_summary_screen(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        title = QLabel("Summary")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        layout.addWidget(self.summary_text, 1)

        btns = QWidget()
        btns_layout = QHBoxLayout(btns)

        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(QApplication.instance().quit)
        btns_layout.addWidget(quit_btn)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(self._summary_back)
        btns_layout.addWidget(back_btn)

        next_btn = QPushButton("Next")
        next_btn.clicked.connect(self._summary_next)
        btns_layout.addWidget(next_btn)

        btns_layout.addStretch(1)
        layout.addWidget(btns)

        return w

    def _populate_summary(self, p, steps: List[WizardStep], mode: str):
        budget = compute_invest_budget(p)
        lines = [
            f"Mode: {mode}",
            f"Future tax (non-investable): {p.cash.future_tax}",
            f"Invest budget (cash - minimal reserve - future tax): {budget}",
            "",
        ]
        if not steps:
            lines.append("No actions required.")
        else:
            lines.append("Planned actions (split per instrument by in-group target percentages):")
            for s in steps:
                action = "BUY" if s.planned_delta_money > 0 else "SELL"
                lines.append(
                    f"- {action} {abs(s.planned_delta_money)} in [{s.asset_group_name}] via [{s.instrument_name}]"
                )

        if mode == "rebalance":
            lines.append("")
            lines.append("Note: SELL steps follow per-instrument in-group targets.")

        self.summary_text.setText("\n".join(lines))

    def _summary_next(self):
        if not self.current_plan_steps:
            # Nothing to do -> go back to main
            self.stack.setCurrentWidget(self.screen_main)
            return
        self._show_current_wizard_step()
        self.stack.setCurrentWidget(self.screen_wizard)

    def _summary_back(self):
        self.stack.setCurrentWidget(self.screen_main)

    # -------------------------
    # Screen 3 (Wizard)
    # -------------------------

    def _build_wizard_screen(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        title = QLabel("Invest per asset group")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.wiz_info = QLabel("-")
        self.wiz_info.setWordWrap(True)
        layout.addWidget(self.wiz_info)

        form = QWidget()
        form_layout = QFormLayout(form)
        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")
        form_layout.addRow("Price (Agorot):", self.price_edit)
        layout.addWidget(form)

        calc_row = QWidget()
        calc_layout = QHBoxLayout(calc_row)
        calc_btn = QPushButton("Calculate")
        calc_btn.clicked.connect(self._wizard_calculate)
        calc_layout.addWidget(calc_btn)

        self.wiz_result = QLabel("Units: - | Spent: - | Leftover vs plan: -")
        self.wiz_result.setWordWrap(True)
        calc_layout.addWidget(self.wiz_result, 1)
        layout.addWidget(calc_row)

        btns = QWidget()
        btns_layout = QHBoxLayout(btns)

        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(QApplication.instance().quit)
        btns_layout.addWidget(quit_btn)

        save_btn = QPushButton("Save and continue")
        save_btn.clicked.connect(self._wizard_save_continue)
        btns_layout.addWidget(save_btn)

        skip_save_btn = QPushButton("Continue without saving")
        skip_save_btn.clicked.connect(self._wizard_continue_without_saving)
        btns_layout.addWidget(skip_save_btn)

        btns_layout.addStretch(1)
        layout.addWidget(btns)

        return w

    def _show_current_wizard_step(self):
        s = self.current_plan_steps[self.current_step_index]
        idx = self.current_step_index + 1
        total = len(self.current_plan_steps)

        action = "BUY" if s.planned_delta_money > 0 else "SELL"
        self.wiz_info.setText(
            f"Step {idx}/{total}\n"
            f"Asset group: {s.asset_group_name}\n"
            f"Instrument: {s.instrument_name}\n"
            f"Planned {action} value: {abs(s.planned_delta_money)}"
        )
        self.price_edit.setText("")
        self.wiz_result.setText("Units: - | Spent/Proceeds: - | Leftover vs plan: -")

        # store last calculation
        self._last_calc = None

    def _wizard_calculate(self):
        try:
            s = self.current_plan_steps[self.current_step_index]
            price = d_from_text(self.price_edit.text(), "price")

            planned = abs(s.planned_delta_money)
            calc = calculate_buy_units(
                instrument_id=s.instrument_id,
                planned_money=planned,
                price_ag=price,
            )
            self._last_calc = calc

            label_money = "Spent" if s.planned_delta_money > 0 else "Proceeds"
            self.wiz_result.setText(
                f"Units: {calc.units} | {label_money}: {calc.spent} | Leftover vs plan: {calc.leftover}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Calculation failed", str(e))

    def _wizard_save_continue(self):
        try:
            if self.current_portfolio is None:
                raise ValueError("No portfolio loaded")

            s = self.current_plan_steps[self.current_step_index]

            # If user didn't calculate, treat as 0 units (skip saving)
            if getattr(self, "_last_calc", None) is None:
                calc_units = 0
                spent = D("0")
            else:
                calc_units = self._last_calc.units
                spent = self._last_calc.spent

            # If no valid trade was calculated, continue without saving changes.
            if calc_units > 0 and spent >= D("1"):
                if s.planned_delta_money > 0:
                    self.current_portfolio = commit_buy(
                        p=self.current_portfolio,
                        instrument_id=s.instrument_id,
                        spent=spent,
                        min_trade_ils=D("100"),
                    )
                else:
                    # SELL from the current wizard instrument
                    self.current_portfolio = commit_sell(
                        p=self.current_portfolio,
                        instrument_id=s.instrument_id,
                        proceeds=spent,
                        min_trade_ils=D("1"),
                    )

                # Persist after each step to support partial execution.
                save_portfolio_file(self.current_portfolio, self.json_path)

            self._advance_wizard_step()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _wizard_continue_without_saving(self):
        try:
            if self.current_portfolio is None:
                raise ValueError("No portfolio loaded")
            self._advance_wizard_step()
        except Exception as e:
            QMessageBox.critical(self, "Continue failed", str(e))

    def _advance_wizard_step(self):
        # Next step or back to main
        self.current_step_index += 1
        if self.current_step_index >= len(self.current_plan_steps):
            # Return to main with the current in-memory portfolio state.
            self._populate_main_from_portfolio(self.current_portfolio)
            self.stack.setCurrentWidget(self.screen_main)
        else:
            self._show_current_wizard_step()

    def _recalc_totals_and_pcts(self) -> None:
        """
        Recompute all derived table values from editable inputs.

        This is the single refresh entrypoint for:
        - aggregated totals (group totals, strategy total, portfolio total)
        - portfolio-level percentages for all rows
        - strategy/diff columns per row scope:
          - group rows: relative to investable strategy universe
          - instrument rows: relative to their parent asset group

        The method intentionally orchestrates small helpers so each step has
        one responsibility and can be reasoned about independently.
        """
        self._suppress_item_changed = True
        try:
            group_items, row_values, portfolio_instruments_total, strategy_total = self._collect_row_values_and_totals()
            cash_value = parse_value_cell(self.cash_value_edit.text())
            future_tax = parse_value_cell(self.future_tax_edit.text())
            portfolio_total = cash_value + portfolio_instruments_total - future_tax

            self._apply_portfolio_pct(row_values, portfolio_total)
            self._apply_group_strategy_and_drift(group_items, row_values, strategy_total)
            self._apply_instrument_strategy_and_drift(row_values)
            self._clear_non_investable_bucket_group_columns()

        finally:
            self._suppress_item_changed = False

    def _normalize_future_tax_input(self) -> None:
        if not self.future_tax_edit.text().strip():
            self.future_tax_edit.setText("0")

    def _update_future_tax_visual_state(self) -> None:
        future_tax = parse_value_cell(self.future_tax_edit.text())
        if future_tax > 0:
            self.future_tax_edit.setStyleSheet("color: #b00020;")
        else:
            self.future_tax_edit.setStyleSheet("")

    def _collect_row_values_and_totals(self) -> tuple[list[QTreeWidgetItem], dict[QTreeWidgetItem, D], D, D]:
        """
        Collect per-row numeric values and aggregate totals used by recalculation steps.

        Parameters
        ----------
        None
            Uses the current state of `self.tree`.

        Returns
        -------
        tuple[list[QTreeWidgetItem], dict[QTreeWidgetItem, Decimal], Decimal, Decimal]
            (group_items, row_values, portfolio_instruments_total, strategy_total)
            - group_items:
              Top-level rows that are real asset groups (excludes the non-investable bucket).
            - row_values:
              Mapping from each processed row item (group and instrument rows) to its numeric value.
            - portfolio_instruments_total:
              Sum of all instrument values (investable + non-investable).
            - strategy_total:
              Sum of investable group totals only.
        """
        group_items: list[QTreeWidgetItem] = []
        row_values: dict[QTreeWidgetItem, D] = {}
        portfolio_instruments_total = D("0")
        strategy_total = D("0")

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            kind = get_item_kind(top)
            if kind not in (RowKind.GROUP.name, RowKind.NON_INVESTABLE_BUCKET.name):
                continue

            total = D("0")
            for j in range(top.childCount()):
                child = top.child(j)
                if get_item_kind(child) != RowKind.INSTRUMENT.name:
                    continue
                v = parse_value_cell(child.text(Col.TOT_VALUE.value))
                total += v
                row_values[child] = v
                portfolio_instruments_total += v

            top.setText(Col.TOT_VALUE.value, str(total))
            row_values[top] = total
            if kind == RowKind.GROUP.name:
                group_items.append(top)
                strategy_total += total

        return group_items, row_values, portfolio_instruments_total, strategy_total

    def _apply_portfolio_pct(self, row_values: dict[QTreeWidgetItem, D], portfolio_total: D) -> None:
        for item, v in row_values.items():
            pct = safe_pct(v, portfolio_total)
            item.setText(Col.PORTFOLIO_PCT.value, "" if pct is None else fmt_pct(pct))

    def _apply_group_strategy_and_drift(
        self,
        group_items: list[QTreeWidgetItem],
        row_values: dict[QTreeWidgetItem, D],
        strategy_total: D,
    ) -> None:
        """
        Fill Strategy % and Drift for top-level asset-group rows.

        Strategy % for a group = group_value / total_investable_strategy_value.
        Drift(pp) = actual_strategy_pct - target_pct.
        """
        for g in group_items:
            gval = row_values.get(g, D("0"))
            sp = safe_pct(gval, strategy_total)
            if sp is None:
                g.setText(Col.STRATEGY_PCT.value, "")
                g.setText(Col.DRIFT_PP.value, "")
                continue

            g.setText(Col.STRATEGY_PCT.value, fmt_pct(sp))
            target = parse_value_cell(g.text(Col.TARGET_PCT.value))
            drift = sp - target
            g.setText(Col.DRIFT_PP.value, fmt_pp(drift))
            apply_drift_color(g, Col.DRIFT_PP.value, drift)

    def _apply_instrument_strategy_and_drift(self, row_values: dict[QTreeWidgetItem, D]) -> None:
        """
        Fill Strategy % and Drift for instrument rows using within-group scope.

        For instruments under asset groups:
        - Strategy % = instrument_value / parent_group_total
        - Drift(pp) = actual_within_group_pct - instrument_target_pct

        For instruments under the non-investable bucket:
        - Target/Strategy/Drift are cleared because these rows are out of strategy scope.
        """
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top_kind = get_item_kind(top)
            group_total = row_values.get(top, D("0"))

            for j in range(top.childCount()):
                child = top.child(j)
                if get_item_kind(child) != RowKind.INSTRUMENT.name:
                    continue

                if top_kind != RowKind.GROUP.name:
                    child.setText(Col.TARGET_PCT.value, "")
                    child.setText(Col.STRATEGY_PCT.value, "")
                    child.setText(Col.DRIFT_PP.value, "")
                    apply_drift_color(child, Col.DRIFT_PP.value, D("0"))
                    continue

                child_sp = safe_pct(row_values.get(child, D("0")), group_total)
                if child_sp is None:
                    child.setText(Col.STRATEGY_PCT.value, "")
                    child.setText(Col.DRIFT_PP.value, "")
                    apply_drift_color(child, Col.DRIFT_PP.value, D("0"))
                    continue

                child.setText(Col.STRATEGY_PCT.value, fmt_pct(child_sp))
                child_target = parse_value_cell(child.text(Col.TARGET_PCT.value))
                child_drift = child_sp - child_target
                child.setText(Col.DRIFT_PP.value, fmt_pp(child_drift))
                apply_drift_color(child, Col.DRIFT_PP.value, child_drift)

    def _clear_non_investable_bucket_group_columns(self) -> None:
        """
        Clear group-only columns for the non-investable bucket top-level row.

        We intentionally scan all top-level rows (without early break) so the UI
        self-heals even if multiple non-investable buckets are present due to
        malformed input or manual tree edits.
        """
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if get_item_kind(top) == RowKind.NON_INVESTABLE_BUCKET.name:
                top.setText(Col.TARGET_PCT.value, "")
                top.setText(Col.STRATEGY_PCT.value, "")
                top.setText(Col.DRIFT_PP.value, "")

    def _after_tree_reorder(self, *args):
        self._refresh_data()

    def _on_item_double_clicked(self, item, column):
        kind = get_item_kind(item)

        if kind == RowKind.INSTRUMENT.name and column == Col.TARGET_PCT.value:
            parent = item.parent()
            if parent is not None and get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET.name:
                return

        if _is_cell_editable(kind, column):
            # Save previous value for this specific column
            item.setData(column, ROLE_PREV_TEXT, item.text(column))

            # Temporarily enable editing
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.tree.editItem(item, column)
            # Disable immediately after edit starts
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _validate_target_pct_cell_or_revert(self, item) -> bool:
        """
        Validates the group's Target % cell. Returns True if OK, False if reverted.
        """
        col = Col.TARGET_PCT.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        try:
            p = Decimal(raw)
        except Exception:
            self._warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False

        if p > 100:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False

        return True

    def _validate_instrument_target_pct_cell_or_revert(self, item) -> bool:
        """
        Validates an instrument row's Target % (in-group target) cell.
        Returns True if accepted, False if reverted/ignored.
        """
        parent = item.parent()
        if parent is None:
            # Defensive: instrument rows should always have a parent.
            return False
        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET.name:
            # In-group % is not applicable for non-investable holdings.
            return False

        col = Col.TARGET_PCT.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        try:
            p = Decimal(raw)
        except Exception:
            self._warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False

        if p < 0:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot be negative.")
            return False

        if p > 100:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False

        return True

    def _warn_and_revert(self, item, col: int, bad: str, prev: str, msg: str) -> None:
        self._suppress_item_changed = True
        try:
            QMessageBox.warning(
                self,
                "Invalid input",
                f"{msg}\n\nYou entered: {bad}\nReverting to previous value: {prev}"
            )
            item.setText(col, prev if prev is not None else "")
        finally:
            self._suppress_item_changed = False
