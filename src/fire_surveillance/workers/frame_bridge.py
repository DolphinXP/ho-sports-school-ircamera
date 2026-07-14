"""Qt <-> camera threading bridge.

The :class:`RtspCamera` / :class:`FFmpegCamera` runs its own capture thread and
pushes frames through a plain callback. Qt widgets must only be touched from the
GUI thread, so this module provides a :class:`FrameBridge` (a ``QObject``) that:

* registers itself as a frame callback on :class:`CameraManager`,
* applies the current pseudo-color mode (raw / rainbow / iron),
* converts each BGR ``numpy`` frame to a self-contained ``QImage`` (``.copy()``
  detaches from the numpy buffer, making it safe to pass across threads), and
* emits ``frame_ready`` — Qt marshals the signal onto the receiver's thread via
  a queued connection, so the ImageView can paint safely.

A ``QTimer`` polls camera status (open / capturing / fps) and playback progress
(position / duration) and re-emits them as typed signals.
"""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from ..device import color
from ..device import CameraManager


class FrameBridge(QObject):
    """Bridges camera frames/status into Qt signals (GUI-thread safe)."""

    #: Emitted for every delivered frame. Carries a self-contained RGB888 QImage.
    frame_ready = Signal(QImage)
    #: Emitted ~5x/sec with (is_open, is_capturing, fps).
    status_changed = Signal(bool, bool, float)
    #: Emitted ~5x/sec with (position_sec, duration_sec) for playback sources.
    playback_progress = Signal(float, float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = CameraManager.instance()
        self._manager.add_frame_callback(self._on_frame)

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(200)  # ms
        self._status_timer.timeout.connect(self._poll)

    def start(self) -> None:
        """Begin polling. Frame relay starts automatically."""
        self._status_timer.start()

    def stop(self) -> None:
        self._status_timer.stop()
        self._manager.remove_frame_callback(self._on_frame)

    # --- frame callback (runs on the camera capture thread) -------------
    def _on_frame(self, frame: np.ndarray, w: int, h: int, ts: float) -> None:
        # Apply the current pseudo-color mode before display.
        try:
            colored = color.render(frame, self._manager.get_color_mode())
        except Exception as exc:  # noqa: BLE001 — never block capture on a render error
            print(f"[FrameBridge] color render error: {exc}")
            colored = frame
        qimg = self._to_qimage(colored)
        if qimg is not None:
            self.frame_ready.emit(qimg)

    @staticmethod
    def _to_qimage(frame: np.ndarray) -> QImage | None:
        if frame is None or frame.size == 0:
            return None
        if frame.ndim == 3 and frame.shape[2] == 3:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            rgb = frame
        h, w = rgb.shape[:2]
        ch = rgb.shape[2] if rgb.ndim == 3 else 1
        if ch == 1:
            return QImage(rgb.data, w, h, w, QImage.Format_Grayscale8).copy()
        bytes_per_line = ch * w
        # .copy() detaches from the numpy buffer -> safe across threads.
        return QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()

    # --- status polling (runs on the GUI thread via QTimer) -------------
    def _poll(self) -> None:
        is_open, is_capturing, fps = self._manager.get_status()
        self.status_changed.emit(bool(is_open), bool(is_capturing), float(fps))
        if self._manager.is_playable():
            self.playback_progress.emit(
                float(self._manager.playback_position()),
                float(self._manager.playback_duration()),
            )

    def status_snapshot(self) -> Tuple[bool, bool, float]:
        is_open, is_capturing, fps = self._manager.get_status()
        return bool(is_open), bool(is_capturing), float(fps)
