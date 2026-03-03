from __future__ import annotations

"""Pytest configuration and shared fixtures for UI/widget test modules.

This file centralizes Qt test setup so individual tests can focus on widget
behavior rather than process-level initialization details.
"""

import os

import pytest
from PySide6.QtWidgets import QApplication

# Qt requires a platform plugin. `offscreen` allows QApplication startup in
# headless environments (e.g., CI runners without an active display server).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return a module-scoped ``QApplication`` instance for widget tests.

    Qt allows only one QApplication per process. Reusing the existing instance
    keeps tests deterministic and avoids setup overhead across test functions in
    the same module.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app
