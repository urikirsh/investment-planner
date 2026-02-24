from __future__ import annotations

from PySide6.QtWidgets import QTreeWidget
from PySide6.QtCore import Qt, Signal

from ui.ui_types import RowKind, Col, ROLE_KIND


class InvestmentTreeWidget(QTreeWidget):
    """
    QTreeWidget that enforces:
    - Top-level items are only GROUP / NON_INVESTABLE_BUCKET
    - INSTRUMENT items must always have a parent (cannot be top-level)
    - GROUP items cannot be dropped under another group
    """

    items_reordered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QTreeWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)

    def _kind_of(self, item) -> RowKind | None:
        # Row kind is stored in the NAME column role.
        return item.data(Col.NAME.value, ROLE_KIND)

    def dropEvent(self, event):
        # Identify the dragged item (single-selection UI).
        dragged = self.currentItem()
        if dragged is None:
            event.ignore()
            return

        dragged_kind = self._kind_of(dragged)

        # Locate target item under cursor (may be None for viewport)
        pos_kind = self.dropIndicatorPosition()
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        target = self.itemAt(pos)

        # If dropping on empty viewport => would make item top-level (bad for instruments)
        if target is None:
            if dragged_kind == RowKind.INSTRUMENT.name:
                event.ignore()
                return
            # For groups, dropping to empty means reorder top-level, which is OK
            super().dropEvent(event)
            return

        target_kind = self._kind_of(target)

        # ---- Allow ON-ITEM only for instrument -> (group or bucket) ----
        if pos_kind == QTreeWidget.OnItem:
            if (
                dragged_kind == RowKind.INSTRUMENT.name
                and target_kind in (RowKind.GROUP.name, RowKind.NON_INVESTABLE_BUCKET.name)
            ):
                # Allowed: move instrument into that group/bucket
                super().dropEvent(event)
                self.items_reordered.emit()
                return

            # Any other "OnItem" drop is forbidden (prevents nesting groups, instruments under instruments, etc.)
            event.ignore()
            return

        # ---- For Above/Below: treat as reorder in the same level; enforce parent constraints ----
        # Above/Below an instrument means "same parent as that instrument"
        # Above/Below a group means "top-level reorder" (parent None)
        target_parent = target.parent()

        # Instruments must always have a parent (cannot become top-level)
        if dragged_kind == RowKind.INSTRUMENT.name:
            if target_parent is None:
                # Above/below a top-level item would make it top-level => forbid
                event.ignore()
                return

        # Groups/bucket must stay top-level (reorder among top-level only)
        if dragged_kind in (RowKind.GROUP.name, RowKind.NON_INVESTABLE_BUCKET.name):
            if target_parent is not None:
                # can't reorder groups inside a group's children
                event.ignore()
                return

        super().dropEvent(event)

        self.items_reordered.emit()
