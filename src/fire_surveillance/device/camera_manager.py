"""Camera manager — application-level singleton over the camera device.

Mirrors the reference .NET ``CameraInstance``: owns the active camera, the
camera list, recording state, and relays frames to subscribers. GUI-agnostic.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np

from ..config import CameraList
from . import ffmpeg as ffmpeg_backend
from .camera import FrameCallback, ICamera, RtspCamera
from .ffmpeg import FFmpegCamera


class CameraManager:
    """Process-wide camera manager (singleton)."""

    _instance: Optional["CameraManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._camera_list = CameraList()
        self._capture_backend: str = "ffmpeg"
        self._camera: ICamera = self._make_camera(self._capture_backend)
        self._lock = threading.Lock()
        self._frame_callbacks: List[FrameCallback] = []
        # Latest raw frame cache (for save-image).
        self._latest_frame: Optional[np.ndarray] = None
        # Pseudo-color mode for display + save.
        self._color_mode: str = "raw"

        # Recording state.
        self._writer: Optional[cv2.VideoWriter] = None
        self._recording_dir: Optional[Path] = None
        self._custom_file_name: Optional[str] = None
        self._record_frame_size: Optional[tuple] = None  # (w, h, fps)

        # Wire the camera frame delivery through our relay so multiple
        # subscribers (display + recorder) both receive frames.
        self._camera.set_frame_callback(self._relay_frame)

    def _make_camera(self, backend: str) -> ICamera:
        """Create a fresh camera of the requested engine type."""
        if backend == "ffmpeg" and ffmpeg_backend.is_available():
            return FFmpegCamera()
        return RtspCamera()

    # --- singleton ------------------------------------------------------
    @classmethod
    def instance(cls) -> "CameraManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # --- camera list ----------------------------------------------------
    @property
    def camera_list(self) -> CameraList:
        return self._camera_list

    def refresh_camera_list(self) -> List[str]:
        self._camera_list.reload()
        return self._camera_list.urls()

    def get_camera_urls(self) -> List[str]:
        return self._camera_list.urls()

    def add_camera(self, url: str, name: Optional[str] = None) -> bool:
        return self._camera_list.add(url, name)

    def remove_camera(self, url: str) -> bool:
        return self._camera_list.remove(url)

    # --- frame subscribers ---------------------------------------------
    def add_frame_callback(self, callback: FrameCallback) -> None:
        with self._lock:
            self._frame_callbacks.append(callback)

    def remove_frame_callback(self, callback: FrameCallback) -> None:
        with self._lock:
            try:
                self._frame_callbacks.remove(callback)
            except ValueError:
                pass

    def _relay_frame(self, frame: np.ndarray, w: int, h: int, ts: float) -> None:
        # Cache the latest frame for save-image and recorder.
        self._latest_frame = frame
        # Recorder runs first so a frame is never missed when the UI is slow.
        self._record_frame(frame)
        with self._lock:
            callbacks = list(self._frame_callbacks)
        for cb in callbacks:
            try:
                cb(frame, w, h, ts)
            except Exception as exc:  # noqa: BLE001
                print(f"[CameraManager] subscriber error: {exc}")

    # --- lifecycle ------------------------------------------------------
    def start_camera(self, url: str) -> bool:
        self._camera.set_extra_params(url, None)
        if not self._camera.open_camera():
            return False
        if not self._camera.start_capture():
            return False
        return True

    def stop_camera(self) -> None:
        # Always stop any recording; only touch the camera if it's actually open.
        self.stop_recording()
        if not self._camera.is_open():
            return
        self._camera.stop_capture()
        self._camera.close_camera()

    def is_running(self) -> bool:
        return self._camera.is_capturing()

    def get_status(self):
        return self._camera.get_status()

    def set_exposure(self, value: int) -> bool:
        # RTSP exposure is controlled at the hardware; we store it for parity.
        return self._camera.set_exposure(float(value))

    # --- playback (file sources) ---------------------------------------
    def is_playable(self) -> bool:
        return self._camera.is_playable_source()

    def playback_duration(self) -> float:
        return self._camera.duration_seconds()

    def playback_position(self) -> float:
        return self._camera.position_seconds()

    def seek(self, seconds: float) -> bool:
        return self._camera.seek_seconds(float(seconds))

    def set_paused(self, paused: bool) -> None:
        self._camera.set_paused(bool(paused))

    def is_paused(self) -> bool:
        return self._camera.is_paused()

    # --- color mode + save image ---------------------------------------
    def set_color_mode(self, mode: str) -> None:
        from .color import normalize
        self._color_mode = normalize(mode)

    def get_color_mode(self) -> str:
        return self._color_mode

    def latest_frame(self) -> Optional[np.ndarray]:
        """Return a copy of the most recent raw frame (or None)."""
        frame = self._latest_frame
        return None if frame is None else frame.copy()

    def save_current_image(self, directory: str, name: Optional[str] = None) -> Optional[str]:
        """Save the latest frame (with the current color mode) to ``directory``.

        Returns the written file path, or None if no frame is available.
        """
        from datetime import datetime

        from .color import render

        frame = self._latest_frame
        if frame is None:
            return None
        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = (name and name.strip()) or datetime.now().strftime("img_%Y%m%d_%H%M%S_%f")
        if not base.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
            base += ".png"
        out_path = out_dir / base
        image = render(frame, self._color_mode)
        ok = cv2.imwrite(str(out_path), image)
        if not ok:
            print(f"[CameraManager] imwrite failed: {out_path}")
            return None
        print(f"[CameraManager] saved image -> {out_path} (mode={self._color_mode})")
        return str(out_path)

    def configure_rtsp(
        self,
        transport: str = "tcp",
        backend: str = "ffmpeg",
        timeout_us: int | None = None,
    ) -> None:
        """Reconfigure the active camera's RTSP transport/backend/timeout.

        If ``backend`` differs from the current engine and the camera is idle,
        the underlying camera object is swapped to the requested engine.
        """
        # Swap engine when idle and a different engine is requested.
        if backend != self._capture_backend and not self._camera.is_open():
            self._capture_backend = backend
            self._camera = self._make_camera(backend)
            self._camera.set_frame_callback(self._relay_frame)

        self._camera.set_rtsp_transport(transport)
        if timeout_us is not None:
            self._camera.set_rtsp_timeout(timeout_us)
        # cv2 sub-backend only applies to RtspCamera.
        set_cv2_backend = getattr(self._camera, "set_backend", None)
        if callable(set_cv2_backend):
            set_cv2_backend(backend if backend in {"ffmpeg", "gstreamer", "any"} else "ffmpeg")

    def capture_backend(self) -> str:
        return self._capture_backend

    def ffmpeg_path(self) -> Optional[str]:
        return ffmpeg_backend.find_ffmpeg()

    # --- recording ------------------------------------------------------
    def set_recording_dir(self, path: str) -> None:
        self._recording_dir = Path(path) if path else None

    def set_custom_file_name(self, name: Optional[str]) -> None:
        self._custom_file_name = name

    def start_recording(self, directory: str, custom_name: Optional[str] = None) -> bool:
        if not self.is_running():
            print("[CameraManager] cannot record: camera not running")
            return False

        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._recording_dir = out_dir
        if custom_name is not None:
            self._custom_file_name = custom_name

        base = self._custom_file_name or datetime.now().strftime("BigIR_%Y%m%d_%H%M%S")
        if not base.lower().endswith(".mp4"):
            base = f"{base}.mp4"
        out_path = out_dir / base

        w = self._camera.cam_param.width
        h = self._camera.cam_param.height
        if w <= 0 or h <= 0:
            print("[CameraManager] cannot record: unknown frame size")
            return False

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps = max(1.0, min(60.0, self._camera.stat.fps or 25.0))
        self._writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
        if not self._writer.isOpened():
            print(f"[CameraManager] failed to open writer: {out_path}")
            self._writer = None
            return False

        self._record_frame_size = (w, h, fps)
        print(f"[CameraManager] recording -> {out_path} ({w}x{h}@{fps:.1f})")
        return True

    def _record_frame(self, frame: np.ndarray) -> None:
        writer = self._writer
        if writer is None:
            return
        try:
            writer.write(frame)
        except Exception as exc:  # noqa: BLE001
            print(f"[CameraManager] write error: {exc}")

    def stop_recording(self) -> None:
        writer = self._writer
        self._writer = None
        if writer is not None:
            try:
                writer.release()
            except Exception:  # noqa: BLE001
                pass
            print("[CameraManager] recording stopped")

    def is_recording(self) -> bool:
        return self._writer is not None
