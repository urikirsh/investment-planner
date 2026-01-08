from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import Qt

ROLE_KIND = Qt.UserRole + 1     # RowKind
ROLE_ID = Qt.UserRole + 2       # the internal id string

class RowKind(Enum):
    GROUP = auto()
    INSTRUMENT = auto()
    NON_INVESTABLE_BUCKET = auto()

class Col(Enum):
    NAME = 0
    TOT_VALUE = 1
    TARGET_PCT = 2
    PREFERRED_INSTR = 3
    INVESTABLE = 4

@dataclass
class WizardStep:
    # One step per asset group, executed via preferred instrument
    asset_group_id: str
    asset_group_name: str
    preferred_instrument_id: str
    preferred_instrument_name: str
    planned_delta_money: D  # positive buy, negative sell

