from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

import ui.dialogs as dialogs
from ui.ui_state import UnsavedChangesDecision


def test_choose_save_path_appends_json_suffix(monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path: Path) -> None:
    _ = qapp
    parent = QWidget()

    selected_path = tmp_path / "portfolio"
    monkeypatch.setattr("ui.dialogs.QFileDialog.getSaveFileName", lambda *args, **kwargs: (str(selected_path), ""))

    chosen = dialogs.choose_save_path(parent, start_path=tmp_path / "start.json")
    assert chosen == tmp_path / "portfolio.json"


def test_choose_save_path_returns_none_when_canceled(
    monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path: Path
) -> None:
    _ = qapp
    parent = QWidget()

    monkeypatch.setattr("ui.dialogs.QFileDialog.getSaveFileName", lambda *args, **kwargs: ("", ""))

    assert dialogs.choose_save_path(parent, start_path=tmp_path / "start.json") is None


def test_choose_open_path_returns_none_when_canceled(
    monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path: Path
) -> None:
    _ = qapp
    parent = QWidget()

    monkeypatch.setattr("ui.dialogs.QFileDialog.getOpenFileName", lambda *args, **kwargs: ("", ""))

    assert dialogs.choose_open_path(parent, start_dir=tmp_path) is None


def test_choose_open_path_returns_selected_path(monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path: Path) -> None:
    _ = qapp
    parent = QWidget()

    selected_path = tmp_path / "portfolio.json"
    monkeypatch.setattr("ui.dialogs.QFileDialog.getOpenFileName", lambda *args, **kwargs: (str(selected_path), ""))

    assert dialogs.choose_open_path(parent, start_dir=tmp_path) == selected_path


@pytest.mark.parametrize(
    ("clicked_key", "expected"),
    [
        ("save", UnsavedChangesDecision.SAVE),
        ("dont_save", UnsavedChangesDecision.DISCARD),
        ("cancel", UnsavedChangesDecision.CANCEL),
        ("none", UnsavedChangesDecision.CANCEL),
    ],
)
def test_confirm_unsaved_changes_maps_button_selection(
    monkeypatch: pytest.MonkeyPatch, qapp: object, clicked_key: str, expected: UnsavedChangesDecision
) -> None:
    _ = qapp

    class FakeMessageBox:
        class Icon:
            Warning = object()

        class ButtonRole:
            AcceptRole = object()
            DestructiveRole = object()
            RejectRole = object()

        next_clicked_key = clicked_key

        def __init__(self, parent: QWidget) -> None:
            self._save_btn: object | None = None
            self._dont_save_btn: object | None = None
            self._cancel_btn: object | None = None
            self._clicked: object | None = None

        def setIcon(self, icon: object) -> None:
            _ = icon

        def setWindowTitle(self, title: str) -> None:
            _ = title

        def setText(self, text: str) -> None:
            _ = text

        def setInformativeText(self, text: str) -> None:
            _ = text

        def addButton(self, label: str, role: object) -> object:
            _ = role
            btn = object()
            if label == "Save":
                self._save_btn = btn
            elif label == "Don't Save":
                self._dont_save_btn = btn
            elif label == "Cancel":
                self._cancel_btn = btn
            return btn

        def setDefaultButton(self, button: object) -> None:
            _ = button

        def exec(self) -> None:
            if self.next_clicked_key == "save":
                self._clicked = self._save_btn
            elif self.next_clicked_key == "dont_save":
                self._clicked = self._dont_save_btn
            elif self.next_clicked_key == "cancel":
                self._clicked = self._cancel_btn
            else:
                self._clicked = None

        def clickedButton(self) -> object | None:
            return self._clicked

    monkeypatch.setattr(dialogs, "QMessageBox", FakeMessageBox)

    result = dialogs.confirm_unsaved_changes(QWidget(), action_text="opening another portfolio")
    assert result == expected
