"""Pseudo-color rendering for IR/thermal frames.

Three modes (matching the UI panel):
* ``raw``   — 原始灰度 (grayscale)
* ``rainbow`` — 彩虹 (JET LUT)
* ``iron``  — 铁红 / ironbow (HOT LUT)

All modes derive from the input's luminance, since thermal/IR data is
monochrome and the color is a visualization choice.
"""

from __future__ import annotations

import cv2
import numpy as np

RAW = "raw"
RAINBOW = "rainbow"
IRON = "iron"
ALL = (RAW, RAINBOW, IRON)

_LABELS = {
    RAW: "原始灰度",
    RAINBOW: "彩虹",
    IRON: "铁红",
}


def normalize(mode: str) -> str:
    """Map any reasonable spelling to one of the canonical modes."""
    if not mode:
        return RAW
    m = mode.strip().lower()
    if m in {RAINBOW, "彩虹", "jet", "turbo"}:
        return RAINBOW
    if m in {IRON, "铁红", "ironbow", "hot", "iron"}:
        return IRON
    return RAW


def label(mode: str) -> str:
    return _LABELS.get(normalize(mode), mode)


def to_gray(frame: np.ndarray) -> np.ndarray:
    """Convert a BGR/gray frame to single-channel grayscale."""
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def render(frame: np.ndarray, mode: str) -> np.ndarray:
    """Return a BGR visualization of ``frame`` for the given color mode."""
    gray = to_gray(frame)
    m = normalize(mode)
    if m == RAINBOW:
        return cv2.applyColorMap(gray, cv2.COLORMAP_JET)
    if m == IRON:
        return cv2.applyColorMap(gray, cv2.COLORMAP_HOT)
    # RAW — grayscale rendered as a 3-channel BGR image (so QImage RGB888 works).
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
