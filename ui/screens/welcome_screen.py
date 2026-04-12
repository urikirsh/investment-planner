"""Welcome/startup screen UI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ui.shared.button_styles import apply_primary_action_button_style, apply_secondary_action_button_style


class WelcomeScreen(QWidget):
    """Startup screen with file-entry actions."""

    def __init__(self, *, app_version: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build(app_version=app_version)

    def _build(self, *, app_version: str | None) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(12)
        layout.addStretch(1)

        title = QLabel("Welcome")
        title.setObjectName("welcome_title")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.version_label = QLabel("")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setStyleSheet("color: #666666;")
        layout.addWidget(self.version_label)
        self.set_app_version(app_version)

        self.open_last_btn = QPushButton("Open Last Portfolio")
        self.open_last_btn.setMinimumHeight(36)
        apply_primary_action_button_style(self.open_last_btn)
        layout.addWidget(self.open_last_btn)

        self.last_path_label = QLabel("No recent portfolio")
        self.last_path_label.setObjectName("welcome_last_path")
        self.last_path_label.setWordWrap(True)
        self.last_path_label.setToolTip("")
        layout.addWidget(self.last_path_label)

        self.load_different_btn = QPushButton("Load Portfolio...")
        apply_secondary_action_button_style(self.load_different_btn)
        self.start_new_btn = QPushButton("Start New File")
        apply_secondary_action_button_style(self.start_new_btn)
        self.quit_btn = QPushButton("Quit")
        for button in (self.load_different_btn, self.start_new_btn, self.quit_btn):
            button.setMinimumHeight(36)
            layout.addWidget(button)
        layout.addStretch(1)

    def set_app_version(self, app_version: str | None) -> None:
        """Render version label from optional version text."""
        if app_version is None:
            self.version_label.setVisible(False)
            self.version_label.setText("")
            return
        self.version_label.setText(f"Version {app_version}")
        self.version_label.setVisible(True)

    def set_last_portfolio_status(
        self,
        *,
        button_enabled: bool,
        path_text: str,
        path_tooltip: str,
        missing_path: bool,
    ) -> None:
        """Update last-portfolio button availability and path display."""
        self.open_last_btn.setEnabled(button_enabled)
        self.last_path_label.setText(path_text)
        self.last_path_label.setToolTip(path_tooltip)
        if missing_path:
            self.last_path_label.setStyleSheet("color: #b00020;")
        else:
            self.last_path_label.setStyleSheet("")
