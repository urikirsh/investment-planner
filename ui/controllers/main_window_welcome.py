from __future__ import annotations

"""Welcome-screen behavior for the composed main window controller."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Final, cast

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from portfolio_core.app_metadata import get_app_version
from portfolio_core.domain.models import Portfolio
from portfolio_core.fx_service import UsdIlsRateQuote, fetch_latest_usd_ils_rate
from portfolio_core.io_json import load_portfolio_file
from portfolio_core.session.portfolio_session import CachedUsdIlsQuote
from portfolio_core.use_cases import StartupPortfolioPriceRefreshError, refresh_portfolio_prices_for_startup
from ui.controllers.protocols import MainWindowWelcomeHost
from ui.dialogs import show_cleanup_in_progress, show_error_with_back
from ui.shared.constants import DEFAULT_CLEANUP_WAIT_MS, STARTUP_FX_FETCH_TIMEOUT_SECONDS
from ui.screens.welcome_screen import WelcomeScreen

_DEFAULT_PATH_MAX_CHARS: Final[int] = 96
_STARTUP_TRANSITION_MIN_DELAY_MS: Final[int] = 1000
_STARTUP_DEBUG_LOG_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "startup_debug.log"


def _append_startup_debug_log(message: str) -> None:
    """Best-effort startup trace logging for crash investigation."""
    timestamp = datetime.now().isoformat(timespec="milliseconds")
    try:
        _STARTUP_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STARTUP_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except Exception:
        return


class _StartupFxFetchWorker(QObject):
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
        _append_startup_debug_log(
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
                _append_startup_debug_log("worker.run fetching usd-ils quote")
                quote = fetch_latest_usd_ils_rate(timeout_seconds=self._timeout_seconds)
                usd_ils_rate = quote.rate
                _append_startup_debug_log(
                    "worker.run fetched usd-ils quote "
                    f"rate={quote.rate} effective_date={quote.effective_date.isoformat()} "
                    f"used_last_published={quote.used_last_published}"
                )
            else:
                usd_ils_rate = self._cached_quote.rate
                _append_startup_debug_log(f"worker.run using cached usd-ils rate={usd_ils_rate}")
            refreshed_portfolio = refresh_portfolio_prices_for_startup(
                self._portfolio,
                usd_ils_rate=usd_ils_rate,
                lookup_timeout_seconds=self._timeout_seconds,
            )
            _append_startup_debug_log(
                "worker.run refresh complete "
                f"instrument_count={len(refreshed_portfolio.instruments)}"
            )
            self.finished.emit(quote, refreshed_portfolio, None)
        except StartupPortfolioPriceRefreshError as exc:
            _append_startup_debug_log(f"worker.run startup refresh error={exc!r}")
            self.finished.emit(None, None, str(exc))
        except Exception as exc:
            _append_startup_debug_log(f"worker.run unexpected error={exc!r}")
            self.finished.emit(None, None, str(exc))


class _StartupFxFetchResultRelay(QObject):
    """GUI-thread relay for startup fetch completion results."""

    def __init__(self, *, on_finished: Callable[[object, object, object], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._on_finished = on_finished

    @Slot(object, object, object)
    def dispatch(self, quote_obj: object, portfolio_obj: object, error_obj: object) -> None:
        """Forward worker results from the GUI thread to the controller callback."""
        _append_startup_debug_log("result_relay.dispatch on gui thread")
        self._on_finished(quote_obj, portfolio_obj, error_obj)


@dataclass(frozen=True)
class WelcomeLastPortfolioStatus:
    """Render-ready welcome-state for remembered portfolio action."""

    button_enabled: bool
    path_text: str
    path_tooltip: str
    missing_path: bool


@dataclass
class _StartupFxFetchLifecycle:
    """Mutable holder for startup FX worker/thread ownership."""

    thread: QThread | None = None
    worker: _StartupFxFetchWorker | None = None
    result_relay: _StartupFxFetchResultRelay | None = None

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
        _append_startup_debug_log(
            "lifecycle.start "
            f"portfolio_present={portfolio is not None} "
            f"cached_quote_present={cached_quote is not None} "
            f"timeout_seconds={timeout_seconds}"
        )
        thread = QThread(parent)
        worker = _StartupFxFetchWorker(
            portfolio=portfolio,
            cached_quote=cached_quote,
            timeout_seconds=timeout_seconds,
        )
        result_relay = _StartupFxFetchResultRelay(on_finished=on_finished, parent=parent)
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
        _append_startup_debug_log(
            "lifecycle.cancel "
            f"thread_present={self.thread is not None} "
            f"thread_running={self.thread.isRunning() if self.thread is not None else False} "
            f"wait_timeout_ms={wait_timeout_ms}"
        )
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            if not self.thread.wait(wait_timeout_ms):
                _append_startup_debug_log("lifecycle.cancel wait timed out")
                return False
        if self.worker is not None:
            self.worker.deleteLater()
        self.clear()
        return True

    def clear(self) -> None:
        _append_startup_debug_log(
            "lifecycle.clear "
            f"thread_present={self.thread is not None} "
            f"worker_present={self.worker is not None} "
            f"result_relay_present={self.result_relay is not None}"
        )
        self.thread = None
        self.worker = None
        self.result_relay = None


@dataclass
class _StartupTransitionState:
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


@dataclass
class _PendingStartupPortfolio:
    """Staged portfolio context prepared before startup fetch succeeds."""

    portfolio: Portfolio
    file_path: Path | None


class MainWindowWelcomeController:
    """Controller for welcome-screen setup and startup action flow."""

    def __init__(self, host: MainWindowWelcomeHost) -> None:
        self._host = host
        self._startup_transition_timer = QTimer(self._host_widget())
        self._startup_transition_timer.setSingleShot(True)
        self._startup_transition_timer.timeout.connect(self._complete_startup_transition_to_main)
        self._startup_fx_fetch = _StartupFxFetchLifecycle()
        self._startup_transition = _StartupTransitionState()
        self._pending_startup_portfolio: _PendingStartupPortfolio | None = None
        self._last_prepare_error_message: str | None = None

    def _host_widget(self) -> QWidget:
        """Return host cast to QWidget for screen/dialog parenting."""
        return cast(QWidget, self._host)

    def init_screen(self) -> None:
        """Build startup welcome screen and connect startup actions."""
        host = self._host
        host.screen_welcome = WelcomeScreen(app_version=get_app_version(), parent=self._host_widget())
        host.screen_welcome.open_last_btn.clicked.connect(self.on_open_last_clicked)
        host.screen_welcome.load_different_btn.clicked.connect(self.on_load_different_clicked)
        host.screen_welcome.start_new_btn.clicked.connect(self.on_start_new_clicked)
        host.screen_welcome.quit_btn.clicked.connect(host._quit_app)

    def show_on_startup(self) -> None:
        """Show startup welcome screen and refresh remembered-file state."""
        host = self._host
        host.setWindowTitle(host._base_window_title)
        self.refresh_last_portfolio_ui()
        host.stack.setCurrentWidget(host.screen_welcome)
        if host.screen_welcome.open_last_btn.isEnabled():
            host.screen_welcome.open_last_btn.setFocus()
        else:
            host.screen_welcome.load_different_btn.setFocus()

    def enter_main_screen(self) -> None:
        """Switch from startup screen to main editor with current file context."""
        host = self._host
        host._update_file_context_ui()
        host.stack.setCurrentWidget(host.screen_main)

    @staticmethod
    def truncate_middle(text: str, *, max_chars: int = _DEFAULT_PATH_MAX_CHARS) -> str:
        """Return middle-truncated text for constrained path labels."""
        if len(text) <= max_chars:
            return text
        part = max((max_chars - 3) // 2, 1)
        return f"{text[:part]}...{text[-part:]}"

    def refresh_last_portfolio_ui(self) -> None:
        """Refresh last-portfolio button state and path text on welcome screen."""
        host = self._host
        remembered_path = host.session.get_remembered_portfolio_path()
        status = self.build_last_portfolio_status(remembered_path)
        host.screen_welcome.set_last_portfolio_status(
            button_enabled=status.button_enabled,
            path_text=status.path_text,
            path_tooltip=status.path_tooltip,
            missing_path=status.missing_path,
        )

    def build_last_portfolio_status(self, remembered_path: Path | None) -> WelcomeLastPortfolioStatus:
        """Build pure welcome-screen status payload from remembered path state."""
        if remembered_path is None:
            return WelcomeLastPortfolioStatus(
                button_enabled=False,
                path_text="No recent portfolio",
                path_tooltip="",
                missing_path=False,
            )

        full_path = str(remembered_path)
        display_path = self.truncate_middle(full_path)
        path_exists = remembered_path.exists()
        path_text = f"Last portfolio: {display_path}" if path_exists else f"Last portfolio: {display_path} (Not found)"

        return WelcomeLastPortfolioStatus(
            button_enabled=path_exists,
            path_text=path_text,
            path_tooltip=full_path,
            missing_path=not path_exists,
        )

    def on_open_last_clicked(self) -> None:
        """Open remembered portfolio when available and enter main screen."""
        remembered_path = self._host.session.get_remembered_portfolio_path()
        if remembered_path is None or not remembered_path.exists():
            self.refresh_last_portfolio_ui()
            return
        self.run_action(
            action=lambda: self._prepare_portfolio_from_path(remembered_path),
            on_failure=self.refresh_last_portfolio_ui,
        )

    def on_load_different_clicked(self) -> None:
        """Open picker flow from welcome screen and enter main on success."""
        self.run_action(action=self._prepare_portfolio_from_picker)

    def on_start_new_clicked(self) -> None:
        """Initialize default portfolio from welcome and enter main editor."""
        self.run_action(action=self.start_default_document)

    def start_default_document(self) -> bool:
        """Create default document for startup flow and report success."""
        self._prepare_default_document()
        return True

    def _prepare_portfolio_from_path(self, path: Path) -> bool:
        """Stage a portfolio from disk without committing it to the live editor yet."""
        _append_startup_debug_log(f"prepare_portfolio_from_path start path={path}")
        self._last_prepare_error_message = None
        try:
            portfolio = load_portfolio_file(path)
        except Exception as exc:
            self._last_prepare_error_message = str(exc) or repr(exc)
            _append_startup_debug_log(f"prepare_portfolio_from_path failed path={path} error={exc!r}")
            return False
        _append_startup_debug_log(
            "prepare_portfolio_from_path success "
            f"path={path} instrument_count={len(portfolio.instruments)}"
        )
        self._pending_startup_portfolio = _PendingStartupPortfolio(portfolio=portfolio, file_path=path)
        return True

    def _prepare_portfolio_from_picker(self) -> bool:
        """Prompt for a portfolio path, then stage it for startup transition."""
        path = self._host._prompt_select_open_path()
        _append_startup_debug_log(f"prepare_portfolio_from_picker selected path={path}")
        if path is None:
            self._last_prepare_error_message = None
            return False
        return self._prepare_portfolio_from_path(path)

    def _prepare_default_document(self) -> None:
        """Stage a new default portfolio without committing it to the live editor yet."""
        portfolio = self._host._build_default_portfolio_for_startup()
        _append_startup_debug_log(
            "prepare_default_document "
            f"instrument_count={len(portfolio.instruments)}"
        )
        self._pending_startup_portfolio = _PendingStartupPortfolio(portfolio=portfolio, file_path=None)

    def run_action(
        self,
        *,
        action: Callable[[], bool],
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        """Run startup action; enter main editor on success."""
        if not action():
            self._show_prepare_error_if_any()
            if on_failure is not None:
                on_failure()
            return
        self._begin_startup_transition_to_main()

    def _show_prepare_error_if_any(self) -> None:
        """Show blocking modal for the most recent prepare/load failure, if any."""
        error_message = self._last_prepare_error_message
        self._last_prepare_error_message = None
        if not error_message:
            return
        show_error_with_back(
            self._host_widget(),
            "Load failed",
            error_message,
        )

    def _begin_startup_transition_to_main(self) -> None:
        """Show loading overlay and enter main only after delay + startup fetch."""
        pending = self._pending_startup_portfolio
        _append_startup_debug_log(
            "begin_startup_transition "
            f"pending_present={pending is not None} "
            f"pending_file_path={pending.file_path if pending is not None else None}"
        )
        self._reset_startup_transition_state(pending=True)
        self._host._show_startup_loading_overlay()
        self._schedule_main_screen_transition()
        self._start_startup_fx_fetch()

    def _complete_startup_transition_to_main(self) -> None:
        """Mark the min-delay timer complete and try finalizing transition."""
        _append_startup_debug_log("complete_startup_transition timer elapsed")
        self._startup_transition.min_delay_elapsed = True
        self._try_finalize_startup_transition()

    def _schedule_main_screen_transition(self) -> None:
        """Schedule minimum-delay transition with a cancelable timer."""
        self._startup_transition_timer.start(_STARTUP_TRANSITION_MIN_DELAY_MS)

    def _start_startup_fx_fetch(self) -> None:
        """Start startup market-data fetch for FX and portfolio prices."""
        pending = self._pending_startup_portfolio
        _append_startup_debug_log(
            "start_startup_fx_fetch "
            f"pending_present={pending is not None} "
            f"pending_file_path={pending.file_path if pending is not None else None} "
            f"instrument_count={len(pending.portfolio.instruments) if pending is not None else 0} "
            f"cached_quote_present={self._host.session.cached_usd_ils_quote is not None}"
        )
        if not self._ensure_startup_cleanup_ready_for_restart():
            return
        self._startup_fx_fetch.start(
            parent=self._host_widget(),
            portfolio=self._pending_portfolio(),
            cached_quote=self._host.session.cached_usd_ils_quote,
            on_finished=self._on_startup_fx_fetch_finished,
            timeout_seconds=STARTUP_FX_FETCH_TIMEOUT_SECONDS,
        )

    def _pending_portfolio(self) -> Portfolio | None:
        """Return the staged portfolio prepared for the current startup action."""
        pending = self._pending_startup_portfolio
        if pending is None:
            return None
        return pending.portfolio

    def _ensure_startup_cleanup_ready_for_restart(self) -> bool:
        """Ensure startup fetch cleanup completed before creating a new worker."""
        _append_startup_debug_log("ensure_startup_cleanup_ready_for_restart")
        if self._cancel_startup_fx_fetch():
            return True
        self._abort_startup_transition_cleanup_in_progress()
        return False

    @Slot(object, object, object)
    def _on_startup_fx_fetch_finished(self, quote_obj: object, portfolio_obj: object, error_obj: object) -> None:
        """Store startup fetch result and finalize transition when ready."""
        quote = quote_obj if isinstance(quote_obj, UsdIlsRateQuote) else None
        refreshed_portfolio = portfolio_obj if isinstance(portfolio_obj, Portfolio) else None
        error_text = str(error_obj) if isinstance(error_obj, str) else ""
        _append_startup_debug_log(
            "on_startup_fx_fetch_finished "
            f"quote_present={quote is not None} "
            f"portfolio_present={refreshed_portfolio is not None} "
            f"error_text={error_text!r}"
        )

        if not error_text and refreshed_portfolio is not None:
            cached_quote = self._host.session.cached_usd_ils_quote
            if quote is not None:
                _append_startup_debug_log("on_startup_fx_fetch_finished caching fetched quote")
                self._host.session.cache_usd_ils_quote(
                    rate=quote.rate,
                    effective_date=quote.effective_date,
                    used_last_published=quote.used_last_published,
                )
            elif cached_quote is None:
                _append_startup_debug_log("on_startup_fx_fetch_finished missing quote and no cache")
                self._startup_transition.fx_fetch_error = "Failed to fetch USD to ILS exchange rate."
                self._startup_transition.fx_fetch_completed = True
                self._try_finalize_startup_transition()
                return
            self._commit_pending_startup_portfolio(refreshed_portfolio)
            self._startup_transition.fx_fetch_error = None
        else:
            self._startup_transition.fx_fetch_error = self._build_startup_fetch_error_message(error_text)
            self._pending_startup_portfolio = None
            _append_startup_debug_log(
                f"on_startup_fx_fetch_finished stored error={self._startup_transition.fx_fetch_error!r}"
            )

        self._startup_transition.fx_fetch_completed = True
        self._try_finalize_startup_transition()

    def _commit_pending_startup_portfolio(self, refreshed_portfolio: Portfolio) -> None:
        """Commit staged startup portfolio into session and main-editor UI."""
        pending = self._pending_startup_portfolio
        if pending is None:
            _append_startup_debug_log("commit_pending_startup_portfolio missing pending portfolio")
            raise RuntimeError("No pending startup portfolio to commit.")
        _append_startup_debug_log(
            "commit_pending_startup_portfolio "
            f"file_path={pending.file_path} "
            f"instrument_count={len(refreshed_portfolio.instruments)}"
        )
        if pending.file_path is None:
            self._host.session.mark_new_document(refreshed_portfolio)
        else:
            self._host.session.document.mark_loaded(refreshed_portfolio, pending.file_path)
            self._host.session.set_active_file_path(pending.file_path)
        self._host._render_main_editor_from_portfolio(refreshed_portfolio, switch_to_main=False)
        self._pending_startup_portfolio = None

    @staticmethod
    def _build_startup_fetch_error_message(error_text: str) -> str:
        """Return a user-facing startup failure message."""
        if error_text:
            return error_text
        return "Failed to fetch USD to ILS exchange rate."

    def _try_finalize_startup_transition(self) -> None:
        """Finalize welcome transition after both min-delay and startup fetch complete."""
        state = self._startup_transition
        _append_startup_debug_log(
            "try_finalize_startup_transition "
            f"pending={state.pending} "
            f"min_delay_elapsed={state.min_delay_elapsed} "
            f"fx_fetch_completed={state.fx_fetch_completed} "
            f"fx_fetch_error={state.fx_fetch_error!r}"
        )
        if not state.pending:
            return
        if not state.min_delay_elapsed or not state.fx_fetch_completed:
            return

        state.pending = False
        self._host._hide_startup_loading_overlay()
        if state.fx_fetch_error:
            _append_startup_debug_log("try_finalize_startup_transition showing error and staying on welcome")
            self._host.stack.setCurrentWidget(self._host.screen_welcome)
            show_error_with_back(
                self._host_widget(),
                "Startup data fetch failed",
                state.fx_fetch_error,
            )
            self.refresh_last_portfolio_ui()
            return
        _append_startup_debug_log("try_finalize_startup_transition entering main screen")
        self.enter_main_screen()

    def _cancel_startup_fx_fetch(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Stop and detach in-flight startup FX fetch worker, if any."""
        return self._startup_fx_fetch.cancel(wait_timeout_ms=wait_timeout_ms)

    def _abort_startup_transition_cleanup_in_progress(self) -> None:
        """Abort transition when prior startup FX cleanup could not finish."""
        _append_startup_debug_log("abort_startup_transition_cleanup_in_progress")
        if self._startup_transition_timer.isActive():
            self._startup_transition_timer.stop()
        self._reset_startup_transition_state(pending=False)
        self._host.stack.setCurrentWidget(self._host.screen_welcome)
        self._host._hide_startup_loading_overlay()
        show_cleanup_in_progress(self._host_widget(), action_verb="starting")
        self._pending_startup_portfolio = None
        self.refresh_last_portfolio_ui()

    def cancel_pending_startup_transition(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Cancel startup transition and return whether FX worker cleanup completed."""
        _append_startup_debug_log(f"cancel_pending_startup_transition wait_timeout_ms={wait_timeout_ms}")
        if self._startup_transition_timer.isActive():
            self._startup_transition_timer.stop()
        self._reset_startup_transition_state(pending=False)
        stopped = self._cancel_startup_fx_fetch(wait_timeout_ms=wait_timeout_ms)
        self._pending_startup_portfolio = None
        self._host._hide_startup_loading_overlay()
        return stopped

    def _reset_startup_transition_state(self, *, pending: bool) -> None:
        """Reset startup-transition gate flags to a known baseline state."""
        _append_startup_debug_log(f"reset_startup_transition_state pending={pending}")
        self._startup_transition.reset(pending=pending)
