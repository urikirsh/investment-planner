from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, cast

from portfolio_core.domain.models import Exchange
from portfolio_core.session.portfolio_session import CachedUsdIlsQuote
from portfolio_core.use_cases import PlanStep
from ui.ui_state import PlanningState, WizardState
from ui.wizard_fx_coordinator import WizardFxCoordinator, WizardFxHost


class _FakeScreen:
    def __init__(self) -> None:
        self.panel_calls: list[dict[str, Any]] = []

    def set_fx_panel(
        self,
        *,
        visible: bool,
        info_text: str,
        error_text: str,
    ) -> None:
        self.panel_calls.append(
            {
                "visible": visible,
                "info_text": info_text,
                "error_text": error_text,
            }
        )


class _FakeSession:
    def __init__(self) -> None:
        self.cached_quote: CachedUsdIlsQuote | None = None

    @property
    def cached_usd_ils_quote(self) -> CachedUsdIlsQuote | None:
        return self.cached_quote


class _FakeHost:
    def __init__(self, steps: list[PlanStep]) -> None:
        self.session = _FakeSession()
        self.planning_state = PlanningState(plan_steps=steps, step_index=0)
        self.wizard_state = WizardState()
        self.screen_wizard = _FakeScreen()
        self.cancel_returns = True

    def _cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = 1000) -> bool:
        _ = wait_timeout_ms
        return self.cancel_returns


def test_render_fx_panel_hides_for_non_usd_steps(make_plan_step: Callable[..., PlanStep]) -> None:
    host = _FakeHost([make_plan_step(delta="50", exchange=Exchange.TASE)])
    coordinator = WizardFxCoordinator(cast(WizardFxHost, host))

    coordinator.render_fx_panel_for_current_step()

    assert host.screen_wizard.panel_calls
    last_panel = host.screen_wizard.panel_calls[-1]
    assert last_panel["visible"] is False
