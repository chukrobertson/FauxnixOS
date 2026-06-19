"""Fauxnix Workspace canvas — plain QWidget composition. No QWidget subclassing to avoid Qt6 Wayland crash."""

import uuid
import json
import time
from pathlib import Path
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, QRect, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QBrush, QColor, QPen, QFont, QPainter, QPainterPath, QTextOption,
    QLinearGradient, QRadialGradient, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QFrame,
    QVBoxLayout, QHBoxLayout,
)

from .theme import (
    CANVAS_BG, CANVAS_DOT,
    NODE_BG, NODE_BORDER, NODE_TITLE_BG, NODE_TITLE_FG,
    ORANGE, CYAN, WHITE, GREEN, RED, YELLOW,
    SELECT_COLOR, SELECT_GLOW,
    DATA_TYPE_COLORS, WIRE_COLOR, WIRE_HOVER,
    TITLE_FONT,
)


# ═══════════════════════════════════════════════════════════════════════
# Node registry
# ═══════════════════════════════════════════════════════════════════════

_NODE_TYPES: dict[str, type] = {}
_NODE_TOOLTIPS: dict[str, str] = {}


def register_node_type(name: str, tooltip: str = ""):
    def deco(cls):
        _NODE_TYPES[name] = cls
        if tooltip:
            _NODE_TOOLTIPS[name] = tooltip
        return cls
    return deco


def get_node_types() -> dict[str, type]:
    return dict(_NODE_TYPES)


def get_node_tooltips() -> dict[str, str]:
    return dict(_NODE_TOOLTIPS)


# ═══════════════════════════════════════════════════════════════════════
# Socket
# ═══════════════════════════════════════════════════════════════════════

class SocketItem:
    RADIUS = 7
    _brush_cache: dict[str, QBrush] = {}

    @classmethod
    def _brush_for(cls, data_type: str) -> QBrush:
        if data_type not in cls._brush_cache:
            c = DATA_TYPE_COLORS.get(data_type, DATA_TYPE_COLORS["data"])
            cls._brush_cache[data_type] = QBrush(c)
        return cls._brush_cache[data_type]

    def __init__(self, parent_node, label: str, data_type: str = "data"):
        self._parent_node = parent_node
        self.label = label
        self.data_type = data_type
        self.socket_index: int = 0
        self.connections: list["ConnectionItem"] = []

    def is_left(self) -> bool:
        return self.socket_index % 2 == 0

    def node_pos(self) -> QPointF:
        node = self._parent_node
        rh = node.TITLE_HEIGHT + node.BODY_PAD
        if node._body_widget:
            rh += node._body_widget.height() + node.BODY_PAD
        row = self.socket_index // 2
        y = rh + row * node.SOCKET_SPACING + self.RADIUS
        x = self.RADIUS if self.is_left() else node._node_width - self.RADIUS
        return QPointF(x, y)

    def global_pos(self) -> QPointF:
        return QPointF(self._parent_node.widget.pos()) + self.node_pos()

    def push_data(self, data):
        for c in self.connections:
            peer = c.other(self)
            peer._parent_node.on_data_received(peer, data)


# ═══════════════════════════════════════════════════════════════════════
# Connection
# ═══════════════════════════════════════════════════════════════════════

class ConnectionItem:
    def __init__(self, a: SocketItem, b: SocketItem):
        self._a = a
        self._b = b
        a.connections.append(self)
        b.connections.append(self)

    def other(self, socket: SocketItem) -> SocketItem:
        return self._b if socket is self._a else self._a

    def path(self, offset: QPoint = QPoint(0, 0), scale: float = 1.0) -> QPainterPath:
        p1 = self._a.global_pos() * scale + QPointF(offset)
        p2 = self._b.global_pos() * scale + QPointF(offset)
        dx = abs(p2.x() - p1.x())
        cpx = max(dx * 0.5, 60)
        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(p1 + QPointF(cpx, 0), p2 - QPointF(cpx, 0), p2)
        return path


# ═══════════════════════════════════════════════════════════════════════
# BaseNode — plain Python class that owns a QWidget (no subclassing)
# ═══════════════════════════════════════════════════════════════════════

class BaseNodeWidget:
    NODE_WIDTH = 280
    TITLE_HEIGHT = 30
    SOCKET_SPACING = 20
    BODY_PAD = 6
    MIN_HEIGHT = 60
    MIN_WIDTH = 140
    RESIZE_HANDLE = 14

    def __init__(self, title: str, color: QColor = NODE_TITLE_BG, width: int | None = None, parent=None):
        self._title = title
        self._color = color
        self._node_width = width or self.NODE_WIDTH
        self._sockets: list[SocketItem] = []
        self._body_widget = None
        self._node_id = uuid.uuid4().hex[:12]
        self._selected = False
        self._resizing = False
        self._resize_start = QPointF()
        self._drag_start = None
        self._dragging = False

        self.widget = QWidget(parent)
        self.widget._node = self
        self.widget.setMouseTracking(True)
        self.widget.setCursor(Qt.CursorShape.OpenHandCursor)
        self.widget.paintEvent = self._paint_event
        self.widget.mousePressEvent = self._mouse_press
        self.widget.mouseMoveEvent = self._mouse_move
        self.widget.mouseReleaseEvent = self._mouse_release
        self.widget.enterEvent = self._enter_event
        self.widget.leaveEvent = self._leave_event

    def select(self):
        self._selected = True
        self.widget.update()

    def deselect(self):
        self._selected = False
        self.widget.update()

    def isSelected(self) -> bool:
        return self._selected

    def add_socket(self, label: str, data_type: str = "data") -> SocketItem:
        s = SocketItem(self, label, data_type)
        s.socket_index = len(self._sockets)
        self._sockets.append(s)
        self.widget.update()
        return s

    def set_body_widget(self, w: QWidget):
        if self._body_widget:
            self._body_widget.setParent(None)
        self._body_widget = w
        w.setParent(self.widget)
        bw = min(w.sizeHint().width(), self._node_width - self.BODY_PAD * 2)
        w.setFixedWidth(max(bw, 80))
        w.move(self.BODY_PAD, self.TITLE_HEIGHT + self.BODY_PAD)
        w.show()
        self._update_size()

    def _update_size(self):
        h = self.TITLE_HEIGHT + self.BODY_PAD * 2
        if self._body_widget:
            h += self._body_widget.height() + self.BODY_PAD
        n = max(len(self._sockets), 1)
        socket_rows = (n + 1) // 2
        h += socket_rows * self.SOCKET_SPACING + self.BODY_PAD
        h = max(h, self.MIN_HEIGHT)
        self.widget.setFixedSize(self._node_width, h)

    def node_type_name(self) -> str:
        for name, cls in _NODE_TYPES.items():
            if isinstance(self, cls):
                return name
        return type(self).__name__

    def serialize(self) -> dict:
        return {
            "type": self.node_type_name(),
            "id": self._node_id,
            "x": self.widget.x(),
            "y": self.widget.y(),
            "w": self._node_width,
        }

    def deserialize(self, data: dict):
        self._node_id = data.get("id", self._node_id)
        self.widget.move(data.get("x", 0), data.get("y", 0))
        w = data.get("w", self._node_width)
        if w != self._node_width:
            self.set_node_width(w)

    def set_node_width(self, w: int):
        w = max(self.MIN_WIDTH, w)
        self._node_width = w
        if self._body_widget:
            bw = min(self._body_widget.sizeHint().width(), w - self.BODY_PAD * 2)
            self._body_widget.setFixedWidth(max(bw, 80))
        self._update_size()
        self.widget.update()

    def on_connected(self, socket: SocketItem, peer: SocketItem):
        pass

    def on_data_received(self, socket: SocketItem, data):
        pass

    def output_data(self, socket: SocketItem) -> dict:
        return {}

    def input_data(self, from_socket: SocketItem | None = None) -> list[dict]:
        results = []
        for s in self._sockets:
            if from_socket is not None and s is not from_socket:
                continue
            for c in s.connections:
                peer = c.other(s)
                data = peer._parent_node.output_data(peer)
                if data:
                    data["_from"] = peer._parent_node._title
                    data["_socket"] = peer.label
                    results.append(data)
        return results

    def tool_schema(self) -> dict | None:
        return None

    def tool_invoke(self, name: str, arguments: dict) -> str:
        return f"Tool '{name}' not implemented on {self._title}"

    def cleanup(self):
        pass

    def socket_at(self, pos: QPoint) -> SocketItem | None:
        for s in self._sockets:
            sp = s.node_pos()
            dx = pos.x() - sp.x()
            dy = pos.y() - sp.y()
            if dx * dx + dy * dy <= (SocketItem.RADIUS + 4) ** 2:
                return s
        return None

    def title_rect(self) -> QRect:
        return QRect(0, 0, self._node_width, self.TITLE_HEIGHT)

    def resize_rect(self) -> QRect:
        h = self.widget.height()
        w = self._node_width
        rh = self.RESIZE_HANDLE
        return QRect(w - rh - 2, h - rh - 2, rh + 2, rh + 2)

    # ── paint (installed on widget) ────────────────────────────────

    def _paint_event(self, event):
        painter = QPainter(self.widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self._node_width
        h = self.widget.height()

        cx, cy = w / 2, h / 2
        glow_radius = max(w, h) * 0.85
        glow = QRadialGradient(cx, cy, glow_radius)
        aura = QColor(SELECT_GLOW) if self._selected else self._color
        aura.setAlpha(60 if self._selected else 30)
        glow.setColorAt(0.0, aura)
        glow.setColorAt(1.0, Qt.GlobalColor.transparent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        r = self.widget.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(SELECT_COLOR if self._selected else NODE_BORDER, 2 if self._selected else 1))
        painter.setBrush(NODE_BG)
        painter.drawRoundedRect(r, 8, 8)

        tr = QRectF(0, 0, w, self.TITLE_HEIGHT)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, self._color)
        grad.setColorAt(1, self._color.lighter(130))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(tr, 8, 8)
        painter.drawRect(QRectF(0, self.TITLE_HEIGHT - 8, w, 8))

        painter.setPen(NODE_TITLE_FG)
        f = QFont(TITLE_FONT[0], 10, QFont.Weight.Bold)
        painter.setFont(f)
        opt = QTextOption()
        opt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        painter.drawText(tr.adjusted(12, 0, -12, 0), self._title, opt)

        painter.setPen(QPen(self._color.lighter(150), 1))
        painter.drawLine(12, self.TITLE_HEIGHT, w - 12, self.TITLE_HEIGHT)

        for s in self._sockets:
            sp = s.node_pos()
            bp = SocketItem._brush_for(s.data_type)
            painter.setPen(QPen(QColor("#4a4d55"), 1.5))
            painter.setBrush(bp)
            painter.drawEllipse(QPointF(sp), SocketItem.RADIUS, SocketItem.RADIUS)

        rh = self.RESIZE_HANDLE
        hx, hy = w - rh - 2, h - rh - 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3a3d44"))
        tri = QPainterPath()
        tri.moveTo(hx + rh, hy + rh)
        tri.lineTo(hx + rh, hy)
        tri.lineTo(hx, hy + rh)
        tri.closeSubpath()
        painter.drawPath(tri)

    # ── mouse (installed on widget) ────────────────────────────────

    def _mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.resize_rect().contains(event.pos()):
                self._resizing = True
                self._resize_start = event.globalPosition()
                event.accept()
                return
            if self.title_rect().contains(event.pos()) and self._body_widget:
                if not self._body_widget.geometry().contains(event.pos()):
                    self._drag_start = event.globalPosition().toPoint()
                    self._dragging = False
                    event.accept()
                    return
        QWidget.mousePressEvent(self.widget, event)

    def _mouse_move(self, event):
        if self._resizing:
            new_w = int(self._node_width + (event.globalPosition().x() - self._resize_start.x()))
            new_w = max(self.MIN_WIDTH, new_w)
            self._resize_start = event.globalPosition()
            self.set_node_width(new_w)
            event.accept()
            return
        if self._drag_start is not None:
            delta = event.globalPosition().toPoint() - self._drag_start
            if delta.manhattanLength() > 3:
                self._dragging = True
                self.widget.move(self.widget.pos() + delta)
                self._drag_start = event.globalPosition().toPoint()
                try:
                    self.widget.parentWidget().update()
                except Exception:
                    pass
            event.accept()
            return
        QWidget.mouseMoveEvent(self.widget, event)

    def _mouse_release(self, event):
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        if self._dragging:
            self._dragging = False
            self._drag_start = None
            event.accept()
            return
        if self._drag_start is not None:
            self._drag_start = None
        QWidget.mouseReleaseEvent(self.widget, event)

    def _enter_event(self, event):
        pos = self.widget.mapFromGlobal(self.widget.cursor().pos())
        if self.resize_rect().contains(pos):
            self.widget.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.widget.setCursor(Qt.CursorShape.OpenHandCursor)

    def _leave_event(self, event):
        self.widget.setCursor(Qt.CursorShape.OpenHandCursor)


# ═══════════════════════════════════════════════════════════════════════
# Canvas — plain QWidget with nodes + wires, no subclassing
# ═══════════════════════════════════════════════════════════════════════

def create_canvas_widget(parent=None):
    """Create a canvas QWidget with grid background, pan, zoom, and wire support."""
    w = QWidget(parent)
    w.setMouseTracking(True)
    w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    state = {
        "scale": 1.0, "min_scale": 0.1, "max_scale": 3.0,
        "pan_offset": QPoint(0, 0), "panning": False, "last_pan": QPoint(),
        "nodes": [], "connections": [],
        "drag_socket": None, "drag_end": QPoint(),
        "selected_node": None,
    }

    def _find_socket_at(global_pos):
        for node in state["nodes"]:
            local = node.widget.mapFromGlobal(global_pos)
            if node.widget.rect().contains(local):
                s = node.socket_at(local)
                if s is not None:
                    return s
        return None

    def paintEvent(event):
        painter = QPainter(w)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(w.rect(), CANVAS_BG)

        grid = max(8, int(40 * state["scale"]))
        alpha = int(max(10, min(50, 50 * state["scale"])))
        dot = QColor(CANVAS_DOT)
        dot.setAlpha(alpha)
        pen = QPen(dot, 1)
        painter.setPen(pen)
        ox = state["pan_offset"].x() % grid
        oy = state["pan_offset"].y() % grid
        for x in range(ox, w.width() + grid, grid):
            for y in range(oy, w.height() + grid, grid):
                painter.drawPoint(x, y)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for conn in state["connections"]:
            a_col = DATA_TYPE_COLORS.get(conn._a.data_type, WIRE_COLOR)
            b_col = DATA_TYPE_COLORS.get(conn._b.data_type, WIRE_COLOR)
            path = conn.path(state["pan_offset"], state["scale"])
            steps = 24
            for i in range(steps + 1):
                t = i / steps
                pt = path.pointAtPercent(t)
                r = 1.0 + (6.0 - 1.0) * abs(2 * t - 1)
                color = QColor(
                    int(a_col.red() + (b_col.red() - a_col.red()) * t),
                    int(a_col.green() + (b_col.green() - a_col.green()) * t),
                    int(a_col.blue() + (b_col.blue() - a_col.blue()) * t),
                    180,
                )
                halo = QColor(color)
                halo.setAlpha(16)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(pt, r * 1.4, r * 1.4)
                painter.setBrush(color)
                painter.drawEllipse(pt, max(r * 0.3, 0.8), max(r * 0.3, 0.8))

        if state["drag_socket"] is not None:
            sp = state["drag_socket"].global_pos() * state["scale"] + QPointF(state["pan_offset"])
            ep = QPointF(state["drag_end"])
            dx = abs(ep.x() - sp.x())
            cpx = max(dx * 0.5, 60)
            dpath = QPainterPath()
            dpath.moveTo(sp)
            dpath.cubicTo(sp + QPointF(cpx, 0), ep - QPointF(cpx, 0), ep)
            painter.setPen(QPen(WIRE_COLOR, 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(dpath)

    def mousePressEvent(event):
        if event.button() == Qt.MouseButton.LeftButton:
            gpos = event.globalPosition().toPoint()
            socket = _find_socket_at(gpos)
            if socket:
                state["drag_socket"] = socket
                state["drag_end"] = event.pos()
                w.update()
                event.accept()
                return
            hit = w.childAt(event.pos())
            while hit and not hasattr(hit, '_node'):
                hit = hit.parentWidget()
            if hit and hasattr(hit, '_node'):
                node = hit._node
                if state["selected_node"] and state["selected_node"] is not node:
                    state["selected_node"].deselect()
                state["selected_node"] = node
                node.select()
                event.accept()
                return
            if state["selected_node"]:
                state["selected_node"].deselect()
                state["selected_node"] = None
            state["panning"] = True
            state["last_pan"] = event.globalPosition().toPoint()
            event.accept()
            return
        QWidget.mousePressEvent(w, event)

    def mouseMoveEvent(event):
        if state["drag_socket"] is not None:
            state["drag_end"] = event.pos()
            w.update()
            event.accept()
            return
        if state["panning"]:
            delta = event.globalPosition().toPoint() - state["last_pan"]
            state["last_pan"] = event.globalPosition().toPoint()
            state["pan_offset"] += delta
            for node in state["nodes"]:
                node.widget.move(node.widget.pos() + delta)
            w.update()
            event.accept()
            return
        QWidget.mouseMoveEvent(w, event)

    def mouseReleaseEvent(event):
        if state["drag_socket"] is not None:
            target = _find_socket_at(event.globalPosition().toPoint())
            if target and target is not state["drag_socket"]:
                _make_connection(state["drag_socket"], target)
            state["drag_socket"] = None
            w.update()
            event.accept()
            return
        if state["panning"]:
            state["panning"] = False
            event.accept()
            return
        QWidget.mouseReleaseEvent(w, event)

    def wheelEvent(event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.1 if delta > 0 else 1 / 1.1
            new_scale = state["scale"] * factor
            if state["min_scale"] <= new_scale <= state["max_scale"]:
                state["scale"] = new_scale
                cursor_pos = event.position()
                state["pan_offset"] = QPoint(
                    int(cursor_pos.x() - (cursor_pos.x() - state["pan_offset"].x()) * factor),
                    int(cursor_pos.y() - (cursor_pos.y() - state["pan_offset"].y()) * factor),
                )
                w.update()
            event.accept()
            return
        QWidget.wheelEvent(w, event)

    def keyPressEvent(event):
        if event.key() == Qt.Key.Key_Delete and state["selected_node"]:
            _remove_node(state["selected_node"])
            state["selected_node"] = None
            event.accept()
            return
        elif event.key() == Qt.Key.Key_F:
            from PyQt6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit
            focus = QApplication.focusWidget()
            if focus and isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
                QWidget.keyPressEvent(w, event)
                return
            _fit_all()
            event.accept()
            return
        QWidget.keyPressEvent(w, event)

    def _make_connection(a: SocketItem, b: SocketItem):
        if a is b or a._parent_node is b._parent_node:
            return
        for c in a.connections:
            if c.other(a) is b:
                return
        conn = ConnectionItem(a, b)
        state["connections"].append(conn)
        a._parent_node.on_connected(a, b)
        b._parent_node.on_connected(b, a)
        w.update()

    def _add_node(node):
        node.widget.setParent(w)
        node.widget.show()
        state["nodes"].append(node)

    def _remove_node(node):
        node.cleanup()
        node.widget.setParent(None)
        if node in state["nodes"]:
            state["nodes"].remove(node)
        for s in node._sockets:
            for c in list(s.connections):
                state["connections"].remove(c)
                other = c.other(s)
                other.connections.remove(c)
        if state["selected_node"] is node:
            state["selected_node"] = None
        w.update()

    def _fit_all():
        if not state["nodes"] and not w._hosts:
            return
        all_widgets = [n.widget for n in state["nodes"]] + [h.widget for h in w._hosts if h.widget.isVisible()]
        if not all_widgets:
            return
        xs = [wd.x() for wd in all_widgets]
        ys = [wd.y() for wd in all_widgets]
        state["pan_offset"] = QPoint(60 - min(xs), 60 - min(ys))
        w.update()

    # Attach all methods and state to the widget
    w.paintEvent = paintEvent
    w.mousePressEvent = mousePressEvent
    w.mouseMoveEvent = mouseMoveEvent
    w.mouseReleaseEvent = mouseReleaseEvent
    w.wheelEvent = wheelEvent
    w.keyPressEvent = keyPressEvent
    w._state = state
    w._add_node = _add_node
    w._remove_node = _remove_node
    w._make_connection = _make_connection
    w._fit_all = _fit_all
    w._find_socket_at = _find_socket_at
    w._hosts = []

    return w
