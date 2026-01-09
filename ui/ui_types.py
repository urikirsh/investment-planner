from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import Qt

"""
ui_types.py

Central definitions for UI-level types used across the GUI layer.

This module contains *UI domain primitives* that are shared between
multiple UI components and should not be coupled to a specific widget
or screen implementation.

What belongs here:
- Enumerations that describe UI concepts (e.g. row kinds, column indices)
- Constants used as Qt item roles
- Small, immutable data containers (dataclasses) that represent UI flow state
  (e.g. wizard steps)

What does NOT belong here:
- Widget classes (QWidget, QMainWindow, etc.)
- Business logic or investment calculations
- JSON / persistence logic
- Formatting or styling helpers (those belong in ui_utils.py)

Design intent:
- Provide a single source of truth for UI semantics
- Avoid magic numbers and magic strings in UI code
- Improve readability, safety, and refactorability of the GUI layer

This file should remain small, stable, and dependency-light.
"""

ROLE_KIND = Qt.UserRole + 1     # RowKind
ROLE_ID = Qt.UserRole + 2       # the internal id string

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

