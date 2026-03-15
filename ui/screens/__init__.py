"""
UI screen widgets package.

This package contains presentational QWidget classes used by `MainWindow`.
Each screen module encapsulates layout and widget construction only.
Behavior and workflow orchestration remain in the coordinator layer.
"""

from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.add_instrument_wizard_dialog import AddInstrumentWizardDialog
from ui.screens.summary_screen import SummaryScreen
from ui.screens.welcome_screen import WelcomeScreen
from ui.screens.wizard_screen import WizardScreen

__all__ = [
    "MainEditorScreen",
    "AddInstrumentWizardDialog",
    "SummaryScreen",
    "WelcomeScreen",
    "WizardScreen",
]
