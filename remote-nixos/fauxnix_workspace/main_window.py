"""Fauxnix Workspace desktop surface — factory functions, no QWidget subclasses."""

import json
import time
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import Qt, QPoint, QPointF, QTimer, QRect
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QMenu, QMessageBox, QInputDialog,
    QVBoxLayout, QHBoxLayout, QFrame, QDialog, QListWidget, QListWidgetItem,
    QLineEdit, QStackedWidget, QSizePolicy,
)
from PyQt6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut

from .canvas import (
    BaseNodeWidget, register_node_type, get_node_types, get_node_tooltips,
    create_canvas_widget,
)
from .theme import APP_QSS

DATA_DIR = Path.home() / ".config" / "fauxnix"
WORKSPACE_DIR = DATA_DIR / "workspaces"
SNAPSHOT_DIR = WORKSPACE_DIR / "snapshots"
SESSION_FILE = WORKSPACE_DIR / "_session.json"


class WorkspaceManager(QDialog):
    def __init__(self, parent_widget, save_cb, load_cb):
        super().__init__(parent_widget, Qt.WindowType.Dialog)
        self.setWindowTitle("Workspace Manager")
        self.setMinimumSize(480, 400)
        self.setStyleSheet("""
            QDialog { background: #141518; color: #d4d4d4; }
            QListWidget { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 4px; outline: none; font-size: 11px; }
            QListWidget::item { padding: 6px; }
            QListWidget::item:selected { background: #ff7800; color: #080909; }
            QListWidget::item:hover { background: #1c1e23; }
            QLineEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 4px; padding: 4px 8px; font-size: 11px; }
            QLineEdit:focus { border-color: #ff7800; }
        """)
        self._save_cb = save_cb
        self._load_cb = load_cb

        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._load)
        layout.addWidget(self._list)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Snapshot name...")
        self._name_input.returnPressed.connect(self._save)
        layout.addWidget(self._name_input)

        btn_row = QHBoxLayout()
        for text, cb in [("Save", self._save), ("Load", self._load), ("Rename", self._rename), ("Delete", self._delete)]:
            btn = QPushButton(text)
            btn.setStyleSheet("QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 4px; padding: 4px 10px; font-size: 11px; } QPushButton:hover { border-color: #ff7800; color: #ff7800; }")
            btn.clicked.connect(cb)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        layout.addStretch()
        hint = QLabel("Esc to close  |  Type name + Enter to save")
        hint.setStyleSheet("color: #555; font-size: 10px;")
        layout.addWidget(hint)
        self._refresh()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)

    def _refresh(self):
        self._list.clear()
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(SNAPSHOT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[:20]:
            try:
                data = json.loads(f.read_text())
                nc = len(data.get("nodes", []))
                ts = data.get("saved_at", 0)
                label = f'{f.stem}  —  {nc} nodes  —  {datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"}'
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, str(f))
                self._list.addItem(item)
            except Exception:
                pass

    def _selected(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _save(self):
        name = self._name_input.text().strip()
        if not name:
            return
        self._save_cb(name)
        self._name_input.clear()
        self._refresh()

    def _load(self):
        path = self._selected()
        if not path:
            return
        self._load_cb(Path(path))
        self.accept()

    def _rename(self):
        old = self._selected()
        new_name = self._name_input.text().strip()
        if not old or not new_name:
            return
        Path(old).rename(SNAPSHOT_DIR / f"{new_name}.json")
        self._name_input.clear()
        self._refresh()

    def _delete(self):
        path = self._selected()
        if not path:
            return
        if QMessageBox.question(self, "Delete", f"Delete '{Path(path).stem}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            Path(path).unlink(missing_ok=True)
            self._refresh()


# ═══════════════════════════════════════════════════════════════════════
# Desktop factory — creates the full desktop UI without QWidget subclass
# ═══════════════════════════════════════════════════════════════════════

def create_desktop():
    """Create and return the desktop QWidget with tab bar, canvas, and toolbar."""
    w = QWidget()
    w.setWindowTitle("Fauxnix Workspace")
    w.setStyleSheet("background: #080909;")
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    main_layout = QVBoxLayout(w)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.setSpacing(0)

    # State
    tabs = []
    tab_buttons = []
    tab_close_btns = []
    stack = QStackedWidget()

    # Tab bar at TOP — also serves as the system bar
    tab_bar = QWidget()
    tab_bar.setFixedHeight(30)
    tab_bar.setStyleSheet("background: rgba(10, 11, 14, 220); border-bottom: 1px solid rgba(30, 30, 38, 150);")
    tab_layout = QHBoxLayout(tab_bar)
    tab_layout.setContentsMargins(6, 0, 6, 0)
    tab_layout.setSpacing(2)

    add_btn = QPushButton("+")
    add_btn.setFixedSize(24, 24)
    add_btn.setStyleSheet("QPushButton { background: transparent; color: #555; border: 1px solid transparent; border-radius: 4px; font-size: 14px; font-weight: bold; } QPushButton:hover { color: #ff7800; border-color: #333; background: rgba(255,120,0,15); }")
    add_btn.clicked.connect(lambda: _new_tab())
    tab_layout.addWidget(add_btn)

    tab_spacer = QWidget()
    tab_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    tab_layout.addWidget(tab_spacer)

    # Clock + date on the right
    clock_label = QLabel("")
    clock_label.setStyleSheet("color: #888; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
    tab_layout.addWidget(clock_label)

    def _update_clock():
        clock_label.setText(datetime.now().strftime("%H:%M  %a %d"))
    _update_clock()
    clock_timer = QTimer(w)
    clock_timer.timeout.connect(_update_clock)
    clock_timer.start(15000)

    # Network indicator
    net_label = QLabel("")
    net_label.setStyleSheet("color: #666; font-size: 11px; padding: 0 8px; background: transparent; border: none;")
    tab_layout.addWidget(net_label)

    def _update_network():
        import subprocess
        try:
            out = subprocess.run(["nmcli", "-t", "-f", "TYPE,STATE", "device", "status"],
                                 capture_output=True, text=True, timeout=2)
            wifi = eth = "-"
            for line in out.stdout.strip().split("\n"):
                parts = line.split(":")
                if len(parts) >= 2 and parts[1] == "connected":
                    if parts[0] == "wifi":
                        ssid = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi", "list"],
                                              capture_output=True, text=True, timeout=2)
                        for l in ssid.stdout.strip().split("\n"):
                            sp = l.split(":")
                            if len(sp) >= 2 and sp[0] == "yes":
                                wifi = sp[1][:12]
                                break
                    elif parts[0] == "ethernet":
                        eth = "eth"
            if wifi != "-":
                net_label.setText(f"\u25e6 {wifi}")
                net_label.setStyleSheet("color: #00c8ff; font-size: 11px; padding: 0 8px; background: transparent; border: none;")
            elif eth != "-":
                net_label.setText("\u2194 eth")
                net_label.setStyleSheet("color: #00cc66; font-size: 11px; padding: 0 8px; background: transparent; border: none;")
            else:
                net_label.setText("\u2717 net")
                net_label.setStyleSheet("color: #555; font-size: 11px; padding: 0 8px; background: transparent; border: none;")
        except Exception:
            net_label.setText("\u2717")
            net_label.setStyleSheet("color: #444; font-size: 11px; padding: 0 8px; background: transparent; border: none;")

    _update_network()
    net_timer = QTimer(w)
    net_timer.timeout.connect(_update_network)
    net_timer.start(30000)

    # Volume indicator
    vol_label = QLabel("")
    vol_label.setStyleSheet("color: #888; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
    tab_layout.addWidget(vol_label)

    def _update_volume():
        import subprocess
        try:
            out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                                 capture_output=True, text=True, timeout=2)
            vol = 0
            for part in out.stdout.split():
                if "." in part:
                    vol = int(float(part) * 100)
                    break
            mute = "MUTED" in out.stdout
            if mute:
                vol_label.setText("\U0001f507 mute")
                vol_label.setStyleSheet("color: #ff4444; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
            else:
                icon = "\U0001f50a" if vol > 50 else "\U0001f509" if vol > 0 else "\U0001f508"
                vol_label.setText(f"{icon} {vol}%")
                vol_label.setStyleSheet("color: #b0b0c0; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
        except Exception:
            vol_label.setText("\u266b")
            vol_label.setStyleSheet("color: #555; font-size: 11px; padding: 0 6px; background: transparent; border: none;")

    _update_volume()
    vol_timer = QTimer(w)
    vol_timer.timeout.connect(_update_volume)
    vol_timer.start(5000)

    # Mic mute indicator
    mic_label = QLabel("")
    mic_label.setStyleSheet("color: #888; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
    tab_layout.addWidget(mic_label)

    def _update_mic():
        import subprocess
        try:
            out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                                 capture_output=True, text=True, timeout=2)
            if "MUTED" in out.stdout:
                mic_label.setText("\U0001f3a4\u0336")
                mic_label.setStyleSheet("color: #ff4444; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
            else:
                mic_label.setText("\U0001f3a4")
                mic_label.setStyleSheet("color: #00cc66; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
        except Exception:
            mic_label.setText("")
    _update_mic()
    mic_timer = QTimer(w)
    mic_timer.timeout.connect(_update_mic)
    mic_timer.start(10000)

    # Brightness indicator
    bri_label = QLabel("")
    bri_label.setStyleSheet("color: #888; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
    tab_layout.addWidget(bri_label)

    def _update_brightness():
        import subprocess
        try:
            out = subprocess.run(["brightnessctl", "-m"], capture_output=True, text=True, timeout=2)
            for line in out.stdout.split("\n"):
                if "intel_backlight" in line:
                    parts = line.split(",")
                    if len(parts) >= 4:
                        pct = parts[3].rstrip("%")
                        bri_label.setText(f"\u2600 {pct}%")
                        bri_label.setStyleSheet("color: #b0b0c0; font-size: 11px; padding: 0 6px; background: transparent; border: none;")
                        return
        except Exception:
            pass
    _update_brightness()
    bri_timer = QTimer(w)
    bri_timer.timeout.connect(_update_brightness)
    bri_timer.start(15000)

    # Power button
    power_btn = QPushButton("\u23fb")
    power_btn.setFixedSize(24, 24)
    power_btn.setToolTip("Power")
    power_btn.setStyleSheet(
        "QPushButton { background: transparent; color: #888; border: 1px solid transparent; "
        "border-radius: 4px; font-size: 13px; }"
        "QPushButton:hover { color: #ff4444; border-color: #444; background: rgba(255,68,68,10); }"
    )
    tab_layout.addWidget(power_btn)

    def _show_power_menu():
        menu = QMenu(w)
        menu.setStyleSheet(
            "QMenu { background: #141518; color: #b0b0b0; border: 1px solid #2a2d33; padding: 4px; }"
            "QMenu::item { padding: 5px 24px; border-radius: 3px; }"
            "QMenu::item:selected { background: #ff4444; color: #080909; }"
        )
        for label, cmd, color in [
            ("\u23fb  Power Off", "systemctl poweroff", "#ff4444"),
            ("\u21bb  Reboot", "systemctl reboot", "#ff7800"),
            ("\u2b2e  Log Out", "loginctl terminate-user \"$USER\"", "#00c8ff"),
        ]:
            act = QAction(label, w)
            act.triggered.connect(lambda checked, c=cmd: __import__("subprocess").run(["sudo", c]))
            menu.addAction(act)
        menu.popup(power_btn.mapToGlobal(QPoint(0, power_btn.height())))

    power_btn.clicked.connect(_show_power_menu)

    main_layout.addWidget(tab_bar)
    main_layout.addWidget(stack)

    # Floating toolbar
    floating_bar = QWidget(w)
    floating_bar.setObjectName("floating_toolbar")
    floating_bar.setStyleSheet("""
        #floating_toolbar { background: rgba(20, 21, 24, 220); border: 1px solid rgba(42, 45, 51, 150); border-radius: 8px; padding: 2px; }
        #floating_toolbar QPushButton { background: transparent; color: #d4d4d4; border: 1px solid transparent; border-radius: 4px; padding: 4px 10px; font-size: 12px; }
        #floating_toolbar QPushButton:hover { background: rgba(42, 45, 51, 180); border-color: #ff7800; color: #ff7800; }
        #floating_toolbar QLabel { color: #666; font-size: 11px; padding: 2px 8px; }
    """)
    tlayout = QHBoxLayout(floating_bar)
    tlayout.setContentsMargins(6, 3, 6, 3)
    tlayout.setSpacing(2)

    zoom_label = QLabel("100%")

    def _current_scale() -> float:
        canvas = _current_canvas()
        if canvas and hasattr(canvas, "_state"):
            return canvas._state.get("scale", 1.0)
        return 1.0

    def _zoom_canvas(factor: float):
        canvas = _current_canvas()
        if canvas and hasattr(canvas, "_apply_zoom"):
            canvas._apply_zoom(factor)
            _update_zoom_label()

    def _zoom_in():
        _zoom_canvas(1.1)

    def _zoom_out():
        _zoom_canvas(1 / 1.1)

    def _update_zoom_label():
        zoom_label.setText(f"{int(_current_scale() * 100)}%")

    def _pos_toolbar():
        floating_bar.adjustSize()
        bw = floating_bar.width()
        x = (w.width() - bw) // 2
        y = w.height() - floating_bar.height() - 12
        floating_bar.move(x, y)

    def _update_tab_buttons():
        for btn in tab_buttons + tab_close_btns:
            if btn is not None:
                tab_layout.removeWidget(btn)
                btn.deleteLater()
        tab_buttons.clear()
        tab_close_btns.clear()
        for i, tab in enumerate(tabs):
            active = (i == stack.currentIndex())
            btn = QPushButton(tab["name"][:18])
            btn.setFixedHeight(24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: {'rgba(255,120,0,30)' if active else 'transparent'}; "
                f"color: {'#ff7800' if active else '#888'}; border: 1px solid {'rgba(255,120,0,80)' if active else 'transparent'}; "
                f"border-radius: 5px; padding: 2px 10px; font-size: 11px; margin-top: 2px; }}"
                f"QPushButton:hover {{ color: {'#ff7800' if not active else '#ffaa44'}; background: rgba(255,120,0,{'20' if not active else '35'}); }}"
            )
            idx = i
            btn.clicked.connect(lambda checked, i=idx: _switch_tab(i))
            close_btn = QPushButton("x")
            close_btn.setFixedSize(18, 18)
            close_btn.setStyleSheet("QPushButton { background: transparent; color: #555; border: 1px solid transparent; border-radius: 3px; font-size: 11px; padding: 0; } QPushButton:hover { color: #ff4444; background: rgba(255,68,68,20); }")
            close_btn.clicked.connect(lambda checked, i=idx: _close_tab(i))
            spacer_idx = tab_layout.indexOf(tab_spacer)
            if spacer_idx < 0:
                spacer_idx = tab_layout.count()
            tab_layout.insertWidget(spacer_idx, btn)
            tab_layout.insertWidget(spacer_idx + 1, close_btn)
            tab_buttons.append(btn)
            tab_close_btns.append(close_btn)

    def _switch_tab(idx):
        if 0 <= idx < stack.count():
            stack.setCurrentIndex(idx)
            _update_tab_buttons()
            _auto_save()

    def _new_tab(name=None):
        name = name or f"Tab {len(tabs) + 1}"
        canvas = create_canvas_widget()
        container = QWidget()
        clayout = QVBoxLayout(container)
        clayout.setContentsMargins(0, 0, 0, 0)
        clayout.addWidget(canvas)
        stack.addWidget(container)
        stack.setCurrentWidget(container)
        tabs.append({"name": name, "canvas": canvas, "modified": False})
        _update_tab_buttons()
        _auto_save()
        return canvas

    def _close_tab(idx):
        if len(tabs) <= 1:
            return
        tabs.pop(idx)
        widget = stack.widget(idx)
        stack.removeWidget(widget)
        widget.deleteLater()
        _update_tab_buttons()
        _auto_save()

    def _current_canvas():
        idx = stack.currentIndex()
        if 0 <= idx < len(tabs):
            return tabs[idx]["canvas"]
        return None

    # ── toolbar buttons ─────────────────────────────────────────

    def _show_add_menu(pos=None):
        canvas = _current_canvas()
        if not canvas:
            return
        if pos is None or isinstance(pos, bool):
            pos = w.cursor().pos()
        menu = QMenu(w)
        menu.setStyleSheet("""
            QMenu { background: #141518; color: #b0b0b0; border: 1px solid #2a2d33; padding: 4px; }
            QMenu::item { padding: 5px 20px; border-radius: 3px; }
            QMenu::item:selected { background: #ff7800; color: #080909; }
        """)
        for name, cls in sorted(get_node_types().items()):
            act = QAction(name, w)
            act.triggered.connect(lambda checked, n=name: _add_node(n))
            menu.addAction(act)
        menu.exec(pos)

    def _add_node(node_type: str):
        canvas = _current_canvas()
        if not canvas:
            return
        cls = get_node_types().get(node_type)
        if not cls:
            return
        node = cls()
        cw = 200 + len(canvas._state["nodes"]) * 50
        ch = 200 + len(canvas._state["nodes"]) * 40
        node.widget.move(cw, ch)
        canvas._add_node(node)
        canvas.update()

    def _fit_all():
        canvas = _current_canvas()
        if canvas:
            canvas._fit_all()

    def _fit_selected():
        canvas = _current_canvas()
        if canvas and hasattr(canvas, "_fit_selected"):
            canvas._fit_selected()

    # ── toolbar ──────────────────────────────────────────────────

    for text, tip, cb in [
        ("+", "Add node", _show_add_menu),
        ("Fit", "Fit all", _fit_all),
        ("Fill", "Fit selected card", _fit_selected),
    ]:
        btn = QPushButton(text)
        btn.setToolTip(tip)
        btn.clicked.connect(cb)
        tlayout.addWidget(btn)

    zoom_out_btn = QPushButton("-")
    zoom_out_btn.setToolTip("Zoom out")
    zoom_out_btn.clicked.connect(_zoom_out)
    tlayout.addWidget(zoom_out_btn)

    tlayout.addWidget(zoom_label)

    zoom_in_btn = QPushButton("+")
    zoom_in_btn.setToolTip("Zoom in")
    zoom_in_btn.clicked.connect(_zoom_in)
    tlayout.addWidget(zoom_in_btn)

    mgr_btn = QPushButton("Mgr")
    mgr_btn.setToolTip("Workspace snapshots")
    mgr_btn.clicked.connect(lambda: WorkspaceManager(w, _save_snapshot, _load_snapshot).exec())
    tlayout.addWidget(mgr_btn)

    ex_btn = QPushButton("Ex")
    ex_btn.setToolTip("Load example workspace")
    ex_btn.clicked.connect(lambda: _show_examples())
    tlayout.addWidget(ex_btn)

    save_btn = QPushButton("Save")
    save_btn.setToolTip("Save session")
    save_btn.clicked.connect(lambda: _auto_save())
    tlayout.addWidget(save_btn)

    def on_resize(event):
        QTimer.singleShot(100, _pos_toolbar)
    w.resizeEvent = on_resize

    # ── serialization ────────────────────────────────────────────

    def _serialize():
        all_tabs = []
        for t in tabs:
            nodes_data = [n.serialize() for n in t["canvas"]._state["nodes"]]
            conns = []
            seen = set()
            for conn in t["canvas"]._state["connections"]:
                pair = (conn._a._parent_node._node_id, conn._a.socket_index,
                        conn._b._parent_node._node_id, conn._b.socket_index)
                rev = (conn._b._parent_node._node_id, conn._b.socket_index,
                       conn._a._parent_node._node_id, conn._a.socket_index)
                if pair not in seen and rev not in seen:
                    seen.add(pair)
                    conns.append({"node_a": conn._a._parent_node._node_id, "socket_a": conn._a.socket_index,
                                  "node_b": conn._b._parent_node._node_id, "socket_b": conn._b.socket_index})
            all_tabs.append({"name": t["name"], "nodes": nodes_data, "connections": conns})
        return all_tabs

    def _auto_save():
        session = {"tabs": _serialize(), "active": stack.currentIndex()}
        SESSION_FILE.write_text(json.dumps(session, indent=2), encoding="utf-8")

    # ── examples ──────────────────────────────────────────────────

    def _show_examples():
        examples_dir = Path(__file__).resolve().parent / "examples"
        if not examples_dir.exists():
            examples_dir = Path("/etc/nixos/fauxnix_workspace/examples")
        menu = QMenu(w)
        menu.setStyleSheet("QMenu { background: #141518; color: #b0b0b0; border: 1px solid #2a2d33; padding: 4px; } QMenu::item { padding: 5px 20px; border-radius: 3px; } QMenu::item:selected { background: #ff7800; color: #080909; }")
        found = False
        for f in sorted(examples_dir.glob("*.json")) if examples_dir.exists() else []:
            name = f.stem.replace("_", " ").title()
            act = QAction(name, w)
            act.triggered.connect(lambda checked, p=f: _load_example(p))
            menu.addAction(act)
            found = True
        if not found:
            act = QAction("(no examples)", w)
            act.setEnabled(False)
            menu.addAction(act)
        menu.exec(w.cursor().pos())

    def _load_example(path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        canvas = _new_tab(data.get("name", data.get("name", "Example")))
        for nd in data.get("nodes", []):
            node_type = nd.get("type", "")
            if not node_type or node_type not in get_node_types():
                continue
            try:
                cls = get_node_types()[node_type]
                node = cls()
                node.widget.move(
                    nd.get("x", 300),
                    nd.get("y", 200)
                )
                canvas._add_node(node)
                QApplication.processEvents()
            except Exception:
                pass
        canvas.update()

    def _auto_restore():
        if not SESSION_FILE.exists():
            return False
        try:
            session = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            return False
        for entry in session.get("tabs", []):
            canvas = _new_tab(entry.get("name", "Restored"))
            node_map = {}
            for nd in entry.get("nodes", []):
                cls = get_node_types().get(nd.get("type", ""))
                if not cls:
                    continue
                try:
                    node = cls()
                    node.deserialize(nd)
                    canvas._add_node(node)
                    node_map[node._node_id] = node
                except Exception:
                    pass
            for cd in entry.get("connections", []):
                na = node_map.get(cd.get("node_a", ""))
                nb = node_map.get(cd.get("node_b", ""))
                if na and nb:
                    sa, sb = cd.get("socket_a", 0), cd.get("socket_b", 0)
                    if sa < len(na._sockets) and sb < len(nb._sockets):
                        canvas._make_connection(na._sockets[sa], nb._sockets[sb])
        idx = session.get("active", 0)
        if 0 <= idx < stack.count():
            stack.setCurrentIndex(idx)
            _update_tab_buttons()
        return True

    def _save_snapshot(name):
        if not tabs:
            return
        t = tabs[stack.currentIndex()]
        data = {"name": name, "nodes": [n.serialize() for n in t["canvas"]._state["nodes"]], "connections": [], "saved_at": time.time()}
        path = SNAPSHOT_DIR / f"{name}.json"
        path.write_text(json.dumps(data, indent=2))

    def _load_snapshot(path):
        data = json.loads(path.read_text())
        canvas = _new_tab(data.get("name", "Restored"))
        node_map = {}
        for nd in data.get("nodes", []):
            cls = get_node_types().get(nd.get("type", ""))
            if not cls:
                continue
            try:
                node = cls()
                node.deserialize(nd)
                canvas._add_node(node)
                node_map[node._node_id] = node
            except Exception:
                pass

    # ── init ─────────────────────────────────────────────────────

    if not _auto_restore():
        _new_tab("Main")

    # Keep the floating zoom label in sync with the active canvas.
    zoom_timer = QTimer(w)
    zoom_timer.timeout.connect(_update_zoom_label)
    zoom_timer.start(200)

    # Keyboard zoom shortcuts (also useful when touchpad Ctrl+scroll is lost).
    QShortcut(QKeySequence("Ctrl++"), w, activated=_zoom_in)
    QShortcut(QKeySequence("Ctrl+="), w, activated=_zoom_in)
    QShortcut(QKeySequence("Ctrl+-"), w, activated=_zoom_out)

    _pos_toolbar()

    # Attach to widget
    w._tabs = tabs
    w._stack = stack
    w._get_canvas = _current_canvas
    w._add_node = _add_node
    w._auto_save = _auto_save
    w._new_tab = _new_tab
    w._update_tab_buttons = _update_tab_buttons

    # Auto-save every 30 seconds
    save_timer = QTimer(w)
    save_timer.timeout.connect(lambda: _auto_save())
    save_timer.start(30000)

    return w
