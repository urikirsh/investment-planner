from __future__ import annotations

from decimal import Decimal
from enum import Enum, auto

from PySide6.QtCore import Qt

"""
ui_types.py

Shared UI-related type definitions.

This module defines enums, constants, and roles used across the UI layer
to describe row kinds, column indices, and item metadata. Centralizing
these definitions ensures consistent interpretation of tree structure
and item behavior throughout the application.
"""


D = Decimal

# Item data roles used on QTreeWidgetItem cells.
# These extend Qt.UserRole to avoid collisions with built-in Qt roles.
ROLE_KIND = int(Qt.ItemDataRole.UserRole) + 1        # RowKind
ROLE_ID = int(Qt.ItemDataRole.UserRole) + 2          # the internal id string
ROLE_PREV_TEXT = int(Qt.ItemDataRole.UserRole) + 50  # previous text in cell (before edit)

class RowKind(Enum):
    """
    Identifies the semantic role of a row in the main tree UI.

    RowKind is used to distinguish between asset groups, instruments,
    and special structural rows (such as the non-investable bucket),
    and drives editing rules, drag-and-drop behavior, and calculations.
    """
    GROUP = auto()
    INSTRUMENT = auto()
    NON_INVESTABLE_BUCKET = auto()

class Col(Enum):
    """
    Defines column indices for the main tree UI.

    This enum provides a single source of truth for column ordering
    and is used throughout the UI layer to access, format, and
    validate cell contents consistently.
    """
    NAME = 0
    TOT_VALUE = 1
    PORTFOLIO_PCT = 2
    TARGET_PCT = 3
    STRATEGY_PCT = 4
    DRIFT_PP = 5
