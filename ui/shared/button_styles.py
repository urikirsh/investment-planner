"""Shared button styles reused across screen footers and primary actions."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton


BUTTON_STYLE_ROLE_PROPERTY = "button_style_role"
PRIMARY_BUTTON_STYLE_ROLE = "primary"
SECONDARY_BUTTON_STYLE_ROLE = "secondary"


def secondary_action_button_style() -> str:
    """Return the shared visual treatment for secondary workflow actions."""
    return "padding: 6px 10px;"


def primary_action_button_style() -> str:
    """Return the shared visual treatment for the primary workflow action."""
    return (
        "QPushButton { background: #2f6fed; color: white; border: 1px solid #275dca; "
        "border-radius: 6px; padding: 6px 14px; font-weight: 600; }"
        "QPushButton:hover { background: #285fcc; }"
        "QPushButton:pressed { background: #214ea8; }"
        "QPushButton:disabled { background: #9eb7ea; border-color: #9eb7ea; color: #eef3ff; }"
    )


def apply_primary_action_button_style(button: QPushButton) -> None:
    """Mark and style a button as the primary workflow action."""
    button.setProperty(BUTTON_STYLE_ROLE_PROPERTY, PRIMARY_BUTTON_STYLE_ROLE)
    button.setStyleSheet(primary_action_button_style())


def apply_secondary_action_button_style(button: QPushButton) -> None:
    """Mark and style a button as a secondary workflow action."""
    button.setProperty(BUTTON_STYLE_ROLE_PROPERTY, SECONDARY_BUTTON_STYLE_ROLE)
    button.setStyleSheet(secondary_action_button_style())
