from __future__ import annotations

"""FX-specific wizard orchestration extracted from ``MainWindowWizardMixin``.

Current responsibility:
- load startup-cached USD/ILS quote into wizard state for each run,
- render USD-step FX panel state from cached values.

The wizard always derives unit recommendations from startup-cached prices, so
the FX panel is now purely explanatory state for USD-priced steps.
"""

from typing import Any, Protocol

from portfolio_core.domain.models import Currency
from portfolio_core.session.portfolio_session import CachedUsdIlsQuote, PortfolioSession
from ui.shared.constants import DEFAULT_CLEANUP_WAIT_MS
from ui.ui_state import PlanningState, WizardState


class WizardFxHost(Protocol):
    """Host contract required by ``WizardFxCoordinator``.

    The host provides wizard/session state plus a cancellation seam reused by
    existing wizard flow guards.
    """

    session: PortfolioSession
    planning_state: PlanningState
    wizard_state: WizardState
    screen_wizard: Any

    def _cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool: ...


class WizardFxCoordinator:
    """Owns wizard FX state hydration and USD-step FX panel rendering."""

    def __init__(self, host: WizardFxHost) -> None:
        self._host = host

    def reset_wizard_fx_state_for_new_run(self) -> bool:
        """Reset transient USD/ILS state and hydrate from session cache.

        Returns ``False`` when host cleanup cannot complete within the wait window.
        """
        if not self._host._cancel_wizard_fx_fetch():
            return False
        state = self._host.wizard_state
        cached = self._host.session.cached_usd_ils_quote
        self._apply_cached_quote_to_wizard_state(state, cached)
        return True

    def cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Return no-op success for backward-compatible cleanup call sites."""
        _ = wait_timeout_ms
        return True

    def render_fx_panel_for_current_step(self) -> None:
        """Render FX quote availability status for the active step.

        For non-USD steps, FX UI rows are hidden.
        For USD steps, this method is the single source of truth for cached
        quote disclosure and rate-unavailable messaging used by the units flow.
        """
        state = self._host.wizard_state
        s = self._host.planning_state.plan_steps[self._host.planning_state.step_index]
        if s.exchange.currency != Currency.USD:
            self._host.screen_wizard.set_fx_panel(
                visible=False,
                info_text="",
                error_text="",
            )
            return

        info_lines: list[str] = []
        if state.usd_ils_rate is not None:
            info_lines.append(
                f"USD/ILS rate: {state.usd_ils_rate} | "
                f"Effective date: {state.usd_ils_rate_date}"
            )
            if state.usd_ils_used_last_published:
                info_lines.append("No new official rate for today; using last published rate.")
            if state.usd_ils_rate_from_cache:
                info_lines.append(
                    f"Using startup-cached rate saved at: {state.usd_ils_rate_cached_at}."
                )

        error_text = ""
        if state.usd_ils_rate is None:
            error_text = "USD/ILS rate unavailable. Return to welcome and try again."

        self._host.screen_wizard.set_fx_panel(
            visible=True,
            info_text="\n".join(info_lines),
            error_text=error_text,
        )

    @staticmethod
    def _apply_cached_quote_to_wizard_state(state: WizardState, cached: CachedUsdIlsQuote | None) -> None:
        """Apply cached quote (or reset defaults) to wizard FX state fields."""
        if cached is None:
            state.usd_ils_rate = None
            state.usd_ils_rate_date = None
            state.usd_ils_used_last_published = False
            state.usd_ils_rate_from_cache = False
            state.usd_ils_rate_cached_at = None
            return
        state.usd_ils_rate = cached.rate
        state.usd_ils_rate_date = cached.effective_date
        state.usd_ils_used_last_published = cached.used_last_published
        state.usd_ils_rate_from_cache = True
        state.usd_ils_rate_cached_at = cached.cached_at
