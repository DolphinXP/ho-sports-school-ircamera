"""Configuration & persistence for FireSurveillance.

Mirrors the reference .NET app's ``camera_list.json`` (list of RTSP cameras) and
``settings`` persistence, but reduced to what a UI + RTSP-display app needs:
the camera list, the last selected camera, integration/exposure, and the last
recording directory.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

# Default RTSP URLs match the reference camera_list.json so the app has something
# usable out of the box (works against a local ffmpeg/mediamtx test stream).
_DEFAULT_CAMERAS: List[dict] = [
    {"name": "BigIR-1", "url": "rtsp://localhost:8554/mystream"},
    {"name": "BigIR-2", "url": "rtsp://localhost:8554/mystream2"},
]


@dataclass
class CameraEntry:
    """A single RTSP camera, as stored in camera_list.json."""

    name: str
    url: str


def _app_dir() -> Path:
    """Directory used for user-editable config/runtime files.

    Resolves to the project root (where this file's ``../../..`` lands in a
    source checkout), so camera_list.json lives at ``config/camera_list.json``
    and is easy to edit. Falls back to CWD next to the frozen executable.
    """
    here = Path(__file__).resolve()
    # src/fire_surveillance/config.py -> project root
    root = here.parents[2]
    if (root / "config").is_dir() or (root / "pyproject.toml").exists():
        return root
    return Path.cwd()


def config_dir() -> Path:
    """Where camera_list.json and settings live."""
    path = _app_dir() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def camera_list_path() -> Path:
    return config_dir() / "camera_list.json"


def settings_path() -> Path:
    return config_dir() / "settings.json"


class CameraList:
    """Loads/persists the list of RTSP cameras from camera_list.json."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or camera_list_path()
        self._cameras: List[CameraEntry] = []
        self.reload()

    def reload(self) -> None:
        self._cameras = []
        if not self._path.exists():
            self._cameras = [CameraEntry(name=c["name"], url=c["url"]) for c in _DEFAULT_CAMERAS]
            self._save()
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for item in data.get("cameras", []):
                url = (item.get("url") or "").strip()
                if not url:
                    continue
                name = (item.get("name") or url).strip()
                self._cameras.append(CameraEntry(name=name, url=url))
        except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
            print(f"[CameraList] failed to read {self._path}: {exc}")
            self._cameras = [CameraEntry(name=c["name"], url=c["url"]) for c in _DEFAULT_CAMERAS]

    @property
    def cameras(self) -> List[CameraEntry]:
        return list(self._cameras)

    def urls(self) -> List[str]:
        return [c.url for c in self._cameras]

    def default_url(self) -> Optional[str]:
        return self._cameras[0].url if self._cameras else None

    def add(self, url: str, name: Optional[str] = None) -> bool:
        url = (url or "").strip()
        if not url:
            return False
        if any(c.url == url for c in self._cameras):
            return False
        label = name.strip() if name and name.strip() else f"BigIR-{len(self._cameras) + 1}"
        self._cameras.append(CameraEntry(name=label, url=url))
        return self._save()

    def remove(self, url: str) -> bool:
        url = (url or "").strip()
        before = len(self._cameras)
        self._cameras = [c for c in self._cameras if c.url != url]
        if len(self._cameras) == before:
            return False
        return self._save()

    def _save(self) -> bool:
        try:
            payload = {"cameras": [{"name": c.name, "url": c.url} for c in self._cameras]}
            self._path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True
        except OSError as exc:  # noqa: BLE001
            print(f"[CameraList] failed to save {self._path}: {exc}")
            return False


@dataclass
class AppSettings:
    """Persisted UI/runtime state (last selection, integration, recording dir)."""

    last_camera_url: str = ""
    exposure_us: int = 10
    last_recording_dir: str = ""
    # RTSP transport hint: "tcp" is more robust to packet loss.
    rtsp_transport: str = "tcp"
    # RTSP socket timeout in microseconds (default 5s).
    rtsp_timeout_us: int = 5_000_000
    # Capture engine: "ffmpeg" = bundled ffmpeg.exe subprocess (default),
    # "opencv" = cv2.VideoCapture.
    capture_backend: str = "ffmpeg"
    # cv2 backend preference when capture_backend == "opencv".
    backend: str = "ffmpeg"
    # Pseudo-color mode for display/save: "raw" | "rainbow" | "iron".
    color_mode: str = "raw"
    # Last used "save image" directory.
    save_image_dir: str = ""
    window_geometry: str = ""

    _extras: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "AppSettings":
        path = settings_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
            print(f"[AppSettings] failed to read {path}: {exc}")
            return cls()
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        kwargs = {k: data[k] for k in known if k in data}
        settings = cls(**kwargs)
        settings._extras = {k: v for k, v in data.items() if k not in known}
        return settings

    def save(self) -> None:
        path = settings_path()
        try:
            data = asdict(self)
            extras = data.pop("_extras", None)
            if isinstance(extras, dict):
                data.update(extras)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:  # noqa: BLE001
            print(f"[AppSettings] failed to save {path}: {exc}")


# Environment variable lets tests / CI override the config root without touching
# the source tree.
def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}
