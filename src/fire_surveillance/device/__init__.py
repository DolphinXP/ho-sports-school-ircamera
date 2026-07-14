"""Device layer: camera abstraction + manager + ffmpeg backend."""

from . import ffmpeg
from .camera import CameraParams, CameraStat, ICamera, RtspCamera
from .camera_manager import CameraManager
from .ffmpeg import FFmpegCamera, find_ffmpeg, find_ffprobe, is_available

__all__ = [
    "CameraParams",
    "CameraStat",
    "ICamera",
    "RtspCamera",
    "FFmpegCamera",
    "CameraManager",
    "ffmpeg",
    "find_ffmpeg",
    "find_ffprobe",
    "is_available",
]
