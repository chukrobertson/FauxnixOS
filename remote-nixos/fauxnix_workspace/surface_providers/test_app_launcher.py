"""Test AppLauncherNode -> Display card -> local-app/Xwayland source flow."""

import sys

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QTimer

from fauxnix_workspace.nodes.node_types import AppLauncherNode


class FakeCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self._state = {"scale": 1.0, "nodes": [], "selected_node": None}

    def _add_node(self, node):
        self._state["nodes"].append(node)
        node.widget.setParent(self)
        node.widget.show()

    def update(self):
        pass


def main():
    app = QApplication(sys.argv)
    canvas = FakeCanvas()
    canvas.resize(1200, 900)
    canvas.show()

    launcher = AppLauncherNode()
    launcher.set_logical_pos(50, 50)
    launcher.widget.setParent(canvas)
    launcher.widget.show()
    launcher._scan()

    if not launcher._apps:
        print("DEBUG: no apps found", flush=True)
        app.quit()
        return

    target = None
    for a in launcher._apps:
        if a["name"] == "Alacritty":
            target = a
            break
    if target is None:
        target = launcher._apps[0]

    print(f"DEBUG: spawning {target['name']}", flush=True)
    launcher._spawn_card(target)

    def status():
        nodes = canvas._state["nodes"]
        app_nodes = [n for n in nodes if hasattr(n, "_provider")]
        for n in app_nodes:
            prov = n._provider
            frame = prov.get_frame() if prov else None
            print(f"DEBUG: card provider running={prov.is_running() if prov else False} frame={frame is not None}", flush=True)

    QTimer.singleShot(5000, status)
    QTimer.singleShot(15000, app.quit)
    app.exec()
    for n in canvas._state["nodes"]:
        if hasattr(n, "cleanup"):
            n.cleanup()


if __name__ == "__main__":
    main()
