from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from portfolio_core.io_json import load_portfolio_file, save_portfolio_file
from portfolio_core.domain.models import Portfolio

"""
portfolio_document.py

Document model for portfolio editing.

Holds the current in-memory portfolio, the active file path (if any),
and the last saved/loaded snapshot used for dirty-state checks.
"""


@dataclass
class PortfolioDocument:
    """
    In-memory representation of the currently edited portfolio document.

    Tracks:
    - ``current_portfolio``: latest model represented by the UI/editor state
    - ``active_path``: current file path associated with this document
    - ``saved_snapshot``: last successfully loaded/saved portfolio snapshot
    """

    current_portfolio: Optional[Portfolio] = None
    active_path: Optional[Path] = None
    saved_snapshot: Optional[Portfolio] = None

    def set_current(self, portfolio: Portfolio) -> None:
        """Replace current in-memory portfolio without mutating saved snapshot."""
        self.current_portfolio = portfolio

    def mark_loaded(self, portfolio: Portfolio, source_path: Path) -> None:
        """Mark document state after loading portfolio from disk."""
        self.current_portfolio = portfolio
        self.saved_snapshot = portfolio
        self.active_path = source_path

    def mark_saved(self, portfolio: Portfolio, target_path: Path) -> None:
        """Mark document state after saving portfolio to disk."""
        self.current_portfolio = portfolio
        self.saved_snapshot = portfolio
        self.active_path = target_path

    def mark_new_unsaved(self, portfolio: Portfolio) -> None:
        """Mark document as newly initialized with no file association yet."""
        self.current_portfolio = portfolio
        self.saved_snapshot = portfolio
        self.active_path = None

    def load_from_path(self, path: Path) -> Portfolio:
        """Load portfolio from path and update document state."""
        portfolio = load_portfolio_file(path)
        self.mark_loaded(portfolio, path)
        return portfolio

    def save_to_path(self, path: Path) -> None:
        """Persist current portfolio to path and update saved snapshot state."""
        if self.current_portfolio is None:
            raise ValueError("No current portfolio to save")
        save_portfolio_file(self.current_portfolio, path)
        self.mark_saved(self.current_portfolio, path)

    def is_dirty(self) -> bool:
        """Return ``True`` when current model differs from saved snapshot."""
        if self.current_portfolio is None:
            return True
        if self.saved_snapshot is None:
            return True
        return self.current_portfolio != self.saved_snapshot
