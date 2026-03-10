from __future__ import annotations

"""Save/Open/New action flows for the main window controller.

This module isolates file-oriented actions and unsaved-changes prompting so
`MainWindow` can stay focused on wiring screens and coordinating flow.
"""

from pathlib import Path
from typing import Optional, cast

from PySide6.QtWidgets import QLineEdit, QTreeWidget, QWidget

from portfolio_core.portfolio_session import PortfolioSession
from portfolio_core.use_cases import save_document_from_data, sync_document_from_data
from ui.dialogs import choose_open_path, choose_save_path, confirm_unsaved_changes, show_error, show_info
from ui.portfolio_editor_adapter import build_portfolio_data_from_main_editor
from ui.ui_state import UnsavedChangesDecision


class MainWindowActionsMixin:
    """Mixin containing save/open/new actions and unsaved-change handling.

    Host methods declared with ``...`` are intentionally interface stubs:
    the concrete ``MainWindow`` implementation provides them.
    """

    session: PortfolioSession
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    _non_investable_bucket_id: str
    _non_investable_bucket_title: str

    def _update_file_context_ui(self) -> None:
        """Refresh file-related UI context after load/save/new flows."""
        ...

    def _load_portfolio_from_file(self, path: Path) -> None:
        """Load portfolio at ``path`` into the main editor state."""
        ...

    def _refresh_data(self) -> None:
        """Recompute and rerender derived values on the main screen."""
        ...

    def _update_future_tax_visual_state(self) -> None:
        """Apply visual cues for current future-tax value."""
        ...

    def _load_default_document(self) -> None:
        """Load default portfolio as a new unsaved document into main editor."""
        ...

    def _save_from_main_ui(self, target_path: Path) -> None:
        """Build, parse, validate and persist current main-screen portfolio state."""
        data = build_portfolio_data_from_main_editor(
            tree=self.tree,
            cash_value_edit=self.cash_value_edit,
            cash_reserve_edit=self.cash_reserve_edit,
            future_tax_edit=self.future_tax_edit,
            allow_partial=False,
        )
        save_document_from_data(self.session, data, target_path)
        self._update_file_context_ui()

    def _show_info(self, title: str, message: str) -> None:
        """Show informational feedback via one overridable wrapper."""
        show_info(cast(QWidget, self), title, message)

    def _show_error(self, title: str, message: str) -> None:
        """Show error feedback via one overridable wrapper."""
        show_error(cast(QWidget, self), title, message)

    def _prompt_select_save_path(self) -> Optional[Path]:
        """Prompt for save location and return normalized target path, or ``None`` if canceled."""
        start_path = self.session.current_file_path or self.session.default_json_path
        return choose_save_path(cast(QWidget, self), start_path=start_path)

    def _prompt_select_open_path(self) -> Optional[Path]:
        """Prompt for portfolio file to open, or return ``None`` if canceled."""
        start_path = self.session.current_file_path or self.session.default_json_path
        return choose_open_path(cast(QWidget, self), start_dir=start_path.parent)

    def _resolve_save_target(self, *, force_save_as: bool) -> Optional[Path]:
        """Resolve destination path for save flows before executing write action."""
        target = None if force_save_as else self.session.current_file_path
        if target is None:
            target = self._prompt_select_save_path()
        return target

    def _execute_save_to_target(self, target: Path, *, show_success: bool) -> bool:
        """Execute save action for a resolved path and emit success/error feedback."""
        try:
            self._save_from_main_ui(target)
            if show_success:
                self._show_info("Saved", f"Portfolio saved to:\n{target}")
            return True
        except Exception as e:
            self._show_error("Validation / Save failed", str(e))
            return False

    def _save_current_or_save_as(self, *, show_success: bool, force_save_as: bool = False) -> bool:
        """Save current editor state to active file or a newly selected file."""
        target = self._resolve_save_target(force_save_as=force_save_as)
        if target is None:
            return False
        return self._execute_save_to_target(target, show_success=show_success)

    def _open_portfolio_from_path(self, path: Path) -> bool:
        """Load selected portfolio path and report success."""
        try:
            self._load_portfolio_from_file(path)
            return True
        except Exception as e:
            self._show_error("Load failed", f"Failed loading JSON:\n{e}")
            return False

    def _open_portfolio_from_picker(self) -> bool:
        """Prompt for a portfolio path, then execute open action."""
        path = self._prompt_select_open_path()
        if path is None:
            return False
        return self._open_portfolio_from_path(path)

    def _prompt_unsaved_changes_decision(self, action_text: str) -> UnsavedChangesDecision:
        """Prompt unsaved-changes confirmation and return typed decision outcome."""
        return confirm_unsaved_changes(cast(QWidget, self), action_text=action_text)

    def _resolve_unsaved_changes_decision(self, decision: UnsavedChangesDecision) -> bool:
        """Apply typed unsaved-changes decision without opening prompt dialogs."""
        if decision == UnsavedChangesDecision.SAVE:
            return self._save_current_or_save_as(show_success=False)
        if decision == UnsavedChangesDecision.DISCARD:
            return True
        return False

    def _confirm_continue_with_unsaved_changes(self, action_text: str) -> bool:
        """Run unsaved-changes prompt + action resolution, returning continuation intent."""
        if not self._has_unsaved_main_changes():
            return True

        decision = self._prompt_unsaved_changes_decision(action_text)
        return self._resolve_unsaved_changes_decision(decision)

    def _on_save_clicked(self) -> None:
        """Handle `Save` action from main screen."""
        self._save_current_or_save_as(show_success=True)

    def _on_save_as_clicked(self) -> None:
        """Handle `Save As` action from main screen."""
        self._save_current_or_save_as(show_success=True, force_save_as=True)

    def _on_open_clicked(self) -> None:
        """Handle `Open` action with unsaved-changes safeguard."""
        if not self._confirm_continue_with_unsaved_changes("opening another portfolio"):
            return
        self._open_portfolio_from_picker()

    def _on_new_clicked(self) -> None:
        """Handle `New` action by loading default portfolio after confirmation."""
        if not self._confirm_continue_with_unsaved_changes("creating a new portfolio"):
            return
        self._load_default_document()

    def _has_unsaved_main_changes(self) -> bool:
        """Compare current UI state against the last loaded/saved snapshot."""
        try:
            current_data = build_portfolio_data_from_main_editor(
                tree=self.tree,
                cash_value_edit=self.cash_value_edit,
                cash_reserve_edit=self.cash_reserve_edit,
                future_tax_edit=self.future_tax_edit,
                allow_partial=True,
            )
            sync_document_from_data(self.session, current_data)
        except Exception:
            return True

        return self.session.document.is_dirty()
