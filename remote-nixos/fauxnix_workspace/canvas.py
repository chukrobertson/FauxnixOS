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
        scale = node._scale
        title_h = int(node.TITLE_HEIGHT * scale)
        body_pad = int(node.BODY_PAD * scale)
        socket_spacing = int(node.SOCKET_SPACING * scale)
        rh = title_h + body_pad
        if node._body_widget:
            rh += node._body_widget.height() + body_pad
        row = self.socket_index // 2
        y = rh + row * socket_spacing + self.RADIUS
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
        self._base_node_width = self._node_width
        self._base_node_height = self.MIN_HEIGHT
        self._base_body_height = 0
        self._scale = 1.0
        self._sockets: list[SocketItem] = []
        self._body_widget = None
        self._node_id = uuid.uuid4().hex[:12]
        self._selected = False
        self._resizing = False
        self._resize_start = QPointF()
        self._drag_start = None
        self._dragging = False
        # Logical (unscaled) canvas coordinates. Screen position is
        # pan_offset + logical_pos * scale.
        self._logical_x = 0.0
        self._logical_y = 0.0

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

    def set_logical_pos(self, x: float, y: float):
        self._logical_x = x
        self._logical_y = y

    def refresh_layout(self, scale: float, pan_offset: QPoint):
        """Reposition and resize the node widget from logical coords, scale, and pan."""
        scale_changed = (scale != self._scale)
        self._scale = scale
        sx = int(pan_offset.x() + self._logical_x * scale)
        sy = int(pan_offset.y() + self._logical_y * scale)
        self.widget.move(sx, sy)

        if scale_changed:
            # Scale outer size.
            self._node_width = max(1, int(self._base_node_width * scale))
            new_height = max(1, int(self._base_node_height * scale))
            self.widget.setFixedSize(self._node_width, new_height)

            # Scale body widget.
            if self._body_widget:
                body_w = max(1, int((self._base_node_width - self.BODY_PAD * 2) * scale))
                body_h = max(1, int(self._base_body_height * scale))
                self._body_widget.setFixedSize(body_w, body_h)
                self._body_widget.move(
                    int(self.BODY_PAD * scale),
                    int(self.TITLE_HEIGHT * scale + self.BODY_PAD * scale),
                )

            self.widget.update()

    def _scale_child_fonts(self, parent: QWidget, scale: float):
        """Roughly scale fonts of simple child widgets with the canvas.

        Avoids QTextEdit/QPlainTextEdit because reflowing them every frame is
        expensive and causes stutter.
        """
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QTextEdit, QPlainTextEdit, QTextBrowser
        for child in parent.findChildren(QWidget):
            if isinstance(child, (QTextEdit, QPlainTextEdit, QTextBrowser)):
                continue
            font = child.font()
            base_size = max(8, min(16, font.pointSize() if font.pointSize() > 0 else 11))
            new_size = max(6, int(base_size * scale))
            if font.pointSize() != new_size:
                font.setPointSize(new_size)
                child.setFont(font)

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
            # Store the unscaled body height so refresh_layout can rescale it.
            self._base_body_height = int(self._body_widget.height() / max(0.01, self._scale))
        n = max(len(self._sockets), 1)
        socket_rows = (n + 1) // 2
        h += socket_rows * self.SOCKET_SPACING + self.BODY_PAD
        h = max(h, self.MIN_HEIGHT)
        # Store unscaled base height.
        self._base_node_height = int(h / max(0.01, self._scale))
        self.widget.setFixedSize(self._node_width, h)

    def node_type_name(self) -> str:
        for name, cls in _NODE_TYPES.items():
            if type(self) is cls:
                return name
        for name, cls in _NODE_TYPES.items():
            if isinstance(self, cls):
                return name
        return type(self).__name__

    def serialize(self) -> dict:
        return {
            "type": self.node_type_name(),
            "id": self._node_id,
            "x": self._logical_x,
            "y": self._logical_y,
            "w": self._node_width,
        }

    def deserialize(self, data: dict):
        self._node_id = data.get("id", self._node_id)
        self.set_logical_pos(data.get("x", 0), data.get("y", 0))
        w = data.get("w", self._node_width)
        if w != self._node_width:
            self.set_node_width(w)

    def set_node_width(self, w: int):
        w = max(self.MIN_WIDTH, w)
        self._base_node_width = w
        self._node_width = int(w * self._scale)
        if self._body_widget:
            bw = min(self._body_widget.sizeHint().width(), w - self.BODY_PAD * 2)
            self._body_widget.setFixedWidth(max(bw, 80))
        self._update_size()
        # Re-apply scale so the widget resizes correctly.
        if self._scale != 1.0:
            self.refresh_layout(self._scale, QPoint(0, 0))
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
        return QRect(0, 0, self.widget.width(), int(self.TITLE_HEIGHT * self._scale))

    def resize_rect(self) -> QRect:
        h = self.widget.height()
        w = self.widget.width()
        rh = max(6, int(self.RESIZE_HANDLE * self._scale))
        return QRect(w - rh - 2, h - rh - 2, rh + 2, rh + 2)

    # ── paint (installed on widget) ────────────────────────────────

    def _paint_event(self, event):
        painter = QPainter(self.widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self._scale
        w = self.widget.width()
        h = self.widget.height()
        title_h = int(self.TITLE_HEIGHT * scale)
        body_pad = int(self.BODY_PAD * scale)
        radius = max(3, int(8 * scale))

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
        painter.drawRoundedRect(r, radius, radius)

        tr = QRectF(0, 0, w, title_h)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, self._color)
        grad.setColorAt(1, self._color.lighter(130))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(tr, radius, radius)
        painter.drawRect(QRectF(0, title_h - radius, w, radius))

        painter.setPen(NODE_TITLE_FG)
        f = QFont(TITLE_FONT[0], max(6, int(10 * scale)), QFont.Weight.Bold)
        painter.setFont(f)
        opt = QTextOption()
        opt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        painter.drawText(tr.adjusted(int(12 * scale), 0, int(-12 * scale), 0), self._title, opt)

        painter.setPen(QPen(self._color.lighter(150), 1))
        painter.drawLine(int(12 * scale), title_h, w - int(12 * scale), title_h)

        for s in self._sockets:
            sp = s.node_pos()
            bp = SocketItem._brush_for(s.data_type)
            painter.setPen(QPen(QColor("#4a4d55"), max(1, 1.5 * scale)))
            painter.setBrush(bp)
            painter.drawEllipse(QPointF(sp), SocketItem.RADIUS, SocketItem.RADIUS)

        rh = max(6, int(self.RESIZE_HANDLE * scale))
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
                # Update logical position by the unscaled delta.
                canvas = self.widget.parentWidget()
                scale = 1.0
                if canvas and hasattr(canvas, "_state"):
                    scale = canvas._state.get("scale", 1.0) or 1.0
                self._logical_x += delta.x() / scale
                self._logical_y += delta.y() / scale
                self.refresh_layout(scale, canvas._state.get("pan_offset", QPoint(0, 0)) if canvas and hasattr(canvas, "_state") else QPoint(0, 0))
                self._drag_start = event.globalPosition().toPoint()
                try:
                    canvas.update()
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
        "scale": 1.0, "min_scale": 0.1, "max_scale": 8.0,
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

        grid = max(16, int(40 * state["scale"]))
        alpha = int(max(10, min(50, 50 * state["scale"])))
        dot = QColor(CANVAS_DOT)
        dot.setAlpha(alpha)
        pen = QPen(dot, 1)
        painter.setPen(pen)
        ox = state["pan_offset"].x() % grid
        oy = state["pan_offset"].y() % grid
        # Batch point drawing for much better pan/zoom performance.
        points = []
        for x in range(ox, w.width() + grid, grid):
            for y in range(oy, w.height() + grid, grid):
                points.append(QPointF(x, y))
        if points:
            painter.drawPoints(points)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for conn in state["connections"]:
            a_col = DATA_TYPE_COLORS.get(conn._a.data_type, WIRE_COLOR)
            b_col = DATA_TYPE_COLORS.get(conn._b.data_type, WIRE_COLOR)
            path = conn.path(state["pan_offset"], state["scale"])
            steps = 12
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

    def _apply_zoom(factor: float, center: QPointF | None = None):
        new_scale = state["scale"] * factor
        if not (state["min_scale"] <= new_scale <= state["max_scale"]):
            return
        state["scale"] = new_scale
        if center is None:
            center = QPointF(w.width() / 2, w.height() / 2)
        state["pan_offset"] = QPoint(
            int(center.x() - (center.x() - state["pan_offset"].x()) * factor),
            int(center.y() - (center.y() - state["pan_offset"].y()) * factor),
        )
        _layout_nodes()
        w.update()


    def _wheel_delta(event):
        """Return a sensible (dx, dy) for wheel/touchpad events."""
        ad = event.angleDelta()
        pd = event.pixelDelta()
        # Prefer angle delta when available; fall back to pixel delta for
        # high-resolution touchpads that only report pixel motion.
        if ad.x() != 0 or ad.y() != 0:
            return ad.x(), ad.y()
        return pd.x(), pd.y()

    def wheelEvent(event):
        mods = event.modifiers()
        has_ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        has_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        dx, dy = _wheel_delta(event)

        if has_ctrl:
            # Touchpads may report scroll as horizontal or vertical deltas.
            # Use whichever axis has the larger motion.
            if abs(dx) >= abs(dy):
                zoom_delta = dx
            else:
                zoom_delta = dy
            if zoom_delta == 0:
                event.accept()
                return
            factor = 1.05 if zoom_delta > 0 else 1 / 1.05
            _apply_zoom(factor, event.position())
            event.accept()
            return

        # Normal wheel pans the canvas.
        if has_shift:
            # Shift+vertical wheel scrolls horizontally.
            dx, dy = dy, dx
        if dx != 0 or dy != 0:
            # Smooth the wheel increments so the canvas does not jump.
            pan_delta = QPoint(int(dx / 4), int(dy / 4))
            state["pan_offset"] += pan_delta
            _layout_nodes()
            w.update()
        event.accept()

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
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and state["selected_node"]:
            _fit_selected()
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
        # If the node has not been assigned logical coords, derive them from
        # its current screen position at the current scale.
        if node._logical_x == 0 and node._logical_y == 0 and (node.widget.x() or node.widget.y()):
            scale = state["scale"]
            if scale != 0:
                node.set_logical_pos(
                    (node.widget.x() - state["pan_offset"].x()) / scale,
                    (node.widget.y() - state["pan_offset"].y()) / scale,
                )
        node.refresh_layout(state["scale"], state["pan_offset"])

    def _layout_nodes():
        scale = state["scale"]
        pan = state["pan_offset"]
        for node in state["nodes"]:
            node.refresh_layout(scale, pan)

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
        nodes = [n for n in state["nodes"]]
        hosts = [h for h in w._hosts if h.widget.isVisible()]
        if not nodes and not hosts:
            return
        xs = [n._logical_x for n in nodes] + [0 for _ in hosts]
        ys = [n._logical_y for n in nodes] + [0 for _ in hosts]
        state["pan_offset"] = QPoint(60, 60)
        state["scale"] = 1.0
        _layout_nodes()
        w.update()

    def _fit_selected():
        node = state["selected_node"]
        if node is None:
            return
        padding = 36
        available_w = max(1, w.width() - padding * 2)
        available_h = max(1, w.height() - padding * 2)
        node_w = max(1, node._base_node_width)
        node_h = max(1, node._base_node_height)
        scale = min(available_w / node_w, available_h / node_h)
        scale = max(state["min_scale"], min(state["max_scale"], scale))
        state["scale"] = scale
        state["pan_offset"] = QPoint(
            int((w.width() - node_w * scale) / 2 - node._logical_x * scale),
            int((w.height() - node_h * scale) / 2 - node._logical_y * scale),
        )
        _layout_nodes()
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
    w._fit_selected = _fit_selected
    w._find_socket_at = _find_socket_at
    w._apply_zoom = _apply_zoom
    w._hosts = []

    return w
