from __future__ import annotations

"""FX-specific wizard orchestration extracted from ``MainWindowWizardMixin``.

This module isolates USD/ILS concerns from general wizard step flow:
- session-cached quote loading for new wizard runs,
- FX panel rendering for USD steps,
- defensive shutdown helpers for legacy fetch thread seams.

The coordinator mutates only wizard-run transient state (`WizardState`) and
delegates host-specific UI calls through a small protocol.
"""

from collections.abc import Callable
from typing import Any, Protocol, cast

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QWidget

from portfolio_core.fx_service import UsdIlsRateQuote, fetch_latest_usd_ils_rate
from portfolio_core.models import Currency
from portfolio_core.portfolio_session import CachedUsdIlsQuote, PortfolioSession
from ui.ui_state import PlanningState, WizardState


class _FxFetchWorker(QObject):
    """Background BOI fetch worker run inside a dedicated ``QThread``."""

    finished = Signal(object, object, int)  # (UsdIlsRateQuote | None, error_text | None, generation)

    def __init__(self, *, timeout_seconds: float = 10.0, generation: int) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds
        self._generation = generation

    @Slot()
    def run(self) -> None:
        try:
            quote = fetch_latest_usd_ils_rate(timeout_seconds=self._timeout_seconds)
            self.finished.emit(quote, None, self._generation)
        except Exception as exc:
            self.finished.emit(None, str(exc), self._generation)


class WizardFxHost(Protocol):
    """Host contract required by ``WizardFxCoordinator``.

    The host is expected to provide wizard/session state plus small callback
    seams that are already part of ``MainWindowWizardMixin``.
    """

    session: PortfolioSession
    planning_state: PlanningState
    wizard_state: WizardState
    screen_wizard: Any
    manual_rate_edit: Any

    def _wizard_has_usd_steps(self) -> bool: ...
    def _cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = 1000) -> bool: ...
    def _on_fx_fetch_finished(self, quote_obj: object, error_obj: object, generation: int) -> None: ...


class WizardFxCoordinator:
    """Owns FX fetch/cache/render mechanics for wizard USD steps.

    This class is intentionally stateful because it manages a live Qt worker
    thread. `MainWindowWizardMixin` keeps thin wrapper methods so existing call
    sites and tests remain stable.
    """

    def __init__(self, host: WizardFxHost, *, show_error_fn: Callable[[QWidget, str, str], None]) -> None:
        self._host = host
        self._show_error = show_error_fn
        self._fx_fetch_thread: QThread | None = None
        self._fx_fetch_worker: _FxFetchWorker | None = None

    def prepare_wizard_fx_rate_cache(self) -> None:
        """No-op: FX is fetched during welcome wait and reused from session cache."""
        self.render_fx_panel_for_current_step()

    def on_fx_fetch_finished(self, quote_obj: object, error_obj: object, generation: int) -> None:
        """Handle legacy async BOI completion callbacks for compatibility."""
        state = self._host.wizard_state
        if generation != state.usd_ils_active_fetch_generation:
            if self._fx_fetch_thread is not None and not self._fx_fetch_thread.isRunning():
                self._fx_fetch_worker = None
                self._fx_fetch_thread = None
            return

        state.usd_ils_fetch_in_progress = False
        state.usd_ils_active_fetch_generation = None
        self._fx_fetch_worker = None
        self._fx_fetch_thread = None

        quote = quote_obj if isinstance(quote_obj, UsdIlsRateQuote) else None
        error_text = str(error_obj) if isinstance(error_obj, str) else ""

        if quote is not None and not error_text:
            state.usd_ils_rate = quote.rate
            state.usd_ils_rate_date = quote.effective_date
            state.usd_ils_used_last_published = quote.used_last_published
            state.usd_ils_fetch_error = None
            state.usd_ils_rate_from_cache = False
            state.usd_ils_rate_cached_at = None
            try:
                self._host.session.write_cached_usd_ils_quote(
                    rate=quote.rate,
                    effective_date=quote.effective_date,
                    used_last_published=quote.used_last_published,
                )
            except Exception:
                pass
            self.render_fx_panel_for_current_step()
            return

        state.usd_ils_fetch_error = error_text or "Unknown fetch failure"
        state.usd_ils_rate = None
        state.usd_ils_rate_date = None
        state.usd_ils_used_last_published = False
        state.usd_ils_rate_from_cache = False
        state.usd_ils_rate_cached_at = None

        cached = self._host.session.read_cached_usd_ils_quote()
        if isinstance(cached, CachedUsdIlsQuote):
            state.usd_ils_rate = cached.rate
            state.usd_ils_rate_date = cached.effective_date
            state.usd_ils_used_last_published = cached.used_last_published
            state.usd_ils_rate_from_cache = True
            state.usd_ils_rate_cached_at = cached.cached_at

        if not state.usd_ils_failure_dialog_shown:
            state.usd_ils_failure_dialog_shown = True
            if state.usd_ils_rate_from_cache:
                self._show_error(
                    cast(QWidget, self._host),
                    "Official USD/ILS fetch failed",
                    "Could not fetch official USD/ILS rate within 10 seconds.\n"
                    f"Using cached USD/ILS rate: {state.usd_ils_rate} "
                    f"(cached at: {state.usd_ils_rate_cached_at}).",
                )
            else:
                self._show_error(
                    cast(QWidget, self._host),
                    "Official USD/ILS fetch failed",
                    "Could not fetch official USD/ILS rate within 10 seconds.\n"
                    "No readable cached rate is available. Enter manual USD/ILS rate to continue.",
                )

        self.render_fx_panel_for_current_step()

    def reset_wizard_fx_state_for_new_run(self) -> bool:
        """Reset transient USD/ILS state and clear manual FX input for a new run.

        Returns ``False`` if an in-flight fetch thread cannot be cancelled
        within the wait window.
        """
        if not self._host._cancel_wizard_fx_fetch():
            return False
        state = self._host.wizard_state
        cached = self._read_session_cached_quote()
        if cached is not None:
            state.usd_ils_rate = cached.rate
            state.usd_ils_rate_date = cached.effective_date
            state.usd_ils_used_last_published = cached.used_last_published
            state.usd_ils_rate_from_cache = True
            state.usd_ils_rate_cached_at = cached.cached_at
        else:
            state.usd_ils_rate = None
            state.usd_ils_rate_date = None
            state.usd_ils_used_last_published = False
            state.usd_ils_rate_from_cache = False
            state.usd_ils_rate_cached_at = None
        state.usd_ils_fetch_attempted = True
        state.usd_ils_fetch_error = None
        state.manual_override_usd_ils_rate = None
        state.usd_ils_fetch_in_progress = False
        state.usd_ils_failure_dialog_shown = False
        state.usd_ils_active_fetch_generation = None
        if hasattr(self._host, "manual_rate_edit"):
            self._host.manual_rate_edit.setText("")
        return True

    def cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = 1000) -> bool:
        """Stop and detach the in-flight FX fetch thread, if any.

        Returns ``True`` when no thread remains running after cancellation.
        """
        thread = self._fx_fetch_thread
        worker = self._fx_fetch_worker
        if thread is not None and thread.isRunning():
            thread.quit()
            if not thread.wait(wait_timeout_ms):
                return False
        if worker is not None:
            worker.deleteLater()
        self._fx_fetch_worker = None
        self._fx_fetch_thread = None
        return True

    def render_fx_panel_for_current_step(self) -> None:
        """Render FX quote/fallback/override status for the active step.

        For non-USD steps, FX UI rows are hidden and calculate is enabled.
        For USD steps, this method is the single source of truth for loading,
        rate/fallback disclosure, and manual override visibility.
        """
        if not hasattr(self._host, "screen_wizard"):
            return

        state = self._host.wizard_state
        s = self._host.planning_state.plan_steps[self._host.planning_state.step_index]
        if s.exchange.currency != Currency.USD:
            self._host.screen_wizard.calculate_btn.setEnabled(True)
            self._host.screen_wizard.set_fx_panel(
                visible=False,
                info_text="",
                error_text="",
                manual_visible=False,
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

        self._host.screen_wizard.calculate_btn.setEnabled(state.usd_ils_rate is not None)
        self._host.screen_wizard.set_fx_panel(
            visible=True,
            info_text="\n".join(info_lines),
            error_text=error_text,
            manual_visible=False,
            manual_value="",
        )

    def _read_session_cached_quote(self) -> CachedUsdIlsQuote | None:
        """Read session-memory USD/ILS cache, falling back to persisted cache."""
        read_session = getattr(self._host.session, "get_session_cached_usd_ils_quote", None)
        if callable(read_session):
            cached = read_session()
            if isinstance(cached, CachedUsdIlsQuote):
                return cached
        read_disk = getattr(self._host.session, "read_cached_usd_ils_quote", None)
        if callable(read_disk):
            cached = read_disk()
            if isinstance(cached, CachedUsdIlsQuote):
                return cached
        return None
