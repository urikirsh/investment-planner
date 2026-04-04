from __future__ import annotations

"""Typing contracts for composed main-window controllers."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QLabel, QLineEdit, QStackedWidget, QTextEdit, QTreeWidget, QWidget

from portfolio_core.domain.models import Portfolio
from portfolio_core.domain.planning_types import PlanningMode
from portfolio_core.session.portfolio_session import PortfolioSession
from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.summary_screen import SummaryScreen
from ui.screens.welcome_screen import WelcomeScreen
from ui.screens.wizard_screen import WizardScreen
from ui.ui_state import PlanningState


class SupportsItemChangedSuppression(Protocol):
    """Protocol for hosts that temporarily suppress item-changed reactions."""

    _suppress_item_changed: bool


@contextmanager
def suppress_item_changed(host: SupportsItemChangedSuppression) -> Iterator[None]:
    """Temporarily suppress item-changed reactions on a controller host."""
    host._suppress_item_changed = True
    try:
        yield
    finally:
        host._suppress_item_changed = False


class MainWindowWelcomeHost(Protocol):
    """Host contract consumed by ``MainWindowWelcomeController``."""
    # state
    _base_window_title: str
    session: PortfolioSession

    # widgets
    stack: QStackedWidget
    screen_welcome: WelcomeScreen
    screen_main: MainEditorScreen

    # callbacks
    def setWindowTitle(self, title: str) -> None: ...

    def _quit_app(self) -> None: ...

    def _update_file_context_ui(self) -> None: ...

    def _open_portfolio_from_path(self, path: Path) -> bool: ...

    def _open_portfolio_from_picker(self) -> bool: ...

    def _prompt_select_open_path(self) -> Path | None: ...

    def _build_default_portfolio_for_startup(self) -> Portfolio: ...

    def _render_main_editor_from_portfolio(self, portfolio: Portfolio, *, switch_to_main: bool) -> None: ...

    # startup transition overlay lifecycle
    def _show_startup_loading_overlay(self) -> None: ...

    def _hide_startup_loading_overlay(self) -> None: ...


class MainWindowMainEditorHost(Protocol):
    """Host contract consumed by ``MainWindowMainEditorController``."""
    # state
    session: PortfolioSession
    _suppress_item_changed: bool
    _non_investable_bucket_id: str
    _non_investable_bucket_title: str

    # widgets
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    investable_balance_label: QLabel
    total_label: QLabel
    screen_main: MainEditorScreen

    # callbacks
    def _on_save_clicked(self) -> None: ...

    def _on_save_as_clicked(self) -> None: ...

    def _on_open_clicked(self) -> None: ...

    def _on_new_clicked(self) -> None: ...

    def _normalize_future_tax_input(self) -> None: ...

    def _refresh_data(self) -> None: ...

    def _update_future_tax_visual_state(self) -> None: ...

    def _update_file_context_ui(self) -> None: ...

    def _render_main_editor_from_portfolio(self, portfolio: Portfolio, *, switch_to_main: bool) -> None: ...

    def _run_planning(self, mode: PlanningMode) -> None: ...

    def _confirm_continue_with_unsaved_changes(self, action_text: str) -> bool: ...


class MainWindowTableEditingHost(Protocol):
    """Host contract consumed by ``MainWindowTableEditingController``."""
    # state
    _suppress_item_changed: bool

    # widgets
    tree: QTreeWidget

    # callbacks
    def _refresh_data(self) -> None: ...


class MainWindowMetricsHost(Protocol):
    """Host contract consumed by ``MainWindowMetricsController``."""
    # state
    _suppress_item_changed: bool
    session: PortfolioSession

    # widgets
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    investable_balance_label: QLabel
    total_label: QLabel


class MainWindowSummaryHost(Protocol):
    """Host contract consumed by ``MainWindowSummaryController``."""
    # state
    planning_state: PlanningState

    # widgets
    stack: QStackedWidget
    screen_main: MainEditorScreen
    screen_wizard: WizardScreen
    screen_summary: SummaryScreen
    summary_text: QTextEdit

    # callbacks
    def _quit_app(self) -> None: ...

    def _show_current_wizard_step(self) -> None: ...
