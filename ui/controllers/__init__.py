"""Composed controllers for screen-specific main-window behavior."""

from .main_window_main_editor import MainWindowMainEditorController
from .main_window_metrics import MainWindowMetricsController
from .main_window_summary import MainWindowSummaryController
from .main_window_table_editing import MainWindowTableEditingController
from .main_window_welcome import MainWindowWelcomeController, WelcomeLastPortfolioStatus

__all__ = [
    "MainWindowMainEditorController",
    "MainWindowMetricsController",
    "MainWindowSummaryController",
    "MainWindowTableEditingController",
    "MainWindowWelcomeController",
    "WelcomeLastPortfolioStatus",
]
