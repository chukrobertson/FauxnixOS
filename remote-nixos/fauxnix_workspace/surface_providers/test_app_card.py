"""Test AppCardNode with XwaylandPerApp provider outside the full workspace."""

import sys

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QTimer

from fauxnix_workspace.nodes.node_types import AppCardNode
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


class FakeCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self._state = {"scale": 1.0, "nodes": []}


def main():
    app = QApplication(sys.argv)
    canvas = FakeCanvas()
    canvas.resize(1000, 800)
    canvas.show()

    app_info = {
        "name": "Alacritty",
        "exec": "alacritty",
        "icon": "utilities-terminal",
        "startup_wm": "Alacritty",
        "env": {"WINIT_UNIX_BACKEND": "x11"},
        "args": [],
    }
    provider = XwaylandPerApp(
        argv=["alacritty"],
        env={"WINIT_UNIX_BACKEND": "x11"},
        width=800,
        height=600,
    )
    card = AppCardNode(app_info, provider=provider)
    card.set_logical_pos(50, 50)
    card.widget.setParent(canvas)
    card.widget.show()
    card._launch()

    def status():
        frame = card._provider.get_frame() if card._provider else None
        print(f"DEBUG: provider running={card._provider.is_running() if card._provider else False} frame={frame is not None}", flush=True)

    QTimer.singleShot(3000, status)
    QTimer.singleShot(10000, app.quit)
    app.exec()
    card.cleanup()


if __name__ == "__main__":
    main()
