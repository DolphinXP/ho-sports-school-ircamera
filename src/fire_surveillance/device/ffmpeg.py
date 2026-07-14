"""FFmpeg subprocess capture backend.

Uses the ``ffmpeg.exe`` bundled in the application directory (the full gyan
build the user ships with the app) to demux an RTSP/video source and pipe raw
``bgr24`` frames to stdout. This decouples capture from OpenCV's bundled FFmpeg
and gives the full codec / protocol coverage of the shipped binary, so the app
is self-contained and refers to ffmpeg in the current directory.

Discovery order for the binary:
    1. ``<app_dir>/ffmpeg/bin/ffmpeg(.exe)``
    2. ``<app_dir>/ffmpeg(.exe)``
    3. the ``PATH`` (via :func:`shutil.which`)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ..config import _app_dir
from .camera import ICamera

_EXTS = (".exe", "") if os.name == "nt" else ("",)


def _resolve(tool: str) -> Optional[str]:
    """Resolve a ffmpeg/ffprobe binary path, preferring the bundled copy."""
    app_dir = _app_dir()
    candidates: List[Path] = []
    for ext in _EXTS:
        candidates.append(app_dir / "ffmpeg" / "bin" / f"{tool}{ext}")
        candidates.append(app_dir / f"{tool}{ext}")
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    # Fall back to PATH.
    return shutil.which(tool)


def find_ffmpeg() -> Optional[str]:
    return _resolve("ffmpeg")


def find_ffprobe() -> Optional[str]:
    return _resolve("ffprobe")


def is_available() -> bool:
    return find_ffmpeg() is not None


def _is_rtsp(url: str) -> bool:
    return url.lower().startswith("rtsp://") or url.lower().startswith("rtsps://")


class FFmpegCamera(ICamera):
    """Camera backed by an ``ffmpeg`` subprocess piping raw frames to stdout."""

    def __init__(self) -> None:
        super().__init__()
        self.cam_param.camera_name = "FFmpeg"
        self.cam_param.width = 640
        self.cam_param.height = 480
        self._rtsp_url: str = ""
        self._rtsp_transport: str = "tcp"
        self._rtsp_timeout_us: int = 5_000_000
        self._ffmpeg_bin: Optional[str] = find_ffmpeg()
        self._ffprobe_bin: Optional[str] = find_ffprobe()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        # Playback state (file sources).
        self._is_file: bool = False
        self._source_fps: float = 0.0
        self._duration_sec: float = 0.0
        self._seek_offset: float = 0.0          # seconds, where the stream started
        self._frames_since_seek: int = 0
        self._pending_seek: Optional[float] = None
        self._last_emit_time: float = 0.0

    # --- configuration --------------------------------------------------
    def get_camera_list(self) -> List[str]:
        return []

    def set_extra_params(self, key: str, value: Optional[object] = None) -> bool:
        if isinstance(key, str) and key.strip():
            self._rtsp_url = key.strip()
        return True

    def set_rtsp_transport(self, transport: str) -> None:
        self._rtsp_transport = transport if transport in {"tcp", "udp"} else "tcp"

    def set_rtsp_timeout(self, timeout_us: int) -> None:
        self._rtsp_timeout_us = max(500_000, min(120_000_000, int(timeout_us)))

    # --- lifecycle ------------------------------------------------------
    def open_camera(self) -> bool:
        url = self._rtsp_url
        if not url:
            print("[FFmpegCamera] no source url set")
            return False
        if not self._ffmpeg_bin:
            print("[FFmpegCamera] ffmpeg binary not found")
            return False

        print(f"[FFmpegCamera] opening: {url} (ffmpeg={self._ffmpeg_bin})")

        self._is_file = _is_rtsp(url) is False and not url.lower().startswith(("http://", "https://"))

        # Probe dimensions/fps/duration first so we know bytes/frame + playback.
        w, h, fps, duration = self._probe(url)
        if w <= 0 or h <= 0:
            print("[FFmpegCamera] could not determine frame size via ffprobe")
            self._b_open = False
            return False
        self.cam_param.width = w
        self.cam_param.height = h
        self.cam_param.frame_size = w * h * 3
        self._source_fps = fps
        self._duration_sec = duration if self._is_file else 0.0
        self._seek_offset = 0.0
        self._frames_since_seek = 0
        self._pending_seek = None
        self._last_emit_time = 0.0
        self._paused = False

        self._proc = self._spawn(url, 0.0)
        if self._proc is None:
            self._b_open = False
            return False

        self._stat.reset()
        self._b_open = True
        self._thread = threading.Thread(target=self._capture_loop, name="FFmpegCapture", daemon=True)
        self._thread.start()
        suffix = f", {self._duration_sec:.1f}s file)" if self._is_file else ")"
        print(f"[FFmpegCamera] open success ({w}x{h}{suffix}")
        return True

    def _spawn(self, url: str, seek_sec: float) -> Optional[subprocess.Popen]:
        """(Re)spawn the ffmpeg subprocess, optionally seeking to ``seek_sec``."""
        cmd = self._build_command(url, seek_sec)
        try:
            return subprocess.Popen(  # noqa: S603 — command is built locally
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=self.cam_param.frame_size,
            )
        except OSError as exc:
            print(f"[FFmpegCamera] failed to spawn ffmpeg: {exc}")
            return None

    def close_camera(self) -> bool:
        if self._b_capture:
            self.stop_capture()
        self._b_open = False

        proc = self._proc
        if proc is not None:
            for _ in range(20):
                if proc.poll() is not None:
                    break
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.05)
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None

        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        print("[FFmpegCamera] closed")
        return True

    def start_capture(self) -> bool:
        with self._lock:
            if not self._b_open:
                return False
            if self._b_capture:
                return True
            self._b_capture = True
        print("[FFmpegCamera] start capturing")
        return True

    def stop_capture(self) -> bool:
        with self._lock:
            self._b_capture = False
        print("[FFmpegCamera] stop capturing")
        return True

    # --- command building ----------------------------------------------
    def _input_options(self, url: str) -> List[str]:
        opts: List[str] = []
        if _is_rtsp(url):
            opts += ["-rtsp_transport", self._rtsp_transport, "-stimeout", str(self._rtsp_timeout_us)]
        return opts

    def _build_command(self, url: str, seek_sec: float = 0.0) -> List[str]:
        cmd = [self._ffmpeg_bin, "-hide_banner", "-loglevel", "warning"]
        if seek_sec > 0:
            cmd += ["-ss", f"{seek_sec:.3f}"]
        cmd += self._input_options(url)
        cmd += ["-i", url, "-an", "-sn", "-dn", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        return cmd

    def _probe(self, url: str) -> Tuple[int, int, float, float]:
        """Return (width, height, fps, duration_sec) via ffprobe (JSON output)."""
        import json

        if not self._ffprobe_bin:
            return 640, 480, 0.0, 0.0
        cmd = [self._ffprobe_bin, "-v", "error"]
        cmd += self._input_options(url)
        cmd += [
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate:format=duration",
            "-of", "json",
            url,
        ]
        try:
            result = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, timeout=30
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"[FFmpegCamera] ffprobe failed: {exc}")
            return 0, 0, 0.0, 0.0

        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return 0, 0, 0.0, 0.0

        streams = data.get("streams") or []
        stream = streams[0] if streams else {}
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        fps = 0.0
        rfr = stream.get("r_frame_rate") or ""
        if "/" in rfr:
            num, _, den = rfr.partition("/")
            try:
                d = float(den)
                fps = float(num) / d if d else 0.0
            except ValueError:
                pass
        duration = 0.0
        fmt = data.get("format") or {}
        try:
            duration = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            pass
        if width == 0 or height == 0:
            return 0, 0, 0.0, 0.0
        return width, height, fps, duration

    # --- playback (file sources: -ss restart seek + real-time pacing) ---
    def is_playable_source(self) -> bool:
        return self._is_file and self._b_open

    def duration_seconds(self) -> float:
        return self._duration_sec

    def position_seconds(self) -> float:
        if self._source_fps > 0:
            return self._seek_offset + (self._frames_since_seek / self._source_fps)
        return self._seek_offset

    def seek_seconds(self, seconds: float) -> bool:
        if not self._is_file:
            return False
        seconds = max(0.0, min(self._duration_sec, float(seconds)))
        self._pending_seek = seconds
        return True

    # --- capture loop ---------------------------------------------------
    def _capture_loop(self) -> None:
        frame_bytes = self.cam_param.frame_size

        # Start the first stderr drain thread.
        self._start_stderr_drain(self._proc)

        while self._b_open:
            if not self._b_capture:
                time.sleep(0.01)
                continue

            # Pause gates delivery (playback) without killing the stream.
            if self._paused:
                time.sleep(0.02)
                continue

            # Handle a pending seek by restarting ffmpeg at the new offset.
            if self._pending_seek is not None:
                self._do_seek(self._rtsp_url, self._pending_seek)
                self._pending_seek = None
                self._last_emit_time = 0.0

            proc = self._proc
            if proc is None or proc.stdout is None:
                break
            if proc.poll() is not None:
                # ffmpeg exited; we're done (EOF for files).
                break

            data = _read_exactly(proc.stdout, frame_bytes)
            if data is None:
                break  # EOF / pipe closed
            try:
                frame = np.frombuffer(data, dtype=np.uint8).reshape(
                    (self.cam_param.height, self.cam_param.width, 3)
                )
            except ValueError:
                continue
            self._frames_since_seek += 1
            now = time.monotonic()
            self._stat.inc_frame(int(frame.nbytes), now)
            self._emit_frame(frame, now)

            # Real-time pacing for file playback.
            if self._is_file and self._source_fps > 0:
                target = 1.0 / self._source_fps
                if self._last_emit_time > 0:
                    delta = now - self._last_emit_time
                    if 0 < delta < target:
                        time.sleep(target - delta)
                self._last_emit_time = time.monotonic()

    def _do_seek(self, url: str, sec: float) -> None:
        """Terminate the current ffmpeg and respawn seeking to ``sec``."""
        self._terminate_proc(self._proc)
        self._proc = self._spawn(url, sec)
        self._seek_offset = sec
        self._frames_since_seek = 0
        self._start_stderr_drain(self._proc)

    def _start_stderr_drain(self, proc: Optional[subprocess.Popen]) -> None:
        if proc is None or proc.stderr is None:
            return
        t = threading.Thread(target=self._drain_stderr, args=(proc,), name="FFmpegStderr", daemon=True)
        t.start()

    @staticmethod
    def _terminate_proc(proc: Optional[subprocess.Popen]) -> None:
        if proc is None:
            return
        for _ in range(20):
            if proc.poll() is not None:
                break
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.05)
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:  # noqa: BLE001
                pass

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        if proc.stderr is None:
            return
        try:
            for line in iter(proc.stderr.readline, b""):
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    print(f"[FFmpegCamera] ffmpeg: {text}")
        except Exception:  # noqa: BLE001
            pass


def _read_exactly(stream, n: int) -> Optional[bytes]:
    """Read exactly ``n`` bytes from a binary pipe, or None on EOF."""
    if n <= 0:
        return b""
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)
