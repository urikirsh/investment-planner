"""Shared surface styles for toolbars, cards, and emphasized info panels."""

from __future__ import annotations


def neutral_card_style() -> str:
    """Return the standard neutral card surface used for toolbars and info panels."""
    return "background: #f5f7fa; border: 1px solid #d8dde6; border-radius: 6px;"


def toolbar_surface_style() -> str:
    """Return the shared toolbar card style."""
    return f"QToolBar {{ {neutral_card_style()} spacing: 6px; padding: 4px; }}"


def info_result_card_style() -> str:
    """Return the highlighted informational card style used for result summaries."""
    return (
        "background: #f7fbff; border: 1px solid #d5e8ff; border-radius: 6px; "
        "padding: 10px 12px; font-size: 15px; font-weight: 600;"
    )
