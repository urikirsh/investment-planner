from __future__ import annotations

"""Welcome-screen behavior for the composed main window controller."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, cast

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget

from portfolio_core.app_metadata import get_app_version
from portfolio_core.domain.models import Portfolio
from portfolio_core.fx_service import UsdIlsRateQuote
from portfolio_core.io_json import load_portfolio_file
from ui.controllers.protocols import MainWindowWelcomeHost
from ui.controllers.startup_transition import (
    StartupTransitionCoordinator,
    StartupTransitionDecision,
)
from ui.dialogs import show_cleanup_in_progress, show_error_with_back
from ui.shared.constants import DEFAULT_CLEANUP_WAIT_MS
from ui.screens.welcome_screen import WelcomeScreen

_DEFAULT_PATH_MAX_CHARS: Final[int] = 96


@dataclass(frozen=True)
class WelcomeLastPortfolioStatus:
    """Render-ready welcome-state for remembered portfolio action."""

    button_enabled: bool
    path_text: str
    path_tooltip: str
    missing_path: bool


@dataclass
class _PendingStartupPortfolio:
    """Staged portfolio context prepared before startup fetch succeeds.

    The portfolio is kept out of the live editor until startup refresh either
    succeeds and is committed, or fails and is discarded.
    """

    portfolio: Portfolio
    file_path: Path | None


@dataclass(frozen=True)
class _StartupFetchCallbackPayload:
    """Typed startup fetch callback payload decoded from Qt signal objects.

    This keeps the slot body free from repeated ``isinstance`` checks on the
    relay's untyped ``object`` signal payloads.
    """

    quote: UsdIlsRateQuote | None
    refreshed_portfolio: Portfolio | None
    error_text: str


@dataclass(frozen=True)
class _StartupFetchResolution:
    """Resolved startup fetch outcome for transition recording/finalization.

    ``already_finalized`` is set only for the edge case where fetch completion
    itself triggers immediate finalization before the caller would otherwise ask
    the coordinator for a new decision.
    """

    transition_error: str | None
    already_finalized: bool = False


class MainWindowWelcomeController:
    """Controller for welcome-screen setup and startup action flow."""

    def __init__(self, host: MainWindowWelcomeHost) -> None:
        self._host = host
        self._startup_transition_coordinator = StartupTransitionCoordinator(self._host_widget())
        self._startup_transition_timer = self._startup_transition_coordinator.timer
        self._startup_transition = self._startup_transition_coordinator.state
        self._startup_transition_timer.timeout.connect(self._complete_startup_transition_to_main)
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
        self._last_prepare_error_message = None
        try:
            portfolio = load_portfolio_file(path)
        except Exception as exc:
            self._last_prepare_error_message = str(exc) or repr(exc)
            return False
        self._pending_startup_portfolio = _PendingStartupPortfolio(portfolio=portfolio, file_path=path)
        return True

    def _prepare_portfolio_from_picker(self) -> bool:
        """Prompt for a portfolio path, then stage it for startup transition."""
        path = self._host._prompt_select_open_path()
        if path is None:
            self._last_prepare_error_message = None
            return False
        return self._prepare_portfolio_from_path(path)

    def _prepare_default_document(self) -> None:
        """Stage a new default portfolio without committing it to the live editor yet."""
        portfolio = self._host._build_default_portfolio_for_startup()
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
        self._reset_startup_transition_state(pending=True)
        self._host._show_startup_loading_overlay()
        self._schedule_main_screen_transition()
        self._start_startup_market_data_fetch()

    def _complete_startup_transition_to_main(self) -> None:
        """Mark the min-delay timer complete and try finalizing transition."""
        decision = self._startup_transition_coordinator.complete_min_delay()
        if decision is not None:
            self._finalize_startup_transition(decision)

    def _schedule_main_screen_transition(self) -> None:
        """Schedule minimum-delay transition with a cancelable timer."""
        self._startup_transition_coordinator.schedule_min_delay()

    def _start_startup_market_data_fetch(self) -> None:
        """Start startup market-data fetch for FX and portfolio prices."""
        if not self._ensure_startup_cleanup_ready_for_restart():
            self._abort_startup_transition_cleanup_in_progress()
            return
        started = self._startup_transition_coordinator.start_fetch(
            parent=self._host_widget(),
            portfolio=self._pending_portfolio(),
            cached_quote=self._host.session.cached_usd_ils_quote,
            on_finished=self._on_startup_market_data_fetch_finished,
        )
        if not started:
            self._abort_startup_transition_cleanup_in_progress()

    def _pending_portfolio(self) -> Portfolio | None:
        """Return the staged portfolio prepared for the current startup action."""
        pending = self._pending_startup_portfolio
        if pending is None:
            return None
        return pending.portfolio

    def _ensure_startup_cleanup_ready_for_restart(self) -> bool:
        """Ensure startup fetch cleanup completed before creating a new worker."""
        if self._cancel_startup_market_data_fetch():
            return True
        return False

    @Slot(object, object, object)
    def _on_startup_market_data_fetch_finished(
        self, quote_obj: object, portfolio_obj: object, error_obj: object
    ) -> None:
        """Store startup fetch result and finalize transition when ready."""
        payload = self._decode_startup_fetch_callback_payload(quote_obj, portfolio_obj, error_obj)
        resolution = self._resolve_startup_fetch_outcome(payload)
        if resolution.already_finalized:
            return

        decision = self._startup_transition_coordinator.complete_fetch(
            error_message=resolution.transition_error
        )
        if decision is not None:
            self._finalize_startup_transition(decision)

    @staticmethod
    def _decode_startup_fetch_callback_payload(
        quote_obj: object,
        portfolio_obj: object,
        error_obj: object,
    ) -> _StartupFetchCallbackPayload:
        """Decode raw Qt callback objects into a typed startup fetch payload."""
        return _StartupFetchCallbackPayload(
            quote=quote_obj if isinstance(quote_obj, UsdIlsRateQuote) else None,
            refreshed_portfolio=portfolio_obj if isinstance(portfolio_obj, Portfolio) else None,
            error_text=str(error_obj) if isinstance(error_obj, str) else "",
        )

    def _resolve_startup_fetch_outcome(self, payload: _StartupFetchCallbackPayload) -> _StartupFetchResolution:
        """Resolve one startup fetch payload into commit/failure transition state.

        Successful payloads commit the refreshed staged portfolio into the live
        session/editor state. Failed payloads clear staged state and return the
        user-facing error that should be recorded with the transition gates.
        """
        if payload.error_text or payload.refreshed_portfolio is None:
            self._pending_startup_portfolio = None
            return _StartupFetchResolution(
                transition_error=self._build_startup_fetch_error_message(payload.error_text)
            )

        if not self._cache_startup_quote_if_available(payload.quote):
            decision = self._startup_transition_coordinator.complete_fetch(
                error_message="Failed to fetch USD to ILS exchange rate."
            )
            if decision is not None:
                self._finalize_startup_transition(decision)
            return _StartupFetchResolution(
                transition_error="Failed to fetch USD to ILS exchange rate.",
                already_finalized=True,
            )

        self._commit_pending_startup_portfolio(payload.refreshed_portfolio)
        return _StartupFetchResolution(transition_error=None)

    def _cache_startup_quote_if_available(self, quote: UsdIlsRateQuote | None) -> bool:
        """Cache a fetched startup quote, or verify a session-cached quote already exists.

        Returns ``False`` only when neither the worker nor the session can
        provide a USD/ILS rate for the current startup transition.
        """
        if quote is not None:
            self._host.session.cache_usd_ils_quote(
                rate=quote.rate,
                effective_date=quote.effective_date,
                used_last_published=quote.used_last_published,
            )
            return True
        return self._host.session.cached_usd_ils_quote is not None

    def _commit_pending_startup_portfolio(self, refreshed_portfolio: Portfolio) -> None:
        """Commit staged startup portfolio into session and main-editor UI.

        This is the point where startup transitions from "prepared" to "live":
        the session document/file context is updated first, then the main editor
        widgets are rendered from the refreshed portfolio.
        """
        pending = self._pending_startup_portfolio
        if pending is None:
            raise RuntimeError("No pending startup portfolio to commit.")
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
        decision = self._startup_transition_coordinator.complete_fetch(
            error_message=self._startup_transition.fx_fetch_error
        )
        if decision is not None:
            self._finalize_startup_transition(decision)

    def _finalize_startup_transition(self, decision: StartupTransitionDecision) -> None:
        """Apply the resolved startup transition outcome to the UI."""
        self._host._hide_startup_loading_overlay()
        if decision.error_message:
            self._host.stack.setCurrentWidget(self._host.screen_welcome)
            show_error_with_back(
                self._host_widget(),
                "Startup data fetch failed",
                decision.error_message,
            )
            self.refresh_last_portfolio_ui()
            return
        self.enter_main_screen()

    def _cancel_startup_market_data_fetch(
        self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS
    ) -> bool:
        """Stop and detach in-flight startup market-data worker, if any."""
        return self._startup_transition_coordinator.cancel_fetch(wait_timeout_ms=wait_timeout_ms)

    def _abort_startup_transition_cleanup_in_progress(self) -> None:
        """Abort transition when prior startup market-data cleanup could not finish."""
        if self._startup_transition_timer.isActive():
            self._startup_transition_timer.stop()
        self._reset_startup_transition_state(pending=False)
        self._host.stack.setCurrentWidget(self._host.screen_welcome)
        self._host._hide_startup_loading_overlay()
        show_cleanup_in_progress(self._host_widget(), action_verb="starting")
        self._pending_startup_portfolio = None
        self.refresh_last_portfolio_ui()

    def cancel_pending_startup_transition(self, *, wait_timeout_ms: int = DEFAULT_CLEANUP_WAIT_MS) -> bool:
        """Cancel startup transition and return whether market-data worker cleanup completed."""
        stopped = self._startup_transition_coordinator.cancel_pending_transition(wait_timeout_ms=wait_timeout_ms)
        self._pending_startup_portfolio = None
        self._host._hide_startup_loading_overlay()
        return stopped

    def _reset_startup_transition_state(self, *, pending: bool) -> None:
        """Reset startup-transition gate flags to a known baseline state."""
        self._startup_transition_coordinator.reset(pending=pending)
