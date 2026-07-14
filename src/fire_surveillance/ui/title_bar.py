"""TitleBar — top bar with brand + system status cards."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPaintEvent, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from .system_status import SystemStatus
from .theme import C


class _LogoBadge(QLabel):
    """A small rounded brand badge (drawn, so no binary asset is needed)."""

    def __init__(self, text: str = "九恒", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFixedSize(44, 44)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"color:white; font-size:15px; font-weight:700; "
            f"background-color:{C.accent}; border-radius:10px;"
        )

    # No custom paint — the stylesheet handles the rounded background.
    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        # Fill rounded rect manually so the border-radius is exact on all styles.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(C.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 10, 10)
        super().paintEvent(_event)


class TitleBar(QFrame):
    """Top dock: brand on the left, system status on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setMinimumHeight(64)
        self.setMaximumHeight(72)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(14)

        self._logo = _LogoBadge()
        layout.addWidget(self._logo)

        self._title = QLabel("野外森林火情监测实验及验证")
        self._title.setObjectName("AppTitle")
        layout.addWidget(self._title)
        layout.addStretch()

        self.system_status = SystemStatus()
        layout.addWidget(self.system_status, alignment=Qt.AlignmentFlag.AlignRight)
