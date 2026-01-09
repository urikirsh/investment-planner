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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget, QHeaderView, QComboBox,
)

from investment_planner.io_json import load_portfolio_file, load_portfolio, save_portfolio_file
from investment_planner.validation import validate_portfolio
from investment_planner.planning import compute_invest_budget, plan_invest_no_sell, plan_rebalance
from investment_planner.calc_stock_units import calculate_buy_units, commit_buy, commit_sell

from ui.ui_types import RowKind, Col, WizardStep
from ui.ui_utils import d_from_text, set_item_meta, get_item_kind, get_item_id, new_id, \
    set_group_tree_item, add_instrument_item_to_group, parse_amount_cell
from ui.ui_utils import safe_pct, fmt_pct, fmt_pp

D = Decimal

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

        self._refresh_data()

    # -------------------------
    # Screen 1 (Main)
    # -------------------------

    def _get_preferred_combo(self, group_item) -> QComboBox | None:
        w = self.tree.itemWidget(group_item, Col.PREFERRED_INSTR.value)
        return w if isinstance(w, QComboBox) else None

    def _refresh_preferred_dropdowns(self) -> None:
        """
        Ensure each group row has a Preferred Instrument dropdown whose options match
        the group's current instrument children (by ID), and whose labels match current names.
        """
        self._suppress_item_changed = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                group_item = self.tree.topLevelItem(i)
                kind = get_item_kind(group_item)
                if kind not in (RowKind.GROUP.name, RowKind.NON_INVESTABLE_BUCKET.name):
                    continue

                # Bucket: no preferred instrument
                if kind == RowKind.NON_INVESTABLE_BUCKET.value:
                    # Remove widget if exists
                    if self.tree.itemWidget(group_item, Col.PREFERRED_INSTR.value) is not None:
                        self.tree.setItemWidget(group_item, Col.PREFERRED_INSTR.value, None)
                    group_item.setText(Col.PREFERRED_INSTR.value, "")
                    continue

                # Collect instruments under this group
                instruments: list[tuple[str, str]] = []  # (id, name)
                for j in range(group_item.childCount()):
                    child = group_item.child(j)
                    if get_item_kind(child) != RowKind.INSTRUMENT.name:
                        continue
                    ins_id = get_item_id(child)
                    ins_name = child.text(Col.NAME.value).strip()
                    if ins_id and ins_name:
                        instruments.append((ins_id, ins_name))

                combo = self._get_preferred_combo(group_item)
                if combo is None:
                    combo = QComboBox()
                    combo.setEditable(False)
                    # When user changes preferred, we might want to trigger validation/refresh
                    combo.currentIndexChanged.connect(lambda _=None: self._on_preferred_changed())
                    self.tree.setItemWidget(group_item, Col.PREFERRED_INSTR.value, combo)

                # Preserve current selection (by ID)
                prev_selected_id = combo.currentData()

                # Rebuild options
                combo.blockSignals(True)
                combo.clear()
                for ins_id, ins_name in instruments:
                    combo.addItem(ins_name, ins_id)  # label, userData=id
                combo.blockSignals(False)

                # Restore selection if still valid
                if prev_selected_id is not None:
                    idx = combo.findData(prev_selected_id)
                else:
                    idx = -1

                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    # If no valid previous selection:
                    # - if only one instrument -> select it
                    # - if multiple -> select first (or leave unselected if you prefer)
                    if combo.count() > 0:
                        combo.setCurrentIndex(0)
        finally:
            self._suppress_item_changed = False

    def _on_item_changed_guard_and_recalc(self, item, column: int):
        if self._suppress_item_changed:
            return

        kind = get_item_kind(item)

        # Prevent editing computed/group-only/instrument-only fields:
        # - group/bucket: Total value is computed, Investable is unused
        # - instrument: Target/Preferred unused
        self._suppress_item_changed = True
        try:
            if kind != RowKind.INSTRUMENT.name:
                if column in (Col.TOT_VALUE.value, Col.PORTFOLIO_PCT.value, Col.STRATEGY_PCT.value, Col.DRIFT_PP.value):
                    # revert by recomputing (will overwrite whatever user typed)
                    pass
                if column == Col.INVESTABLE.value:
                    item.setText(Col.INVESTABLE.value, "")

            if kind == RowKind.INSTRUMENT.name:
                if column == Col.TARGET_PCT.value:
                    item.setText(Col.TARGET_PCT.value, "")
                if column == Col.PREFERRED_INSTR.value:
                    item.setText(Col.PREFERRED_INSTR.value, "")

        finally:
            self._suppress_item_changed = False
            self._refresh_data()

    def _generate_cash_box(self) -> QWidget:
        # Cash block (fixed)
        cash_box = QWidget()
        cash_layout = QHBoxLayout(cash_box)

        cash_layout.addWidget(QLabel("Cash value:"))
        self.cash_amount_edit = QLineEdit()  # TODO: rename
        self.cash_amount_edit.setPlaceholderText("e.g. 1000")
        cash_layout.addWidget(self.cash_amount_edit)

        cash_layout.addWidget(QLabel("Minimal cash reserve:"))
        self.cash_reserve_edit = QLineEdit()
        self.cash_reserve_edit.setPlaceholderText("e.g. 20000")
        cash_layout.addWidget(self.cash_reserve_edit)

        cash_layout.addStretch(1)
        return cash_box

    def _init_group_and_instruments_tree(self) -> None:
        # Tree: Groups as top-level, instruments as children
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(
            [
                "Name",
                "Total value",
                "Portfolio %",
                "Target %",
                "Strategy %",
                "Drift (pp)",
                "Preferred Instrument",
                "Investable",
            ]
        )
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.tree.setIndentation(22)

        # Set column widths and drag behaviors
        header = self.tree.header()

        for col in Col:
            if col == Col.NAME:
                header.setSectionResizeMode(col.value, QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(col.value, QHeaderView.ResizeToContents)

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
        delete_row.clicked.connect(self._delete_selected)
        controls_layout.addWidget(delete_row)

        controls_layout.addStretch(1)
        return controls

    def _generate_total_portfolio_value_widget(self) -> QWidget:
        totals = QWidget()
        totals_layout = QHBoxLayout(totals)
        self.total_label = QLabel("Total portfolio value: —")
        totals_layout.addWidget(self.total_label)
        totals_layout.addStretch(1)
        return totals

    def _generate_bottom_buttons_widget(self) -> QWidget:
        btns = QWidget()
        btns_layout = QHBoxLayout(btns)

        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(QApplication.instance().quit)
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
        self.tree.itemChanged.connect(self._refresh_total_label)
        self.cash_amount_edit.textChanged.connect(self._refresh_total_label)
        self.cash_reserve_edit.textChanged.connect(self._refresh_total_label)

        return main_screen_widget

    def _add_asset_group(self):
        # gid = _new_id("grp")
        gitem = QTreeWidgetItem(self.tree)

        set_group_tree_item(self.tree, gitem, "New Asset Group", 0)

        self.tree.expandAll()
        self._refresh_data()

    def _add_instrument(self):
        sel = self.tree.currentItem()
        if sel is None:
            QMessageBox.warning(self, "Add instrument", "Select a group (or an instrument under a group) first.")
            return

        # If instrument selected, use its parent group
        parent = sel.parent() or sel

        add_instrument_item_to_group(parent, "New Instrument", "1", True, "ins")

        self.tree.expandAll()
        self._refresh_data()

    def _delete_selected(self):
        sel = self.tree.currentItem()
        if sel is None:
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
                "cash": {"amount": "12000", "min_reserve": "2000"},
                "groups": [
                    {"id": "sp500", "name": "S&P 500", "targetPercentage": "100", "preferredInstrumentId": "spx_a"}
                ],
                "instruments": [
                    {"id": "spx_a", "name": "SPX 500", "amount": "1", "investable": True, "groupId": "sp500"}
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
            self.cash_amount_edit.setText(str(p.cash.value))
            self.cash_reserve_edit.setText(str(p.cash.min_reserve))

            # group -> list instruments (keep input order as stored)
            ins_by_group: Dict[str, List[Dict[str, Any]]] = {}
            non_investable: List[Dict[str, Any]] = []

            for ins in p.instruments:
                row = {
                    "id": ins.id,
                    "name": ins.name,
                    "amount": str(ins.value),
                    "investable": ins.investable,
                    "groupId": ins.asset_group_id,
                }
                if ins.investable and ins.asset_group_id:
                    ins_by_group.setdefault(ins.asset_group_id, []).append(row)
                else:
                    non_investable.append(row)

            for g in p.asset_groups:
                gitem = QTreeWidgetItem(self.tree)
                set_group_tree_item(self.tree, gitem, g.name, g.target_pct, g.id)

                for ins in ins_by_group.get(g.id, []):
                    add_instrument_item_to_group(gitem, ins["name"], ins["amount"], ins["investable"], ins["id"])

            # Non-investable section (optional): keep simple as a group-like bucket at bottom
            if non_investable:
                non_investable_bucket = QTreeWidgetItem(self.tree)
                set_group_tree_item(self.tree,
                                     non_investable_bucket,
                                     "Non-investable (excluded from strategy)",
                                     0,
                                     RowKind.NON_INVESTABLE_BUCKET.name)

                for ins in non_investable:
                    add_instrument_item_to_group(non_investable_bucket, ins["name"], ins["amount"], False, ins["id"])

            self.tree.expandAll()
        finally:
            self.tree.blockSignals(False)

    def _refresh_data(self):
        self._refresh_total_label()
        self._recalc_totals_and_pcts()
        self._refresh_preferred_dropdowns()

    def _refresh_total_label(self):
        try:
            data = self._build_data_from_main_ui(allow_partial=True)
            # Total portfolio = cash + all instruments amounts
            cash_amt = D(str(data["cash"]["value"]))
            total = cash_amt
            for ins in data.get("instruments", []):
                total += D(str(ins["value"]))
            self.total_label.setText(f"Total portfolio: {total}")
        except Exception:
            self.total_label.setText("Total portfolio: —")


    def _build_data_from_main_ui(self, allow_partial: bool = False)\
            -> Dict[str, Any]:
        cash_amount = self.cash_amount_edit.text().strip()
        cash_reserve = self.cash_reserve_edit.text().strip()

        if not allow_partial:
            if not cash_amount or not cash_reserve:
                raise ValueError("Cash amount and reserve must be filled")

        # In allow_partial, default to "0" if empty for total display
        cash_amount = cash_amount or "0"
        cash_reserve = cash_reserve or "0"

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

            combo = self._get_preferred_combo(gitem)
            if combo is None:
                raise ValueError(f"Group '{gitem}' is missing preferred instrument selector")

            preferred_id = combo.currentData()
            if not preferred_id:
                raise ValueError(f"Group '{gitem}' must have a preferred instrument selected")

            is_non_investable_bucket = (
                        kind == RowKind.NON_INVESTABLE_BUCKET.name)  # Special bucket treated as not-a-group in JSON strategy

            if not is_non_investable_bucket:
                groups.append(
                    {
                        "id": gid,
                        "name": gname,
                        "targetPercentage": target_pct,
                        "preferredInstrumentId": preferred_id,
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
                investable_txt = (ins.text(Col.INVESTABLE.value).strip().lower() or "false")
                investable = investable_txt in ("true", "1", "yes", "y")

                if is_non_investable_bucket:
                    investable = False
                    group_id = None
                else:
                    group_id = gid

                instruments.append(
                    {
                        "id": iid,
                        "name": iname,
                        "value": tot_value,
                        "investable": investable,
                        **({"groupId": group_id} if group_id is not None else {}),
                    }
                )

        return {"cash": {"value": cash_amount, "min_reserve": cash_reserve}, "groups": groups, "instruments": instruments}

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

            # Build wizard steps in group order, executing via preferred instrument
            # Only include non-zero deltas (and for invest mode they are already non-negative)
            ins_by_id = {ins.id: ins for ins in p.instruments}

            steps: List[WizardStep] = []
            for r in rows:
                if r.planned_delta_money == 0:
                    continue
                pref = ins_by_id.get(r.preferred_instrument_id)
                if pref is None:
                    raise ValueError(f"Preferred instrument not found: {r.preferred_instrument_id}")

                steps.append(
                    WizardStep(
                        asset_group_id=r.asset_group_id,
                        asset_group_name=r.asset_group_name,
                        preferred_instrument_id=pref.id,
                        preferred_instrument_name=pref.name,
                        planned_delta_money=r.planned_delta_money,
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

        next_btn = QPushButton("Next")
        next_btn.clicked.connect(self._summary_next)
        btns_layout.addWidget(next_btn)

        btns_layout.addStretch(1)
        layout.addWidget(btns)

        return w

    def _populate_summary(self, p, steps: List[WizardStep], mode: str):
        budget = compute_invest_budget(p)
        lines = [f"Mode: {mode}", f"Invest budget (cash - minimal reserve): {budget}", ""]
        if not steps:
            lines.append("No actions required.")
        else:
            lines.append("Planned actions (executed via preferred instrument per asset group):")
            for s in steps:
                action = "BUY" if s.planned_delta_money > 0 else "SELL"
                lines.append(
                    f"- {action} {abs(s.planned_delta_money)} in [{s.asset_group_name}] via [{s.preferred_instrument_name}]"
                )

        if mode == "rebalance":
            lines.append("")
            lines.append("Note: SELL steps will be executed using the preferred instrument (simple rule).")

        self.summary_text.setText("\n".join(lines))

    def _summary_next(self):
        if not self.current_plan_steps:
            # Nothing to do -> go back to main
            self.stack.setCurrentWidget(self.screen_main)
            return
        self._show_current_wizard_step()
        self.stack.setCurrentWidget(self.screen_wizard)

    # -------------------------
    # Screen 3 (Wizard)
    # -------------------------

    def _build_wizard_screen(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        title = QLabel("Invest per asset group")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.wiz_info = QLabel("—")
        self.wiz_info.setWordWrap(True)
        layout.addWidget(self.wiz_info)

        form = QWidget()
        form_layout = QFormLayout(form)
        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")
        form_layout.addRow("Price:", self.price_edit)
        layout.addWidget(form)

        calc_row = QWidget()
        calc_layout = QHBoxLayout(calc_row)
        calc_btn = QPushButton("Calculate")
        calc_btn.clicked.connect(self._wizard_calculate)
        calc_layout.addWidget(calc_btn)

        self.wiz_result = QLabel("Units: — | Spent: — | Leftover vs plan: —")
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
            f"Instrument: {s.preferred_instrument_name}\n"
            f"Planned {action} amount (money): {abs(s.planned_delta_money)}"
        )
        self.price_edit.setText("")
        self.wiz_result.setText("Units: — | Spent/Proceeds: — | Leftover vs plan: —")

        # store last calculation
        self._last_calc = None

    def _wizard_calculate(self):
        try:
            s = self.current_plan_steps[self.current_step_index]
            price = d_from_text(self.price_edit.text(), "price")

            planned = abs(s.planned_delta_money)
            calc = calculate_buy_units(
                instrument_id=s.preferred_instrument_id,
                planned_money=planned,
                price=price,
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

            # Allow save&continue with 0 units -> skip saving (your requirement)
            if calc_units > 0 and spent >= D("1"):
                if s.planned_delta_money > 0:
                    self.current_portfolio = commit_buy(
                        p=self.current_portfolio,
                        instrument_id=s.preferred_instrument_id,
                        spent=spent,
                        min_trade_ils=D("1"),
                    )
                else:
                    # SELL (simple: sell from preferred instrument)
                    self.current_portfolio = commit_sell(
                        p=self.current_portfolio,
                        instrument_id=s.preferred_instrument_id,
                        proceeds=spent,
                        min_trade_ils=D("1"),
                    )

                # Persist after each step (matches your “partial saves ok”)
                save_portfolio_file(self.current_portfolio, self.json_path)

            # Next step or back to main
            self.current_step_index += 1
            if self.current_step_index >= len(self.current_plan_steps):
                # Return to main with updated data
                self._populate_main_from_portfolio(self.current_portfolio)
                self.stack.setCurrentWidget(self.screen_main)
            else:
                self._show_current_wizard_step()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _on_preferred_changed(self):
        pass

    def _recalc_totals_and_pcts(self) -> None:
        """
        Updates:
        - group total value = sum(child instrument Values)
        - strategy total value (sum of group values)
        - portfolio total value (cash + all instrument values)
        - Portfolio % for all rows
        - Strategy % + Drift(pp) for group rows only
        """
        print(f"DEBUG: called _recalc_totals_and_pcts")
        self._suppress_item_changed = True
        try:
            # 1) First pass: compute group values and collect row values
            group_items: list[QTreeWidgetItem] = []
            row_value: dict[QTreeWidgetItem, D] = {}

            portfolio_instruments_total = D("0")  # all instruments (investable + non)
            strategy_total = D("0")  # sum of investable group totals

            # Compute investable group totals and child instrument totals
            for i in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(i)
                kind = get_item_kind(top)

                if kind == RowKind.GROUP.name:
                    # sum children
                    total = D("0")
                    for j in range(top.childCount()):
                        child = top.child(j)
                        if get_item_kind(child) != RowKind.INSTRUMENT.name:
                            continue
                        v = parse_amount_cell(child.text(Col.TOT_VALUE.value))
                        total += v
                        row_value[child] = v
                        portfolio_instruments_total += v

                    top.setText(Col.TOT_VALUE.value, str(total))
                    row_value[top] = total
                    group_items.append(top)
                    strategy_total += total

                elif kind == RowKind.NON_INVESTABLE_BUCKET:
                    v = parse_amount_cell(top.text(Col.TOT_VALUE.value))
                    row_value[top] = v
                    portfolio_instruments_total += v

            cash_value = parse_amount_cell(self.cash_amount_edit.text())  # rename field when you do value migration
            portfolio_total = cash_value + portfolio_instruments_total

            # 2) Portfolio % for all items
            for item, v in row_value.items():
                pct = safe_pct(v, portfolio_total)
                item.setText(Col.PORTFOLIO_PCT.value, "" if pct is None else fmt_pct(pct))

            # 3) Strategy % + Drift for groups only (exclude non-investables + cash already excluded)
            for g in group_items:
                gval = row_value.get(g, D("0"))
                sp = safe_pct(gval, strategy_total)
                if sp is None:
                    g.setText(Col.STRATEGY_PCT.value, "")
                    g.setText(Col.DRIFT_PP.value, "")
                else:
                    g.setText(Col.STRATEGY_PCT.value, fmt_pct(sp))

                    # target pct is user-entered decimal string
                    target = parse_amount_cell(g.text(Col.TARGET_PCT.value))
                    drift = sp - target
                    g.setText(Col.DRIFT_PP.value, fmt_pp(drift))

            # 4) Clear group-only columns for non-group rows (optional cleanliness)
            for i in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(i)
                if get_item_kind(top) == RowKind.NON_INVESTABLE_BUCKET:
                    top.setText(Col.TARGET_PCT.value, "")
                    top.setText(Col.STRATEGY_PCT.value, "")
                    top.setText(Col.DRIFT_PP.value, "")
                    top.setText(Col.PREFERRED_INSTR.value, "")

        finally:
            self._suppress_item_changed = False

