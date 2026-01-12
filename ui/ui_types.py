from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from decimal import Decimal

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

ROLE_KIND = Qt.UserRole + 1        # RowKind
ROLE_ID = Qt.UserRole + 2          # the internal id string
ROLE_PREV_TEXT = Qt.UserRole + 50  # previous text in cell (before edit)

class RowKind(Enum):
    GROUP = auto()
    INSTRUMENT = auto()
    NON_INVESTABLE_BUCKET = auto()

class Col(Enum):
    NAME = 0
    TOT_VALUE = 1
    PORTFOLIO_PCT = 2
    TARGET_PCT = 3
    STRATEGY_PCT = 4
    DRIFT_PP = 5
    PREFERRED_INSTR = 6

@dataclass
class WizardStep:
    # One step per asset group, executed via preferred instrument
    asset_group_id: str
    asset_group_name: str
    preferred_instrument_id: str
    preferred_instrument_name: str
    planned_delta_money: D  # positive buy, negative sell

