from __future__ import annotations

"""Startup welcome-transition state machine and worker lifecycle helpers."""

from dataclasses import dataclass
from typing import Callable, Final

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from portfolio_core.constants import DEFAULT_MARKET_DATA_TIMEOUT_SECONDS
from portfolio_core.domain.models import Portfolio
from portfolio_core.fx_service import UsdIlsRateQuote, fetch_latest_usd_ils_rate
from portfolio_core.session.portfolio_session import CachedUsdIlsQuote
from portfolio_core.workflows import (
    StartupPortfolioPriceRefreshError,
    portfolio_requires_usd_ils_rate,
    refresh_portfolio_prices_for_startup,
)
from ui.shared.constants import DEFAULT_CLEANUP_WAIT_MS

_STARTUP_TRANSITION_MIN_DELAY_MS: Final[int] = 1000


class StartupMarketDataWorker(QObject):
    """Background startup market-data worker for welcome->main transition.

    The worker fetches a USD/ILS quote only when the staged portfolio contains
    a USD-priced instrument and no session-cached quote exists, refreshes all
    instrument values for the staged portfolio, and emits exactly one
    completion signal carrying either:
    - a quote plus refreshed portfolio on success, or
    - an error message on failure.

    ILS-only portfolios therefore complete successfully with ``quote=None``.
    """

    finished = Signal(object, object, object)  # (UsdIlsRateQuote | None, Portfolio | None, error_text | None)

    def __init__(
        self,
        *,
        portfolio: Portfolio | None,
        cached_quote: CachedUsdIlsQuote | None,
        timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self._portfolio = portfolio
        self._cached_quote = cached_quote
        self._timeout_seconds = timeout_seconds

    @Slot()
    def run(self) -> None:
        """Fetch startup market data and emit a normalized success/error payload.

        The emitted quote is optional because startup can refresh an ILS-only
        portfolio without consulting the FX service.
        """
        try:
            if self._portfolio is None:
                raise StartupPortfolioPriceRefreshError("No portfolio loaded for startup price refresh.")
            quote = None
            usd_ils_rate = None
            if portfolio_requires_usd_ils_rate(self._portfolio):
                if self._cached_quote is None:
                    quote = fetch_latest_usd_ils_rate(timeout_seconds=self._timeout_seconds)
                    usd_ils_rate = quote.rate
                else:
                    usd_ils_rate = self._cached_quote.rate
            refreshed_portfolio = refresh_portfolio_prices_for_startup(
                self._portfolio,
                usd_ils_rate=usd_ils_rate,
                lookup_timeout_seconds=self._timeout_seconds,
            )
            self.finished.emit(quote, refreshed_portfolio, None)
        except StartupPortfolioPriceRefreshError as exc:
            self.finished.emit(None, None, str(exc))
        except Exception as exc:
            self.finished.emit(None, None, str(exc))


class StartupMarketDataResultRelay(QObject):
    """GUI-thread relay for startup fetch completion results."""

    def __init__(self, *, on_finished: Callable[[object, object, object], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._on_finished = on_finished

    @Slot(object, object, object)
    def dispatch(self, quote_obj: object, portfolio_obj: object, error_obj: object) -> None:
        """Forward worker results from the GUI thread to the controller callback."""
        self._on_finished(quote_obj, portfolio_obj, error_obj)


@dataclass
class StartupMarketDataLifecycle:
    """Mutable holder for startup market-data worker/thread ownership.

    This wrapper centralizes thread creation, shutdown, and object detachment so
    the welcome controller and coordinator can reason about startup cleanup in
    one place.
    """

    thread: QThread | None = None
    worker: StartupMarketDataWorker | None = None
    result_relay: StartupMarketDataResultRelay | None = None

    def start(
        self,
        *,
        parent: QWidget,
        portfolio: Portfolio | None,
        cached_quote: CachedUsdIlsQuote | None,
        on_finished: Callable[[object, object, object], None],
        timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
    ) -> None:
        """Create, wire, and start the startup market-data worker thread."""
        thread = QThread(parent)
        worker = StartupMarketDataWorker(
            portfolio=portfolio,
            cached_quote=cached_quote,
            timeout_seconds=timeout_seconds,
        )
        result_relay = StartupMarketDataResultRelay(on_finished=on_finished, parent=parent)
        self.thread = thread
        self.worker = worker
        self.result_relay = result_relay
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(result_relay.dispatch)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self.clear)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def cancel(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Stop and detach in-flight worker/thread, if any.

        Returns ``False`` only when the thread does not stop within the
        requested wait timeout.
        """
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            if not self.thread.wait(wait_timeout_ms):
                return False
        if self.worker is not None:
            try:
                self.worker.deleteLater()
            except RuntimeError:
                pass
        self.clear()
        return True

    def clear(self) -> None:
        """Drop tracked thread/worker references after shutdown or completion."""
        self.thread = None
        self.worker = None
        self.result_relay = None


@dataclass
class StartupTransitionState:
    """Gate state for welcome->main transition completion conditions.

    A startup transition completes only after two independent gates finish:
    - the minimum-delay timer for the blocking overlay
    - the background startup fetch
    """

    pending: bool = False
    min_delay_elapsed: bool = False
    fx_fetch_completed: bool = False
    fx_fetch_error: str | None = None

    def reset(self, *, pending: bool) -> None:
        self.pending = pending
        self.min_delay_elapsed = False
        self.fx_fetch_completed = False
        self.fx_fetch_error = None


@dataclass(frozen=True)
class StartupTransitionDecision:
    """Resolved startup transition outcome once both gating conditions complete.

    ``error_message`` is populated when the controller should stay on the
    welcome screen and show a blocking startup failure dialog.
    """

    error_message: str | None


class StartupTransitionCoordinator:
    """Own startup transition timing, fetch lifecycle, and state resolution.

    The coordinator is intentionally UI-agnostic: it tracks gate completion and
    worker ownership, and returns a decision only when the welcome transition is
    ready to be finalized by the controller.
    """

    def __init__(self, parent: QWidget) -> None:
        self.timer = QTimer(parent)
        self.timer.setSingleShot(True)
        self.state = StartupTransitionState()
        self._market_data_fetch = StartupMarketDataLifecycle()

    def schedule_min_delay(self) -> None:
        """Start the minimum-delay timer for the welcome loading overlay."""
        self.timer.start(_STARTUP_TRANSITION_MIN_DELAY_MS)

    def reset(self, *, pending: bool) -> None:
        """Reset startup-transition gate flags to a known baseline state."""
        self.state.reset(pending=pending)

    def start_fetch(
        self,
        *,
        parent: QWidget,
        portfolio: Portfolio | None,
        cached_quote: CachedUsdIlsQuote | None,
        on_finished: Callable[[object, object, object], None],
        timeout_seconds: float = DEFAULT_MARKET_DATA_TIMEOUT_SECONDS,
    ) -> bool:
        """Start the startup market-data fetch worker for the current staged portfolio."""
        self._market_data_fetch.start(
            parent=parent,
            portfolio=portfolio,
            cached_quote=cached_quote,
            on_finished=on_finished,
            timeout_seconds=timeout_seconds,
        )
        return True

    def ensure_cleanup_ready_for_restart(self) -> bool:
        """Ensure startup fetch cleanup completed before creating a new worker."""
        return self.cancel_fetch()

    def complete_min_delay(self) -> StartupTransitionDecision | None:
        """Mark the overlay minimum-delay gate as complete and resolve if ready."""
        self.state.min_delay_elapsed = True
        return self._try_finalize()

    def complete_fetch(self, *, error_message: str | None) -> StartupTransitionDecision | None:
        """Mark the fetch gate as complete and resolve if both startup gates are done."""
        self.state.fx_fetch_error = error_message
        self.state.fx_fetch_completed = True
        return self._try_finalize()

    def cancel_fetch(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Stop and detach the in-flight startup market-data worker, if any."""
        return self._market_data_fetch.cancel(wait_timeout_ms=wait_timeout_ms)

    def cancel_pending_transition(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Cancel startup transition and return whether market-data worker cleanup completed."""
        if self.timer.isActive():
            self.timer.stop()
        self.reset(pending=False)
        return self.cancel_fetch(wait_timeout_ms=wait_timeout_ms)

    def _try_finalize(self) -> StartupTransitionDecision | None:
        """Resolve final transition outcome once timer and fetch have both completed."""
        state = self.state
        if not state.pending:
            return None
        if not state.min_delay_elapsed or not state.fx_fetch_completed:
            return None
        state.pending = False
        return StartupTransitionDecision(error_message=state.fx_fetch_error)
