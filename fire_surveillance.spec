# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a windowed one-dir build of FireSurveillance.

Build with:
    pyinstaller fire_surveillance.spec
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ


project_root = Path(globals().get("specpath") or Path.cwd()).resolve()
src_dir = project_root / "src"
app_name = "FireSurveillance"


datas: list[tuple[str, str]] = []
camera_list = project_root / "config" / "camera_list.json"
if camera_list.is_file():
    datas.append((str(camera_list), "config"))


ffmpeg_root = project_root / "ffmpeg"
if ffmpeg_root.is_dir():
    # Keep the ffmpeg tree intact so the frozen app can resolve
    # <app>/ffmpeg/bin/ffmpeg.exe and <app>/ffmpeg/bin/ffprobe.exe.
    for file_path in ffmpeg_root.rglob("*"):
        if file_path.is_file():
            datas.append((str(file_path), str(file_path.relative_to(project_root).parent)))


binaries: list[tuple[str, str]] = []


a = Analysis(
    [str(project_root / "src" / "fire_surveillance" / "__main__.py")],
    pathex=[str(src_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)