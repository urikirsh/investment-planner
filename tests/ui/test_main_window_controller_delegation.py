from __future__ import annotations

"""Delegation seams for composed `MainWindow` controller objects."""

import pytest
from PySide6.QtWidgets import QTreeWidgetItem

from ui.controllers import (
    MainWindowMainEditorController,
    MainWindowMetricsController,
    MainWindowSummaryController,
    MainWindowTableEditingController,
    MainWindowWelcomeController,
)
from ui.main_window import MainWindow
from ui.ui_types import Col


def test_main_window_composes_screen_controllers(window: MainWindow) -> None:
    assert isinstance(window._welcome_controller, MainWindowWelcomeController)
    assert isinstance(window._main_editor_controller, MainWindowMainEditorController)
    assert isinstance(window._summary_controller, MainWindowSummaryController)
    assert isinstance(window._metrics_controller, MainWindowMetricsController)
    assert isinstance(window._table_editing_controller, MainWindowTableEditingController)


def test_main_window_wrapper_methods_delegate_to_composed_controllers(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    dummy_item = QTreeWidgetItem(window.tree)

    cases: list[tuple[str, str, str, tuple[object, ...], dict[str, object]]] = [
        ("_welcome_controller", "on_load_different_clicked", "_on_welcome_load_different_clicked", (), {}),
        ("_welcome_controller", "on_start_new_clicked", "_on_welcome_start_new_clicked", (), {}),
        ("_main_editor_controller", "add_asset_group", "_add_asset_group", (), {}),
        ("_main_editor_controller", "add_instrument", "_add_instrument", (), {}),
        ("_main_editor_controller", "delete_selected_row", "_delete_selected_row", (), {}),
        ("_main_editor_controller", "on_refresh_requested", "_on_main_refresh_requested", ("x",), {}),
        ("_main_editor_controller", "on_invest_clicked", "_on_invest_clicked", (), {}),
        ("_main_editor_controller", "on_rebalance_clicked", "_on_rebalance_clicked", (), {}),
        ("_summary_controller", "summary_next", "_summary_next", (), {}),
        ("_summary_controller", "summary_back", "_summary_back", (), {}),
        ("_metrics_controller", "refresh_data", "_refresh_data", (), {}),
        ("_metrics_controller", "refresh_total_portfolio", "_refresh_total_portfolio", (), {}),
        ("_metrics_controller", "recalc_totals_and_pcts", "_recalc_totals_and_pcts", (), {}),
        ("_metrics_controller", "normalize_future_tax_input", "_normalize_future_tax_input", (), {}),
        ("_metrics_controller", "update_future_tax_visual_state", "_update_future_tax_visual_state", (), {}),
        ("_metrics_controller", "update_investable_balance_visual_state", "_update_investable_balance_visual_state", (), {}),
        (
            "_table_editing_controller",
            "on_item_changed_guard_and_recalc",
            "_on_item_changed_guard_and_recalc",
            (dummy_item, Col.QUANTITY.value),
            {},
        ),
        (
            "_table_editing_controller",
            "on_item_double_clicked",
            "_on_item_double_clicked",
            (dummy_item, Col.TICKER.value),
            {},
        ),
    ]

    for controller_attr, delegated_method, wrapper_name, args, kwargs in cases:
        controller = getattr(window, controller_attr)
        tag = f"{controller_attr}.{delegated_method}"
        monkeypatch.setattr(controller, delegated_method, lambda *a, _tag=tag, **k: calls.append(_tag))
        getattr(window, wrapper_name)(*args, **kwargs)

    assert calls == [f"{controller}.{method}" for controller, method, *_ in cases]
