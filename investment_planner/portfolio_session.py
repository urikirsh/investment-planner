from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from investment_planner.io_json import load_portfolio
from investment_planner.portfolio_document import PortfolioDocument
from investment_planner.models import Portfolio

"""
portfolio_session.py

Session-level portfolio file state and persistence helpers.

This module centralizes:
- startup path resolution from global user config
- a PortfolioDocument with current portfolio model, active file path,
  saved snapshot, and dirty-state
- building the minimal default in-memory portfolio

Important startup behavior:
- If a remembered file path exists and is valid, it is used.
- If the remembered path is missing/invalid, it is cleared.
- If no remembered path exists, callers should load the minimal default
  portfolio (this module intentionally does not fall back to any fixed file).
"""

DEFAULT_PORTFOLIO_DATA: Dict[str, Any] = {
    "cash": {"value": "12000", "min_reserve": "2000", "future_tax": "0"},
    "groups": [{"id": "sp500", "name": "S&P 500", "targetPercentage": "100"}],
    "instruments": [
        {
            "id": "spx_a",
            "name": "SPX 500",
            "value": "1",
            "investable": True,
            "groupId": "sp500",
            "targetInGroupPercentage": "100",
        }
    ],
}


def build_default_portfolio() -> Portfolio:
    """Build the minimal default in-memory portfolio model."""
    return load_portfolio(DEFAULT_PORTFOLIO_DATA)


class PortfolioSession:
    """Holds active file context and snapshot state for a portfolio editing session."""

    def __init__(self, default_json_path: Path, config_path: Path):
        """
        Initialize session state.

        Parameters
        ----------
        default_json_path:
            Project-level default path used by the UI as the initial location
            for open/save dialogs. It is not used as a startup load fallback.
        config_path:
            Global config file path used to persist/read the last opened
            portfolio path.
        """
        self.default_json_path = default_json_path
        self.document = PortfolioDocument()
        self._config_path = config_path

    @property
    def current_file_path(self) -> Optional[Path]:
        """Expose active file path tracked by the current document."""
        return self.document.active_path

    def _read_last_loaded_path_from_config(self) -> Optional[Path]:
        """Read and parse the remembered portfolio path from config, if any."""
        if not self._config_path.exists():
            return None
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        path_str = raw.get("last_portfolio_path")
        if not isinstance(path_str, str) or not path_str.strip():
            return None
        return Path(path_str).expanduser()

    def _write_last_loaded_path_to_config(self, path: Optional[Path]) -> None:
        """Persist the currently active file path to global user config."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_portfolio_path": str(path.resolve()) if path is not None else ""}
        self._config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def set_active_file_path(self, path: Optional[Path]) -> None:
        """Update active file path in-memory and best-effort persist it to config."""
        self.document.active_path = path
        try:
            self._write_last_loaded_path_to_config(path)
        except Exception:
            # Non-fatal: config persistence should not block main workflow.
            pass

    def resolve_startup_path(self) -> Optional[Path]:
        """
        Resolve the file path to load at startup from remembered global config.

        Returns
        -------
        Optional[Path]
            Valid remembered path when available; otherwise ``None``.
        """
        startup_path = self._read_last_loaded_path_from_config()
        if startup_path is not None and not startup_path.exists():
            self.set_active_file_path(None)
            startup_path = None

        return startup_path

    def load_document_from_path(self, path: Path) -> Portfolio:
        """Load document from a file and persist active path in config."""
        portfolio = self.document.load_from_path(path)
        self.set_active_file_path(path)
        return portfolio

    def save_document_to_path(self, path: Path) -> None:
        """Save current document to file and persist active path in config."""
        self.document.save_to_path(path)
        self.set_active_file_path(path)

    def mark_new_document(self, portfolio: Portfolio) -> None:
        """Initialize a new unsaved document and clear active path in config."""
        self.document.mark_new_unsaved(portfolio)
        self.set_active_file_path(None)
