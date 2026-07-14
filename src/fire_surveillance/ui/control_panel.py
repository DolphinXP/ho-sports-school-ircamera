"""ControlPanel — right-side panel with live camera info + RTSP settings.

The reference app has PTU / focus tabs (hardware control) and detection
settings; those are out of scope for a UI + RTSP-display build. Instead this
panel shows useful, working content: live camera statistics and RTSP transport
configuration.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import AppSettings
from ..device import CameraManager, color
from .theme import C


class _InfoRow(QFrame):
    """A label/value row used in the info tab."""

    def __init__(self, caption: str, value: str = "--") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        cap = QLabel(caption)
        cap.setStyleSheet(f"color:{C.text_secondary}; font-size:12px;")
        cap.setMinimumWidth(86)
        self._value = QLabel(value)
        self._value.setStyleSheet(f"color:{C.text_primary}; font-size:12px; font-weight:600;")
        self._value.setWordWrap(True)
        lay.addWidget(cap)
        lay.addWidget(self._value, stretch=1)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class _CameraInfoTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 12, 8, 8)
        layout.setSpacing(8)

        title = QLabel("相机信息")
        title.setObjectName("SectionLabel")
        layout.addWidget(title)

        self._rows = {
            "状态": _InfoRow("状态", "未连接"),
            "相机名称": _InfoRow("相机名称", "--"),
            "分辨率": _InfoRow("分辨率", "--"),
            "帧率": _InfoRow("帧率 (FPS)", "0"),
            "累计帧数": _InfoRow("累计帧数", "0"),
            "数据量": _InfoRow("数据量", "0 B"),
            "RTSP 地址": _InfoRow("RTSP 地址", "--"),
        }
        for row in self._rows.values():
            layout.addWidget(row)
        layout.addStretch()

    def refresh(self, manager: CameraManager) -> None:
        is_open, is_capturing, fps = manager.get_status()
        cam = manager._camera  # type: ignore[attr-defined]
        params = cam.cam_param

        if not is_open:
            status_text, status_color = "未连接", C.text_tertiary
        elif is_capturing:
            status_text, status_color = "运行中", C.success
        else:
            status_text, status_color = "已就绪", C.warning
        self._rows["状态"]._value.setText(status_text)  # type: ignore[attr-defined]
        self._rows["状态"]._value.setStyleSheet(  # type: ignore[attr-defined]
            f"color:{status_color}; font-size:12px; font-weight:600;"
        )

        self._rows["相机名称"].set_value(params.camera_name)
        res = f"{params.width} × {params.height}" if params.width else "--"
        self._rows["分辨率"].set_value(res)
        self._rows["帧率"].set_value(f"{fps:.1f}")
        self._rows["累计帧数"].set_value(f"{cam.stat.frames:,}")
        self._rows["数据量"].set_value(_format_bytes(cam.stat.bytes_in))
        self._rows["RTSP 地址"].set_value(cam._rtsp_url or "--")  # type: ignore[attr-defined]


class _RtspSettingsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._manager = CameraManager.instance()
        self._settings = AppSettings.load()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 12, 8, 8)
        layout.setSpacing(10)

        title = QLabel("RTSP 设置")
        title.setObjectName("SectionLabel")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setSpacing(8)

        self._transport = QComboBox()
        self._transport.addItems(["tcp", "udp"])
        self._transport.setCurrentText(self._settings.rtsp_transport)
        form.addRow("传输协议", self._transport)

        self._engine = QComboBox()
        self._engine.addItem("ffmpeg (内置子进程)", "ffmpeg")
        self._engine.addItem("opencv (cv2)", "opencv")
        idx = 0 if self._settings.capture_backend == "ffmpeg" else 1
        # If the bundled ffmpeg is missing, prefer opencv as the default.
        from ..device import is_available as _ffmpeg_ok

        if not _ffmpeg_ok():
            idx = 1
        self._engine.setCurrentIndex(idx)
        form.addRow("采集引擎", self._engine)

        # RTSP connect/read timeout in seconds (stored as microseconds).
        self._timeout = QDoubleSpinBox()
        self._timeout.setRange(0.5, 120.0)
        self._timeout.setSingleStep(0.5)
        self._timeout.setSuffix(" s")
        self._timeout.setValue(self._settings.rtsp_timeout_us / 1_000_000)
        form.addRow("连接超时", self._timeout)
        layout.addLayout(form)

        # Show the resolved ffmpeg binary so it's obvious which one is in use.
        from ..device import find_ffmpeg

        ffmpeg_path = find_ffmpeg() or "未找到（将回退到 opencv）"
        self._ffmpeg_label = QLabel(ffmpeg_path)
        self._ffmpeg_label.setStyleSheet(
            f"color:{C.text_tertiary}; font-size:11px;"
        )
        self._ffmpeg_label.setWordWrap(True)
        form.addRow("ffmpeg 路径", self._ffmpeg_label)

        hint = QLabel(
            "提示：\n"
            "• 采集引擎默认使用程序目录下的 ffmpeg.exe（全编解码/协议支持）。\n"
            "• TCP 抗丢包更稳定；UDP 延迟更低但易花屏。\n"
            "• 连接超时越短，失败相机的反馈越快。\n"
            "修改后，重新开始成像即可生效。"
        )
        hint.setStyleSheet(f"color:{C.text_tertiary}; font-size:11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        apply_btn = QPushButton("保存并应用")
        apply_btn.setObjectName("AccentButton")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.clicked.connect(self._apply)
        layout.addWidget(apply_btn)
        layout.addStretch()

    def _apply(self) -> None:
        self._settings.rtsp_transport = self._transport.currentText()
        self._settings.capture_backend = self._engine.currentData()
        self._settings.rtsp_timeout_us = int(self._timeout.value() * 1_000_000)
        self._settings.save()
        self._manager.configure_rtsp(
            transport=self._settings.rtsp_transport,
            backend=self._settings.capture_backend,
            timeout_us=self._settings.rtsp_timeout_us,
        )


class ControlPanel(QFrame):
    """Right-side panel container."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlPanel")
        self.setStyleSheet("QFrame#ControlPanel { background: transparent; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(0)

        # Custom tab bar using a horizontal button strip + stacked content.
        from PySide6.QtWidgets import QStackedWidget

        self._tab_bar = QHBoxLayout()
        self._tab_bar.setContentsMargins(0, 0, 0, 12)
        self._tab_bar.setSpacing(18)
        self._tabs: list[tuple[QPushButton, QWidget]] = []
        self._stack = QStackedWidget()

        self._add_tab("相机信息", _CameraInfoTab())
        self._add_tab("RTSP 设置", _RtspSettingsTab())
        layout.addLayout(self._tab_bar)
        layout.addWidget(self._stack, stretch=1)

        # Third panel: pseudo-color selector, below the tab panel.
        self._color_panel = _PseudoColorPanel()
        layout.addWidget(self._color_panel)

        # Fourth panel: image save controls, beneath the pseudo-color panel.
        self._save_panel = _SavePanel()
        layout.addWidget(self._save_panel)

        self._select_tab(0)

        # Poll for status to refresh the info tab.
        self._manager = CameraManager.instance()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh_info)
        self._timer.start()

    def _add_tab(self, label: str, widget: QWidget) -> None:
        btn = QPushButton(label)
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(True)
        btn.setStyleSheet(
            f"QPushButton {{ border:none; background:transparent; "
            f"color:{C.text_secondary}; font-weight:600; font-size:14px; padding:0 0 8px 0; }}"
            f"QPushButton:checked {{ color:{C.accent}; "
            f"border-bottom:2px solid {C.accent}; }}"
        )
        index = len(self._tabs)
        btn.clicked.connect(lambda _checked=False, i=index: self._select_tab(i))
        self._tab_bar.addWidget(btn)
        self._stack.addWidget(widget)
        self._tabs.append((btn, widget))

    def _select_tab(self, index: int) -> None:
        for i, (btn, _widget) in enumerate(self._tabs):
            btn.setChecked(i == index)
        self._stack.setCurrentIndex(index)

    def _refresh_info(self) -> None:
        info_tab = self._tabs[0][1]
        if isinstance(info_tab, _CameraInfoTab):
            info_tab.refresh(self._manager)
        self._save_panel.refresh()


class _PseudoColorPanel(QFrame):
    """Pseudo-color mode selector: 原始灰度 / 彩虹 / 铁红 (OpenCV colormaps)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self._manager = CameraManager.instance()
        self._settings = AppSettings.load()

        # Apply persisted mode to the manager up-front.
        self._manager.set_color_mode(self._settings.color_mode)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("伪彩设置")
        title.setObjectName("SectionLabel")
        layout.addWidget(title)

        from PySide6.QtWidgets import QButtonGroup, QRadioButton

        self._group = QButtonGroup(self)
        self._modes = [
            ("raw", "原始灰度"),
            ("rainbow", "彩虹"),
            ("iron", "铁红"),
        ]
        self._buttons: dict[str, QRadioButton] = {}
        row = QHBoxLayout()
        row.setSpacing(14)
        for mode, label_text in self._modes:
            rb = QRadioButton(label_text)
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            rb.setChecked(color.normalize(self._settings.color_mode) == mode)
            rb.toggled.connect(lambda checked, m=mode: self._on_toggled(m, checked))
            self._group.addButton(rb)
            self._buttons[mode] = rb
            row.addWidget(rb)
        row.addStretch()
        layout.addLayout(row)

    def _on_toggled(self, mode: str, checked: bool) -> None:
        if not checked:
            return
        self._manager.set_color_mode(mode)
        self._settings.color_mode = mode
        self._settings.save()


class _SavePanel(QFrame):
    """Save-image controls: pick a destination folder + save the current frame.

    Works in both camera and replay modes; the save button is enabled only
    while imaging (polled via :meth:`refresh`).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self._manager = CameraManager.instance()
        self._settings = AppSettings.load()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("图像保存")
        title.setObjectName("SectionLabel")
        header.addWidget(title)
        # Inline save-result status, shown beside the title instead of a dialog.
        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{C.text_tertiary}; font-size:11px;")
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(self._status)
        header.addStretch()
        layout.addLayout(header)

        # Folder picker + read-only path display.
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self._btn_save_path = QPushButton("📂")
        self._btn_save_path.setObjectName("IconButton")
        self._btn_save_path.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save_path.setFixedSize(36, 36)
        self._btn_save_path.setToolTip("选择图像保存路径")
        self._btn_save_path.clicked.connect(self._on_pick_save_dir)
        path_row.addWidget(self._btn_save_path)

        self._save_path_edit = QLineEdit()
        self._save_path_edit.setReadOnly(True)
        self._save_path_edit.setPlaceholderText("未选择保存路径")
        self._save_path_edit.setToolTip("图像保存路径（只读，点击左侧文件夹按钮修改）")
        path_row.addWidget(self._save_path_edit, stretch=1)
        layout.addLayout(path_row)

        self._btn_save_img = QPushButton("保存图像")
        self._btn_save_img.setObjectName("AccentButton")
        self._btn_save_img.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save_img.setToolTip("保存当前帧（按当前伪彩模式）到所选路径")
        self._btn_save_img.setEnabled(False)
        self._btn_save_img.clicked.connect(self._on_save_image)
        layout.addWidget(self._btn_save_img)

        self._refresh_save_path_display()

    def refresh(self) -> None:
        """Poll-driven enable/disable (called from the control panel timer)."""
        self._btn_save_img.setEnabled(self._manager.is_running())

    def _refresh_save_path_display(self) -> None:
        """Sync the read-only save-path textbox with the persisted setting."""
        path = self._settings.save_image_dir or ""
        self._save_path_edit.setText(path)
        self._save_path_edit.setCursorPosition(0)
        self._btn_save_path.setToolTip(
            f"图像保存路径：\n{path or '（未选择）'}\n（点击修改）"
        )

    def _on_pick_save_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择图像保存路径", self._settings.save_image_dir or ""
        )
        if folder:
            self._settings.save_image_dir = folder
            self._settings.save()
            self._refresh_save_path_display()

    def _set_status(self, text: str, color: str, tip: str = "") -> None:
        """Show the save result inline beside the section title."""
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{color}; font-size:11px;")
        self._status.setToolTip(tip)

    def _on_save_image(self) -> None:
        if not self._manager.is_running():
            self._set_status("请先开始成像", C.warning)
            return
        folder = self._settings.save_image_dir
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "选择图像保存路径", "")
            if not folder:
                return
            self._settings.save_image_dir = folder
            self._settings.save()
        path = self._manager.save_current_image(folder)
        if path:
            self._set_status(f"已保存 ✓ {Path(path).name}", C.success, path)
        else:
            self._set_status("保存失败：无可用帧", C.danger)


def _format_bytes(n: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < step:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= step
    return f"{n:.1f} PB"
