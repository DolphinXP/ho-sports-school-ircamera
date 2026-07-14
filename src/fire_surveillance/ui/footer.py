"""Footer — bottom dock hosting the camera control bar."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QWidget

from .camera_controls import CameraControls


class Footer(QFrame):
    """Bottom bar that holds :class:`CameraControls`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Footer")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)

        self.camera_controls = CameraControls()
        layout.addWidget(self.camera_controls)
        layout.addStretch()
