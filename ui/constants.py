"""Shared UI-level constants.

`APP_VERSION` is read from `pyproject.toml` and surfaced in the startup
welcome screen.
"""

from __future__ import annotations

from pathlib import Path
import tomllib

APP_NAME = "Investment Planner"
_DEFAULT_APP_VERSION = "0.1.0"


def _read_project_version_from_pyproject() -> str:
    """Read app version from repository `pyproject.toml`."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        raw = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return _DEFAULT_APP_VERSION

    project = raw.get("project")
    if not isinstance(project, dict):
        return _DEFAULT_APP_VERSION
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        return _DEFAULT_APP_VERSION
    return version


APP_VERSION = _read_project_version_from_pyproject()
