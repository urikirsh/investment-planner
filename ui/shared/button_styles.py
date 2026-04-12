"""Shared button styles reused across screen footers and primary actions.

This module exposes two stable concepts that tests and screens can both rely on:
- role: whether a button is the primary or a secondary workflow action
- size: whether a button uses the compact editor/welcome sizing or the regular
  wizard sizing

Screens should prefer the `apply_*` helpers so the semantic Qt properties stay
in sync with the stylesheet text applied to the widget.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton


BUTTON_STYLE_ROLE_PROPERTY = "button_style_role"
BUTTON_STYLE_SIZE_PROPERTY = "button_style_size"
PRIMARY_BUTTON_STYLE_ROLE = "primary"
SECONDARY_BUTTON_STYLE_ROLE = "secondary"
COMPACT_BUTTON_STYLE_SIZE = "compact"
REGULAR_BUTTON_STYLE_SIZE = "regular"


def secondary_action_button_style(*, size: str = COMPACT_BUTTON_STYLE_SIZE) -> str:
    """Return the shared visual treatment for secondary workflow actions."""
    if size == REGULAR_BUTTON_STYLE_SIZE:
        return "font-size: 15px; padding: 8px 12px;"
    return "padding: 6px 10px;"


def primary_action_button_style(*, size: str = COMPACT_BUTTON_STYLE_SIZE) -> str:
    """Return the shared visual treatment for the primary workflow action."""
    padding = "8px 12px" if size == REGULAR_BUTTON_STYLE_SIZE else "6px 14px"
    font_size = " font-size: 15px;" if size == REGULAR_BUTTON_STYLE_SIZE else ""
    return (
        "QPushButton { background: #2f6fed; color: white; border: 1px solid #275dca; "
        f"border-radius: 6px; padding: {padding}; font-weight: 600;{font_size} }}"
        "QPushButton:hover { background: #285fcc; }"
        "QPushButton:pressed { background: #214ea8; }"
        "QPushButton:disabled { background: #9eb7ea; border-color: #9eb7ea; color: #eef3ff; }"
    )


def apply_primary_action_button_style(
    button: QPushButton,
    *,
    size: str = COMPACT_BUTTON_STYLE_SIZE,
) -> None:
    """Mark and style a button as the primary workflow action.

    The helper also records the semantic role/size on the widget so tests can
    assert hierarchy without depending on exact stylesheet strings.
    """
    button.setProperty(BUTTON_STYLE_ROLE_PROPERTY, PRIMARY_BUTTON_STYLE_ROLE)
    button.setProperty(BUTTON_STYLE_SIZE_PROPERTY, size)
    button.setStyleSheet(primary_action_button_style(size=size))


def apply_secondary_action_button_style(
    button: QPushButton,
    *,
    size: str = COMPACT_BUTTON_STYLE_SIZE,
) -> None:
    """Mark and style a button as a secondary workflow action.

    The helper also records the semantic role/size on the widget so tests can
    assert hierarchy without depending on exact stylesheet strings.
    """
    button.setProperty(BUTTON_STYLE_ROLE_PROPERTY, SECONDARY_BUTTON_STYLE_ROLE)
    button.setProperty(BUTTON_STYLE_SIZE_PROPERTY, size)
    button.setStyleSheet(secondary_action_button_style(size=size))
