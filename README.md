# FireSurveillance 改造 (体院拍摄版)

为了到体院拍摄，将原来的火情监测系统改造为**红外 / 热成像摄像头 RTSP 监控 UI**，只保留 UI + 实时 RTSP 视频显示部分。

IR / thermal-camera **RTSP surveillance UI** — UI + live RTSP video display only.
This is a Python re-implementation of the UI & RTSP-display portion of the
reference `ho-fire-surveillance` (.NET / Avalonia) project. **Fire detection is
intentionally excluded.**

Built with **PySide6 (Qt)** for the UI and **OpenCV** for RTSP capture.

## Features

- Dark, modern desktop UI mirroring the reference layout:
  - Title bar with live **系统状态** cards (相机状态 / 帧率 / 录制状态)
  - Central image view with **zoom / pan** (mouse wheel + drag), info overlay,
    and a zoom toolbar (+/−/1:1/fit)
  - Right-side **相机信息** + **RTSP 设置** panel
  - Bottom control bar: mode (相机 / 回放), camera list (add / delete / refresh),
    start/stop imaging, integration (积分) control, and recording
- RTSP / video playback via a **bundled `ffmpeg.exe` subprocess** (default) that
  pipes raw frames to the app — full codec/protocol coverage, self-contained.
  An OpenCV (`cv2.VideoCapture`) engine is selectable as a fallback.
- Frames are delivered to the UI through a thread-safe Qt signal bridge.
- Camera list persisted to `config/camera_list.json`; settings to
  `config/settings.json`.

### Bundled ffmpeg

The app looks for `ffmpeg.exe` in this order and uses the first match:

1. `<app>/ffmpeg/bin/ffmpeg(.exe)` — **the shipped full build**
2. `<app>/ffmpeg(.exe)`
3. the system `PATH`

Drop the gyan "full_build" ffmpeg release into `./ffmpeg/bin/` (it ships
`ffmpeg.exe` + `ffprobe.exe`) and the app uses it automatically. The `ffmpeg/`
folder is git-ignored (it's ~200 MB). If no local ffmpeg is found, the app
falls back to the OpenCV engine.

## Requirements

- Python 3.11–3.13
- [uv](https://docs.astral.sh/uv/) for dependency management

## Quick start

```bash
uv sync
uv run fire-surveillance
# or
uv run python -m fire_surveillance
```

### Test RTSP source

The default `config/camera_list.json` points at local
`rtsp://localhost:8554/mystream`. Spin one up with ffmpeg:

```bash
# stream a test pattern to rtsp://localhost:8554/mystream
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=25 \
  -c:v libx264 -f rtsp rtsp://localhost:8554/mystream
```

Or open a local video file via the **回放** (playback) tab.

## Project layout

```
src/fire_surveillance/
  app.py              # QApplication bootstrap + theme
  config.py           # camera_list.json + settings.json (AppSettings)
  device/
    camera.py         # ICamera (abstract) + RtspCamera (OpenCV capture loop)
    camera_manager.py # CameraManager singleton (start/stop/record/relay, backend select)
    ffmpeg.py         # FFmpegCamera — bundled ffmpeg.exe subprocess backend
  workers/
    frame_bridge.py   # camera thread -> Qt signal bridge (QImage)
  ui/
    theme.py          # dark palette + QSS stylesheet
    main_window.py    # docked layout assembly
    title_bar.py      # brand + SystemStatus
    system_status.py  # status cards
    footer.py         # bottom dock
    camera_controls.py# control bar (list / imaging / exposure / recording)
    image_view.py     # zoom/pan image canvas + overlays
    control_panel.py  # camera info + RTSP settings tabs
config/
  camera_list.json    # editable camera list
```
