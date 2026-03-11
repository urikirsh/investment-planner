from __future__ import annotations

"""Reusable blocking loading overlay used during startup/async transitions.

The overlay is intentionally host-agnostic so it can be reused on other
screens (for example, future main-window data fetch flows).
"""

from math import ceil

from PySide6.QtCore import QEvent, QObject, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QHideEvent, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SpinningTicker(QWidget):
    """Painted spinner with fading ticks and timer-driven rotation."""

    def __init__(
        self,
        *,
        diameter: int = 132,
        tick_count: int = 12,
        tick_length: int = 28,
        tick_width: int = 8,
        color: QColor | None = None,
        interval_ms: int = 70,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tick_count = tick_count
        self._tick_length = tick_length
        self._tick_width = tick_width
        self._color = color or QColor("#222222")
        self._active_tick = 0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)
        self.setFixedSize(diameter, diameter)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _on_tick(self) -> None:
        self._active_tick = (self._active_tick + 1) % self._tick_count
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.rect().center())
        step_angle = 360.0 / self._tick_count
        for tick in range(self._tick_count):
            distance = (tick - self._active_tick) % self._tick_count
            alpha = ceil(255 * (1 - distance / self._tick_count))
            color = QColor(self._color)
            color.setAlpha(max(35, alpha))
            painter.setPen(QPen(color, self._tick_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(0, -self.width() / 2 + self._tick_width),
                QPointF(0, -self.width() / 2 + self._tick_width + self._tick_length),
            )
            painter.rotate(step_angle)


class LoadingOverlay(QWidget):
    """Semi-transparent overlay that blocks interaction and shows loading state.

    The overlay always tracks its parent geometry and consumes mouse/keyboard
    events while shown, so host widgets cannot be interacted with underneath.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("loading_overlay")
        self.setStyleSheet("background-color: rgba(100, 100, 100, 165);")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._spinner = SpinningTicker(parent=self)
        self._status_label = QLabel("fetching data", self)
        self._status_label.setObjectName("loading_overlay_status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            "font-size: 34px; font-weight: 700; color: #1f1f1f; border: none; background: transparent;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        layout.addStretch(1)
        layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        parent.installEventFilter(self)
        self._sync_to_parent_geometry()
        self.hide()

    def show_overlay(self) -> None:
        """Show overlay and capture focus so keyboard events stay blocked."""
        self._sync_to_parent_geometry()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def hide_overlay(self) -> None:
        """Hide overlay and release focus back to regular widget flow."""
        self.hide()
        self.clearFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep overlay geometry in sync when the parent moves or resizes."""
        if watched is self.parent() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            self._sync_to_parent_geometry()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        event.accept()

    def _sync_to_parent_geometry(self) -> None:
        """Resize overlay to fully cover the current parent client rect."""
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
