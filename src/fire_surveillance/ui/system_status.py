"""SystemStatus — the status cards shown in the title bar.

Cards: 相机状态 (camera), 帧率 (FPS), 录制状态 (recording). The reference
app also shows an "AI检测引擎" card; that is omitted because this build does
not include fire detection.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import C


class _StatusDot(QLabel):
    """A tiny coloured circle used as a status indicator."""

    def __init__(self, color: str = C.success, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(10, 10)
        self._dim = False

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_dim(self, dim: bool) -> None:
        self._dim = dim
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self._color)
        if self._dim:
            c.setAlpha(90)
        painter.setBrush(c)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())


class _StatusCard(QFrame):
    """One status tile: caption row + bold value."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(104)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(9, 7, 9, 7)
        self._layout.setSpacing(2)

        self._caption_row = QHBoxLayout()
        self._caption_row.setSpacing(6)
        self._dot = _StatusDot(C.text_tertiary)
        self._caption = QLabel(caption)
        self._caption.setObjectName("StatusCaption")
        self._caption_row.addWidget(self._dot)
        self._caption_row.addWidget(self._caption)
        self._caption_row.addStretch()
        self._layout.addLayout(self._caption_row)

        self._value = QLabel("--")
        self._value.setObjectName("StatusValue")
        self._layout.addWidget(self._value)

    def set_value(self, text: str, *, accent: bool = False) -> None:
        self._value.setObjectName("StatusValueAccent" if accent else "StatusValue")
        # Force the stylesheet to re-evaluate for the renamed object.
        self._value.style().unpolish(self._value)
        self._value.style().polish(self._value)
        self._value.setText(text)

    def set_dot(self, color: str, *, dim: bool = False) -> None:
        self._dot.set_color(color)
        self._dot.set_dim(dim)


class SystemStatus(QWidget):
    """Composite of the three status cards."""

    #: Emitted when the recording card is clicked (lets the footer sync).
    recording_toggled_from_status = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        header = QLabel("系统状态")
        header.setObjectName("SectionLabel")
        root.addWidget(header)

        self._camera_card = _StatusCard("相机状态")
        self._fps_card = _StatusCard("帧率 (FPS)")
        self._record_card = _StatusCard("录制状态")
        for card in (self._camera_card, self._fps_card, self._record_card):
            root.addWidget(card)

        self.set_idle()

    # --- public setters (driven by FrameBridge.status_changed) ----------
    def set_idle(self) -> None:
        self._camera_card.set_value("未连接", accent=False)
        self._camera_card.set_dot(C.text_tertiary, dim=True)
        self._fps_card.set_value("0", accent=False)
        self._record_card.set_value("未录制", accent=False)
        self._record_card.set_dot(C.text_tertiary, dim=True)

    def set_camera_status(self, is_open: bool, is_capturing: bool, fps: float) -> None:
        if not is_open:
            self._camera_card.set_value("未连接", accent=False)
            self._camera_card.set_dot(C.text_tertiary, dim=True)
            self._fps_card.set_value("0", accent=False)
        elif is_capturing:
            self._camera_card.set_value("运行中", accent=False)
            self._camera_card.set_dot(C.success)
            self._fps_card.set_value(f"{fps:.1f}", accent=True)
        else:
            self._camera_card.set_value("已就绪", accent=False)
            self._camera_card.set_dot(C.warning)
            self._fps_card.set_value("0", accent=False)

    def set_recording(self, recording: bool) -> None:
        if recording:
            self._record_card.set_value("录制中", accent=True)
            self._record_card.set_dot(C.danger)
        else:
            self._record_card.set_value("未录制", accent=False)
            self._record_card.set_dot(C.text_tertiary, dim=True)
