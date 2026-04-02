from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QTreeWidgetItem

import ui.controllers.main_window_main_editor as controller_mod
from portfolio_core.domain.models import Exchange
from portfolio_core.io_json import load_portfolio
from portfolio_core.domain.ticker_rules import ExchangeTickerLocationIndex, build_exchange_ticker_key
from ui.main_window import MainWindow
from ui.shared.ui_types import Col
from ui.shared.ui_utils import add_instrument_item_to_group, set_group_tree_item


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
    window.session.cache_usd_ils_quote(
        rate=Decimal("3.5"),
        effective_date=date.fromisoformat("2026-03-25"),
        used_last_published=False,
    )
    group = QTreeWidgetItem(window.tree)
    set_group_tree_item(group, "Equity", "100", "grp_equity")
    window.tree.setCurrentItem(group)

    class _FakeWizard:
        def __init__(self, **kwargs: object) -> None:
            _ = kwargs
            self.result_data = SimpleNamespace(
                exchange=Exchange.NYSE,
                ticker="AB12",
                name="World ETF",
                last_traded_price=Decimal("10.123"),
                target_in_group_pct="25",
                units=12,
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
    assert child.text(Col.QUANTITY.value) == "12"
    assert child.text(Col.TOT_VALUE.value) == "425.17"
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


def test_add_instrument_passes_existing_exchange_ticker_locations_to_wizard(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = QTreeWidgetItem(window.tree)
    set_group_tree_item(group, "Equity", "100", "grp_equity")
    add_instrument_item_to_group(
        group,
        "ab12",
        "World ETF",
        10,
        "1",
        "100",
        exchange=Exchange.NYSE,
    )
    window.tree.setCurrentItem(group)
    captured_kwargs: dict[str, object] = {}

    class _FakeWizard:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)
            self.result_data = None

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(controller_mod, "LoadingOverlay", _FakeOverlay)
    monkeypatch.setattr(controller_mod, "AddInstrumentWizardDialog", _FakeWizard)

    window._main_editor_controller.add_instrument()

    index = captured_kwargs["existing_ticker_locations"]
    assert isinstance(index, ExchangeTickerLocationIndex)
    key = build_exchange_ticker_key(exchange=Exchange.NYSE, raw_ticker="AB12")
    assert index.find_location(key=key) == "Equity"


def test_load_default_document_uses_refreshed_default_portfolio(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refreshed = load_portfolio(
        {
            "cash": {"value": "12000", "min_reserve": "2000", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "Group", "targetPercentage": "100"}],
            "instruments": [
                {
                    "id": "i1",
                    "ticker": "1234567",
                    "name": "ETF",
                    "quantity": 1,
                    "value": "150",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g1",
                    "targetInGroupPercentage": "100",
                }
            ],
        }
    )
    rendered: list[tuple[object, bool]] = []
    updated_file_context: list[bool] = []

    monkeypatch.setattr(
        controller_mod,
        "create_new_default_document_with_price_refresh",
        lambda session: session.mark_new_document(refreshed) or refreshed,
    )
    monkeypatch.setattr(
        MainWindow,
        "_render_main_editor_from_portfolio",
        lambda self, portfolio, *, switch_to_main: rendered.append((portfolio, switch_to_main)),
    )
    monkeypatch.setattr(
        MainWindow,
        "_update_file_context_ui",
        lambda self: updated_file_context.append(True),
    )

    window._main_editor_controller.load_default_document()

    assert rendered == [(refreshed, False)]
    assert updated_file_context == [True]
    assert window.session.current_file_path is None
