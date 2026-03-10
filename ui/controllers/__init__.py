"""Controller mixins for screen-specific main-window behavior."""

from .main_window_main_editor import MainWindowMainEditorMixin
from .main_window_metrics import MainWindowMetricsMixin
from .main_window_summary import MainWindowSummaryMixin
from .main_window_table_editing import MainWindowTableEditingMixin
from .main_window_welcome import MainWindowWelcomeMixin

__all__ = [
    "MainWindowMainEditorMixin",
    "MainWindowMetricsMixin",
    "MainWindowSummaryMixin",
    "MainWindowTableEditingMixin",
    "MainWindowWelcomeMixin",
]
