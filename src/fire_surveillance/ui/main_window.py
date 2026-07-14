"""MainWindow — assembles the docked layout and wires the frame bridge.

Layout mirrors the reference Avalonia ``MainWindow``: a title bar docked on
top, a footer docked on bottom, and a central splitter with the image view on
the left and the control panel on the right.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..device import CameraManager
from ..workers import FrameBridge
from .control_panel import ControlPanel
from .footer import Footer
from .image_view import ImageView
from .title_bar import TitleBar


class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("九恒科技 - IR 监控系统 | v0.1 | © 2026")
        self.setMinimumSize(1280, 1024)
        self.resize(1280, 860)

        central = QWidget(objectName="CentralWidget")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top dock.
        self.title_bar = TitleBar()
        root.addWidget(self.title_bar)

        # Central splitter: image view | control panel.
        self.image_view = ImageView()
        self.control_panel = ControlPanel()

        left_card = QFrame(objectName="Card")
        left_layout = QHBoxLayout(left_card)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.image_view)

        right_card = QFrame(objectName="Glass")
        right_layout = QHBoxLayout(right_card)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.control_panel)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(8)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(left_card)
        self.splitter.addWidget(right_card)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([900, 460])

        body = QFrame()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.addWidget(self.splitter)
        root.addWidget(body, stretch=1)

        # Bottom dock.
        self.footer = Footer()
        root.addWidget(self.footer)

        # Cross-widget wiring.
        self.footer.camera_controls.recording_changed.connect(
            self.title_bar.system_status.set_recording
        )
        # Playback bar visibility/range/seek.
        self.footer.camera_controls.playback_active.connect(
            self.image_view.set_playback_visible
        )
        self.footer.camera_controls.playback_ready.connect(
            self.image_view.set_playback_range
        )
        self.bridge_playback_connected = False  # connected on first ready
        self.footer.camera_controls.playback_ready.connect(self._connect_playback_progress)
        self.image_view.seek_requested.connect(
            lambda sec: CameraManager.instance().seek(sec)
        )

        # Frame/status bridge.
        self.bridge = FrameBridge(self)
        self.bridge.frame_ready.connect(self.image_view.display_frame)
        self.bridge.status_changed.connect(
            self.title_bar.system_status.set_camera_status
        )
        self.bridge.start()

    def _connect_playback_progress(self, _duration: float) -> None:
        """Wire playback position updates once a replay source is ready."""
        if self.bridge_playback_connected:
            return
        self.bridge.playback_progress.connect(self.image_view.set_playback_position)
        self.bridge_playback_connected = True

    # --- shutdown -------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        try:
            # Stop recording + camera before tearing down, so no worker writes
            # to a destroyed widget.
            manager = CameraManager.instance()
            manager.stop_camera()
            self.bridge.stop()
        finally:
            super().closeEvent(event)
