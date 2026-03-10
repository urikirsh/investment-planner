from __future__ import annotations

"""Welcome-screen behavior extracted from the main window controller."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from PySide6.QtWidgets import QStackedWidget, QWidget

from portfolio_core.app_metadata import get_app_version
from portfolio_core.portfolio_session import PortfolioSession
from ui.controllers.protocols import MainWindowWelcomeDependencies
from ui.screens.welcome_screen import WelcomeScreen


@dataclass(frozen=True)
class _WelcomeLastPortfolioStatus:
    """Render-ready welcome-state for remembered portfolio action."""

    button_enabled: bool
    path_text: str
    path_tooltip: str
    missing_path: bool


class MainWindowWelcomeMixin:
    """Mixin containing welcome-screen setup and startup action flow."""

    _base_window_title: str
    session: PortfolioSession
    stack: QStackedWidget
    screen_welcome: WelcomeScreen
    screen_main: QWidget

    def _init_welcome_screen(self) -> None:
        """Build startup welcome screen and connect startup actions."""
        deps = cast(MainWindowWelcomeDependencies, self)
        self.screen_welcome = WelcomeScreen(app_version=get_app_version(), parent=cast(QWidget, self))
        self.screen_welcome.open_last_btn.clicked.connect(self._on_welcome_open_last_clicked)
        self.screen_welcome.load_different_btn.clicked.connect(self._on_welcome_load_different_clicked)
        self.screen_welcome.start_new_btn.clicked.connect(self._on_welcome_start_new_clicked)
        self.screen_welcome.quit_btn.clicked.connect(deps._quit_app)

    def _show_welcome_screen_on_startup(self) -> None:
        """Show startup welcome screen and refresh remembered-file state."""
        cast(QWidget, self).setWindowTitle(self._base_window_title)
        self._refresh_welcome_last_portfolio_ui()
        self.stack.setCurrentWidget(self.screen_welcome)
        if self.screen_welcome.open_last_btn.isEnabled():
            self.screen_welcome.open_last_btn.setFocus()
        else:
            self.screen_welcome.load_different_btn.setFocus()

    def _enter_main_screen(self) -> None:
        """Switch from startup screen to main editor with current file context."""
        deps = cast(MainWindowWelcomeDependencies, self)
        deps._update_file_context_ui()
        self.stack.setCurrentWidget(self.screen_main)

    @staticmethod
    def _truncate_middle(text: str, *, max_chars: int = 96) -> str:
        """Return middle-truncated text for constrained path labels."""
        if len(text) <= max_chars:
            return text
        part = max((max_chars - 3) // 2, 1)
        return f"{text[:part]}...{text[-part:]}"

    def _refresh_welcome_last_portfolio_ui(self) -> None:
        """Refresh last-portfolio button state and path text on welcome screen."""
        remembered_path = self.session.get_remembered_portfolio_path()
        status = self._build_welcome_last_portfolio_status(remembered_path)
        self.screen_welcome.set_last_portfolio_status(
            button_enabled=status.button_enabled,
            path_text=status.path_text,
            path_tooltip=status.path_tooltip,
            missing_path=status.missing_path,
        )

    def _build_welcome_last_portfolio_status(self, remembered_path: Path | None) -> _WelcomeLastPortfolioStatus:
        """Build pure welcome-screen status payload from remembered path state."""
        if remembered_path is None:
            return _WelcomeLastPortfolioStatus(
                button_enabled=False,
                path_text="No recent portfolio",
                path_tooltip="",
                missing_path=False,
            )

        full_path = str(remembered_path)
        display_path = self._truncate_middle(full_path)
        path_exists = remembered_path.exists()
        if path_exists:
            path_text = f"Last portfolio: {display_path}"
        else:
            path_text = f"Last portfolio: {display_path} (Not found)"

        return _WelcomeLastPortfolioStatus(
            button_enabled=path_exists,
            path_text=path_text,
            path_tooltip=full_path,
            missing_path=not path_exists,
        )

    def _on_welcome_open_last_clicked(self) -> None:
        """Open remembered portfolio when available and enter main screen."""
        deps = cast(MainWindowWelcomeDependencies, self)
        remembered_path = self.session.get_remembered_portfolio_path()
        if remembered_path is None or not remembered_path.exists():
            self._refresh_welcome_last_portfolio_ui()
            return
        self._run_welcome_action(
            action=lambda: deps._open_portfolio_from_path(remembered_path),
            on_failure=self._refresh_welcome_last_portfolio_ui,
        )

    def _on_welcome_load_different_clicked(self) -> None:
        """Open picker flow from welcome screen and enter main on success."""
        deps = cast(MainWindowWelcomeDependencies, self)
        self._run_welcome_action(action=deps._open_portfolio_from_picker)

    def _on_welcome_start_new_clicked(self) -> None:
        """Initialize default portfolio from welcome and enter main editor."""
        self._run_welcome_action(action=self._start_default_document_from_welcome)

    def _start_default_document_from_welcome(self) -> bool:
        """Create default document for startup flow and report success."""
        deps = cast(MainWindowWelcomeDependencies, self)
        deps._load_default_document()
        return True

    def _run_welcome_action(
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
        self._enter_main_screen()
