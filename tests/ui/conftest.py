from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

# Ensure Qt can initialize in headless CI/local test runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Provide a reusable QApplication instance for widget-based tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app
