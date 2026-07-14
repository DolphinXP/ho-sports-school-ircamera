"""CameraControls — the bottom control bar.

Functional groups (mirrors the reference ``CameraControls.axaml`` minus the
fire-detection radios, which are intentionally omitted):
* mode toggle (相机 / 回放),
* camera URL combo + add / delete / refresh,
* playback file picker (mode-dependent),
* start / stop imaging,
* integration (exposure) control,
* recording controls.

All actions delegate to :class:`CameraManager`; frame delivery to the view is
handled separately by the :class:`FrameBridge`.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QWidget,
)

from ..config import AppSettings
from ..device import CameraManager
from .theme import C


class _Group(QFrame):
    """A rounded container for a cluster of related controls."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(8)

    def addWidget(self, widget: QWidget) -> None:  # type: ignore[override]
        self._layout.addWidget(widget)

    def addLayout(self, layout) -> None:  # type: ignore[override]
        self._layout.addLayout(layout)

    def addStretch(self) -> None:  # type: ignore[override]
        self._layout.addStretch()


class CameraControls(QWidget):
    """Bottom dock control bar."""

    recording_changed = Signal(bool)
    #: Emitted (True) when a replay source is imaging; False when it stops.
    playback_active = Signal(bool)
    #: Emitted (duration_sec) once a replay source reports a duration.
    playback_ready = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = CameraManager.instance()
        self._settings = AppSettings.load()
        self._manager.configure_rtsp(
            transport=self._settings.rtsp_transport,
            backend=self._settings.capture_backend,
            timeout_us=self._settings.rtsp_timeout_us,
        )
        self._is_imaging = False
        self._is_paused = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        root.addWidget(self._build_mode_group())
        root.addWidget(self._build_camera_group())
        root.addWidget(self._build_playback_group())
        root.addWidget(self._build_imaging_group())
        root.addWidget(self._build_exposure_group())
        root.addWidget(self._build_record_group())
        root.addStretch()

        self.refresh_cameras()
        self._apply_mode()
        self._restore_settings()

        # Poll for playback readiness (duration) when a replay source is open.
        from PySide6.QtCore import QTimer

        self._pb_timer = QTimer(self)
        self._pb_timer.setInterval(300)
        self._pb_timer.timeout.connect(self._poll_playback)
        self._pb_timer.start()

    # --- builders -------------------------------------------------------
    def _build_mode_group(self) -> _Group:
        g = _Group()
        self._mode_camera = QRadioButton("相机")
        self._mode_playback = QRadioButton("回放")
        self._mode_camera.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._mode_camera)
        self._mode_group.addButton(self._mode_playback)
        self._mode_camera.toggled.connect(self._on_mode_toggled)
        g.addWidget(self._mode_camera)
        g.addWidget(self._mode_playback)
        return g

    def _build_camera_group(self) -> _Group:
        g = _Group()
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setMinimumWidth(220)
        self._combo.lineEdit().setPlaceholderText("输入或选择 RTSP 地址")
        g.addWidget(self._combo)

        self._btn_add = self._icon_btn("+", "添加相机地址")
        self._btn_del = self._icon_btn("−", "删除选中相机地址")
        self._btn_refresh = self._icon_btn("⟳", "刷新相机列表")
        self._btn_add.clicked.connect(self._on_add_camera)
        self._btn_del.clicked.connect(self._on_delete_camera)
        self._btn_refresh.clicked.connect(self._on_refresh_cameras)
        g.addWidget(self._btn_add)
        g.addWidget(self._btn_del)
        g.addWidget(self._btn_refresh)
        self._camera_group = g
        return g

    def _build_playback_group(self) -> _Group:
        g = _Group()
        self._playback_path = QComboBox()
        self._playback_path.setEditable(True)
        self._playback_path.lineEdit().setReadOnly(True)
        self._playback_path.lineEdit().setPlaceholderText("选择回放文件")
        self._playback_path.setMinimumWidth(260)
        self._playback_path.lineEdit().setStyleSheet("color: #9aa0a6;")
        g.addWidget(self._playback_path)

        self._btn_pick = self._icon_btn("📁", "选择回放文件")
        self._btn_pick.clicked.connect(self._on_pick_playback_file)
        g.addWidget(self._btn_pick)
        self._playback_group = g
        return g

    def _build_imaging_group(self) -> _Group:
        g = _Group()
        self._btn_start = QPushButton("▶")
        self._btn_start.setObjectName("AccentButton")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.setToolTip("开始成像")
        self._btn_start.setFixedSize(36, 36)
        self._btn_start.clicked.connect(self._on_start_imaging)

        self._btn_stop = QPushButton("■")
        self._btn_stop.setObjectName("IconButton")
        self._btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop.setToolTip("停止成像")
        self._btn_stop.setFixedSize(36, 36)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop_imaging)

        g.addWidget(self._btn_start)
        g.addWidget(self._btn_stop)
        return g

    def _build_exposure_group(self) -> _Group:
        g = _Group()
        g.addWidget(QLabel("积分 (us)"))
        self._exposure = QSpinBox()
        self._exposure.setRange(1, 80)
        self._exposure.setValue(self._settings.exposure_us or 10)
        self._exposure.setFixedWidth(90)
        self._exposure.setEnabled(False)
        g.addWidget(self._exposure)

        self._btn_exposure = self._icon_btn("✓", "应用积分时间")
        self._btn_exposure.setEnabled(False)
        self._btn_exposure.clicked.connect(self._on_set_exposure)
        g.addWidget(self._btn_exposure)
        self._exposure_group = g
        return g

    def _build_record_group(self) -> _Group:
        g = _Group()
        self._btn_record = QPushButton("●")
        self._btn_record.setObjectName("IconButton")
        self._btn_record.setStyleSheet(
            f"QPushButton#IconButton {{ color:{C.danger}; font-size:18px; }}"
        )
        self._btn_record.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_record.setToolTip("开始存储")
        self._btn_record.setFixedSize(36, 36)
        self._btn_record.setEnabled(False)
        self._btn_record.clicked.connect(self._on_start_recording)

        self._btn_stop_rec = QPushButton("■")
        self._btn_stop_rec.setObjectName("IconButton")
        self._btn_stop_rec.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop_rec.setToolTip("停止存储")
        self._btn_stop_rec.setFixedSize(36, 36)
        self._btn_stop_rec.setEnabled(False)
        self._btn_stop_rec.clicked.connect(self._on_stop_recording)

        g.addWidget(self._btn_record)
        g.addWidget(self._btn_stop_rec)
        self._record_group = g
        return g

    def _icon_btn(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("IconButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(36, 36)
        btn.setToolTip(tip)
        return btn

    # --- camera list ----------------------------------------------------
    def refresh_cameras(self) -> None:
        urls: List[str] = self._manager.refresh_camera_list()
        current = self._combo.currentText().strip()
        self._combo.clear()
        for url in urls:
            self._combo.addItem(url)
        if current and current in urls:
            self._combo.setCurrentText(current)
        elif urls:
            self._combo.setCurrentIndex(0)

    def _current_camera_url(self) -> str:
        text = self._combo.currentText().strip()
        if text:
            return text
        return self._combo.currentData() or ""

    # --- mode -----------------------------------------------------------
    def _on_mode_toggled(self) -> None:
        self._apply_mode()

    def _apply_mode(self) -> None:
        is_camera = self._mode_camera.isChecked()
        self._camera_group.setVisible(is_camera)
        self._playback_group.setVisible(not is_camera)
        # 积分 and recording only apply to a live camera; hide them in replay.
        self._exposure_group.setVisible(is_camera)
        self._record_group.setVisible(is_camera)
        if not is_camera and self._manager.is_recording():
            self._manager.stop_recording()

    # --- imaging --------------------------------------------------------
    def _on_start_imaging(self) -> None:
        # In replay mode, toggle play/pause if already imaging.
        if self._mode_playback.isChecked() and self._is_imaging:
            self._is_paused = not self._is_paused
            self._manager.set_paused(self._is_paused)
            self._update_play_icon()
            return

        if self._mode_playback.isChecked():
            path = self._playback_path.currentText().strip()
            if not path or not Path(path).exists():
                self._error("请选择有效的回放文件。", "回放")
                return
            ok = self._manager.start_camera(path)
            target = path
        else:
            url = self._current_camera_url()
            if not url:
                self._error("请输入或选择相机地址。", "相机")
                return
            ok = self._manager.start_camera(url)
            target = url

        if ok:
            self._is_imaging = True
            self._is_paused = False
            self._set_imaging_state(True)
            self._update_play_icon()
            if self._mode_camera.isChecked():
                self._manager.set_exposure(int(self._exposure.value()))
                self._settings.last_camera_url = target
            else:
                self.playback_active.emit(True)
            self._settings.save()
        else:
            mode = "回放" if self._mode_playback.isChecked() else "相机"
            self._error(f"连接{mode}失败，请检查地址是否可达。\n\n{target}", f"{mode}错误")

    def _on_stop_imaging(self) -> None:
        was_playback = self._mode_playback.isChecked() and self._is_imaging
        self._manager.stop_camera()
        self._is_imaging = False
        self._is_paused = False
        self._set_imaging_state(False)
        self._update_play_icon()
        if was_playback:
            self.playback_active.emit(False)

    def _update_play_icon(self) -> None:
        """Play/pause icon on the start button (replay mode only)."""
        if self._mode_playback.isChecked() and self._is_imaging:
            if self._is_paused:
                self._btn_start.setText("▶")
                self._btn_start.setToolTip("继续播放")
            else:
                self._btn_start.setText("❚❚")
                self._btn_start.setToolTip("暂停播放")
        else:
            self._btn_start.setText("▶")
            self._btn_start.setToolTip("开始成像")

    def _set_imaging_state(self, imaging: bool) -> None:
        # In replay mode, keep Start enabled so it can toggle play/pause.
        startable = imaging and self._mode_playback.isChecked()
        self._btn_start.setEnabled(not imaging or startable)
        self._btn_stop.setEnabled(imaging)
        self._mode_camera.setEnabled(not imaging)
        self._mode_playback.setEnabled(not imaging)

        is_camera = self._mode_camera.isChecked()
        # Camera-mode-only controls.
        for w in (self._combo, self._btn_add, self._btn_del, self._btn_refresh):
            w.setEnabled(not imaging and is_camera)
        self._btn_pick.setEnabled(not imaging and not is_camera)

        self._exposure.setEnabled(imaging and is_camera)
        self._btn_exposure.setEnabled(imaging and is_camera)

        self._btn_record.setEnabled(imaging and is_camera)
        if not imaging:
            self._btn_stop_rec.setEnabled(False)
            if self._manager.is_recording():
                self.recording_changed.emit(False)

    def _poll_playback(self) -> None:
        """Report playback duration once a replay source is open."""
        if self._mode_playback.isChecked() and self._is_imaging and self._manager.is_playable():
            self.playback_ready.emit(self._manager.playback_duration())

    # --- camera CRUD ----------------------------------------------------
    def _on_add_camera(self) -> None:
        url = self._current_camera_url()
        if not url:
            self._error("请输入 RTSP 地址。", "添加相机")
            return
        name, ok = QInputDialog.getText(self, "添加相机", "相机名称（可选）:")
        if not ok:
            return
        if self._manager.add_camera(url, name or None):
            self.refresh_cameras()
            self._combo.setCurrentText(url)
        else:
            self._error("添加失败，地址可能已存在。", "添加相机")

    def _on_delete_camera(self) -> None:
        url = self._current_camera_url()
        if not url:
            self._error("请选择要删除的相机地址。", "删除相机")
            return
        if self._manager.remove_camera(url):
            self.refresh_cameras()
        else:
            self._error("删除失败，地址未找到。", "删除相机")

    def _on_refresh_cameras(self) -> None:
        self.refresh_cameras()

    # --- playback -------------------------------------------------------
    def _on_pick_playback_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择回放文件",
            self._settings.last_recording_dir or "",
            "Video Files (*.mp4 *.avi *.mkv *.mov *.flv *.wmv);;All Files (*.*)",
        )
        if path:
            self._playback_path.setEditText(path)

    # --- exposure / recording ------------------------------------------
    def _on_set_exposure(self) -> None:
        self._manager.set_exposure(int(self._exposure.value()))
        self._settings.exposure_us = int(self._exposure.value())
        self._settings.save()

    def _on_start_recording(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择存储路径", self._settings.last_recording_dir or ""
        )
        if not folder:
            return
        self._settings.last_recording_dir = folder
        self._settings.save()

        name, ok = QInputDialog.getText(
            self,
            "文件名",
            "文件名（不含扩展名，留空使用时间戳）:",
            text=self._settings.last_camera_url or "",
        )
        custom = name.strip() if ok else None
        if ok and not self._manager.start_recording(folder, custom):
            self._error("开始存储失败。", "存储")
            return
        if ok:
            self._btn_record.setEnabled(False)
            self._btn_stop_rec.setEnabled(True)
            self.recording_changed.emit(True)

    def _on_stop_recording(self) -> None:
        self._manager.stop_recording()
        self._btn_record.setEnabled(True)
        self._btn_stop_rec.setEnabled(False)
        self.recording_changed.emit(False)

    # --- helpers --------------------------------------------------------
    def _restore_settings(self) -> None:
        last = self._settings.last_camera_url
        if last:
            idx = self._combo.findText(last)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
            else:
                self._combo.setEditText(last)

    def _error(self, message: str, title: str) -> None:
        QMessageBox.warning(self, title, message)
