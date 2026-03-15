from __future__ import annotations

"""Main-editor screen setup and row-level editing actions."""

from typing import cast

from PySide6.QtWidgets import QApplication, QDialog, QTreeWidgetItem, QWidget

from portfolio_core.planning_types import PlanningMode
from portfolio_core.use_cases import create_new_default_document
from ui.controllers.protocols import MainWindowMainEditorHost
from ui.dialogs import show_warning
from ui.shared.loading_overlay import LoadingOverlay
from ui.shared.ui_types import Col
from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.add_instrument_wizard_dialog import AddInstrumentWizardDialog
from ui.shared.ui_types import RowKind
from ui.shared.ui_utils import add_instrument_item_to_group, get_item_kind, set_group_tree_item


class MainWindowMainEditorController:
    """Controller for main-editor screen wiring and direct row actions."""

    def __init__(self, host: MainWindowMainEditorHost) -> None:
        self._host = host

    def _host_widget(self) -> QWidget:
        """Return host cast to QWidget for dialog parenting/screen construction."""
        return cast(QWidget, self._host)

    @staticmethod
    def _determine_default_in_group_pct(parent: QTreeWidgetItem) -> str:
        """Return default in-group target for newly added instrument rows."""
        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            return ""
        return "100" if parent.childCount() == 0 else "0"

    def _build_existing_instrument_name_locations(self) -> dict[str, str]:
        """Return normalized-name -> first-found human-readable location mapping."""
        tree = self._host.tree
        name_locations: dict[str, str] = {}
        for top_index in range(tree.topLevelItemCount()):
            parent = tree.topLevelItem(top_index)
            if parent is None:
                continue
            parent_kind = get_item_kind(parent)
            if parent_kind == RowKind.NON_INVESTABLE_BUCKET:
                location = "non-investable bucket"
            else:
                location = parent.text(Col.NAME.value).strip() or "unnamed group"

            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child is None or get_item_kind(child) != RowKind.INSTRUMENT:
                    continue
                child_name = child.text(Col.NAME.value).strip()
                if not child_name:
                    continue
                normalized_name = child_name.casefold()
                if normalized_name not in name_locations:
                    name_locations[normalized_name] = location
        return name_locations

    def init_screen(self) -> None:
        """Build main-editor widget and wire all signal handlers."""
        host = self._host
        host.screen_main = MainEditorScreen(self._host_widget())
        host.tree = host.screen_main.tree
        host.cash_value_edit = host.screen_main.cash_value_edit
        host.cash_reserve_edit = host.screen_main.cash_reserve_edit
        host.future_tax_edit = host.screen_main.future_tax_edit
        host.investable_balance_label = host.screen_main.investable_balance_label
        host.total_label = host.screen_main.total_label

        host.screen_main.add_group_btn.clicked.connect(self.add_asset_group)
        host.screen_main.add_instrument_btn.clicked.connect(self.add_instrument)
        host.screen_main.delete_row_btn.clicked.connect(self.delete_selected_row)
        host.screen_main.quit_btn.clicked.connect(self.on_quit_clicked)
        host.screen_main.invest_btn.clicked.connect(self.on_invest_clicked)
        host.screen_main.rebalance_btn.clicked.connect(self.on_rebalance_clicked)
        host.screen_main.save_btn.clicked.connect(host._on_save_clicked)
        host.screen_main.save_as_btn.clicked.connect(host._on_save_as_clicked)
        host.screen_main.open_btn.clicked.connect(host._on_open_clicked)
        host.screen_main.new_btn.clicked.connect(host._on_new_clicked)

        host.tree.items_reordered.connect(self.on_refresh_requested)
        host.cash_value_edit.textChanged.connect(self.on_refresh_requested)
        host.cash_reserve_edit.textChanged.connect(self.on_refresh_requested)
        host.future_tax_edit.textChanged.connect(self.on_refresh_requested)
        host.future_tax_edit.editingFinished.connect(host._normalize_future_tax_input)

    def add_asset_group(self) -> None:
        """Append a new editable asset-group row and refresh derived values."""
        host = self._host
        new_item = QTreeWidgetItem(host.tree)
        set_group_tree_item(new_item, "New Asset Group", 0)
        host.tree.expandAll()
        host._refresh_data()

    def add_instrument(self) -> None:
        """Open add-instrument wizard and add row under selected group on success."""
        host = self._host
        sel = host.tree.currentItem()
        if sel is None:
            show_warning(
                self._host_widget(),
                "Add instrument",
                "Select a group (or an instrument under a group) first.",
            )
            return

        parent = sel.parent() or sel
        parent_kind = get_item_kind(parent)
        is_non_investable_group = parent_kind == RowKind.NON_INVESTABLE_BUCKET
        default_in_group_pct = self._determine_default_in_group_pct(parent)
        parent_group_name = parent.text(Col.NAME.value).strip() or "Unnamed Group"

        overlay = LoadingOverlay(host.screen_main)
        overlay.show_overlay()
        try:
            wizard = AddInstrumentWizardDialog(
                instrument_group_name=parent_group_name,
                is_non_investable_group=is_non_investable_group,
                existing_name_locations=self._build_existing_instrument_name_locations(),
                parent=self._host_widget(),
            )
            accepted = wizard.exec() == QDialog.DialogCode.Accepted and wizard.result_data is not None
        finally:
            overlay.hide_overlay()
            overlay.deleteLater()

        if not accepted or wizard.result_data is None:
            return

        result = wizard.result_data
        in_group_pct = default_in_group_pct if result.target_in_group_pct == "" else result.target_in_group_pct
        add_instrument_item_to_group(
            parent,
            result.ticker,
            result.name,
            0,
            "1",
            in_group_pct,
            exchange=result.exchange,
        )
        host.tree.expandAll()
        host._refresh_data()

    def delete_selected_row(self) -> None:
        """Delete selected group/instrument row unless it is the protected bucket."""
        host = self._host
        sel = host.tree.currentItem()
        if sel is None:
            return

        if get_item_kind(sel) == RowKind.NON_INVESTABLE_BUCKET:
            show_warning(self._host_widget(), "Not allowed", "The non-investable bucket cannot be deleted.")
            return

        parent = sel.parent()
        if parent is None:
            idx = host.tree.indexOfTopLevelItem(sel)
            if idx >= 0:
                host.tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(sel)
        host._refresh_data()

    def load_default_document(self) -> None:
        """Load default portfolio into main editor as a new unsaved document."""
        host = self._host
        p = create_new_default_document(host.session)
        host._render_main_editor_from_portfolio(p, switch_to_main=False)
        host._update_file_context_ui()

    def on_refresh_requested(self, *_args: object) -> None:
        """Single dispatcher for main-screen refresh requests from signals."""
        self._host._refresh_data()

    def on_invest_clicked(self) -> None:
        """Start invest planning from current main-editor state."""
        self._host._run_planning(mode=PlanningMode.INVEST)

    def on_rebalance_clicked(self) -> None:
        """Start rebalance planning from current main-editor state."""
        self._host._run_planning(mode=PlanningMode.REBALANCE)

    def on_quit_clicked(self) -> None:
        """Quit app after unsaved-changes confirmation when needed."""
        host = self._host
        if not host._confirm_continue_with_unsaved_changes("quitting"):
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()
