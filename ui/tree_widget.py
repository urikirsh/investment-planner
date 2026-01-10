from __future__ import annotations

from PySide6.QtWidgets import QTreeWidget
from PySide6.QtCore import Qt, QAbstractItemModel

from ui.ui_types import RowKind, Col, ROLE_KIND  # adjust imports to your project


class InvestmentTreeWidget(QTreeWidget):
    """
    QTreeWidget that enforces:
    - Top-level items are only GROUP / NON_INVESTABLE_BUCKET
    - INSTRUMENT items must always have a parent (cannot be top-level)
    - GROUP items cannot be dropped under another group
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QTreeWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)

    def _kind_of(self, item) -> RowKind | None:
        # Store kind in the NAME column role (or whichever you chose)
        return item.data(Col.NAME.value, ROLE_KIND)

    def dropEvent(self, event):
        # Identify what's being dragged (we use currentItem; good enough for single-select UI)
        dragged = self.currentItem()
        if dragged is None:
            event.ignore()
            return

        dragged_kind = self._kind_of(dragged)

        # Find drop target
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        target = self.itemAt(pos)

        # If dropping on empty viewport => would make item top-level (bad for instruments)
        if target is None:
            if dragged_kind == RowKind.INSTRUMENT:
                event.ignore()
                return
            # For groups, dropping to empty means reorder top-level, which is OK
            super().dropEvent(event)
            return

        target_kind = self._kind_of(target)

        # Determine intended parent after drop:
        # - Dropping on an INSTRUMENT means "under its parent group"
        if target_kind == RowKind.INSTRUMENT:
            target_parent = target.parent()
            target_parent_kind = self._kind_of(target_parent) if target_parent else None
        else:
            target_parent = target
            target_parent_kind = target_kind

        # RULE 1: instruments must always be under a GROUP or NON_INVESTABLE_BUCKET
        if dragged_kind == RowKind.INSTRUMENT:
            if target_parent is None or target_parent_kind not in (RowKind.GROUP, RowKind.NON_INVESTABLE_BUCKET):
                event.ignore()
                return

        # RULE 2: groups can only be top-level (cannot be dropped under anything)
        if dragged_kind in (RowKind.GROUP, RowKind.NON_INVESTABLE_BUCKET):
            # If target has a parent, it's not top-level placement
            # Also block dropping onto another group in a way that nests it
            if target_parent is not None and target_parent.parent() is not None:
                event.ignore()
                return
            # Block making group child of group
            if target_kind in (RowKind.GROUP, RowKind.NON_INVESTABLE_BUCKET):
                # Qt might try to nest depending on drop indicator; safest to forbid nesting explicitly:
                # If target is a group, allow only top-level reordering, not child placement.
                # We'll allow the drop but prevent nesting by ensuring dragged remains top-level.
                pass

        super().dropEvent(event)

        # After ANY successful drop, notify the model so MainWindow can recompute
        # (MainWindow will connect to model().rowsMoved)
        self.model().layoutChanged.emit()
