from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable, cast

from portfolio_core.fx_service import UsdIlsRateQuote
from portfolio_core.models import Currency, Exchange
from portfolio_core.portfolio_session import CachedUsdIlsQuote
from portfolio_core.use_cases import PlanStep
from ui.ui_state import PlanningState, WizardState
from ui.wizard_fx_coordinator import WizardFxCoordinator, WizardFxHost


@dataclass
class _FakeButton:
    enabled: bool = True

    def setEnabled(self, value: bool) -> None:
        self.enabled = value


class _FakeScreen:
    def __init__(self) -> None:
        self.calculate_btn = _FakeButton()
        self.panel_calls: list[dict[str, Any]] = []

    def set_fx_panel(
        self,
        *,
        visible: bool,
        info_text: str,
        error_text: str,
        manual_visible: bool,
        manual_value: str = "",
    ) -> None:
        self.panel_calls.append(
            {
                "visible": visible,
                "info_text": info_text,
                "error_text": error_text,
                "manual_visible": manual_visible,
                "manual_value": manual_value,
            }
        )


class _FakeSession:
    def __init__(self) -> None:
        self.cached_quote: CachedUsdIlsQuote | None = None

    def read_cached_usd_ils_quote(self) -> CachedUsdIlsQuote | None:
        return self.cached_quote

    def write_cached_usd_ils_quote(self, **_kwargs: object) -> None:
        return None


class _FakeHost:
    def __init__(self, steps: list[PlanStep]) -> None:
        self.session = _FakeSession()
        self.planning_state = PlanningState(plan_steps=steps, step_index=0)
        self.wizard_state = WizardState()
        self.screen_wizard = _FakeScreen()
        self.manual_rate_edit = SimpleNamespace(setText=lambda _value: None)
        self.cancel_returns = True

    def _wizard_has_usd_steps(self) -> bool:
        return any(step.exchange.currency == Currency.USD for step in self.planning_state.plan_steps)

    def _cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = 1000) -> bool:
        _ = wait_timeout_ms
        return self.cancel_returns

    def _on_fx_fetch_finished(self, quote_obj: object, error_obj: object, generation: int) -> None:
        _ = (quote_obj, error_obj, generation)
        return None


def test_prepare_wizard_fx_rate_cache_shows_wait_when_cancel_fails(
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost([make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.cancel_returns = False
    shown: list[tuple[str, str]] = []
    coordinator = WizardFxCoordinator(cast(WizardFxHost, host), show_error_fn=lambda _p, t, m: shown.append((t, m)))

    coordinator.prepare_wizard_fx_rate_cache()

    assert host.wizard_state.usd_ils_fetch_attempted is False
    assert shown == []


def test_on_fx_fetch_finished_ignores_stale_generation(
    make_plan_step: Callable[..., PlanStep],
) -> None:
    host = _FakeHost([make_plan_step(delta="50", exchange=Exchange.NYSE)])
    host.wizard_state.usd_ils_rate = Decimal("3.7")
    host.wizard_state.usd_ils_active_fetch_generation = 2
    coordinator = WizardFxCoordinator(cast(WizardFxHost, host), show_error_fn=lambda _p, _t, _m: None)

    coordinator.on_fx_fetch_finished(
        UsdIlsRateQuote(
            rate=Decimal("3.9"),
            effective_date=datetime.fromisoformat("2026-03-01T00:00:00").date(),
            used_last_published=False,
        ),
        None,
        1,
    )

    assert host.wizard_state.usd_ils_rate == Decimal("3.7")


def test_render_fx_panel_hides_for_non_usd_steps(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost([make_plan_step(delta="50", exchange=Exchange.TASE)])
    coordinator = WizardFxCoordinator(cast(WizardFxHost, host), show_error_fn=lambda _p, _t, _m: None)

    coordinator.render_fx_panel_for_current_step()

    assert host.screen_wizard.calculate_btn.enabled is True
    assert host.screen_wizard.panel_calls
    last_panel = host.screen_wizard.panel_calls[-1]
    assert last_panel["visible"] is False
    assert last_panel["manual_visible"] is False
