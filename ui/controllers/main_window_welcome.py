from __future__ import annotations

"""Welcome-screen behavior for the composed main window controller."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Final, cast

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from portfolio_core.app_metadata import get_app_version
from portfolio_core.fx_service import UsdIlsRateQuote, fetch_latest_usd_ils_rate
from ui.controllers.protocols import MainWindowWelcomeHost
from ui.dialogs import show_cleanup_in_progress, show_error_with_back
from ui.screens.welcome_screen import WelcomeScreen

_DEFAULT_PATH_MAX_CHARS: Final[int] = 96
_STARTUP_TRANSITION_MIN_DELAY_MS: Final[int] = 1000


class _StartupFxFetchWorker(QObject):
    """Background BOI fetch worker for welcome->main transition."""

    finished = Signal(object, object)  # (UsdIlsRateQuote | None, error_text | None)

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds

    @Slot()
    def run(self) -> None:
        try:
            quote = fetch_latest_usd_ils_rate(timeout_seconds=self._timeout_seconds)
            self.finished.emit(quote, None)
        except Exception as exc:
            self.finished.emit(None, str(exc))


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

    def start(
        self,
        *,
        parent: QWidget,
        on_finished: Callable[[object, object], None],
        timeout_seconds: float = 10.0,
    ) -> None:
        """Create, wire, and start the startup FX fetch worker thread."""
        thread = QThread(parent)
        worker = _StartupFxFetchWorker(timeout_seconds=timeout_seconds)
        self.thread = thread
        self.worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def cancel(self, *, wait_timeout_ms: int = 1000) -> bool:
        """Stop and detach in-flight worker/thread, if any."""
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            if not self.thread.wait(wait_timeout_ms):
                return False
        if self.worker is not None:
            self.worker.deleteLater()
        self.clear()
        return True

    def clear(self) -> None:
        self.thread = None
        self.worker = None


class MainWindowWelcomeController:
    """Controller for welcome-screen setup and startup action flow."""

    def __init__(self, host: MainWindowWelcomeHost) -> None:
        self._host = host
        self._startup_transition_timer = QTimer(self._host_widget())
        self._startup_transition_timer.setSingleShot(True)
        self._startup_transition_timer.timeout.connect(self._complete_startup_transition_to_main)
        self._startup_fx_fetch = _StartupFxFetchLifecycle()
        self._startup_transition_pending = False
        self._startup_min_delay_elapsed = False
        self._startup_fx_fetch_completed = False
        self._startup_fx_fetch_error: str | None = None

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
            action=lambda: self._host._open_portfolio_from_path(remembered_path),
            on_failure=self.refresh_last_portfolio_ui,
        )

    def on_load_different_clicked(self) -> None:
        """Open picker flow from welcome screen and enter main on success."""
        self.run_action(action=self._host._open_portfolio_from_picker)

    def on_start_new_clicked(self) -> None:
        """Initialize default portfolio from welcome and enter main editor."""
        self.run_action(action=self.start_default_document)

    def start_default_document(self) -> bool:
        """Create default document for startup flow and report success."""
        self._host._load_default_document()
        return True

    def run_action(
        self,
        *,
        action: Callable[[], bool],
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        """Run startup action; enter main editor on success."""
        if not action():
            if on_failure is not None:
                on_failure()
            return
        self._begin_startup_transition_to_main()

    def _begin_startup_transition_to_main(self) -> None:
        """Show loading overlay and enter main only after delay + FX fetch."""
        self._reset_startup_transition_state(pending=True)
        self._host._show_startup_loading_overlay()
        self._schedule_main_screen_transition()
        self._start_startup_fx_fetch()

    def _complete_startup_transition_to_main(self) -> None:
        """Mark the min-delay timer complete and try finalizing transition."""
        self._startup_min_delay_elapsed = True
        self._try_finalize_startup_transition()

    def _schedule_main_screen_transition(self) -> None:
        """Schedule minimum-delay transition with a cancelable timer."""
        self._startup_transition_timer.start(_STARTUP_TRANSITION_MIN_DELAY_MS)

    def _start_startup_fx_fetch(self) -> None:
        """Start USD/ILS fetch unless already cached for this app session."""
        if self._host.session.get_session_cached_usd_ils_quote() is not None:
            self._startup_fx_fetch_completed = True
            self._try_finalize_startup_transition()
            return

        if not self._cancel_startup_fx_fetch():
            self._abort_startup_transition_cleanup_in_progress()
            return
        self._startup_fx_fetch.start(
            parent=self._host_widget(),
            on_finished=self._on_startup_fx_fetch_finished,
            timeout_seconds=10.0,
        )

    @Slot(object, object)
    def _on_startup_fx_fetch_finished(self, quote_obj: object, error_obj: object) -> None:
        """Store startup fetch result and finalize transition when ready."""
        self._startup_fx_fetch.clear()
        quote = quote_obj if isinstance(quote_obj, UsdIlsRateQuote) else None
        error_text = str(error_obj) if isinstance(error_obj, str) else ""

        if quote is not None and not error_text:
            now = datetime.now(timezone.utc)
            self._host.session.set_session_cached_usd_ils_quote(
                rate=quote.rate,
                effective_date=quote.effective_date,
                used_last_published=quote.used_last_published,
                cached_at=now,
            )
            try:
                self._host.session.write_cached_usd_ils_quote(
                    rate=quote.rate,
                    effective_date=quote.effective_date,
                    used_last_published=quote.used_last_published,
                    cached_at=now,
                )
            except Exception:
                pass
            self._startup_fx_fetch_error = None
        else:
            self._startup_fx_fetch_error = "Failed to fetch USD to ILS exchange rate."

        self._startup_fx_fetch_completed = True
        self._try_finalize_startup_transition()

    def _try_finalize_startup_transition(self) -> None:
        """Finalize welcome transition after both min-delay and FX-fetch complete."""
        if not self._startup_transition_pending:
            return
        if not self._startup_min_delay_elapsed or not self._startup_fx_fetch_completed:
            return

        self._startup_transition_pending = False
        self._host._hide_startup_loading_overlay()
        if self._startup_fx_fetch_error:
            self._host.stack.setCurrentWidget(self._host.screen_welcome)
            show_error_with_back(
                self._host_widget(),
                "Exchange rate fetch failed",
                self._startup_fx_fetch_error,
            )
            self.refresh_last_portfolio_ui()
            return
        self.enter_main_screen()

    def _cancel_startup_fx_fetch(self, *, wait_timeout_ms: int = 1000) -> bool:
        """Stop and detach in-flight startup FX fetch worker, if any."""
        return self._startup_fx_fetch.cancel(wait_timeout_ms=wait_timeout_ms)

    def _abort_startup_transition_cleanup_in_progress(self) -> None:
        """Abort transition when prior startup FX cleanup could not finish."""
        if self._startup_transition_timer.isActive():
            self._startup_transition_timer.stop()
        self._reset_startup_transition_state(pending=False)
        self._host.stack.setCurrentWidget(self._host.screen_welcome)
        self._host._hide_startup_loading_overlay()
        show_cleanup_in_progress(self._host_widget())
        self.refresh_last_portfolio_ui()

    def cancel_pending_startup_transition(self, *, wait_timeout_ms: int = 1000) -> bool:
        """Cancel startup transition and return whether FX worker cleanup completed."""
        if self._startup_transition_timer.isActive():
            self._startup_transition_timer.stop()
        self._reset_startup_transition_state(pending=False)
        stopped = self._cancel_startup_fx_fetch(wait_timeout_ms=wait_timeout_ms)
        self._host._hide_startup_loading_overlay()
        return stopped

    def _reset_startup_transition_state(self, *, pending: bool) -> None:
        """Reset startup-transition gate flags to a known baseline state."""
        self._startup_transition_pending = pending
        self._startup_min_delay_elapsed = False
        self._startup_fx_fetch_completed = False
        self._startup_fx_fetch_error = None
