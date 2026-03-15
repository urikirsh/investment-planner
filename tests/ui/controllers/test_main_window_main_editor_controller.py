from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QTreeWidgetItem

import ui.controllers.main_window_main_editor as controller_mod
from ui.main_window import MainWindow
from ui.shared.ui_types import Col
from ui.shared.ui_utils import set_group_tree_item


class _FakeOverlay:
    def __init__(self, parent: object) -> None:
        _ = parent

    def show_overlay(self) -> None:
        return None

    def hide_overlay(self) -> None:
        return None

    def deleteLater(self) -> None:
        return None


def test_add_instrument_creates_row_from_wizard_result(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = QTreeWidgetItem(window.tree)
    set_group_tree_item(group, "Equity", "100", "grp_equity")
    window.tree.setCurrentItem(group)

    class _FakeWizard:
        def __init__(self, **kwargs: object) -> None:
            _ = kwargs
            self.result_data = SimpleNamespace(
                exchange="NYSE",
                ticker="AB12",
                name="World ETF",
                target_in_group_pct="25",
            )

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(controller_mod, "LoadingOverlay", _FakeOverlay)
    monkeypatch.setattr(controller_mod, "AddInstrumentWizardDialog", _FakeWizard)

    window._main_editor_controller.add_instrument()

    assert group.childCount() == 1
    child = group.child(0)
    assert child is not None
    assert child.text(Col.TICKER.value) == "AB12"
    assert child.text(Col.NAME.value) == "World ETF"
    assert child.text(Col.EXCHANGE.value) == "NYSE"
    assert child.text(Col.TARGET_PCT.value) == "25"


def test_add_instrument_noop_when_wizard_is_canceled(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = QTreeWidgetItem(window.tree)
    set_group_tree_item(group, "Equity", "100", "grp_equity")
    window.tree.setCurrentItem(group)

    class _FakeWizard:
        def __init__(self, **kwargs: object) -> None:
            _ = kwargs
            self.result_data = None

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(controller_mod, "LoadingOverlay", _FakeOverlay)
    monkeypatch.setattr(controller_mod, "AddInstrumentWizardDialog", _FakeWizard)

    window._main_editor_controller.add_instrument()

    assert group.childCount() == 0
