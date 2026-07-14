"""Camera device abstraction.

GUI-agnostic. Mirrors the reference .NET app's ``ICamera`` / ``BigIRCamera``:
an abstract camera plus an RTSP implementation backed by OpenCV's
``VideoCapture`` (FFmpeg backend), with a background capture thread that
delivers frames through a callback.

Only RTSP/video display is implemented here — no fire detection.
"""

from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import cv2
import numpy as np

# Frame callback signature: (frame_bgr: np.ndarray, width, height, timestamp)
FrameCallback = Callable[[np.ndarray, int, int, float], None]


@dataclass
class CameraParams:
    camera_name: str = "IR"
    width: int = 0
    height: int = 0
    pixel_depth: int = 8
    frame_size: int = 0


@dataclass
class CameraStat:
    """Lightweight capture statistics (frame count, fps)."""

    frames: int = 0
    bytes_in: int = 0
    _timestamps: List[float] = field(default_factory=list)

    def reset(self) -> None:
        self.frames = 0
        self.bytes_in = 0
        self._timestamps.clear()

    def inc_frame(self, nbytes: int, now: float) -> None:
        self.frames += 1
        self.bytes_in += nbytes
        self._timestamps.append(now)
        # Keep a 2-second rolling window for fps.
        cutoff = now - 2.0
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.pop(0)

    @property
    def fps(self) -> float:
        n = len(self._timestamps)
        if n < 2:
            return 0.0
        span = self._timestamps[-1] - self._timestamps[0]
        return (n - 1) / span if span > 0 else 0.0


class ICamera(ABC):
    """Abstract camera interface (mirrors the C# ``ICamera``)."""

    def __init__(self) -> None:
        self.cam_param = CameraParams()
        self._b_open = False
        self._b_capture = False
        self._paused = False
        self._exposure = 0.0
        self._fps_target = 0.0
        self._stat = CameraStat()
        self._lock = threading.Lock()
        self._on_frame: Optional[FrameCallback] = None

    # --- frame callback -------------------------------------------------
    def set_frame_callback(self, callback: Optional[FrameCallback]) -> None:
        self._on_frame = callback

    def _emit_frame(self, frame: np.ndarray, now: float) -> None:
        if self._on_frame is not None:
            try:
                self._on_frame(frame, self.cam_param.width, self.cam_param.height, now)
            except Exception as exc:  # noqa: BLE001 — never let a UI callback kill capture
                print(f"[ICamera] frame callback error: {exc}")

    # --- abstract API ---------------------------------------------------
    @abstractmethod
    def get_camera_list(self) -> List[str]: ...

    @abstractmethod
    def open_camera(self) -> bool: ...

    @abstractmethod
    def close_camera(self) -> bool: ...

    @abstractmethod
    def start_capture(self) -> bool: ...

    @abstractmethod
    def stop_capture(self) -> bool: ...

    # --- virtual helpers ------------------------------------------------
    def is_open(self) -> bool:
        return self._b_open

    def is_capturing(self) -> bool:
        return self._b_capture

    def set_extra_params(self, key: str, value: Optional[object] = None) -> bool:
        return False

    def set_exposure(self, value: float, value2: float = 0.0) -> bool:
        self._exposure = value
        return True

    def set_fps(self, value: float) -> bool:
        self._fps_target = value
        return True

    @property
    def exposure(self) -> float:
        return self._exposure

    # --- playback (optional; default no-op) -----------------------------
    def is_playable_source(self) -> bool:
        """True if the current source supports duration/seek/pause (file playback)."""
        return False

    def duration_seconds(self) -> float:
        return 0.0

    def position_seconds(self) -> float:
        return 0.0

    def seek_seconds(self, seconds: float) -> bool:
        return False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def is_paused(self) -> bool:
        return getattr(self, "_paused", False)

    @property
    def stat(self) -> CameraStat:
        return self._stat

    def get_status(self):
        """Return (is_open, is_capturing, fps)."""
        if not self._b_open:
            return False, False, 0.0
        if not self._b_capture:
            return True, False, 0.0
        return True, True, self._stat.fps


class RtspCamera(ICamera):
    """RTSP/video camera backed by OpenCV ``VideoCapture`` (FFmpeg).

    Equivalent of the reference ``BigIRCamera``. A background thread reads
    frames continuously; ``start_capture``/``stop_capture`` gate delivery.
    """

    def __init__(self) -> None:
        super().__init__()
        self.cam_param.camera_name = "BigIR"
        self.cam_param.width = 1280
        self.cam_param.height = 1024
        self._rtsp_url: str = ""
        # Default to TCP transport for robustness over lossy links.
        self._rtsp_transport: str = "tcp"
        self._rtsp_timeout_us: int = 5_000_000  # FFmpeg socket timeout (5s)
        self._backend: int = cv2.CAP_FFMPEG
        self._capture: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        # Playback state (file sources).
        self._is_file: bool = False
        self._source_fps: float = 0.0
        self._duration_sec: float = 0.0
        self._last_emit_time: float = 0.0

    # --- list management is handled by CameraList; kept for parity -----
    def get_camera_list(self) -> List[str]:
        return []

    def set_extra_params(self, key: str, value: Optional[object] = None) -> bool:
        # The C# version stores the RTSP url via SetExtraParams(url, null).
        if isinstance(key, str) and key.strip():
            self._rtsp_url = key.strip()
        return True

    def set_rtsp_transport(self, transport: str) -> None:
        self._rtsp_transport = transport if transport in {"tcp", "udp"} else "tcp"

    def set_rtsp_timeout(self, timeout_us: int) -> None:
        # Clamp to [500ms, 120s]; stimeout is microseconds for FFmpeg RTSP/TCP.
        self._rtsp_timeout_us = max(500_000, min(120_000_000, int(timeout_us)))

    def set_backend(self, backend: str) -> None:
        self._backend = {
            "ffmpeg": cv2.CAP_FFMPEG,
            "gstreamer": cv2.CAP_GSTREAMER,
            "any": cv2.CAP_ANY,
        }.get(backend.lower(), cv2.CAP_FFMPEG)

    def _ffmpeg_options(self) -> str:
        """Build the OPENCV_FFMPEG_CAPTURE_OPTIONS string for this session.

        ``stimeout`` is FFmpeg's RTSP/TCP socket-I/O timeout (microseconds).
        Without it FFmpeg blocks ~30s on unreachable cameras.
        """
        opts = [f"rtsp_transport;{self._rtsp_transport}"]
        if self._rtsp_transport == "tcp":
            opts.append(f"stimeout;{self._rtsp_timeout_us}")
        return "|".join(opts)

    # --- lifecycle ------------------------------------------------------
    def open_camera(self) -> bool:
        url = self._rtsp_url or ""
        if not url:
            print("[RtspCamera] no RTSP url set")
            self._b_open = False
            return False

        print(f"[RtspCamera] opening RTSP stream: {url}")
        # OpenCV reads FFmpeg options from this env var. Setting it right before
        # construction scopes the transport + timeout to this capture session.
        prev = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = self._ffmpeg_options()
        try:
            cap = cv2.VideoCapture(url, self._backend)
        finally:
            if prev is None:
                os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
            else:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = prev

        if not cap.isOpened():
            self._b_open = False
            print(f"[RtspCamera] open failed: {url}")
            cap.release()
            return False

        self._capture = cap
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width > 0 and height > 0:
            self.cam_param.width = width
            self.cam_param.height = height
        self.cam_param.frame_size = self.cam_param.width * self.cam_param.height * 3

        # Probe file-source metadata (for the playback bar).
        self._is_file = self._detect_file_source(url)
        self._source_fps = 0.0
        self._duration_sec = 0.0
        if self._is_file:
            fps = cap.get(cv2.CAP_PROP_FPS)
            self._source_fps = fps if fps and fps > 0 else 0.0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if self._source_fps > 0 and frame_count and frame_count > 0:
                self._duration_sec = float(frame_count) / self._source_fps
        self._last_emit_time = 0.0
        self._paused = False

        self._stat.reset()
        self._b_open = True
        self._thread = threading.Thread(target=self._capture_loop, name="RtspCapture", daemon=True)
        self._thread.start()
        print(
            f"[RtspCamera] open success ({self.cam_param.width}x{self.cam_param.height}"
            + (f", {self._duration_sec:.1f}s file)" if self._is_file else ")")
        )
        return True

    @staticmethod
    def _detect_file_source(url: str) -> bool:
        low = url.lower()
        return not (
            low.startswith("rtsp://")
            or low.startswith("rtsps://")
            or low.startswith("http://")
            or low.startswith("https://")
        )

    # --- playback (file sources: native cv2 seek + real-time pacing) ----
    def is_playable_source(self) -> bool:
        return self._is_file and self._b_open

    def duration_seconds(self) -> float:
        return self._duration_sec

    def position_seconds(self) -> float:
        cap = self._capture
        if cap is None:
            return 0.0
        try:
            return float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
        except Exception:  # noqa: BLE001
            return 0.0

    def seek_seconds(self, seconds: float) -> bool:
        cap = self._capture
        if cap is None or not self._is_file:
            return False
        seconds = max(0.0, min(self._duration_sec or seconds, float(seconds)))
        try:
            ok = cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            self._last_emit_time = 0.0
        return bool(ok)

    def close_camera(self) -> bool:
        if self._b_capture:
            self.stop_capture()
        self._b_open = False

        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None

        cap = self._capture
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._capture = None
        print("[RtspCamera] closed")
        return True

    def start_capture(self) -> bool:
        with self._lock:
            if not self._b_open:
                return False
            if self._b_capture:
                return True
            self._b_capture = True
        print("[RtspCamera] start capturing")
        return True

    def stop_capture(self) -> bool:
        with self._lock:
            self._b_capture = False
        print("[RtspCamera] stop capturing")
        return True

    # --- capture loop ---------------------------------------------------
    def _capture_loop(self) -> None:
        while self._b_open:
            if not self._b_capture:
                time.sleep(0.01)
                continue
            cap = self._capture
            if cap is None:
                time.sleep(0.05)
                continue

            # Pause gates delivery (playback) without closing the stream.
            if self._paused:
                time.sleep(0.02)
                continue

            try:
                ok, frame = cap.read()
            except Exception as exc:  # noqa: BLE001
                print(f"[RtspCamera] read error: {exc}")
                time.sleep(0.05)
                continue

            if not ok or frame is None or frame.size == 0:
                # RTSP streams can have brief read gaps; for files, EOF means done.
                if self._is_file:
                    break
                time.sleep(0.05)
                continue

            h, w = frame.shape[:2]
            if w != self.cam_param.width or h != self.cam_param.height:
                self.cam_param.width = w
                self.cam_param.height = h
                self.cam_param.frame_size = w * h * 3

            now = time.monotonic()
            self._stat.inc_frame(int(frame.nbytes), now)
            # frame is already BGR uint8 — deliver as-is so the UI can convert.
            self._emit_frame(frame, now)

            # Real-time pacing for file playback so the progress bar moves at
            # 1x and seek is meaningful.
            if self._is_file and self._source_fps > 0:
                self._pace(self._source_fps)

    def _pace(self, fps: float) -> None:
        """Sleep the remainder of the 1/fps interval for real-time playback."""
        target = 1.0 / fps if fps > 0 else 0.0
        now = time.monotonic()
        if self._last_emit_time > 0:
            delta = now - self._last_emit_time
            if 0 < delta < target:
                time.sleep(target - delta)
        self._last_emit_time = time.monotonic()
