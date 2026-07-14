"""ImageView — the central camera display with zoom / pan / info overlay.

Mirrors the reference Avalonia ``ImageView``: a scrollable black canvas, a
top-left info overlay (width / height / channels / zoom), a bottom-right zoom
toolbar (+/-/1:1/fit), and a playback progress bar (shown for replay sources)
that can be dragged to seek. The canvas is centred when smaller than the
viewport. Mouse wheel zooms; left-drag pans.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .theme import C

MIN_ZOOM = 0.1
MAX_ZOOM = 10.0
ZOOM_STEP = 0.1

# Slider granularity: milliseconds of media time per slider tick.
_SLIDER_SCALE = 1000


def _format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class _OverlayFrame(QFrame):
    """A floating panel that sits on top of the image canvas."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)


class ImageView(QFrame):
    """Central RTSP/video display widget."""

    #: Emitted (seconds) when the user finishes dragging the progress bar.
    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ImageView")
        self.setStyleSheet(
            f"QFrame#ImageView {{ background-color: {C.image_bg}; border-radius: 10px; }}"
        )

        self._pixmap: QPixmap | None = None
        self._zoom = 1.0
        self._channels = 3
        self._orig_w = 0
        self._orig_h = 0

        self._panning = False
        self._pan_start = QPoint()
        self._scroll_start = QPoint()

        # Playback state.
        self._duration = 0.0
        self._dragging = False

        self._build()

    # --- construction ---------------------------------------------------
    def _build(self) -> None:
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent; border: none;")

        # Centering container: when the canvas is smaller than the viewport it
        # is centred; when larger, the scroll area shows scrollbars.
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._canvas = QLabel(objectName="ImageCanvas")
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setMinimumSize(1, 1)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        container_layout.addWidget(self._canvas)
        self._scroll.setWidget(self._container)

        # Info overlay (top-left).
        self._info = _OverlayFrame(self)
        self._info.setStyleSheet(
            f"background-color: rgba(20,23,28,0.78); border:1px solid {C.glass_border}; "
            f"border-radius:6px;"
        )
        info_layout = QVBoxLayout(self._info)
        info_layout.setContentsMargins(10, 8, 10, 8)
        info_layout.setSpacing(3)
        self._lbl_w = QLabel("Width: --")
        self._lbl_h = QLabel("Height: --")
        self._lbl_c = QLabel("Channels: --")
        self._lbl_z = QLabel("Zoom: 100%")
        for lbl in (self._lbl_w, self._lbl_h, self._lbl_c, self._lbl_z):
            lbl.setStyleSheet(f"color:{C.text_secondary}; font-size:11px;")
            info_layout.addWidget(lbl)

        # Zoom toolbar (bottom-right).
        self._zoom_bar = _OverlayFrame(self)
        zb = QVBoxLayout(self._zoom_bar)
        zb.setContentsMargins(0, 0, 0, 0)
        zb.setSpacing(8)
        self._btn_in = self._make_zoom_btn("+")
        self._btn_out = self._make_zoom_btn("-")
        self._btn_reset = self._make_zoom_btn("1:1", small=True)
        self._btn_fit = self._make_zoom_btn("⛶", small=True)
        self._btn_in.clicked.connect(lambda: self._set_zoom(self._zoom + ZOOM_STEP))
        self._btn_out.clicked.connect(lambda: self._set_zoom(self._zoom - ZOOM_STEP))
        self._btn_reset.clicked.connect(lambda: self._set_zoom(1.0))
        self._btn_fit.clicked.connect(self._fit_to_window)
        for btn in (self._btn_in, self._btn_out, self._btn_reset, self._btn_fit):
            zb.addWidget(btn)
        self._btn_in.setToolTip("放大")
        self._btn_out.setToolTip("缩小")
        self._btn_reset.setToolTip("原始尺寸 (1:1)")
        self._btn_fit.setToolTip("适应窗口")

        # Playback bar (bottom; hidden until a replay source is shown).
        self._playback_bar = _OverlayFrame(self)
        self._playback_bar.setStyleSheet(
            f"background-color: rgba(20,23,28,0.92); border:1px solid {C.glass_border}; "
            f"border-radius:6px;"
        )
        pb = QHBoxLayout(self._playback_bar)
        pb.setContentsMargins(12, 6, 12, 6)
        pb.setSpacing(10)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.setEnabled(False)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        pb.addWidget(self._slider, stretch=1)
        self._lbl_cur = QLabel("00:00")
        self._lbl_tot = QLabel("00:00")
        sep = QLabel("/")
        for lbl in (self._lbl_cur, sep, self._lbl_tot):
            lbl.setStyleSheet(f"color:{C.text_secondary}; font-size:11px;")
        pb.addWidget(self._lbl_cur)
        pb.addWidget(sep)
        pb.addWidget(self._lbl_tot)
        self._playback_bar.setVisible(False)

    def _make_zoom_btn(self, text: str, *, small: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("IconButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(36, 36)
        if small:
            f = btn.font()
            f.setPointSize(9)
            btn.setFont(f)
        return btn

    # --- public: display a frame ---------------------------------------
    def display_frame(self, image) -> None:
        """Slot for FrameBridge.frame_ready (QImage)."""
        if image is None or image.isNull():
            return
        self._orig_w = image.width()
        self._orig_h = image.height()
        self._channels = 3
        self._pixmap = QPixmap.fromImage(image)
        self._apply_zoom()
        self._lbl_w.setText(f"Width: {self._orig_w}")
        self._lbl_h.setText(f"Height: {self._orig_h}")
        self._lbl_c.setText(f"Channels: {self._channels}")

    def clear_display(self) -> None:
        self._pixmap = None
        self._canvas.clear()
        self._zoom = 1.0
        self._lbl_w.setText("Width: --")
        self._lbl_h.setText("Height: --")
        self._lbl_c.setText("Channels: --")
        self._lbl_z.setText("Zoom: 100%")

    # --- zoom -----------------------------------------------------------
    def _set_zoom(self, value: float) -> None:
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, round(value, 3)))
        self._apply_zoom()
        self._lbl_z.setText(f"Zoom: {self._zoom * 100:.0f}%")

    def _apply_zoom(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        w = max(1, int(self._pixmap.width() * self._zoom))
        h = max(1, int(self._pixmap.height() * self._zoom))
        scaled = self._pixmap.scaled(
            w, h, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._canvas.setPixmap(scaled)
        self._canvas.adjustSize()

    def _fit_to_window(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        vw = self._scroll.viewport().width()
        vh = self._scroll.viewport().height()
        if vw <= 0 or vh <= 0:
            return
        zx = vw / self._pixmap.width()
        zy = vh / self._pixmap.height()
        self._set_zoom(min(zx, zy) * 0.95)
        self._scroll.horizontalScrollBar().setValue(0)
        self._scroll.verticalScrollBar().setValue(0)

    # --- mouse: wheel zoom, drag pan -----------------------------------
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            return
        step = ZOOM_STEP if delta > 0 else -ZOOM_STEP
        self._set_zoom(self._zoom + step)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap is not None:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self._scroll_start = QPoint(
                self._scroll.horizontalScrollBar().value(),
                self._scroll.verticalScrollBar().value(),
            )
            self._canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._panning:
            delta = event.position().toPoint() - self._pan_start
            self._scroll.horizontalScrollBar().setValue(self._scroll_start.x() - delta.x())
            self._scroll.verticalScrollBar().setValue(self._scroll_start.y() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._panning:
            self._panning = False
            self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # --- playback bar ---------------------------------------------------
    def set_playback_visible(self, visible: bool) -> None:
        self._playback_bar.setVisible(visible)
        self._replay_resize()

    def set_playback_range(self, duration: float) -> None:
        self._duration = max(0.0, float(duration))
        self._slider.setRange(0, int(self._duration * _SLIDER_SCALE))
        self._slider.setEnabled(self._duration > 0)
        self._lbl_tot.setText(_format_time(self._duration))
        self._lbl_cur.setText(_format_time(self._slider.value() / _SLIDER_SCALE))

    def set_playback_position(self, seconds: float) -> None:
        if self._dragging:
            return  # don't fight the user's drag
        if self._duration <= 0:
            return
        value = int(max(0.0, min(self._duration, float(seconds))) * _SLIDER_SCALE)
        self._slider.blockSignals(True)
        self._slider.setValue(value)
        self._slider.blockSignals(False)
        self._lbl_cur.setText(_format_time(seconds))

    def _on_slider_pressed(self) -> None:
        self._dragging = True

    def _on_slider_moved(self, value: int) -> None:
        # Live time-label update while dragging; no seek yet.
        self._lbl_cur.setText(_format_time(value / _SLIDER_SCALE))

    def _on_slider_released(self) -> None:
        self._dragging = False
        seconds = self._slider.value() / _SLIDER_SCALE
        self.seek_requested.emit(seconds)

    # --- geometry / overlays -------------------------------------------
    def _replay_resize(self) -> None:
        """Lay out the scroll area and overlays for the current size/mode."""
        pad = 14
        top = 0
        scroll_h = self.height() - top
        if self._playback_bar.isVisible():
            self._playback_bar.adjustSize()
            pb_h = self._playback_bar.height()
            scroll_h -= pb_h + 8
            self._playback_bar.setGeometry(
                pad, self.height() - pb_h - pad, self.width() - 2 * pad, pb_h
            )
        self._scroll.setGeometry(0, top, self.width(), max(0, scroll_h))

        # Info overlay: top-left.
        self._info.adjustSize()
        self._info.move(pad, pad)
        self._info.raise_()

        # Zoom toolbar: bottom-right (above playback bar if present).
        self._zoom_bar.adjustSize()
        bottom = self.height() - pad
        if self._playback_bar.isVisible():
            bottom -= self._playback_bar.height() + 8
        self._zoom_bar.move(self.width() - self._zoom_bar.width() - pad, bottom - self._zoom_bar.height())
        self._zoom_bar.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._replay_resize()
