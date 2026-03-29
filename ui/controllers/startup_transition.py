from __future__ import annotations

"""Startup welcome-transition state machine and worker lifecycle helpers."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Final

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from portfolio_core.domain.models import Portfolio
from portfolio_core.fx_service import UsdIlsRateQuote, fetch_latest_usd_ils_rate
from portfolio_core.session.portfolio_session import CachedUsdIlsQuote
from portfolio_core.use_cases import StartupPortfolioPriceRefreshError, refresh_portfolio_prices_for_startup
from ui.shared.constants import DEFAULT_CLEANUP_WAIT_MS, STARTUP_FX_FETCH_TIMEOUT_SECONDS

_STARTUP_TRANSITION_MIN_DELAY_MS: Final[int] = 1000
_STARTUP_DEBUG_LOG_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "startup_debug.log"


def append_startup_debug_log(message: str) -> None:
    """Best-effort startup trace logging for crash investigation."""
    timestamp = datetime.now().isoformat(timespec="milliseconds")
    try:
        _STARTUP_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STARTUP_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except Exception:
        return


class StartupFxFetchWorker(QObject):
    """Background startup market-data worker for welcome->main transition."""

    finished = Signal(object, object, object)  # (UsdIlsRateQuote | None, Portfolio | None, error_text | None)

    def __init__(
        self,
        *,
        portfolio: Portfolio | None,
        cached_quote: CachedUsdIlsQuote | None,
        timeout_seconds: float = STARTUP_FX_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self._portfolio = portfolio
        self._cached_quote = cached_quote
        self._timeout_seconds = timeout_seconds

    @Slot()
    def run(self) -> None:
        append_startup_debug_log(
            "worker.run start "
            f"portfolio_present={self._portfolio is not None} "
            f"cached_quote_present={self._cached_quote is not None} "
            f"timeout_seconds={self._timeout_seconds}"
        )
        try:
            if self._portfolio is None:
                raise StartupPortfolioPriceRefreshError("No portfolio loaded for startup price refresh.")
            quote = None
            if self._cached_quote is None:
                append_startup_debug_log("worker.run fetching usd-ils quote")
                quote = fetch_latest_usd_ils_rate(timeout_seconds=self._timeout_seconds)
                usd_ils_rate = quote.rate
                append_startup_debug_log(
                    "worker.run fetched usd-ils quote "
                    f"rate={quote.rate} effective_date={quote.effective_date.isoformat()} "
                    f"used_last_published={quote.used_last_published}"
                )
            else:
                usd_ils_rate = self._cached_quote.rate
                append_startup_debug_log(f"worker.run using cached usd-ils rate={usd_ils_rate}")
            refreshed_portfolio = refresh_portfolio_prices_for_startup(
                self._portfolio,
                usd_ils_rate=usd_ils_rate,
                lookup_timeout_seconds=self._timeout_seconds,
            )
            append_startup_debug_log(
                "worker.run refresh complete "
                f"instrument_count={len(refreshed_portfolio.instruments)}"
            )
            self.finished.emit(quote, refreshed_portfolio, None)
        except StartupPortfolioPriceRefreshError as exc:
            append_startup_debug_log(f"worker.run startup refresh error={exc!r}")
            self.finished.emit(None, None, str(exc))
        except Exception as exc:
            append_startup_debug_log(f"worker.run unexpected error={exc!r}")
            self.finished.emit(None, None, str(exc))


class StartupFxFetchResultRelay(QObject):
    """GUI-thread relay for startup fetch completion results."""

    def __init__(self, *, on_finished: Callable[[object, object, object], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._on_finished = on_finished

    @Slot(object, object, object)
    def dispatch(self, quote_obj: object, portfolio_obj: object, error_obj: object) -> None:
        """Forward worker results from the GUI thread to the controller callback."""
        append_startup_debug_log("result_relay.dispatch on gui thread")
        self._on_finished(quote_obj, portfolio_obj, error_obj)


@dataclass
class StartupFxFetchLifecycle:
    """Mutable holder for startup FX worker/thread ownership."""

    thread: QThread | None = None
    worker: StartupFxFetchWorker | None = None
    result_relay: StartupFxFetchResultRelay | None = None

    def start(
        self,
        *,
        parent: QWidget,
        portfolio: Portfolio | None,
        cached_quote: CachedUsdIlsQuote | None,
        on_finished: Callable[[object, object, object], None],
        timeout_seconds: float = STARTUP_FX_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        """Create, wire, and start the startup FX fetch worker thread."""
        append_startup_debug_log(
            "lifecycle.start "
            f"portfolio_present={portfolio is not None} "
            f"cached_quote_present={cached_quote is not None} "
            f"timeout_seconds={timeout_seconds}"
        )
        thread = QThread(parent)
        worker = StartupFxFetchWorker(
            portfolio=portfolio,
            cached_quote=cached_quote,
            timeout_seconds=timeout_seconds,
        )
        result_relay = StartupFxFetchResultRelay(on_finished=on_finished, parent=parent)
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
        """Stop and detach in-flight worker/thread, if any."""
        append_startup_debug_log(
            "lifecycle.cancel "
            f"thread_present={self.thread is not None} "
            f"thread_running={self.thread.isRunning() if self.thread is not None else False} "
            f"wait_timeout_ms={wait_timeout_ms}"
        )
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            if not self.thread.wait(wait_timeout_ms):
                append_startup_debug_log("lifecycle.cancel wait timed out")
                return False
        if self.worker is not None:
            try:
                self.worker.deleteLater()
            except RuntimeError:
                append_startup_debug_log("lifecycle.cancel worker already deleted")
        self.clear()
        return True

    def clear(self) -> None:
        append_startup_debug_log(
            "lifecycle.clear "
            f"thread_present={self.thread is not None} "
            f"worker_present={self.worker is not None} "
            f"result_relay_present={self.result_relay is not None}"
        )
        self.thread = None
        self.worker = None
        self.result_relay = None


@dataclass
class StartupTransitionState:
    """Gate state for welcome->main transition completion conditions."""

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
    """Resolved startup transition outcome once both gating conditions complete."""

    error_message: str | None


class StartupTransitionCoordinator:
    """Own startup transition timing, fetch lifecycle, and state resolution."""

    def __init__(self, parent: QWidget) -> None:
        self.timer = QTimer(parent)
        self.timer.setSingleShot(True)
        self.state = StartupTransitionState()
        self._fx_fetch = StartupFxFetchLifecycle()

    def schedule_min_delay(self) -> None:
        """Start the minimum-delay timer for the welcome loading overlay."""
        self.timer.start(_STARTUP_TRANSITION_MIN_DELAY_MS)

    def reset(self, *, pending: bool) -> None:
        """Reset startup-transition gate flags to a known baseline state."""
        append_startup_debug_log(f"reset_startup_transition_state pending={pending}")
        self.state.reset(pending=pending)

    def start_fetch(
        self,
        *,
        parent: QWidget,
        portfolio: Portfolio | None,
        cached_quote: CachedUsdIlsQuote | None,
        on_finished: Callable[[object, object, object], None],
        pending_file_path: Path | None,
        timeout_seconds: float = STARTUP_FX_FETCH_TIMEOUT_SECONDS,
    ) -> bool:
        """Start startup market-data fetch if prior worker cleanup is complete."""
        append_startup_debug_log(
            "start_startup_fx_fetch "
            f"pending_present={portfolio is not None} "
            f"pending_file_path={pending_file_path} "
            f"instrument_count={len(portfolio.instruments) if portfolio is not None else 0} "
            f"cached_quote_present={cached_quote is not None}"
        )
        self._fx_fetch.start(
            parent=parent,
            portfolio=portfolio,
            cached_quote=cached_quote,
            on_finished=on_finished,
            timeout_seconds=timeout_seconds,
        )
        return True

    def ensure_cleanup_ready_for_restart(self) -> bool:
        """Ensure startup fetch cleanup completed before creating a new worker."""
        append_startup_debug_log("ensure_startup_cleanup_ready_for_restart")
        return self.cancel_fetch()

    def on_min_delay_elapsed(self) -> StartupTransitionDecision | None:
        """Mark the min-delay timer complete and resolve outcome when ready."""
        append_startup_debug_log("complete_startup_transition timer elapsed")
        self.state.min_delay_elapsed = True
        return self._try_finalize()

    def record_fetch_outcome(self, *, error_message: str | None) -> StartupTransitionDecision | None:
        """Store fetch completion state and resolve outcome when ready."""
        self.state.fx_fetch_error = error_message
        self.state.fx_fetch_completed = True
        return self._try_finalize()

    def cancel_fetch(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Stop and detach in-flight startup FX fetch worker, if any."""
        return self._fx_fetch.cancel(wait_timeout_ms=wait_timeout_ms)

    def cancel_pending_transition(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Cancel startup transition and return whether FX worker cleanup completed."""
        append_startup_debug_log(f"cancel_pending_startup_transition wait_timeout_ms={wait_timeout_ms}")
        if self.timer.isActive():
            self.timer.stop()
        self.reset(pending=False)
        return self.cancel_fetch(wait_timeout_ms=wait_timeout_ms)

    def _try_finalize(self) -> StartupTransitionDecision | None:
        """Resolve final transition outcome once timer and fetch have both completed."""
        state = self.state
        append_startup_debug_log(
            "try_finalize_startup_transition "
            f"pending={state.pending} "
            f"min_delay_elapsed={state.min_delay_elapsed} "
            f"fx_fetch_completed={state.fx_fetch_completed} "
            f"fx_fetch_error={state.fx_fetch_error!r}"
        )
        if not state.pending:
            return None
        if not state.min_delay_elapsed or not state.fx_fetch_completed:
            return None
        state.pending = False
        return StartupTransitionDecision(error_message=state.fx_fetch_error)
