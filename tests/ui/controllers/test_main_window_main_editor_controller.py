from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QTreeWidgetItem

import ui.controllers.main_window_main_editor as controller_mod
from portfolio_core.domain.models import Exchange
from portfolio_core.domain.ticker_rules import ExchangeTickerLocationIndex, build_exchange_ticker_key
from portfolio_core.io_json import load_portfolio
from portfolio_core.workflows import HardRefreshFallback, HardRefreshPortfolioMarketDataResult
import ui.controllers.main_window_metrics as metrics_mod
from ui.controllers.protocols import suppress_item_changed
from ui.main_window import MainWindow
from ui.shared.ui_types import Col
from ui.shared.ui_utils import add_instrument_item_to_group, set_group_tree_item


class _FakeOverlay:
    def __init__(self, parent: object) -> None:
        _ = parent
        self.status_text = ""
        self.shown = False

    def show_overlay(self) -> None:
        self.shown = True

    def hide_overlay(self) -> None:
        self.shown = False

    def deleteLater(self) -> None:
        return None

    def set_status_text(self, text: str) -> None:
        self.status_text = text


class _FakeMarketDataRefreshLifecycle:
    def __init__(self) -> None:
        self.cancel_calls: list[int] = []
        self.start_calls: list[dict[str, object]] = []

    def start(self, **kwargs: object) -> None:
        self.start_calls.append(kwargs)

    def cancel(self, *, wait_timeout_ms: int) -> bool:
        self.cancel_calls.append(wait_timeout_ms)
        return True


def _make_fake_overlay_factory(overlays: list[_FakeOverlay]):
    def _factory(parent: object) -> _FakeOverlay:
        overlay = _FakeOverlay(parent)
        overlays.append(overlay)
        return overlay

    return _factory


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
    monkeypatch.setattr(metrics_mod, "resolve_cached_instrument_price_ils", lambda **_kwargs: Decimal("425.17"))

    window._main_editor_controller.add_instrument()

    assert group.childCount() == 1
    child = group.child(0)
    assert child is not None
    assert child.text(Col.TICKER.value) == "AB12"
    assert child.text(Col.NAME.value) == "World ETF"
    assert child.text(Col.QUANTITY.value) == "12"
    assert child.text(Col.TOT_VALUE.value) == "5,102.04"
    assert child.text(Col.EXCHANGE.value) == "NYSE"
    assert child.text(Col.TARGET_PCT.value) == "25.0%"


def test_add_instrument_suppresses_item_changed_during_row_creation(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = QTreeWidgetItem(window.tree)
    set_group_tree_item(group, "Equity", "100", "grp_equity")
    window.tree.setCurrentItem(group)
    suppress_states: list[bool] = []

    class _FakeWizard:
        def __init__(self, **kwargs: object) -> None:
            _ = kwargs
            self.result_data = SimpleNamespace(
                exchange=Exchange.TASE,
                ticker="1234567",
                name="Local ETF",
                last_traded_price=Decimal("10"),
                target_in_group_pct="25",
                units=2,
            )

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    def _recording_add(
        gitem: QTreeWidgetItem,
        ticker: str,
        name: str,
        quantity: int,
        in_group_pct: str,
        id_str: str = "",
        exchange: str | Exchange = "TASE",
    ) -> None:
        suppress_states.append(window._suppress_item_changed)
        add_instrument_item_to_group(gitem, ticker, name, quantity, in_group_pct, id_str, exchange)

    monkeypatch.setattr(controller_mod, "LoadingOverlay", _FakeOverlay)
    monkeypatch.setattr(controller_mod, "AddInstrumentWizardDialog", _FakeWizard)
    monkeypatch.setattr(controller_mod, "add_instrument_item_to_group", _recording_add)
    monkeypatch.setattr(metrics_mod, "resolve_cached_instrument_price_ils", lambda **_kwargs: Decimal("10"))

    window._main_editor_controller.add_instrument()

    assert suppress_states == [True]
    assert window._suppress_item_changed is False


def test_suppress_item_changed_restores_flag_after_exception() -> None:
    class _Host:
        _suppress_item_changed = False

    host = _Host()

    try:
        with suppress_item_changed(host):
            assert host._suppress_item_changed is True
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert host._suppress_item_changed is False


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
    monkeypatch.setattr(metrics_mod, "resolve_cached_instrument_price_ils", lambda **_kwargs: Decimal("1"))
    group = QTreeWidgetItem(window.tree)
    set_group_tree_item(group, "Equity", "100", "grp_equity")
    add_instrument_item_to_group(
        group,
        "ab12",
        "World ETF",
        10,
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
        "create_new_default_document",
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


def test_refresh_market_data_uses_current_editor_state_and_starts_worker(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = load_portfolio(
        {
            "cash": {"value": "100", "min_reserve": "0", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "Group", "targetPercentage": "100"}],
            "instruments": [],
        }
    )
    fake_lifecycle = _FakeMarketDataRefreshLifecycle()
    overlays: list[_FakeOverlay] = []

    monkeypatch.setattr(controller_mod, "LoadingOverlay", _make_fake_overlay_factory(overlays))
    monkeypatch.setattr(window._main_editor_controller, "_market_data_refresh", fake_lifecycle)
    monkeypatch.setattr(window._main_editor_controller, "_build_current_main_editor_portfolio", lambda: portfolio)

    window._main_editor_controller.on_refresh_market_data_clicked()

    assert fake_lifecycle.cancel_calls == [1500]
    assert fake_lifecycle.start_calls[0]["portfolio"] is portfolio
    assert fake_lifecycle.start_calls[0]["cached_usd_ils_quote"] is window.session.cached_usd_ils_quote
    assert overlays[0].status_text == "Refreshing market data..."
    assert overlays[0].shown is True
    assert window.stack.isEnabled() is False


def test_refresh_market_data_finished_rerenders_and_shows_fallback_info(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refreshed = load_portfolio(
        {
            "cash": {"value": "100", "min_reserve": "0", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "Group", "targetPercentage": "100"}],
            "instruments": [],
        }
    )
    overlays: list[_FakeOverlay] = []
    rendered: list[tuple[object, bool]] = []
    info_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(controller_mod, "LoadingOverlay", _make_fake_overlay_factory(overlays))
    monkeypatch.setattr(
        MainWindow,
        "_render_main_editor_from_portfolio",
        lambda self, portfolio, *, switch_to_main: rendered.append((portfolio, switch_to_main)),
    )
    monkeypatch.setattr(window, "_show_info", lambda title, message: info_calls.append((title, message)))
    window._main_editor_controller._show_market_data_refresh_overlay()

    result = HardRefreshPortfolioMarketDataResult(
        portfolio=refreshed,
        fallbacks=(
            HardRefreshFallback(
                instrument_id="i1",
                instrument_name="TASE ETF",
            ),
        ),
    )
    window._main_editor_controller._on_market_data_refresh_finished(
        result,
        None,
    )

    assert overlays[0].shown is False
    assert window.stack.isEnabled() is True
    assert window.session.document.current_portfolio == refreshed
    assert rendered == [(refreshed, False)]
    assert info_calls == [
        (
            "Market data refresh used cached fallback",
            "TASE ETF: live price refresh failed, so the app reused the cached market price.",
        )
    ]
