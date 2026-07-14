"""Application bootstrap — builds the QApplication and shows the main window."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .ui import MainWindow, apply_theme


def run(argv: list[str] | None = None) -> int:
    """Create the QApplication, apply the theme, show the window, run the loop."""
    argv = list(sys.argv if argv is None else argv)

    # Crisp fractional scaling on high-DPI Windows displays.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("FireSurveillance")
    app.setOrganizationName("JiuHeng")
    apply_theme(app)

    window = MainWindow()
    window.show()
    return app.exec()


def main() -> int:
    return run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
