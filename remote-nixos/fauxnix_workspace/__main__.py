"""Fauxnix Workspace — desktop canvas for FauxnixOS."""
import sys
import os


def main():
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    os.environ.setdefault("QT_SCALE_FACTOR", "1")

    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication

    app = QApplication(sys.argv)
    app.setApplicationName("Fauxnix Workspace")

    if "--prime" in sys.argv:
        w = QWidget()
        w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        w.setFixedSize(1, 1)
        w.move(-10, -10)
        w.show()
        sys.exit(app.exec())

    from . import nodes  # noqa: F401 triggers @register_node_type decorators
    from .main_window import create_desktop
    from .theme import APP_QSS

    app.setStyleSheet(APP_QSS)

    window = create_desktop()
    window.setWindowFlags(Qt.WindowType.FramelessWindowHint)
    screen = QGuiApplication.primaryScreen()
    if screen:
        geo = screen.availableGeometry()
        window.setGeometry(0, 0, geo.width(), geo.height())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
