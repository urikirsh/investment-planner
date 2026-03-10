"""Application metadata helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import tomllib


def _read_project_version_from_pyproject() -> str | None:
    """Read app version from repository `pyproject.toml`."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        raw = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None

    project = raw.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        return None
    return version


@lru_cache(maxsize=1)
def get_app_version() -> str | None:
    """Resolve and cache app version lazily at first call."""
    return _read_project_version_from_pyproject()
