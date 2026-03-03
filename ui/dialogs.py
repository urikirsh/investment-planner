from __future__ import annotations

"""Shared UI dialog wrappers used by controller/action code.

This module centralizes common QMessageBox/QFileDialog interactions so
controller logic can be tested with narrower seams and fewer Qt-specific
details.
"""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ui.ui_state import UnsavedChangesDecision


def show_info(parent: QWidget, title: str, message: str) -> None:
    """Show informational feedback."""
    QMessageBox.information(parent, title, message)


def show_error(parent: QWidget, title: str, message: str) -> None:
    """Show error feedback."""
    QMessageBox.critical(parent, title, message)


def show_warning(parent: QWidget, title: str, message: str) -> None:
    """Show warning feedback."""
    QMessageBox.warning(parent, title, message)


def choose_save_path(parent: QWidget, *, start_path: Path) -> Path | None:
    """Prompt for save destination and normalize suffix to ``.json``."""
    selected, _ = QFileDialog.getSaveFileName(
        parent,
        "Save Portfolio As",
        str(start_path),
        "Portfolio JSON (*.json);;JSON files (*.json);;All files (*)",
    )
    if not selected:
        return None
    chosen = Path(selected).expanduser()
    if chosen.suffix.lower() != ".json":
        chosen = chosen.with_suffix(".json")
    return chosen


def choose_open_path(parent: QWidget, *, start_dir: Path) -> Path | None:
    """Prompt for a portfolio file path to open."""
    selected, _ = QFileDialog.getOpenFileName(
        parent,
        "Open Portfolio",
        str(start_dir),
        "Portfolio JSON (*.json);;JSON files (*.json);;All files (*)",
    )
    if not selected:
        return None
    return Path(selected).expanduser()


def confirm_unsaved_changes(parent: QWidget, *, action_text: str) -> UnsavedChangesDecision:
    """Prompt unsaved-changes decision and return typed user choice."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Unsaved changes")
    box.setText("Your current changes are not saved.")
    box.setInformativeText(f"Do you want to save before {action_text}?")
    save_btn = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
    dont_save_btn = box.addButton("Don't Save", QMessageBox.ButtonRole.DestructiveRole)
    cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(save_btn)
    box.exec()

    clicked = box.clickedButton()
    if clicked == save_btn:
        return UnsavedChangesDecision.SAVE
    if clicked == dont_save_btn:
        return UnsavedChangesDecision.DISCARD
    if clicked == cancel_btn:
        return UnsavedChangesDecision.CANCEL
    return UnsavedChangesDecision.CANCEL
