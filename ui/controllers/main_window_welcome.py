from __future__ import annotations

"""Welcome-screen behavior for the composed main window controller."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, cast

from PySide6.QtWidgets import QWidget

from portfolio_core.app_metadata import get_app_version
from ui.controllers.protocols import MainWindowWelcomeHost
from ui.screens.welcome_screen import WelcomeScreen

_DEFAULT_PATH_MAX_CHARS: Final[int] = 96


@dataclass(frozen=True)
class WelcomeLastPortfolioStatus:
    """Render-ready welcome-state for remembered portfolio action."""

    button_enabled: bool
    path_text: str
    path_tooltip: str
    missing_path: bool


class MainWindowWelcomeController:
    """Controller for welcome-screen setup and startup action flow."""

    def __init__(self, host: MainWindowWelcomeHost) -> None:
        self._host = host

    def init_screen(self) -> None:
        """Build startup welcome screen and connect startup actions."""
        host = self._host
        host.screen_welcome = WelcomeScreen(app_version=get_app_version(), parent=cast(QWidget, host))
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
        self.enter_main_screen()
