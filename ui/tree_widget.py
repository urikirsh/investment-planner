from __future__ import annotations

from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem, QWidget
from PySide6.QtCore import Qt, Signal

from ui.ui_types import RowKind, ROLE_KIND


class InvestmentTreeWidget(QTreeWidget):
    """
    QTreeWidget that enforces:
    - Top-level items are only GROUP / NON_INVESTABLE_BUCKET
    - INSTRUMENT items must always have a parent (cannot be top-level)
    - GROUP items cannot be dropped under another group
    """

    items_reordered = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize tree widget with internal drag-and-drop behavior."""
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)

    def _kind_of(self, item: QTreeWidgetItem) -> RowKind | None:
        """
        Return the semantic row kind stored in item metadata.

        Row kind is stored in column index 0 under `ROLE_KIND` and parsed via
        `RowKind.from_raw` to tolerate missing/invalid metadata.
        """
        return RowKind.from_raw(item.data(0, ROLE_KIND))

    def dropEvent(self, event: QDropEvent) -> None:
        """
        Enforce portfolio-tree structural invariants during drag-and-drop.

        Rules enforced:
        - Group and non-investable bucket rows remain top-level only.
        - Instrument rows must always have a parent (group or bucket).
        - On-item drops are only allowed for instrument -> (group or bucket).

        Emits
        -----
        items_reordered
            Emitted after successful accepted drops that may affect display order
            or parent-child relationships.
        """
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
            if dragged_kind == RowKind.INSTRUMENT:
                event.ignore()
                return
            # For groups, dropping to empty means reorder top-level, which is OK
            super().dropEvent(event)
            return

        target_kind = self._kind_of(target)

        # ---- Allow ON-ITEM only for instrument -> (group or bucket) ----
        if pos_kind == QAbstractItemView.DropIndicatorPosition.OnItem:
            if (
                dragged_kind == RowKind.INSTRUMENT
                and target_kind in (RowKind.GROUP, RowKind.NON_INVESTABLE_BUCKET)
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
        if dragged_kind == RowKind.INSTRUMENT:
            if target_parent is None:
                # Above/below a top-level item would make it top-level => forbid
                event.ignore()
                return

        # Groups/bucket must stay top-level (reorder among top-level only)
        if dragged_kind in (RowKind.GROUP, RowKind.NON_INVESTABLE_BUCKET):
            if target_parent is not None:
                # can't reorder groups inside a group's children
                event.ignore()
                return

        super().dropEvent(event)

        self.items_reordered.emit()
