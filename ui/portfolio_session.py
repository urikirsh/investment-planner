from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QStandardPaths

from investment_planner.io_json import load_portfolio
from investment_planner.models import Portfolio

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
    return load_portfolio(DEFAULT_PORTFOLIO_DATA)


class PortfolioSession:
    def __init__(self, default_json_path: Path):
        self.default_json_path = default_json_path
        self.current_file_path: Optional[Path] = None
        self.saved_portfolio_snapshot: Optional[Portfolio] = None
        self._config_path = self._resolve_config_path()

    def _resolve_config_path(self) -> Path:
        app_cfg_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        base_dir = Path(app_cfg_dir) if app_cfg_dir else Path.home() / ".investment_planner"
        return base_dir / "config.json"

    def _read_last_loaded_path_from_config(self) -> Optional[Path]:
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
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_portfolio_path": str(path.resolve()) if path is not None else ""}
        self._config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def set_active_file_path(self, path: Optional[Path]) -> None:
        self.current_file_path = path
        try:
            self._write_last_loaded_path_to_config(path)
        except Exception:
            # Non-fatal: config persistence should not block main workflow.
            pass

    def resolve_startup_path(self) -> Optional[Path]:
        startup_path = self._read_last_loaded_path_from_config()
        if startup_path is not None and not startup_path.exists():
            self.set_active_file_path(None)
            startup_path = None

        if startup_path is None and self.default_json_path.exists():
            startup_path = self.default_json_path

        return startup_path

    def mark_loaded(self, portfolio: Portfolio, source_path: Path) -> None:
        self.saved_portfolio_snapshot = portfolio
        self.set_active_file_path(source_path)

    def mark_saved(self, portfolio: Portfolio, target_path: Path) -> None:
        self.saved_portfolio_snapshot = portfolio
        self.set_active_file_path(target_path)

    def mark_new_unsaved(self, portfolio: Portfolio) -> None:
        self.saved_portfolio_snapshot = portfolio
        self.set_active_file_path(None)

    def has_unsaved_changes(self, current_portfolio: Portfolio) -> bool:
        if self.saved_portfolio_snapshot is None:
            return True
        return current_portfolio != self.saved_portfolio_snapshot
