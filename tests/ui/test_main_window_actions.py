from __future__ import annotations

"""Focused tests for ``MainWindowActionsMixin`` behavior."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import ui.main_window_actions as actions_mod
from ui.main_window_actions import MainWindowActionsMixin
from ui.ui_state import UnsavedChangesDecision


class _FakeHost(MainWindowActionsMixin):
    """Minimal host implementing dependencies required by the mixin."""

    session: Any
    tree: Any
    cash_value_edit: Any
    cash_reserve_edit: Any
    future_tax_edit: Any

    def __init__(self, *, current_file_path: Path | None) -> None:
        self.session = SimpleNamespace(
            current_file_path=current_file_path,
            default_json_path=Path("default.json"),
            document=SimpleNamespace(is_dirty=lambda: False),
        )
        self.tree = object()  # only passed through to patched adapter functions
        self.cash_value_edit = object()
        self.cash_reserve_edit = object()
        self.future_tax_edit = object()
        self._non_investable_bucket_id = "non_investable_bucket"
        self._non_investable_bucket_title = "Non-investable holdings (excluded from strategy)"

    def _update_file_context_ui(self) -> None:
        return None

    def _load_portfolio_from_file(self, path: Path) -> None:
        _ = path
        return None

    def _refresh_data(self) -> None:
        return None

    def _update_future_tax_visual_state(self) -> None:
        return None


def test_resolve_save_target_uses_current_path_when_available() -> None:
    current = Path("active.json")
    host = _FakeHost(current_file_path=current)

    assert host._resolve_save_target(force_save_as=False) == current


def test_resolve_save_target_uses_prompt_when_forced_or_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    prompted = Path("prompted.json")

    host_missing = _FakeHost(current_file_path=None)
    monkeypatch.setattr(host_missing, "_prompt_select_save_path", lambda: prompted)
    assert host_missing._resolve_save_target(force_save_as=False) == prompted

    host_forced = _FakeHost(current_file_path=Path("active.json"))
    monkeypatch.setattr(host_forced, "_prompt_select_save_path", lambda: prompted)
    assert host_forced._resolve_save_target(force_save_as=True) == prompted


@pytest.mark.parametrize(
    ("decision", "save_result", "expected", "save_calls"),
    [
        (UnsavedChangesDecision.SAVE, True, True, 1),
        (UnsavedChangesDecision.SAVE, False, False, 1),
        (UnsavedChangesDecision.DISCARD, True, True, 0),
        (UnsavedChangesDecision.CANCEL, True, False, 0),
    ],
)
def test_resolve_unsaved_changes_decision(
    monkeypatch: pytest.MonkeyPatch,
    decision: UnsavedChangesDecision,
    save_result: bool,
    expected: bool,
    save_calls: int,
) -> None:
    host = _FakeHost(current_file_path=Path("active.json"))
    calls: list[dict[str, Any]] = []

    def fake_save_current_or_save_as(*, show_success: bool, force_save_as: bool = False) -> bool:
        calls.append({"show_success": show_success, "force_save_as": force_save_as})
        return save_result

    monkeypatch.setattr(host, "_save_current_or_save_as", fake_save_current_or_save_as)

    assert host._resolve_unsaved_changes_decision(decision) is expected
    assert len(calls) == save_calls
    if save_calls:
        assert calls[0] == {"show_success": False, "force_save_as": False}


def test_has_unsaved_main_changes_handles_parse_failure_and_dirty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    host = _FakeHost(current_file_path=Path("active.json"))

    # Parse failure should be treated as unsaved changes.
    monkeypatch.setattr(
        actions_mod,
        "build_portfolio_data_from_main_editor",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("bad input")),
    )
    assert host._has_unsaved_main_changes() is True

    # Successful parse should defer to document dirty state.
    monkeypatch.setattr(actions_mod, "build_portfolio_data_from_main_editor", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(actions_mod, "sync_document_from_data", lambda session, data: None)
    host.session.document = SimpleNamespace(is_dirty=lambda: True)
    assert host._has_unsaved_main_changes() is True

    host.session.document = SimpleNamespace(is_dirty=lambda: False)
    assert host._has_unsaved_main_changes() is False
