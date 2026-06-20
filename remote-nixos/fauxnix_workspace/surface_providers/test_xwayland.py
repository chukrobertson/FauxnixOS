"""Standalone test: run Alacritty inside Xwayland and show it in a Qt window."""

import sys
import time

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QImage, QPixmap

from .xwayland_per_app import XwaylandPerApp


WIDTH = 800
HEIGHT = 600


def main():
    print("DEBUG: creating QApplication", flush=True)
    app = QApplication([])
    print("DEBUG: creating window", flush=True)
    win = QWidget()
    win.resize(WIDTH, HEIGHT)
    layout = QVBoxLayout(win)
    layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel("Starting Xwayland + Alacritty...")
    label.setFixedSize(WIDTH, HEIGHT)
    layout.addWidget(label)
    print("DEBUG: showing window", flush=True)
    win.show()
    print("DEBUG: window shown", flush=True)

    provider = XwaylandPerApp(
        argv=["alacritty"],
        env={"WINIT_UNIX_BACKEND": "x11"},
        width=WIDTH,
        height=HEIGHT,
    )
    provider.start()

    def update():
        provider.poll()
        frame = provider.get_frame()
        if frame is None:
            return
        data, w, h = frame
        image = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        pixmap = QPixmap.fromImage(image)
        label.setPixmap(pixmap)

    timer = QTimer()
    timer.timeout.connect(update)
    timer.start(100)

    # Stop provider on quit.
    def on_quit():
        provider.stop()
    app.aboutToQuit.connect(on_quit)

    QTimer.singleShot(10000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
