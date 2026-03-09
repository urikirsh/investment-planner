from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

from portfolio_core.io_json import load_portfolio
from portfolio_core.portfolio_document import PortfolioDocument
from portfolio_core.models import Exchange, Portfolio

"""
portfolio_session.py

Session-level portfolio file state and persistence helpers.

This module centralizes:
- startup path resolution from global user config
- a PortfolioDocument with current portfolio model, active file path,
  saved snapshot, and dirty-state
- config-backed cache for last successful USD/ILS quote (used by wizard fallback)
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
            "ticker": "1234567",
            "name": "SPX 500",
            "quantity": 1,
            "value": "1",
            "exchange": Exchange.TASE.value,
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
        raw = self._read_config_payload()
        path_str = raw.get("last_portfolio_path")
        if not isinstance(path_str, str) or not path_str.strip():
            return None
        return Path(path_str).expanduser()

    def _write_last_loaded_path_to_config(self, path: Optional[Path]) -> None:
        """Persist the currently active file path to global user config."""
        payload = self._read_config_payload()
        payload["last_portfolio_path"] = str(path.resolve()) if path is not None else ""
        self._write_config_payload(payload)

    def _read_config_payload(self) -> dict[str, Any]:
        """Best-effort read of full session config payload.

        The payload currently stores (when available):
        - `last_portfolio_path`: absolute path string for startup restore
        - `last_usd_ils_quote`: last successful BOI quote cache used for
          wizard fallback when network fetch fails
        """
        if not self._config_path.exists():
            return {}
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw

    def _write_config_payload(self, payload: dict[str, Any]) -> None:
        """Persist full session config payload."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def read_cached_usd_ils_quote(self) -> "CachedUsdIlsQuote | None":
        """Read last successful USD/ILS quote cache from session config.

        Returns ``None`` for any missing/corrupt/incomplete payload so callers
        can treat cache as optional and fail soft to manual entry.

        This method is intentionally fail-soft: unreadable or partially-invalid
        cache payloads are treated as "no cache" instead of raising.
        """
        payload = self._read_config_payload().get("last_usd_ils_quote")
        if not isinstance(payload, dict):
            return None

        raw_rate = payload.get("rate")
        raw_effective_date = payload.get("effective_date")
        raw_cached_at = payload.get("cached_at")
        raw_last_published = payload.get("used_last_published")

        if not isinstance(raw_rate, str) or not isinstance(raw_effective_date, str):
            return None
        if not isinstance(raw_cached_at, str):
            return None

        try:
            rate = Decimal(raw_rate)
        except (InvalidOperation, ValueError):
            return None
        if rate <= 0:
            return None

        try:
            effective_date = date.fromisoformat(raw_effective_date)
        except ValueError:
            return None

        try:
            cached_at = datetime.fromisoformat(raw_cached_at)
        except ValueError:
            return None
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        return CachedUsdIlsQuote(
            rate=rate,
            effective_date=effective_date,
            used_last_published=bool(raw_last_published),
            cached_at=cached_at,
        )

    def write_cached_usd_ils_quote(
        self,
        *,
        rate: Decimal,
        effective_date: date,
        used_last_published: bool,
        cached_at: datetime | None = None,
    ) -> None:
        """Persist last successful USD/ILS quote cache to session config.

        This intentionally writes only successful official fetches. Manual
        overrides are transient wizard state and are never persisted.
        """
        now = cached_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        payload = self._read_config_payload()
        payload["last_usd_ils_quote"] = {
            "rate": str(rate),
            "effective_date": effective_date.isoformat(),
            "used_last_published": bool(used_last_published),
            "cached_at": now.isoformat(),
        }
        self._write_config_payload(payload)

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


@dataclass(frozen=True)
class CachedUsdIlsQuote:
    """Typed representation of cached USD/ILS quote stored in config.

    Fields:
    - `rate`: quote numeric value
    - `effective_date`: BOI quote effective date
    - `used_last_published`: whether BOI fell back to latest published day
    - `cached_at`: local timestamp when cache was written
    """

    rate: Decimal
    effective_date: date
    used_last_published: bool
    cached_at: datetime
