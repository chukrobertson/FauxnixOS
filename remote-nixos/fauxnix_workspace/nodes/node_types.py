"""Fauxnix Workspace node types — Chat, Terminal, Browser, Threads, Files, etc."""

import json
import os
import threading
import urllib.request
import urllib.parse

from PyQt6.QtCore import Qt, QSize, QRectF, QUrl, QThread, pyqtSignal, QTimer, QPoint, QEvent
from PyQt6.QtGui import QColor, QFont, QPainter, QTextCursor, QImage, QPixmap, QIcon, QWindow
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTextEdit, QPushButton,
    QLabel, QComboBox, QLineEdit, QPlainTextEdit, QScrollArea,
    QProgressBar, QFrame, QSizePolicy,
)

from ..canvas import (
    BaseNodeWidget, register_node_type,
    NODE_TITLE_BG, SocketItem,
)
from ..theme import (
    ORANGE, CYAN, GREEN, RED, YELLOW, WHITE,
    NODE_TITLE_FG, BODY_FONT, TITLE_FONT, NODE_BG, NODE_BORDER,
)
from ..fauxd_client import (
    get_summary, get_telemetry, get_weather, get_thread_cards,
    get_notes as fd_get_notes, get_files_recent,
    get_clipboard, set_clipboard, do_action,
)
from ..window_thumbnail import (
    capture_thumbnail, capture_thumbnail_for_pid, find_window_for_pid,
    find_window_geometry, raise_window, move_resize_window,
    _scale_rgba,
)
from ..surface_providers.base import SurfaceProvider, InputEvent
from ..surface_providers.registry import (
    create_source,
    normalize_source_spec,
    source_descriptors,
    provider_descriptors,
)


# ═══════════════════════════════════════════════════════════════════════
# Chat Node — streaming Ollama with tool calling
# ═══════════════════════════════════════════════════════════════════════

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "fennix-local"


class OllamaThread(QThread):
    chunk = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    tool_call = pyqtSignal(str, dict)

    def __init__(self, prompt: str, model: str = DEFAULT_MODEL, context: list[int] | None = None,
                 messages: list | None = None, tools: list | None = None):
        super().__init__()
        self._prompt = prompt
        self._model = model
        self._context = context
        self._messages = messages
        self._tools = tools

    def run(self):
        try:
            body = {
                "model": self._model,
                "stream": True,
                "options": {"num_predict": 2048},
            }
            if self._messages:
                body["messages"] = self._messages
                if self._tools:
                    body["tools"] = self._tools
            else:
                body["prompt"] = self._prompt
                if self._context:
                    body["context"] = self._context
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat" if self._messages else f"{OLLAMA_URL}/api/generate",
                data=json.dumps(body).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            full = ""
            with urllib.request.urlopen(req, timeout=120) as resp:
                for line in resp:
                    try:
                        chunk_data = json.loads(line.decode("utf-8"))
                        msg = chunk_data.get("message", {})
                        content = msg.get("content", "")
                        tool_calls = msg.get("tool_calls", [])
                        if content:
                            full += content
                            self.chunk.emit(content)
                        if tool_calls:
                            for tc in tool_calls:
                                fn = tc.get("function", {})
                                self.tool_call.emit(fn.get("name", ""), fn.get("arguments", {}))
                        if chunk_data.get("done"):
                            self.finished.emit(full)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            self.error.emit(str(e))


@register_node_type("Chat", "Talk to Fennix/Ollama with streaming — drag corner to resize")
class ChatNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Chat", QColor("#1a1a30"), 380)
        self._model = DEFAULT_MODEL
        self._context: list[int] = []
        self._history: list[str] = []
        self._thread: OllamaThread | None = None
        self._tool_rounds = 0
        self._max_tool_rounds = 5
        self._tool_map: dict = {}
        self._pending_messages: list = []
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()}; color: {WHITE.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        top = QHBoxLayout()
        self._model_combo = QComboBox()
        self._model_combo.addItems([DEFAULT_MODEL, "qwen3:1.7b", "qwen3:0.6b", "qwen2.5-coder:14b"])
        self._model_combo.setCurrentText(self._model)
        self._model_combo.currentTextChanged.connect(self._on_model_change)
        self._model_combo.setStyleSheet(
            "QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 2px 6px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #141518; color: #d4d4d4; "
            "selection-background-color: #ff7800; }"
        )
        top.addWidget(self._model_combo)
        layout.addLayout(top)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 12px; }"
        )
        self._output.setMinimumHeight(120)
        self._output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._output, 1)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask Fennix...")
        self._input.setStyleSheet(
            "QLineEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
            "QLineEdit:focus { border-color: #ff7800; }"
        )
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input)

        send_btn = QPushButton("Send")
        send_btn.setStyleSheet(
            "QPushButton { background: #ff7800; color: #080909; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-weight: bold; }"
            "QPushButton:hover { background: #ff9940; }"
        )
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        w.setMinimumHeight(180)
        self.set_body_widget(w)

    def _on_model_change(self, model: str):
        self._model = model

    def _send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._tool_rounds = 0
        self._history.append(f"You: {text}")
        self._output.append(f'<b style="color:#ff7800;">You:</b> {text}')

        # Discover tools and build name→node map
        tools, self._tool_map = self._discover_tools()
        # Gather context from wired nodes
        ctx = self._gather_context()
        # Retrieve relevant memories
        mem_ctx = self._retrieve_memories(text)

        parts = []
        if mem_ctx:
            parts.append("Relevant memories:\n" + mem_ctx)
        if ctx:
            parts.append("Current system context:\n" + ctx)

        system_prompt = (
            "You are Fennix, the FauxnixOS assistant. You have access to tools on the workspace canvas. "
            "Use tools when helpful. Be concise.\n\n" + "\n\n".join(parts)
        ) if parts else (
            "You are Fennix, the FauxnixOS assistant. Use tools when helpful. Be concise."
        )

        self._pending_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        self._output.append(f'<i style="color:#666;">Fennix:</i> ')
        self._run_chat(tools)

    def _retrieve_memories(self, query: str) -> str:
        """Pull relevant notes from fauxd to inject as context."""
        try:
            from ..fauxd_client import get_notes as fd_get_notes
            notes = fd_get_notes()
            if not notes:
                return ""
            matches = [n for n in notes if any(w in str(n.get("title","") + " " + n.get("content","")).lower() for w in query.lower().split())]
            if not matches:
                matches = notes[:3]
            lines = []
            for n in matches[:5]:
                title = n.get("title", n.get("content", ""))[:80]
                lines.append(f"- {title}")
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    def _discover_tools(self) -> tuple[list, dict]:
        tools = []
        tool_map = {}
        seen = set()
        # Find canvas widget in parent chain
        canvas = None
        w = self.widget
        while w and not canvas:
            w = w.parentWidget()
            if w and hasattr(w, '_state') and 'nodes' in w._state:
                canvas = w
        if canvas:
            for node in canvas._state.get("nodes", []):
                if node is self:
                    continue
                schema = node.tool_schema()
                if schema:
                    name = schema["function"]["name"]
                    if name not in seen:
                        seen.add(name)
                        tools.append(schema)
                        tool_map[name] = node
        return tools, tool_map

    def _gather_context(self) -> str:
        parts = []
        for data in self.input_data():
            source = data.get("_from", "?")
            for k, v in data.items():
                if not k.startswith("_") and v:
                    parts.append(f"[{source}] {k}: {v}")
        return "; ".join(parts) if parts else ""

    def _run_chat(self, tools: list):
        self._thread = OllamaThread(
            "", self._model,
            messages=self._pending_messages,
            tools=tools if tools else None,
        )
        self._thread.chunk.connect(self._on_chunk)
        self._thread.finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.tool_call.connect(self._on_tool_call)
        self._thread.start()

    def _on_tool_call(self, name: str, arguments: dict):
        self._output.append(f'\n<span style="color:#ffb74d;">[Tool: {name}({arguments})]</span>\n')
        node = getattr(self, "_tool_map", {}).get(name)
        result = f"Tool '{name}' not found on canvas"
        if node:
            try:
                result = node.tool_invoke(name, arguments)
            except Exception as e:
                result = f"Tool error: {e}"
        # Add result to conversation and continue
        self._pending_messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]})
        self._pending_messages.append({"role": "tool", "content": result[:2000]})
        self._tool_rounds += 1
        if self._tool_rounds < self._max_tool_rounds:
            tools, self._tool_map = self._discover_tools()
            self._run_chat(tools)
        else:
            self._output.append(f'\n<span style="color:#888;">(tool limit reached)</span>')

    def _on_chunk(self, token: str):
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(token)
        self._output.ensureCursorVisible()

    def _on_finished(self, full: str):
        self._history.append(f"Fennix: {full}")
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"text": full, "model": self._model})

    def _on_error(self, err: str):
        self._output.append(f'<span style="color:#ff4444;">Error: {err}</span>')

    def serialize(self) -> dict:
        d = super().serialize()
        d["model"] = self._model
        d["history"] = self._history[-10:]
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._model = data.get("model", DEFAULT_MODEL)
        self._model_combo.setCurrentText(self._model)
        self._history = data.get("history", [])
        for h in self._history:
            self._output.append(h)


# ═══════════════════════════════════════════════════════════════════════
# Terminal Node — embedded terminal card
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Terminal", "Resizable terminal — drag corner to resize. Run shell commands.")
class TerminalNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Terminal", QColor("#0d1a0d"), 500)
        self._build_ui()
        self.add_socket("in", "command")
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "QTextEdit { background: #050505; color: #00cc66; border: 1px solid #1a2a1a; "
            "border-radius: 4px; padding: 4px; font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace; "
            "font-size: 11px; }"
        )
        self._output.setMinimumHeight(200)
        self._output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._output, 1)

        input_row = QHBoxLayout()
        self._cmd = QLineEdit()
        self._cmd.setPlaceholderText("$ command...")
        self._cmd.setStyleSheet(
            "QLineEdit { background: #050505; color: #00cc66; border: 1px solid #1a2a1a; "
            "border-radius: 4px; padding: 4px 8px; font-family: 'Cascadia Code', 'Fira Code', monospace; "
            "font-size: 11px; }"
            "QLineEdit:focus { border-color: #00cc66; }"
        )
        self._cmd.returnPressed.connect(self._run_cmd)
        input_row.addWidget(self._cmd)
        layout.addLayout(input_row)

        self.set_body_widget(w)

    def _run_cmd(self):
        cmd = self._cmd.text().strip()
        if not cmd:
            return
        self._cmd.clear()
        self._output.append(f'<span style="color:#888;">$ {cmd}</span>')
        try:
            import subprocess
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30,
                                    cwd=str(__import__("pathlib").Path.home()))
            if result.stdout:
                self._output.append(
                    f'<span style="color:#00cc66;">{result.stdout.strip().replace("<", "&lt;").replace(">", "&gt;")}</span>'
                )
            if result.stderr:
                self._output.append(
                    f'<span style="color:#ff6644;">{result.stderr.strip().replace("<", "&lt;").replace(">", "&gt;")}</span>'
                )
            for s in self._sockets:
                if s.label == "out":
                    s.push_data({"text": result.stdout, "exit_code": result.returncode})
        except Exception as e:
            self._output.append(f'<span style="color:#ff4444;">{e}</span>')

    def tool_schema(self) -> dict | None:
        return {
            "type": "function",
            "function": {
                "name": "run_shell_command",
                "description": "Run a shell command on the Fauxnix system and return the output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"}
                    },
                    "required": ["command"]
                }
            }
        }

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "run_shell_command":
            cmd = arguments.get("command", "")
            import subprocess
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                return result.stdout or result.stderr or "(no output)"
            except Exception as e:
                return str(e)
        return f"Unknown tool: {name}"

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in" and "command" in data:
            self._output.append(f'<span style="color:#444;">> {data["command"]}</span>')
            self._cmd.setText(data["command"])
            self._run_cmd()

    def serialize(self) -> dict:
        d = super().serialize()
        d["output_lines"] = self._output.toPlainText().split("\n")[-20:]
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        for line in data.get("output_lines", []):
            self._output.append(line)


# ═══════════════════════════════════════════════════════════════════════
# Browser Node — live web view on canvas, zoom to fullscreen
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Browser", "Live Chromium/Firefox-like web view on the canvas — zoom to fullscreen")
class BrowserNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Browser", QColor("#1a2030"), 520)
        self._current_url = "https://lite.duckduckgo.com"
        self._current_title = ""
        self._fullscreen_window = None
        self._fullscreen = False
        self._web = None
        self._build_ui()
        self.add_socket("in", "url")
        self.add_socket("out", "url")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Navigation bar
        nav = QHBoxLayout()
        back_btn = QPushButton("<")
        back_btn.setFixedWidth(24)
        back_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            "QPushButton:hover { border-color: #ff7800; }"
        )
        back_btn.clicked.connect(lambda: self._web.back() if self._web else None)
        nav.addWidget(back_btn)

        fwd_btn = QPushButton(">")
        fwd_btn.setFixedWidth(24)
        fwd_btn.setStyleSheet(back_btn.styleSheet())
        fwd_btn.clicked.connect(lambda: self._web.forward() if self._web else None)
        nav.addWidget(fwd_btn)

        self._url_bar = QLineEdit()
        self._url_bar.setText(self._current_url)
        self._url_bar.setStyleSheet(
            "QLineEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #00c8ff; }"
        )
        self._url_bar.returnPressed.connect(self._navigate)
        nav.addWidget(self._url_bar)

        fs_btn = QPushButton("[]")
        fs_btn.setFixedWidth(28)
        fs_btn.setToolTip("Toggle fullscreen (F11)")
        fs_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; "
            "border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            "QPushButton:hover { background: #00c8ff; color: #080909; }"
        )
        fs_btn.clicked.connect(self._toggle_fullscreen)
        nav.addWidget(fs_btn)
        layout.addLayout(nav)

        # Web view — lazy init to avoid QGraphicsScene + QWebEngineView crash on Wayland
        self._web_placeholder = QLabel("Click Go or enter URL to open browser")
        self._web_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._web_placeholder.setStyleSheet(
            "color: #666; font-size: 11px; padding: 20px; border: 2px dashed #2a2d33; border-radius: 8px;"
        )
        self._web_placeholder.setMinimumSize(440, 200)
        self._web_placeholder.mousePressEvent = lambda e: self._init_web()
        layout.addWidget(self._web_placeholder)

        w.setFixedHeight(40)
        self.set_body_widget(w)

        # Reposition web proxy when node moves
        self._check_zoom_timer = QTimer()
        self._check_zoom_timer.timeout.connect(self._check_zoom)
        self._check_zoom_timer.start(1000)

    def _init_web(self):
        """Lazy-init the web view to avoid QGraphicsScene crash on Wayland."""
        if self._web is not None:
            return
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtWebEngineCore import QWebEngineSettings
            self._web = QWebEngineView()
            self._web.setMinimumSize(440, 280)
            settings = self._web.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            self._web.load(QUrl(self._current_url))
            self._web.urlChanged.connect(self._on_url_change)
            self._web.titleChanged.connect(self._on_title_change)
            self._web.setParent(self)
            self._web.move(self.BODY_PAD, self.TITLE_HEIGHT + self.BODY_PAD)
            self._web.show()
            if self._web_placeholder:
                self._web_placeholder.hide()
            self._layout_web()
        except ImportError:
            self._web_placeholder.setText("QtWebEngine not available")

    def cleanup(self):
        self._check_zoom_timer.stop()
        if self._fullscreen_window:
            self._fullscreen_window.close()
            self._fullscreen_window = None

    def _layout_web(self):
        if not self._web:
            return
        body_bottom = 0
        if self._body_widget:
            body_bottom = self._body_widget.y() + self._body_widget.height()
        y = body_bottom + self.BODY_PAD
        self._web.move(self.BODY_PAD, y)
        bw = self._node_width - self.BODY_PAD * 2
        self._web.resize(bw, max(self._web.height(), 280))

    def total_height(self) -> float:
        base = super().total_height()
        return base + 370

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._node_width, self.total_height())

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"browse_web","description":"Navigate the embedded browser to a URL or search query","parameters":{"type":"object","properties":{"url":{"type":"string","description":"URL or search term to navigate to"}},"required":["url"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "browse_web":
            self._url_bar.setText(arguments.get("url", ""))
            self._navigate()
            return f"Navigating to: {arguments.get("url", "")}"
        return f"Unknown: {name}"

    def _navigate(self):
        self._init_web()
        url = self._url_bar.text().strip()
        if not url:
            return
        if not url.startswith("http"):
            url = "https://" + url
        self._current_url = url
        self._url_bar.setText(url)
        if self._web:
            self._web.load(QUrl(url))

    def _on_url_change(self, url):
        self._current_url = url.toString()
        self._url_bar.setText(self._current_url)
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"url": self._current_url, "title": self._current_title})

    def _on_title_change(self, title):
        self._current_title = title
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"url": self._current_url, "title": title})

    def _check_zoom(self):
        parent = self.widget.parentWidget()
        if not parent or not hasattr(parent, '_state'):
            return
        scale = parent._state.get("scale", 1.0)
        if self.isSelected() and scale > 1.8 and not self._fullscreen:
            self._enter_fullscreen()
        elif scale < 0.5 and self._fullscreen:
            self._exit_fullscreen()

    def _toggle_fullscreen(self):
        if self._fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        if not self._web or self._fullscreen:
            return
        self._fullscreen = True
        self._fullscreen_window = QWidget()
        self._fullscreen_window.setWindowTitle("Browser — F11 to exit")
        self._fullscreen_window.setWindowFlags(Qt.WindowType.Window)
        layout = QVBoxLayout(self._fullscreen_window)
        layout.setContentsMargins(0, 0, 0, 0)

        # Nav bar for fullscreen
        nav = QHBoxLayout()
        nav.setContentsMargins(4, 4, 4, 4)
        url_bar = QLineEdit(self._current_url)
        url_bar.setStyleSheet(
            "QLineEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 6px 12px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #00c8ff; }"
        )
        url_bar.returnPressed.connect(lambda: self._web.load(QUrl(url_bar.text())))
        nav.addWidget(url_bar)
        layout.addLayout(nav)

        self._web.setParent(None)
        layout.addWidget(self._web)

        self._fullscreen_window.resize(1400, 850)
        self._fullscreen_window.show()

    def _exit_fullscreen(self):
        if not self._fullscreen:
            return
        self._fullscreen = False
        if self._fullscreen_window:
            self._fullscreen_window.close()
            self._fullscreen_window = None
        if self._web:
            self._web.setParent(self)
            self._web.move(self.BODY_PAD, self.TITLE_HEIGHT + self.BODY_PAD)
            self._web.show()
            self._layout_web()
            self._layout_web()

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in" and "url" in data:
            self._url_bar.setText(data["url"])
            self._navigate()

    def serialize(self) -> dict:
        d = super().serialize()
        d["current_url"] = self._current_url
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._current_url = data.get("current_url", self._current_url)
        self._url_bar.setText(self._current_url)
        if self._web:
            self._web.load(QUrl(self._current_url))


# ═══════════════════════════════════════════════════════════════════════
def _load_app_icon(icon_name: str) -> QIcon | None:
    """Load a QIcon from an icon name or desktop-file icon field."""
    if not icon_name:
        return None
    # Try theme icon first.
    icon = QIcon.fromTheme(icon_name)
    if not icon.isNull():
        return icon
    # Search common icon directories for a matching file.
    import os, glob
    roots = [
        "/run/current-system/sw/share/icons",
        os.path.expanduser("~/.local/share/icons"),
        "/usr/share/icons",
        "/usr/share/pixmaps",
    ]
    exts = (".png", ".svg", ".xpm")
    for root in roots:
        if not os.path.isdir(root):
            continue
        # Fast paths in standard theme layouts.
        for sub in ["hicolor", "Adwaita", "breeze", "gnome"]:
            base = os.path.join(root, sub)
            if not os.path.isdir(base):
                continue
            for size_dir in ["scalable", "symbolic"]:
                for ext in exts:
                    candidate = os.path.join(base, size_dir, "apps", f"{icon_name}{ext}")
                    if os.path.isfile(candidate):
                        return QIcon(candidate)
            for size_dir in os.listdir(base):
                for category in ["apps", "mimetypes"]:
                    for ext in exts:
                        candidate = os.path.join(base, size_dir, category, f"{icon_name}{ext}")
                        if os.path.isfile(candidate):
                            return QIcon(candidate)
        # Fallback: shallow search, then recursive if necessary.
        for path in glob.glob(f"{root}/{icon_name}.*"):
            if path.lower().endswith(exts):
                return QIcon(path)
        for path in glob.glob(f"{root}/**/{icon_name}.*", recursive=True):
            if path.lower().endswith(exts):
                return QIcon(path)
    return None


# App Launcher Node — icon grid that spawns a card for each launched app
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Apps", "App launcher with icons — click an app to spawn a live card on the canvas")
class AppLauncherNode(BaseNodeWidget):
    # Apps we want in the launcher. Everything else is filtered out.
    _EMBEDDABLE_APPS: set[str] = {
        "Chromium", "Firefox", "VSCodium",
        "LibreOffice", "LibreOffice Writer", "LibreOffice Calc",
        "LibreOffice Impress", "LibreOffice Draw", "LibreOffice Base",
        "LibreOffice Math",
        "GIMP", "Amberol", "Krita",
        "Alacritty", "xterm", "Rofi",
        "pavucontrol", "Advanced Network Configuration",
        "Fennix", "Manage Printing",
    }

    # Force each app onto XWayland so its window can be embedded.
    _X11_LAUNCH: dict[str, dict] = {
        "Firefox": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "VSCodium": {"env": {}, "args": ["--ozone-platform=x11"]},
        "LibreOffice": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "LibreOffice Writer": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "LibreOffice Calc": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "LibreOffice Impress": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "LibreOffice Draw": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "LibreOffice Base": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "LibreOffice Math": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "GIMP": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "Amberol": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "Krita": {"env": {"QT_QPA_PLATFORM": "xcb"}, "args": []},
        "Alacritty": {"env": {"WINIT_UNIX_BACKEND": "x11"}, "args": []},
        "pavucontrol": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "Advanced Network Configuration": {"env": {"GDK_BACKEND": "x11"}, "args": []},
        "Chromium": {"env": {}, "args": ["--ozone-platform=x11"]},
    }

    def __init__(self):
        super().__init__("Apps", QColor("#1a2030"), 320)
        self._apps: list[dict] = []
        self._build_ui()
        self.add_socket("out", "data")
        QTimer.singleShot(200, self._scan)

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter apps")
        self._filter.setStyleSheet(
            "QLineEdit { background: #111318; color: #d4d4d4; border: 1px solid #262a32; "
            "border-radius: 5px; padding: 4px 7px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #00c8ff; }"
        )
        self._filter.textChanged.connect(self._render_apps)
        layout.addWidget(self._filter)

        self._status = QLabel("Scanning apps...")
        self._status.setStyleSheet("color: #7f8996; font-size: 10px; background: transparent;")
        layout.addWidget(self._status)

        self._grid = QWidget()
        self._grid_layout = QGridLayout(self._grid)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidget(self._grid)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setMaximumHeight(250)
        layout.addWidget(scroll)

        refresh_btn = QPushButton("Rescan Apps")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; "
            "border-radius: 4px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #00c8ff; color: #080909; }"
        )
        refresh_btn.clicked.connect(self._scan)
        layout.addWidget(refresh_btn)

        w.setFixedHeight(360)
        self.set_body_widget(w)

    def _scan(self):
        import os, configparser, glob
        self._apps = []
        seen = set()
        for d in ["/run/current-system/sw/share/applications",
                   os.path.expanduser("~/.local/share/applications"),
                   "/etc/profiles/per-user/chvk/share/applications"]:
            for f in sorted(glob.glob(f"{d}/*.desktop")):
                try:
                    cfg = configparser.ConfigParser(interpolation=None)
                    cfg.read(f)
                    if "Desktop Entry" not in cfg:
                        continue
                    sec = cfg["Desktop Entry"]
                    name = sec.get("Name", os.path.basename(f).replace(".desktop", ""))
                    exe = sec.get("Exec", "")
                    # Drop field codes (%f, %F, %u, %U, etc.)
                    exe = " ".join(p for p in exe.split() if not p.startswith("%"))
                    icon = sec.get("Icon", "")
                    startup_wm = sec.get("StartupWMClass", "")
                    nodisplay = sec.get("NoDisplay", "false").lower() == "true"
                    terminal = sec.get("Terminal", "false").lower() == "true"
                    if nodisplay or terminal or not exe or name in seen:
                        continue
                    if name not in self._EMBEDDABLE_APPS:
                        continue
                    seen.add(name)
                    x11_cfg = self._X11_LAUNCH.get(name, {"env": {}, "args": []})
                    self._apps.append({
                        "name": name, "exec": exe, "icon": icon,
                        "desktop": f, "startup_wm": startup_wm,
                        "env": x11_cfg.get("env", {}),
                        "args": x11_cfg.get("args", []),
                    })
                except Exception:
                    pass

        self._render_apps()

    def _render_apps(self, *_):
        if not hasattr(self, "_grid_layout"):
            return
        query = ""
        if hasattr(self, "_filter"):
            query = self._filter.text().strip().lower()
        apps = sorted(self._apps, key=lambda a: a["name"].lower())
        if query:
            apps = [
                app for app in apps
                if query in app.get("name", "").lower()
                or query in app.get("exec", "").lower()
            ]

        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if hasattr(self, "_status"):
            if query:
                self._status.setText(f"{len(apps)} of {len(self._apps)} app(s)")
            else:
                self._status.setText(f"{len(self._apps)} app(s) launch as cards")

        cols = 4
        for idx, app in enumerate(apps):
            btn = QPushButton(app["name"])
            btn.setToolTip(app["exec"])
            btn.setFixedSize(68, 68)
            btn.setStyleSheet(
                "QPushButton { background: #141518; color: #888; border: 1px solid #1e1e24; "
                "border-radius: 6px; padding: 2px; font-size: 9px; text-align: center; }"
                "QPushButton:hover { color: #ff7800; border-color: #ff7800; background: #1a1a20; }"
            )
            icon = _load_app_icon(app["icon"])
            if icon:
                btn.setIcon(icon)
                btn.setIconSize(QSize(32, 32))
            btn.clicked.connect(lambda checked, a=app: self._spawn_card(a))
            self._grid_layout.addWidget(btn, idx // cols, idx % cols)

    def _spawn_card(self, app: dict):
        canvas = self._find_canvas()
        if canvas is None:
            return
        # Place the new card near the launcher, staggered by how many cards
        # already exist so they do not stack exactly on top of each other.
        offset = 30 + (len(canvas._state.get("nodes", [])) % 8) * 30
        spawn_x = self._logical_x + offset
        spawn_y = self._logical_y + offset

        # Build a DisplaySource descriptor for this app. The Display card is
        # the monitor; the local app source owns the private display machinery.
        import shlex
        argv = shlex.split(app.get("exec", "")) + app.get("args", [])
        source_spec = {
            "kind": "local-app",
            "argv": argv or ["alacritty"],
            "env": app.get("env", {}),
            "width": 1280,
            "height": 720,
            "aspect": 16 / 9,
            "card_title": app.get("name", "App"),
            "surface_name": app.get("name", "App"),
            "surface_kind": "app",
            "source_name": app.get("name", "App"),
            "source_kind": "local-app",
            "icon": app.get("icon", ""),
            "context": {
                "app": app.get("name", "App"),
                "exec": app.get("exec", ""),
                "startup_wm": app.get("startup_wm", ""),
                "source": "local-app",
            },
        }
        provider = create_source(source_spec)

        card = GenericSurfaceCardNode(
            provider=provider,
            source_spec=source_spec,
            surface_name=app.get("name", "App"),
            surface_kind="app",
            width=560,
            node_title=app.get("name", "App"),
        )
        card.set_logical_pos(spawn_x, spawn_y)
        canvas._add_node(card)
        # Select the new card so it is visible immediately.
        if canvas._state.get("selected_node"):
            canvas._state["selected_node"].deselect()
        canvas._state["selected_node"] = card
        card.select()
        canvas.update()
        # Launch after the card exists so the user sees feedback immediately.
        card._launch()
        for s in self._sockets:
            if s.label == "out":
                s.push_data({
                    "app": app["name"],
                    "exec": app["exec"],
                    "type": "display_source",
                    "source_spec": source_spec,
                    "action": "spawned_display",
                })

    def _find_canvas(self):
        w = self.widget
        while w:
            if hasattr(w, "_state") and "nodes" in w._state:
                return w
            w = w.parentWidget()
        return None

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"launch_app","description":"Launch a desktop application by name from the app grid","parameters":{"type":"object","properties":{"app":{"type":"string","description":"App name as shown on the Apps card"}},"required":["app"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "launch_app":
            target = arguments.get("app", "").lower()
            for a in self._apps:
                if target in a["name"].lower():
                    self._spawn_card(a)
                    return f"Spawned card for: {a['name']}"
            return f"App not found: {target}"
        return f"Unknown: {name}"

    def output_data(self, socket: SocketItem) -> dict:
        return {a["name"]: a["exec"] for a in self._apps[:10]}

    def serialize(self) -> dict:
        d = super().serialize()
        d["apps"] = self._apps[:20]
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._apps = data.get("apps", [])
        if self._apps:
            self._scan()


# ═══════════════════════════════════════════════════════════════════════
# App Card Node — one card per launched app, with thumbnail and zoom states
# ═══════════════════════════════════════════════════════════════════════

class DisplayCardNode(BaseNodeWidget):
    THUMB_INTERVAL_MS = 1200
    FRAME_INTERVAL_MS = 80
    IDLE_FRAME_INTERVAL_MS = 250
    DEFAULT_ASPECT = 4 / 3
    MIN_VIEWPORT_HEIGHT = 140
    MAX_VIEWPORT_HEIGHT = 720
    BODY_CHROME_HEIGHT = 104

    def __init__(self, title: str = "Display", color: QColor = QColor("#1a2330"),
                 width: int = 280, provider: SurfaceProvider | None = None,
                 surface_name: str | None = None, surface_kind: str = "display",
                 icon_name: str = "", provider_spec: dict | None = None,
                 source_spec: dict | None = None,
                 node_title: str | None = None,
                 auto_build: bool = True):
        super().__init__(node_title or title, color, width)
        if source_spec is not None and provider_spec is None:
            provider_spec = source_spec
        self._provider = provider
        self._provider_started = bool(provider is not None and provider.is_running())
        self._provider_spec: dict | None = None
        self._provider_error: str = ""
        self._surface_name = surface_name or title
        self._surface_kind = surface_kind
        self._surface_icon_name = icon_name
        self._surface_aspect = self.DEFAULT_ASPECT
        self._surface_context: dict = {}
        self._node_title_override = node_title
        self._last_surface_event: dict = {"event": "created", "type": "surface_event"}
        self._zoom_mode: str = "thumb"
        self._last_thumb: QPixmap | None = None
        self._fullscreen_window: QWidget | None = None
        if provider is not None:
            self._update_surface_aspect_from_dimensions(
                getattr(provider, "_width", None),
                getattr(provider, "_height", None),
            )
        if provider_spec is not None:
            if self._provider is None:
                self._attach_provider(provider_spec, launch=False)
            else:
                self._provider_spec = normalize_source_spec(provider_spec)
                self._update_surface_aspect_from_spec(self._provider_spec)
                self._apply_surface_identity(self._provider_spec)
                context = self._provider_spec.get("context")
                if isinstance(context, dict):
                    self._surface_context.update(context)
        if auto_build:
            self._build_surface_ui()
            self._add_surface_sockets()
            self._tick()

    def _build_surface_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()}; color: {WHITE.name()};")
        self._layout = QVBoxLayout(w)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(4)

        top = QHBoxLayout()
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(32, 32)
        icon = _load_app_icon(self._surface_icon_name) if self._surface_icon_name else None
        if icon:
            self._icon_label.setPixmap(icon.pixmap(32, 32))
        top.addWidget(self._icon_label)

        self._title_label = QLabel(self._surface_name)
        self._title_label.setStyleSheet("color: #d4d4d4; font-weight: bold; font-size: 12px; background: transparent;")
        self._title_label.setWordWrap(True)
        top.addWidget(self._title_label, 1)
        self._source_badge = QLabel("")
        self._source_badge.setStyleSheet(
            "color: #9aa7b5; background: #111820; border: 1px solid #26313d; "
            "border-radius: 6px; padding: 1px 6px; font-size: 9px;"
        )
        top.addWidget(self._source_badge)
        self._layout.addLayout(top)

        self._status = QLabel("Ready - attach or launch a display source")
        self._status.setStyleSheet("color: #888; font-size: 10px; padding: 2px; background: transparent;")
        self._status.setWordWrap(True)
        self._layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._buttons = {}
        for key, label, cb in [
            ("launch", "Launch", self._launch),
            ("focus", "Focus", self._focus),
            ("window", "Window", lambda: self._apply_zoom_mode("window")),
            ("fullscreen", "Fullscreen", lambda: self._apply_zoom_mode("fullscreen")),
            ("hide", "Hide", self._minimize),
            ("close", "Close", self._close),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
                "border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
                "QPushButton:hover { border-color: #ff7800; color: #ff7800; }"
            )
            btn.clicked.connect(cb)
            self._buttons[key] = btn
            btn_row.addWidget(btn)
        self._layout.addLayout(btn_row)

        self._thumb_label = QLabel()
        self._thumb_label.setStyleSheet("background: #0d0e12; border: 1px solid #1e1e24; border-radius: 4px;")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setMinimumHeight(120)
        self._thumb_label.setWordWrap(True)
        self._thumb_label.setText(self._placeholder_text())
        self._thumb_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._thumb_label.setMouseTracking(True)
        self._thumb_label.installEventFilter(self.widget)
        self._layout.addWidget(self._thumb_label, 1)

        w.setMinimumHeight(240)
        self.set_body_widget(w)
        self.widget.eventFilter = self._event_filter
        self._sync_surface_chrome()
        self._sync_surface_viewport_geometry()

    def _add_surface_sockets(self):
        existing = {s.label for s in self._sockets}
        for label, dtype in [
            ("control", "command"),
            ("status", "data"),
            ("input", "event"),
            ("events", "event"),
            ("context", "context"),
            ("context-out", "context"),
        ]:
            if label not in existing:
                self.add_socket(label, dtype)

    def _source_kind(self) -> str:
        spec = self._provider_spec or {}
        return str(
            spec.get("source_kind")
            or spec.get("kind")
            or spec.get("provider_kind")
            or self._surface_kind
            or "display"
        )

    def _source_label(self) -> str:
        kind = self._source_kind().replace("_", "-")
        labels = {
            "local-app": "local app",
            "xwayland-per-app": "xwayland",
            "fauxpass-app": "fauxpass",
            "fauxpass-local": "fauxpass",
            "fauxpass-remote": "remote",
            "display": "display",
            "app": "app",
        }
        return labels.get(kind, kind)

    def _placeholder_text(self, detail: str | None = None) -> str:
        title = self._surface_name or "Display"
        if self._provider is None:
            return f"{title}\nPlug a source into this display"
        if detail:
            return f"{title}\n{detail}"
        if self._provider_started:
            return f"{title}\nWaiting for first frame..."
        action = "Open" if self._surface_kind == "app" else "Launch"
        return f"{title}\n{action} source to begin"

    def _set_card_title(self, title: str | None):
        if not title:
            return
        self._title = str(title)
        try:
            self.widget.update()
        except Exception:
            pass

    def _sync_surface_chrome(self):
        if hasattr(self, "_source_badge"):
            label = self._source_label()
            self._source_badge.setText(f" {label} ")
            if self._surface_kind == "app" or self._source_kind() == "local-app":
                self._source_badge.setStyleSheet(
                    "color: #8fdcff; background: #0f1b24; border: 1px solid #1c5f7a; "
                    "border-radius: 6px; padding: 1px 6px; font-size: 9px;"
                )
            else:
                self._source_badge.setStyleSheet(
                    "color: #9aa7b5; background: #111820; border: 1px solid #26313d; "
                    "border-radius: 6px; padding: 1px 6px; font-size: 9px;"
                )
        if hasattr(self, "_buttons"):
            launch = self._buttons.get("launch")
            hide = self._buttons.get("hide")
            if launch is not None:
                launch.setText("Open" if self._surface_kind == "app" else "Launch")
            if hide is not None:
                hide.setText("Hide")
        if hasattr(self, "_thumb_label") and self._last_thumb is None:
            self._thumb_label.setText(self._placeholder_text())

    def _status_text(self, running: bool) -> str:
        if self._provider is None:
            return f"Empty display | zoom={self._canvas_scale():.2f} | {self._zoom_mode}"
        if running:
            state = "Live"
        elif self._provider_started:
            state = "Stopped"
        else:
            state = "Ready"
        return f"{state} | {self._source_label()} | zoom={self._canvas_scale():.2f} | {self._zoom_mode}"

    def _update_surface_aspect_from_dimensions(self, width, height):
        try:
            width = float(width)
            height = float(height)
            if width > 0 and height > 0:
                aspect = width / height
                if 0.25 <= aspect <= 5.0:
                    self._surface_aspect = aspect
        except (TypeError, ValueError):
            pass

    def _update_surface_aspect_from_spec(self, spec: dict):
        if not isinstance(spec, dict):
            return
        aspect = spec.get("aspect")
        try:
            if aspect is not None:
                aspect = float(aspect)
                if 0.25 <= aspect <= 5.0:
                    self._surface_aspect = aspect
                    return
        except (TypeError, ValueError):
            pass
        self._update_surface_aspect_from_dimensions(
            spec.get("width", spec.get("w")),
            spec.get("height", spec.get("h")),
        )

    def _surface_viewport_height(self) -> int:
        body_w = max(80, int(self._base_node_width - self.BODY_PAD * 2))
        height = int(body_w / max(0.25, self._surface_aspect))
        return max(self.MIN_VIEWPORT_HEIGHT, min(self.MAX_VIEWPORT_HEIGHT, height))

    def _sync_surface_viewport_geometry(self):
        if not hasattr(self, "_thumb_label") or self._body_widget is None:
            return
        viewport_w = max(80, int(self._base_node_width - self.BODY_PAD * 4))
        viewport_h = self._surface_viewport_height()
        body_h = self.BODY_CHROME_HEIGHT + viewport_h
        self._thumb_label.setMinimumWidth(viewport_w)
        self._thumb_label.setMinimumHeight(viewport_h)
        self._thumb_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._body_widget.setMinimumHeight(body_h)
        self._body_widget.setFixedHeight(body_h)
        layout = self._body_widget.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self._update_size()

    def _surface_viewport_target_size(self) -> tuple[int, int]:
        target_w = max(1, int(self._base_node_width - self.BODY_PAD * 4))
        target_h = max(1, self._surface_viewport_height())
        if not hasattr(self, "_thumb_label"):
            return target_w, target_h
        label_w = max(1, self._thumb_label.width())
        label_h = max(1, self._thumb_label.height())
        if label_w >= target_w * 0.8 and label_h >= target_h * 0.8:
            return label_w, label_h
        return target_w, target_h

    def set_node_width(self, w: int):
        w = max(self.MIN_WIDTH, w)
        self._base_node_width = w
        self._node_width = int(w * self._scale)
        if self._body_widget:
            bw = max(w - self.BODY_PAD * 2, 80)
            self._body_widget.setFixedWidth(bw)
        self._sync_surface_viewport_geometry()
        canvas = self.widget.parentWidget()
        pan = canvas._state.get("pan_offset", QPoint(0, 0)) if canvas and hasattr(canvas, "_state") else QPoint(0, 0)
        self.refresh_layout(self._scale, pan)
        self.widget.update()

    def _apply_surface_identity(self, spec: dict):
        name = (
            spec.get("surface_name")
            or spec.get("source_name")
            or spec.get("name")
            or spec.get("title")
        )
        kind = spec.get("surface_kind") or spec.get("display_kind")
        icon = spec.get("icon") or spec.get("icon_name")
        card_title = spec.get("card_title") or spec.get("node_title")
        if name:
            self._surface_name = str(name)
            if hasattr(self, "_title_label"):
                self._title_label.setText(self._surface_name)
        if kind:
            self._surface_kind = str(kind)
        if card_title:
            self._set_card_title(str(card_title))
        elif self._node_title_override is None and self._surface_kind == "app" and name:
            self._set_card_title(str(name))
        if icon:
            self._surface_icon_name = str(icon)
            if hasattr(self, "_icon_label"):
                loaded = _load_app_icon(self._surface_icon_name)
                if loaded:
                    self._icon_label.setPixmap(loaded.pixmap(32, 32))
        self._sync_surface_chrome()

    def _attach_provider(self, spec, launch: bool = False) -> bool:
        try:
            provider_spec = normalize_source_spec(spec)
            if self._provider is not None:
                self._provider.stop()
            self._provider = create_source(provider_spec)
            self._provider_started = False
            self._provider_spec = provider_spec
            self._provider_error = ""
            self._update_surface_aspect_from_spec(provider_spec)
            self._apply_surface_identity(provider_spec)
            self._sync_surface_viewport_geometry()
            context = provider_spec.get("context")
            if isinstance(context, dict):
                self._surface_context.update(context)
            self._record_surface_event(
                "source_attached",
                source_kind=provider_spec.get("kind"),
                provider_kind=provider_spec.get("kind"),
            )
            if launch:
                self._launch()
            return True
        except Exception as e:
            self._provider = None
            self._provider_started = False
            self._provider_spec = None
            self._provider_error = str(e)
            if hasattr(self, "_status"):
                self._status.setText(f"Source attach failed: {e}")
            self._record_surface_event("source_error", message=str(e))
            return False

    @staticmethod
    def _provider_spec_from_payload(payload):
        if not isinstance(payload, dict):
            return None
        for key in ("source_spec", "display_source", "provider_spec", "surface_provider"):
            if key in payload:
                return payload[key]
        for key in ("source", "display", "provider"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        if any(key in payload for key in (
            "kind", "source_kind", "provider_kind", "backend", "argv", "command", "exec"
        )):
            return payload
        return None

    _source_spec_from_payload = _provider_spec_from_payload

    def _emit_socket(self, label: str, data: dict):
        for socket in self._sockets:
            if socket.label == label:
                socket.push_data(data)

    def _record_surface_event(self, event_name: str, **data):
        payload = {
            "event": event_name,
            "type": "surface_event",
            "display": self._surface_name,
            "display_kind": self._surface_kind,
            "surface": self._surface_name,
            "surface_kind": self._surface_kind,
            "zoom_mode": self._zoom_mode,
        }
        payload.update(data)
        self._last_surface_event = payload
        self._emit_socket("events", payload)

    def _provider_dimensions(self) -> tuple[int, int]:
        if self._provider is None or not hasattr(self, "_thumb_label"):
            return 1, 1
        return (
            max(1, int(getattr(self._provider, "_width", self._thumb_label.width()))),
            max(1, int(getattr(self._provider, "_height", self._thumb_label.height()))),
        )

    def _resize_provider_to_card(self) -> None:
        if self._provider is None or not hasattr(self, "_thumb_label"):
            return
        try:
            width, height = self._surface_viewport_target_size()
            if (width, height) != self._provider_dimensions():
                self._provider.resize(width, height)
        except Exception:
            pass

    def _surface_status(self) -> dict:
        provider_status = {}
        provider_meta = {}
        if self._provider is not None:
            try:
                provider_status = self._provider.status()
            except Exception:
                provider_status = {}
            try:
                provider_meta = self._provider.metadata()
            except Exception:
                provider_meta = {}
        width, height = self._provider_dimensions()
        status = {
            "type": "surface_status",
            "display": self._surface_name,
            "display_kind": self._surface_kind,
            "surface": self._surface_name,
            "surface_kind": self._surface_kind,
            "source": type(self._provider).__name__ if self._provider is not None else None,
            "source_attached": self._provider is not None,
            "source_started": self._provider_started,
            "source_spec": dict(self._provider_spec) if self._provider_spec else None,
            "source_error": self._provider_error,
            "available_sources": source_descriptors(),
            "provider": type(self._provider).__name__ if self._provider is not None else None,
            "provider_attached": self._provider is not None,
            "provider_started": self._provider_started,
            "provider_spec": dict(self._provider_spec) if self._provider_spec else None,
            "provider_error": self._provider_error,
            "available_providers": provider_descriptors(),
            "running": self._provider.is_running() if self._provider is not None else False,
            "zoom_mode": self._zoom_mode,
            "width": width,
            "height": height,
            "context": dict(self._surface_context),
        }
        status.update(provider_meta)
        status.update(provider_status)
        return status

    def _push_surface_status(self):
        self._emit_socket("status", self._surface_status())

    def _canvas_scale(self) -> float:
        parent = self.widget.parentWidget()
        if parent and hasattr(parent, "_state"):
            return parent._state.get("scale", 1.0)
        return 1.0

    def refresh_layout(self, scale: float, pan_offset: QPoint):
        super().refresh_layout(scale, pan_offset)
        self._resize_provider_to_card()

    def _next_tick_interval(self) -> int:
        if self._provider is not None and self._provider.is_running():
            if self.isSelected() or self._zoom_mode in ("window", "fullscreen"):
                return self.FRAME_INTERVAL_MS
            return self.IDLE_FRAME_INTERVAL_MS
        return self.THUMB_INTERVAL_MS

    def _schedule_tick(self):
        QTimer.singleShot(self._next_tick_interval(), self._tick)

    def _map_to_provider(self, pos: QPoint) -> tuple[float, float]:
        if self._provider is None:
            return 0.0, 0.0
        tw = max(1, self._thumb_label.width())
        th = max(1, self._thumb_label.height())
        pw, ph = self._provider_dimensions()
        return pos.x() * pw / tw, pos.y() * ph / th

    @staticmethod
    def _qt_button_to_x11(button: Qt.MouseButton) -> int | None:
        return {
            Qt.MouseButton.LeftButton: 1,
            Qt.MouseButton.MiddleButton: 2,
            Qt.MouseButton.RightButton: 3,
            Qt.MouseButton.BackButton: 8,
            Qt.MouseButton.ForwardButton: 9,
        }.get(button)

    def _event_filter(self, watched, event):
        if watched is not self._thumb_label or self._provider is None:
            return False
        if event.type() == QEvent.Type.Enter:
            self._thumb_label.setFocus()
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            self._focus()
            btn = self._qt_button_to_x11(event.button())
            if btn is None:
                return False
            x, y = self._map_to_provider(event.pos())
            self._provider.send_input(InputEvent(type="button_press", x=x, y=y, button=btn))
            self._record_surface_event("pointer_button_press", x=x, y=y, button=btn)
            return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            btn = self._qt_button_to_x11(event.button())
            if btn is None:
                return False
            x, y = self._map_to_provider(event.pos())
            self._provider.send_input(InputEvent(type="button_release", x=x, y=y, button=btn))
            self._record_surface_event("pointer_button_release", x=x, y=y, button=btn)
            return True
        if event.type() == QEvent.Type.MouseMove:
            x, y = self._map_to_provider(event.pos())
            self._provider.send_input(InputEvent(type="pointer_move", x=x, y=y))
            return True
        if event.type() == QEvent.Type.Wheel:
            x, y = self._map_to_provider(event.position().toPoint())
            delta_y = event.angleDelta().y()
            if delta_y != 0:
                self._provider.send_input(InputEvent(type="axis", x=x, y=y, delta_y=delta_y))
                self._record_surface_event("axis", x=x, y=y, delta_y=delta_y)
            return True
        if event.type() == QEvent.Type.KeyPress:
            self._focus()
            keycode = event.nativeScanCode()
            if keycode > 0:
                self._provider.send_input(InputEvent(type="key_press", key=keycode))
                self._record_surface_event("key_press", key=keycode)
            return True
        if event.type() == QEvent.Type.KeyRelease:
            keycode = event.nativeScanCode()
            if keycode > 0:
                self._provider.send_input(InputEvent(type="key_release", key=keycode))
            return True
        return False

    def _tick(self):
        if self._provider is not None:
            self._resize_provider_to_card()
            self._provider.poll()
            frame = self._provider.get_frame()
            if frame is not None:
                data, w, h = frame
                try:
                    tw = max(1, self._thumb_label.width())
                    th = max(1, self._thumb_label.height())
                    scaled = _scale_rgba(data, w, h, tw, th)
                    image = QImage(scaled, tw, th, tw * 4, QImage.Format.Format_RGBA8888).copy()
                    pixmap = QPixmap.fromImage(image)
                    self._last_thumb = pixmap
                    self._thumb_label.setPixmap(pixmap)

                    if self._fullscreen_window is not None and hasattr(self, "_fullscreen_label"):
                        fs_label = self._fullscreen_label
                        fw = max(1, fs_label.width())
                        fh = max(1, fs_label.height())
                        fscaled = _scale_rgba(data, w, h, fw, fh)
                        fimage = QImage(fscaled, fw, fh, fw * 4, QImage.Format.Format_RGBA8888).copy()
                        fs_label.setPixmap(QPixmap.fromImage(fimage))
                except Exception:
                    pass
            elif self._last_thumb is None:
                self._thumb_label.setText(self._placeholder_text())
            if not self.isSelected() and self._zoom_mode != "thumb":
                self._apply_zoom_mode("thumb")
            running = self._provider.is_running()
            self._status.setText(self._status_text(running))
        else:
            self._status.setText(self._status_text(False))
        self._schedule_tick()

    def _apply_zoom_mode(self, mode: str):
        if mode == self._zoom_mode:
            return
        old = self._zoom_mode
        self._zoom_mode = mode
        if mode == "thumb" and old == "fullscreen":
            self._exit_fullscreen()
        elif mode == "fullscreen" and old == "thumb":
            self._enter_fullscreen()
        if self._provider is not None:
            if mode == "thumb":
                self._provider.minimize()
            else:
                self._focus()
        self._record_surface_event("zoom_mode", mode=mode)

    def _enter_fullscreen(self):
        if self._fullscreen_window is not None:
            return
        w = QWidget()
        w.setWindowTitle(f"{self._surface_name} — Esc to exit")
        w.setWindowFlags(Qt.WindowType.Window)
        w.setStyleSheet("background: #0b0d12;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self._fullscreen_label = QLabel()
        self._fullscreen_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._fullscreen_label)
        w.showFullScreen()
        self._fullscreen_window = w

    def _exit_fullscreen(self):
        if self._fullscreen_window is None:
            return
        self._fullscreen_window.close()
        self._fullscreen_window.deleteLater()
        self._fullscreen_window = None
        self._fullscreen_label = None

    def _launch(self):
        if self._provider is None or self._provider_started:
            return
        try:
            if hasattr(self, "_status"):
                self._status.setText(f"Launching {self._surface_name}...")
            if hasattr(self, "_thumb_label") and self._last_thumb is None:
                self._thumb_label.setText(self._placeholder_text("Starting source..."))
            self._provider.start()
            self._provider_started = True
            self._resize_provider_to_card()
            self._apply_zoom_mode("fullscreen")
            self._record_surface_event("started")
        except Exception as e:
            self._status.setText(f"Launch failed: {e}")
            self._record_surface_event("error", message=str(e))

    def _focus(self):
        if self._provider is None:
            return
        self._thumb_label.setFocus()
        self._provider.focus()
        self._record_surface_event("focused")

    def _minimize(self):
        if self._provider is None:
            return
        if self._zoom_mode != "thumb":
            self._apply_zoom_mode("thumb")
        self._provider.minimize()
        if hasattr(self, "_status"):
            self._status.setText(f"Hidden | {self._source_label()}")
        self._record_surface_event("minimized")

    def _close(self):
        if self._provider is None:
            return
        if self._provider_started and self._zoom_mode != "thumb":
            self._apply_zoom_mode("thumb")
        self._provider.close()
        self._provider_started = False
        self._last_thumb = None
        if hasattr(self, "_thumb_label"):
            self._thumb_label.clear()
            self._thumb_label.setText(self._placeholder_text("Source closed"))
        if hasattr(self, "_status"):
            self._status.setText(self._status_text(False))
        self._record_surface_event("closed")

    def _handle_surface_control(self, data):
        if isinstance(data, str):
            action = data.strip().lower()
            payload = {}
        elif isinstance(data, dict):
            payload = data
            action = str(
                data.get("action")
                or data.get("command")
                or data.get("control")
                or ""
            ).strip().lower()
            if not action and self._provider_spec_from_payload(payload) is not None:
                action = "attach"
        else:
            return
        if action in (
            "attach", "attach-source", "attach_source", "set-source", "set_source",
            "attach-provider", "attach_provider", "set-provider", "set_provider",
        ):
            spec = self._provider_spec_from_payload(payload)
            if spec is not None:
                self._attach_provider(spec, launch=bool(payload.get("launch", False)))
        elif action in ("launch", "start", "open"):
            spec = self._provider_spec_from_payload(payload)
            if spec is not None:
                self._attach_provider(spec, launch=True)
            else:
                self._launch()
        elif action == "focus":
            self._focus()
        elif action in ("minimize", "hide"):
            self._minimize()
        elif action in ("close", "stop"):
            self._close()
        elif action in ("detach", "detach-source", "detach_source", "detach-provider", "detach_provider"):
            if self._provider is not None:
                self._provider.stop()
            self._provider = None
            self._provider_started = False
            self._provider_spec = None
            self._provider_error = ""
            self._record_surface_event("source_detached")
        elif action in ("sources", "list-sources", "list_sources", "providers", "list-providers", "list_providers"):
            self._record_surface_event(
                "sources",
                sources=source_descriptors(),
                providers=provider_descriptors(),
            )
        elif action in ("thumb", "thumbnail"):
            self._apply_zoom_mode("thumb")
        elif action in ("window", "card"):
            self._apply_zoom_mode("window")
        elif action == "fullscreen":
            self._apply_zoom_mode("fullscreen")
        elif action == "resize" and self._provider is not None:
            width = int(payload.get("width", payload.get("w", self._provider_dimensions()[0])))
            height = int(payload.get("height", payload.get("h", self._provider_dimensions()[1])))
            self._provider.resize(max(1, width), max(1, height))
            self._record_surface_event("resized", width=width, height=height)
        elif action in ("set-title", "set_title"):
            title = str(payload.get("title", self._surface_name))
            self._surface_name = title
            if hasattr(self, "_title_label"):
                self._title_label.setText(title)
            self._record_surface_event("title_changed", title=title)
        if payload.get("context") and isinstance(payload["context"], dict):
            self._surface_context.update(payload["context"])
        self._push_surface_status()

    def _handle_surface_input(self, data):
        if self._provider is None:
            return
        events = data.get("events") if isinstance(data, dict) else None
        if events is None:
            events = [data]
        for item in events:
            if not isinstance(item, dict):
                continue
            event_type = item.get("type") or item.get("event")
            if not event_type:
                continue
            self._provider.send_input(InputEvent(
                type=str(event_type),
                x=float(item.get("x", 0.0)),
                y=float(item.get("y", 0.0)),
                button=item.get("button"),
                key=item.get("key"),
                modifiers=int(item.get("modifiers", 0)),
                delta_x=float(item.get("delta_x", 0.0)),
                delta_y=float(item.get("delta_y", 0.0)),
            ))
        self._record_surface_event("input_received")

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "control":
            self._handle_surface_control(data)
        elif socket.label == "input":
            self._handle_surface_input(data)
        elif socket.label == "context" and isinstance(data, dict):
            self._surface_context.update(data)
            self._record_surface_event("context_updated")
            self._push_surface_status()

    def output_data(self, socket: SocketItem) -> dict:
        if socket.label == "status":
            return self._surface_status()
        if socket.label == "events":
            return self._last_surface_event
        if socket.label in ("context-out", "context"):
            return {
                "type": "display_context",
                "display": self._surface_name,
                "display_kind": self._surface_kind,
                "surface": self._surface_name,
                "surface_kind": self._surface_kind,
                "context": dict(self._surface_context),
                "status": self._surface_status(),
            }
        return {}

    def cleanup(self):
        if self._provider is not None:
            self._provider.stop()

    def serialize(self) -> dict:
        d = super().serialize()
        d["surface_name"] = self._surface_name
        d["surface_kind"] = self._surface_kind
        d["surface_context"] = self._surface_context
        d["source_spec"] = self._provider_spec
        d["provider_spec"] = self._provider_spec
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._surface_name = data.get("surface_name", self._surface_name)
        self._surface_kind = data.get("surface_kind", self._surface_kind)
        self._surface_context = data.get("surface_context", {})
        provider_spec = data.get("source_spec", data.get("provider_spec"))
        if provider_spec is not None and self._provider is None:
            self._attach_provider(provider_spec, launch=False)
        if hasattr(self, "_title_label"):
            self._title_label.setText(self._surface_name)


SurfaceCardNode = DisplayCardNode


@register_node_type("Surface", "Compatibility alias for Display cards")
@register_node_type("Display", "Monitor-style card - plug in any app, VM, remote, or stream source")
class GenericSurfaceCardNode(DisplayCardNode):
    def __init__(self, provider: SurfaceProvider | None = None, provider_spec: dict | None = None,
                 source_spec: dict | None = None,
                 surface_name: str = "Display", surface_kind: str = "display",
                 width: int = 320, node_title: str | None = None):
        super().__init__(
            node_title or "Display",
            QColor("#1a2330"),
            width,
            provider=provider,
            provider_spec=provider_spec,
            source_spec=source_spec,
            surface_name=surface_name,
            surface_kind=surface_kind,
            node_title=node_title,
        )


DisplayNode = GenericSurfaceCardNode


@register_node_type("App", "Compatibility app card; Apps launcher now prefers Display cards with local-app sources")
class AppCardNode(SurfaceCardNode):
    
    def __init__(self, app: dict | None = None, provider: SurfaceProvider | None = None,
                 provider_spec: dict | None = None):
        app = app or {}
        self._app_name = app.get("name", "App")
        self._app_exec = app.get("exec", "")
        self._app_icon_name = app.get("icon", "")
        self._startup_wm = app.get("startup_wm", "")
        self._x11_env: dict[str, str] = app.get("env", {})
        self._x11_args: list[str] = app.get("args", [])
        super().__init__(
            "App", QColor("#1a2330"), 280,
            provider=provider,
            provider_spec=provider_spec,
            surface_name=self._app_name,
            surface_kind="app",
            icon_name=self._app_icon_name,
            auto_build=False,
        )
        self._wm = get_window_manager()
        self._surface_context.update({
            "app": self._app_name,
            "exec": self._app_exec,
            "startup_wm": self._startup_wm,
        })
        self._app_id_hints: set[str] = set()
        if self._startup_wm:
            self._app_id_hints.add(self._startup_wm)
        if self._app_name:
            self._app_id_hints.add(self._app_name)
        # Derive an app-id hint from the exec command basename.
        if self._app_exec:
            base = self._app_exec.split()[0].split("/")[-1]
            if base:
                self._app_id_hints.add(base)
        self._process: subprocess.Popen | None = None
        self._pid: int | None = None
        self._window_info: dict | None = None
        self._build_ui()
        self._add_surface_sockets()
        self._tick()

    def refresh_layout(self, scale: float, pan_offset: QPoint):
        super().refresh_layout(scale, pan_offset)
        if self._provider is not None and hasattr(self, "_thumb_label"):
            self._resize_provider_to_card()

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()}; color: {WHITE.name()};")
        self._layout = QVBoxLayout(w)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(4)

        top = QHBoxLayout()
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(32, 32)
        icon = _load_app_icon(self._app_icon_name) if self._app_icon_name else None
        if icon:
            self._icon_label.setPixmap(icon.pixmap(32, 32))
        top.addWidget(self._icon_label)

        self._title_label = QLabel(self._app_name)
        self._title_label.setStyleSheet("color: #d4d4d4; font-weight: bold; font-size: 12px; background: transparent;")
        self._title_label.setWordWrap(True)
        top.addWidget(self._title_label, 1)
        self._layout.addLayout(top)

        self._status = QLabel("Ready — click Launch")
        self._status.setStyleSheet("color: #888; font-size: 10px; padding: 2px; background: transparent;")
        self._status.setWordWrap(True)
        self._layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        for label, cb in [
            ("Launch", self._launch),
            ("Focus", self._focus),
            ("Window", lambda: self._apply_zoom_mode("window")),
            ("Fullscreen", lambda: self._apply_zoom_mode("fullscreen")),
            ("Min", self._minimize),
            ("Close", self._close),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
                "border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
                "QPushButton:hover { border-color: #ff7800; color: #ff7800; }"
            )
            btn.clicked.connect(cb)
            btn_row.addWidget(btn)
        self._layout.addLayout(btn_row)

        self._thumb_label = QLabel()
        self._thumb_label.setStyleSheet("background: #0d0e12; border: 1px solid #1e1e24; border-radius: 4px;")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setMinimumHeight(120)
        self._thumb_label.setWordWrap(True)
        self._thumb_label.setText("Thumbnail will appear when the app window is visible")
        self._thumb_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._thumb_label.setMouseTracking(True)
        self._thumb_label.installEventFilter(self.widget)
        self._layout.addWidget(self._thumb_label, 1)

        w.setMinimumHeight(240)
        self.set_body_widget(w)
        self.widget.eventFilter = self._event_filter
        self._sync_surface_viewport_geometry()

    def _find_window(self) -> dict | None:
        # If we already know the window, verify it still exists on X11.
        if self._window_info:
            cached_app_id = self._window_info.get("app_id", "")
            cached_title = self._window_info.get("title", "")
            geom = find_window_geometry(app_id=cached_app_id, title=cached_title)
            if geom:
                return {**geom, "app_id": cached_app_id, "title": cached_title}
        # Prefer PID match if we launched the process.
        if self._pid:
            info = find_window_for_pid(self._pid)
            if info:
                return info
        # Fall back to app-id/title matching.
        for app_id in self._app_id_hints:
            for win in self._wm.list_windows():
                if app_id.lower() in win.app_id.lower() or app_id.lower() in win.title.lower():
                    geom = find_window_geometry(app_id=win.app_id, title=win.title)
                    if geom:
                        return {**geom, "app_id": win.app_id, "title": win.title}
        return None

    def _canvas_scale(self) -> float:
        parent = self.widget.parentWidget()
        if parent and hasattr(parent, "_state"):
            return parent._state.get("scale", 1.0)
        return 1.0

    def _card_screen_geometry(self) -> tuple[int, int, int, int] | None:
        if not self.widget.parentWidget():
            return None
        pos = self.widget.mapToGlobal(QPoint(0, 0))
        return pos.x(), pos.y(), self.widget.width(), self.widget.height()

    def _surface_status(self) -> dict:
        status = super()._surface_status()
        status.update({
            "surface": self._app_name,
            "surface_kind": "app",
            "app": self._app_name,
            "exec": self._app_exec,
            "startup_wm": self._startup_wm,
            "window_info": self._window_info,
        })
        if self._provider is None:
            process_running = self._process is not None and self._process.poll() is None
            status.update({
                "provider": "native-window-fallback",
                "running": bool(self._window_info or process_running),
            })
        return status

    # ═══════════════════════════════════════════════════════════════════════
    # Input forwarding for surface-provider cards
    # ═══════════════════════════════════════════════════════════════════════

    def _provider_dimensions(self) -> tuple[int, int]:
        if self._provider is None:
            return 1, 1
        return (
            max(1, int(getattr(self._provider, "_width", self._thumb_label.width()))),
            max(1, int(getattr(self._provider, "_height", self._thumb_label.height()))),
        )

    def _resize_provider_to_card(self) -> None:
        if self._provider is None:
            return
        try:
            width, height = self._surface_viewport_target_size()
            if (width, height) != self._provider_dimensions():
                self._provider.resize(width, height)
        except Exception:
            pass

    def _map_to_provider(self, pos: QPoint) -> tuple[float, float]:
        """Map a point inside the thumbnail label to provider framebuffer coords."""
        if self._provider is None:
            return 0.0, 0.0
        tw = max(1, self._thumb_label.width())
        th = max(1, self._thumb_label.height())
        pw, ph = self._provider_dimensions()
        px = pos.x() * pw / tw
        py = pos.y() * ph / th
        return px, py

    @staticmethod
    def _qt_button_to_x11(button: Qt.MouseButton) -> int | None:
        return {
            Qt.MouseButton.LeftButton: 1,
            Qt.MouseButton.MiddleButton: 2,
            Qt.MouseButton.RightButton: 3,
            Qt.MouseButton.BackButton: 8,
            Qt.MouseButton.ForwardButton: 9,
        }.get(button)

    def _event_filter(self, watched, event):
        """Filter thumb-label events when a Display source is active."""
        if watched is not self._thumb_label or self._provider is None:
            return False

        if event.type() == QEvent.Type.Enter:
            self._thumb_label.setFocus()
            return False

        if event.type() == QEvent.Type.MouseButtonPress:
            self._focus()
            btn = self._qt_button_to_x11(event.button())
            if btn is None:
                return False
            x, y = self._map_to_provider(event.pos())
            self._provider.send_input(InputEvent(type="button_press", x=x, y=y, button=btn))
            return True

        if event.type() == QEvent.Type.MouseButtonRelease:
            btn = self._qt_button_to_x11(event.button())
            if btn is None:
                return False
            x, y = self._map_to_provider(event.pos())
            self._provider.send_input(InputEvent(type="button_release", x=x, y=y, button=btn))
            return True

        if event.type() == QEvent.Type.MouseMove:
            x, y = self._map_to_provider(event.pos())
            self._provider.send_input(InputEvent(type="pointer_move", x=x, y=y))
            return True

        if event.type() == QEvent.Type.Wheel:
            x, y = self._map_to_provider(event.position().toPoint())
            delta_y = event.angleDelta().y()
            if delta_y != 0:
                self._provider.send_input(InputEvent(type="axis", x=x, y=y, delta_y=delta_y))
            return True

        if event.type() == QEvent.Type.KeyPress:
            self._focus()
            keycode = event.nativeScanCode()
            if keycode > 0:
                self._provider.send_input(InputEvent(type="key_press", key=keycode))
            return True

        if event.type() == QEvent.Type.KeyRelease:
            keycode = event.nativeScanCode()
            if keycode > 0:
                self._provider.send_input(InputEvent(type="key_release", key=keycode))
            return True

        return False

    def _tick(self):
        if self._provider is not None:
            self._resize_provider_to_card()
            self._provider.poll()
            frame = self._provider.get_frame()
            if frame is not None:
                data, w, h = frame
                try:
                    tw = max(1, self._thumb_label.width())
                    th = max(1, self._thumb_label.height())
                    scaled = _scale_rgba(data, w, h, tw, th)
                    image = QImage(scaled, tw, th, tw * 4, QImage.Format.Format_RGBA8888).copy()
                    pixmap = QPixmap.fromImage(image)
                    self._last_thumb = pixmap
                    self._thumb_label.setPixmap(pixmap)
                except Exception:
                    pass
            if not self.isSelected() and self._zoom_mode != "thumb":
                self._apply_zoom_mode("thumb")
            running = self._provider.is_running()
            self._status.setText(
                f"{'Live' if running else 'Stopped'} | zoom={self._canvas_scale():.2f} | {self._zoom_mode}"
            )
            self._schedule_tick()
            return

        self._window_info = self._find_window()
        if self._window_info:
            self._title_label.setText(self._window_info.get("title") or self._app_name)
            self._capture_thumb()
            if not self.isSelected() and self._zoom_mode != "thumb":
                self._apply_zoom_mode("thumb")
            self._status.setText(
                f"{self._window_info.get('app_id', 'app')} | zoom={self._canvas_scale():.2f} | {self._zoom_mode}"
            )
        else:
            self._title_label.setText(self._app_name)
            self._status.setText(f"Not running | zoom={self._canvas_scale():.2f} | {self._zoom_mode}")

        self._schedule_tick()

    def _capture_thumb(self):
        result = None
        if self._pid and self._window_info:
            result = capture_thumbnail_for_pid(self._pid, max_size=260)
        if result is None and self._window_info:
            result = capture_thumbnail(
                app_id=self._window_info.get("app_id"),
                title=self._window_info.get("title"),
                max_size=260,
            )
        if result is None:
            return
        data, w, h = result
        try:
            tw = max(1, self._thumb_label.width())
            th = max(1, self._thumb_label.height())
            scaled = _scale_rgba(data, w, h, tw, th)
            image = QImage(scaled, tw, th, tw * 4, QImage.Format.Format_RGBA8888).copy()
            pixmap = QPixmap.fromImage(image)
            self._last_thumb = pixmap
            self._thumb_label.setPixmap(pixmap)
        except Exception:
            pass

    def _apply_zoom_mode(self, mode: str):
        self._zoom_mode = mode
        if self._provider is not None:
            if mode == "thumb":
                self._provider.minimize()
            else:
                self._focus()
            self._record_surface_event("zoom_mode", mode=mode)
            return
        if not self._window_info:
            return
        title = self._window_info.get("title", "")
        app_id = self._window_info.get("app_id", "")
        if mode == "thumb":
            self._wm.minimize(title)
        elif mode == "window":
            self._wm.focus(title)
            geom = self._card_screen_geometry()
            if geom:
                x, y, cw, ch = geom
                nw = max(cw, 900)
                nh = max(ch, 600)
                x = max(0, x - (nw - cw) // 2)
                y = max(0, y - (nh - ch) // 2)
                move_resize_window(app_id=app_id, title=title, x=x, y=y, width=nw, height=nh)
            raise_window(app_id=app_id, title=title)
        elif mode == "fullscreen":
            self._wm.fullscreen(title)
        self._record_surface_event("zoom_mode", mode=mode)

    def _launch(self):
        if self._provider is not None:
            if self._provider_started:
                return
            try:
                self._provider.start()
                self._provider_started = True
                self._resize_provider_to_card()
                self._focus()
                self._status.setText("Launching...")
                self._record_surface_event("started")
            except Exception as e:
                self._status.setText(f"Launch failed: {e}")
                self._record_surface_event("error", message=str(e))
            return

        if self._process and self._process.poll() is None:
            self._focus()
            return
        if self._window_info:
            self._focus()
            return
        try:
            import shlex, os
            env = os.environ.copy()
            for k, v in self._x11_env.items():
                env[k] = v
            cmd = shlex.split(self._app_exec) + self._x11_args
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            self._pid = self._process.pid
            self._status.setText("Launching...")
            self._record_surface_event("started", pid=self._pid)
        except Exception as e:
            self._status.setText(f"Launch failed: {e}")
            self._record_surface_event("error", message=str(e))

    def _focus(self):
        if self._provider is not None:
            self._thumb_label.setFocus()
            self._provider.focus()
            self._record_surface_event("focused")
            return
        if self._window_info:
            self._wm.focus(self._window_info.get("title", ""))
            self._record_surface_event("focused", title=self._window_info.get("title", ""))

    def _minimize(self):
        if self._provider is not None:
            self._provider.minimize()
            self._record_surface_event("minimized")
            return
        if self._window_info:
            self._wm.minimize(self._window_info.get("title", ""))
            self._record_surface_event("minimized", title=self._window_info.get("title", ""))

    def _close(self):
        if self._provider is not None:
            self._provider.close()
            self._provider_started = False
            self._record_surface_event("closed")
            return
        if self._window_info:
            self._wm.close(self._window_info.get("title", ""))
            self._window_info = None
            self._record_surface_event("closed")
        elif self._process and self._process.poll() is None:
            self._process.terminate()
            self._record_surface_event("closed")

    def cleanup(self):
        if self._provider is not None:
            self._provider.stop()
            return
        if self._window_info:
            self._wm.minimize(self._window_info.get("title", ""))

    def serialize(self) -> dict:
        d = super().serialize()
        d["app_name"] = self._app_name
        d["app_exec"] = self._app_exec
        d["app_icon"] = self._app_icon_name
        d["startup_wm"] = self._startup_wm
        d["env"] = self._x11_env
        d["args"] = self._x11_args
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._app_name = data.get("app_name", self._app_name)
        self._app_exec = data.get("app_exec", self._app_exec)
        self._app_icon_name = data.get("app_icon", self._app_icon_name)
        self._startup_wm = data.get("startup_wm", self._startup_wm)
        self._x11_env = data.get("env", {})
        self._x11_args = data.get("args", [])
        self._surface_name = self._app_name
        self._surface_kind = "app"
        self._surface_context.update({
            "app": self._app_name,
            "exec": self._app_exec,
            "startup_wm": self._startup_wm,
        })
        self._title_label.setText(self._app_name)
        icon = _load_app_icon(self._app_icon_name) if self._app_icon_name else None
        if icon:
            self._icon_label.setPixmap(icon.pixmap(32, 32))


# ═══════════════════════════════════════════════════════════════════════
# Fauxpass Sources Node — bridge faux-pass app sources into Display cards
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Fauxpass", "List faux-pass local/remote app sources and spawn Display cards")
class FauxPassSourcesNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Fauxpass", QColor("#182230"), 340)
        self._sources: list[dict] = []
        self._last_error = ""
        self._build_ui()
        self.add_socket("control", "command")
        self.add_socket("out", "data")
        QTimer.singleShot(200, self._refresh)

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()}; color: {WHITE.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._status = QLabel("Scanning faux-pass sources...")
        self._status.setStyleSheet("color: #888; font-size: 10px; padding: 2px; background: transparent;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidget(self._list)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setMaximumHeight(240)
        layout.addWidget(scroll)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; "
            "border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
            "QPushButton:hover { background: #00c8ff; color: #080909; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        layout.addWidget(refresh_btn)

        w.setMinimumHeight(300)
        self.set_body_widget(w)

    def _run_faux_pass(self, *args: str) -> dict:
        import subprocess

        try:
            result = subprocess.run(
                ["faux-pass", "--json", *args],
                check=False,
                timeout=8,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                payload = json.loads(result.stdout)
            else:
                payload = {}
            if result.returncode != 0 and "ok" not in payload:
                payload = {"ok": False, "error": result.stderr.strip() or "faux-pass failed"}
            return payload
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}

    def _refresh(self):
        payload = self._run_faux_pass("apps")
        if not payload.get("ok"):
            self._sources = []
            self._last_error = str(payload.get("error", "faux-pass unavailable"))
            self._status.setText(self._last_error)
            self._render_sources()
            return
        apps = payload.get("apps", [])
        self._sources = [app for app in apps if isinstance(app, dict)]
        self._last_error = ""
        remote_count = sum(1 for app in self._sources if app.get("remote"))
        self._status.setText(f"{len(self._sources)} source(s) | {remote_count} remote")
        self._render_sources()
        self._push_sources()

    def _render_sources(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._sources:
            empty = QLabel(self._last_error or "No faux-pass sources found")
            empty.setStyleSheet("color: #777; font-size: 11px; background: transparent;")
            empty.setWordWrap(True)
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch()
            return

        for source in self._sources:
            provider = source.get("provider_name") or source.get("provider") or "provider"
            badge = "remote" if source.get("remote") else "local"
            launchable = "launchable" if source.get("launchable") else "planned"
            label = f"{source.get('name', source.get('id', 'app'))}  ·  {provider}  ·  {badge}/{launchable}"
            btn = QPushButton(label)
            btn.setToolTip(json.dumps(self._provider_spec(source), sort_keys=True))
            btn.setStyleSheet(
                "QPushButton { background: #141518; color: #d4d4d4; border: 1px solid #1e1e24; "
                "border-radius: 5px; padding: 5px 8px; font-size: 10px; text-align: left; }"
                "QPushButton:hover { color: #00c8ff; border-color: #00c8ff; background: #16202a; }"
            )
            btn.clicked.connect(lambda checked, app=source: self._spawn_display(app))
            self._list_layout.addWidget(btn)
        self._list_layout.addStretch()

    def _provider_spec(self, source: dict) -> dict:
        name = str(source.get("name") or source.get("id") or "Fauxpass App")
        provider_id = str(source.get("provider") or "")
        return {
            "kind": "fauxpass-app",
            "app": str(source.get("id") or name),
            "provider_id": provider_id,
            "width": 800,
            "height": 600,
            "surface_name": name,
            "surface_kind": "fauxpass-remote" if source.get("remote") else "fauxpass-local",
            "source_name": name,
            "source_kind": "fauxpass-app",
            "context": {
                "source": "faux-pass",
                "provider": provider_id,
                "provider_name": source.get("provider_name", ""),
                "remote": bool(source.get("remote")),
                "launchable": bool(source.get("launchable")),
            },
        }

    def _push_sources(self):
        for socket in self._sockets:
            if socket.label == "out":
                socket.push_data(self.output_data(socket))

    def _find_canvas(self):
        w = self.widget
        while w:
            if hasattr(w, "_state") and "nodes" in w._state:
                return w
            w = w.parentWidget()
        return None

    def _spawn_display(self, source: dict):
        canvas = self._find_canvas()
        spec = self._provider_spec(source)
        if canvas is None:
            self._push_sources()
            return
        offset = 30 + (len(canvas._state.get("nodes", [])) % 8) * 30
        card = GenericSurfaceCardNode(
            source_spec=spec,
            surface_name=spec["surface_name"],
            surface_kind=spec["surface_kind"],
        )
        card.set_logical_pos(self._logical_x + offset, self._logical_y + offset)
        canvas._add_node(card)
        if canvas._state.get("selected_node"):
            canvas._state["selected_node"].deselect()
        canvas._state["selected_node"] = card
        card.select()
        canvas.update()
        card._launch()
        for socket in self._sockets:
            if socket.label == "out":
                socket.push_data({
                    "type": "fauxpass_source",
                    "action": "spawned_display",
                    "source": source,
                    "source_spec": spec,
                    "provider_spec": spec,
                })

    def on_data_received(self, socket: SocketItem, data):
        if socket.label != "control":
            return
        if isinstance(data, str):
            action = data.strip().lower()
            if action == "refresh":
                self._refresh()
            else:
                self._launch_named(action)
        elif isinstance(data, dict):
            action = str(data.get("action") or data.get("command") or "").strip().lower()
            if action == "refresh":
                self._refresh()
            elif action in ("launch", "open", "spawn"):
                self._launch_named(str(data.get("app") or data.get("id") or data.get("name") or ""))

    def _launch_named(self, query: str):
        wanted = query.strip().lower()
        if not wanted:
            return
        for source in self._sources:
            names = [str(source.get("id", "")), str(source.get("name", ""))]
            if any(wanted == name.lower() or wanted in name.lower() for name in names):
                self._spawn_display(source)
                return

    def output_data(self, socket: SocketItem) -> dict:
        return {
            "type": "fauxpass_sources",
            "sources": self._sources,
            "source_specs": [self._provider_spec(source) for source in self._sources],
            "provider_specs": [self._provider_spec(source) for source in self._sources],
            "error": self._last_error,
        }

    def serialize(self) -> dict:
        d = super().serialize()
        d["sources"] = self._sources
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._sources = data.get("sources", [])
        self._render_sources()


# ═══════════════════════════════════════════════════════════════════════
# Thread Node — thread activity card
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# Files Node — Archivist file evidence card
# ═══════════════════════════════════════════════════════════════════════
# Files Node — Archivist file evidence card
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Files", "File evidence from fauxd watched roots — recent, search, preview")
class FilesNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Files", QColor("#101a20"), 300)
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "file")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        self._list = QTextEdit()
        self._list.setReadOnly(True)
        self._list.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0c0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
        )
        self._list.setMinimumHeight(100)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; "
            "border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
            "QPushButton:hover { background: #00c8ff; color: #080909; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        w.setFixedHeight(160)
        self.set_body_widget(w)

        self._poller = QTimer()
        self._poller.timeout.connect(self._refresh)
        self._poller.start(15000)
        QTimer.singleShot(2000, self._refresh)

    def cleanup(self):
        self._poller.stop()

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            from ..fauxd_client import search_files
            q = data.get("text", data.get("query", ""))
            if q:
                result = search_files(q)
                if result:
                    self._list.clear()
                    for f in result[:10]:
                        name = f.get("name", f.get("path", "?"))
                        self._list.append(f"\u2022 {name}")

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"search_files","description":"Search indexed files on the system","parameters":{"type":"object","properties":{"query":{"type":"string","description":"Search query for filenames"}},"required":["query"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "search_files":
            from ..fauxd_client import search_files
            r = search_files(arguments.get("query", ""))
            if r:
                return "\n".join([f.get("name",f.get("path","?")) for f in r[:10]])
            return "No files found"
        return f"Unknown: {name}"

    def _refresh(self):
        if not self.widget.parentWidget():
            return
        try:
            result = get_files_recent(12)
            self._list.clear()
            if result:
                for f in result:
                    name = f.get("name", f.get("path", "?"))
                    src = f.get("source", "?")
                    icon = {"high": "⬤", "medium": "◉", "candidate": "○"}.get(
                        f.get("confidence", ""), "·"
                    )
                    self._list.append(f'{icon} <span style="color:#888;">[{src}]</span> {name}')
            else:
                self._list.append('<span style="color:#666;">fauxd not reachable</span>')
        except Exception:
            self._list.clear()
            self._list.append('<span style="color:#666;">fauxd offline</span>')

    def serialize(self) -> dict:
        d = super().serialize()
        d["recent"] = self._list.toPlainText().split("\n")[-15:]
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        for line in data.get("recent", []):
            self._list.append(line)


# ═══════════════════════════════════════════════════════════════════════
# Telemetry Node — CPU / RAM / battery / audio gauges
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Telemetry", "System telemetry gauges — CPU, RAM, battery, audio, network")
class TelemetryNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Telemetry", QColor("#201010"), 280)
        self._build_ui()
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        self._cpu_bar = QProgressBar()
        self._cpu_bar.setStyleSheet(
            "QProgressBar { background: #0d0e12; border: 1px solid #1e1e24; border-radius: 3px; "
            "height: 14px; text-align: center; font-size: 9px; color: #d4d4d4; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 #ff7800, stop:1 #ff9940); border-radius: 2px; }"
        )
        layout.addWidget(QLabel("CPU"))
        layout.addWidget(self._cpu_bar)

        self._ram_bar = QProgressBar()
        self._ram_bar.setStyleSheet(
            "QProgressBar { background: #0d0e12; border: 1px solid #1e1e24; border-radius: 3px; "
            "height: 14px; text-align: center; font-size: 9px; color: #d4d4d4; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 #00c8ff, stop:1 #33d4ff); border-radius: 2px; }"
        )
        layout.addWidget(QLabel("RAM"))
        layout.addWidget(self._ram_bar)

        self._battery_label = QLabel("BAT: —")
        self._battery_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._battery_label)

        self._net_label = QLabel("NET: —")
        self._net_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._net_label)

        self._audio_label = QLabel("AUD: —")
        self._audio_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._audio_label)

        w.setFixedHeight(160)
        self.set_body_widget(w)

        self._poller = QTimer()
        self._poller.timeout.connect(self._poll)
        self._poller.start(3000)
        QTimer.singleShot(100, self._poll)

    def _poll(self):
        result = get_telemetry()
        if not result:
            return
        data = result.get("telemetry", result)
        cpu_pct = data.get("cpu_percent", 0)
        ram_pct = data.get("memory_percent", 0)
        bat = data.get("battery_percent", None)
        bat_text = data.get("battery_text", "")
        net_text = data.get("network_text", "")
        audio_pct = data.get("audio_percent", None)
        audio_text = data.get("audio_text", "")

        self._cpu_bar.setValue(int(cpu_pct))
        self._ram_bar.setValue(int(ram_pct))

        if bat is not None:
            self._battery_label.setText(f"BAT: {bat}% {bat_text}")
        self._net_label.setText(f"NET: {net_text}")
        if audio_pct is not None:
            self._audio_label.setText(f"AUD: {audio_pct}% {audio_text}")

    def serialize(self) -> dict:
        return super().serialize()

    def deserialize(self, data: dict):
        super().deserialize(data)
        QTimer.singleShot(500, self._poll)


# ═══════════════════════════════════════════════════════════════════════
# Weather Node — weather card
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Weather", "Local weather from fauxd / wttr.in")
class WeatherNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Weather", QColor("#1a201a"), 200)
        self._build_ui()
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        self._label = QLabel("Loading...")
        self._label.setStyleSheet(f"color: {WHITE.name()}; font-size: 12px;")
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        w.setFixedHeight(50)
        self.set_body_widget(w)

        self._poller = QTimer()
        self._poller.timeout.connect(self._poll)
        self._poller.start(600000)
        QTimer.singleShot(100, self._poll)

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"get_weather","description":"Get current weather for the configured location","parameters":{"type":"object","properties":{}}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "get_weather":
            self._poll()
            return self._label.text()
        return f"Unknown: {name}"

    def _poll(self):
        result = get_weather()
        if result:
            temp = result.get("temperature", result.get("temp", "?"))
            cond = result.get("condition", result.get("weather", "?"))
            loc = result.get("location", "")
            self._label.setText(f"{loc}  {temp}  {cond}")
        else:
            self._label.setText("Weather unavailable")

    def serialize(self) -> dict:
        d = super().serialize()
        d["last_weather"] = self._label.text()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._label.setText(data.get("last_weather", "Loading..."))


# ═══════════════════════════════════════════════════════════════════════
# Notes Node — notes and clipboard card
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Notes", "Notes and clipboard — capture ideas and clipboard content")
class NotesNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Notes", QColor("#201a10"), 300)
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        self._notes_list = QTextEdit()
        self._notes_list.setReadOnly(True)
        self._notes_list.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0c0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
        )
        self._notes_list.setMinimumHeight(80)
        layout.addWidget(self._notes_list)

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Type a note...")
        self._input.setStyleSheet(
            "QPlainTextEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
            "QPlainTextEdit:focus { border-color: #ff7800; }"
        )
        self._input.setMaximumHeight(50)
        layout.addWidget(self._input)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(
            "QPushButton { background: #ff7800; color: #080909; border: none; "
            "border-radius: 4px; padding: 3px 12px; font-size: 11px; }"
            "QPushButton:hover { background: #ff9940; }"
        )
        save_btn.clicked.connect(self._save_note)
        btn_row.addWidget(save_btn)

        clip_btn = QPushButton("Clip")
        clip_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 3px 12px; font-size: 11px; }"
            "QPushButton:hover { border-color: #ff7800; }"
        )
        clip_btn.clicked.connect(self._paste_clipboard)
        btn_row.addWidget(clip_btn)
        layout.addLayout(btn_row)

        w.setFixedHeight(180)
        self.set_body_widget(w)

        QTimer.singleShot(100, self._refresh_notes)

    def _save_note(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        title = text[:40] + ("..." if len(text) > 40 else "")
        from ..fauxd_client import create_note
        result = create_note(title, text)
        if result:
            self._refresh_notes()
            for s in self._sockets:
                if s.label == "out":
                    s.push_data({"text": text, "type": "note"})

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            text = data.get("text", data.get("content", ""))
            if text:
                from ..fauxd_client import create_note
                title = text[:40] + ("..." if len(text) > 40 else "")
                create_note(title, text)
                QTimer.singleShot(500, self._refresh_notes)

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"create_note","description":"Create a new note in the system","parameters":{"type":"object","properties":{"content":{"type":"string","description":"The note content"}},"required":["content"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "create_note":
            content_text = arguments.get("content", "")
            from ..fauxd_client import create_note
            title = content_text[:40] + ("..." if len(content_text) > 40 else "")
            create_note(title, content_text)
            return f"Note saved: {title}"
        return f"Unknown: {name}"

    def _paste_clipboard(self):
        result = get_clipboard()
        self._notes_list.clear()
        self._notes_list.append('<b>Clipboard:</b>')
        if result:
            for item in result[:10]:
                clip_text = item.get("text", item.get("content", ""))[:100]
                ts = item.get("timestamp", item.get("ts", ""))
                self._notes_list.append(f'<span style="color:#888;">[{ts}]</span> {clip_text}')
        self._notes_list.append(f'<hr><span style="color:#666;">Use Notes: Save above</span>')

    def _refresh_notes(self):
        result = fd_get_notes()
        self._notes_list.clear()
        self._notes_list.append('<b>Recent notes:</b>')
        if result:
            for n in result[:8]:
                title = n.get("title", n.get("content", ""))[:60]
                status = n.get("status", n.get("kind", ""))
                self._notes_list.append(f'· [{status}] {title}')
        else:
            self._notes_list.append('<span style="color:#666;">No notes</span>')

    def serialize(self) -> dict:
        d = super().serialize()
        d["notes_html"] = self._notes_list.toHtml()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        if "notes_html" in data:
            self._notes_list.setHtml(data["notes_html"])


# ═══════════════════════════════════════════════════════════════════════
# Clock Node — time / date
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Clock", "Live clock with date — minimal card")
class ClockNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Clock", QColor("#18181e"), 200)
        self._build_ui()

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        self._time_label = QLabel("00:00:00")
        self._time_label.setStyleSheet(f"color: {WHITE.name()}; font-size: 22px; font-weight: bold;")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._time_label)

        self._date_label = QLabel("Monday, Jan 1")
        self._date_label.setStyleSheet("color: #888; font-size: 10px;")
        self._date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._date_label)

        w.setFixedHeight(60)
        self.set_body_widget(w)

        self._ticker = QTimer()
        self._ticker.timeout.connect(self._tick)
        self._ticker.start(1000)
        self._tick()

    def cleanup(self):
        self._ticker.stop()

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"get_current_time","description":"Get the current date and time","parameters":{"type":"object","properties":{}}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "get_current_time":
            self._tick()
            return f"{self._date_label.text()} {self._time_label.text()}"
        return f"Unknown: {name}"

    def _tick(self):
        from datetime import datetime
        now = datetime.now()
        self._time_label.setText(now.strftime("%H:%M:%S"))
        self._date_label.setText(now.strftime("%A, %b %d"))


# ═══════════════════════════════════════════════════════════════════════
# Text Note Node — simple editable text scratchpad
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Text Note", "Editable markdown/text scratchpad — feeds content to connected nodes")
class TextNoteNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Text Note", QColor("#1a1a20"), 300)
        self._build_ui()
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("Write here...")
        self._editor.setStyleSheet(
            "QPlainTextEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 6px; font-size: 12px; }"
            "QPlainTextEdit:focus { border-color: #b366ff; }"
        )
        self._editor.setMinimumHeight(80)
        self._editor.textChanged.connect(self._on_text_change)
        layout.addWidget(self._editor)

        w.setFixedHeight(120)
        self.set_body_widget(w)

    def _on_text_change(self):
        text = self._editor.toPlainText()
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"text": text, "type": "note"})

    def output_data(self, socket: SocketItem) -> dict:
        return {"text": self._editor.toPlainText(), "type": "note"}

    def serialize(self) -> dict:
        d = super().serialize()
        d["content"] = self._editor.toPlainText()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._editor.setPlainText(data.get("content", ""))


# ═══════════════════════════════════════════════════════════════════════
# System Settings Node — display, audio, power, network controls
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Settings", "System settings — display, audio, power, network. Wire to Chat for AI control.")
class SettingsNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Settings", QColor("#281a10"), 320)
        self._settings_state: dict = {}
        self._build_ui()
        self.add_socket("in", "command")
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        # Sections using QTextEdit for display
        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setMaximumHeight(130)
        self._display.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0c0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
        layout.addWidget(self._display)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.setSpacing(3)

        bright_down = self._btn("-", "#ff7800")
        bright_down.clicked.connect(lambda: self._brightness(-10))
        ctrl.addWidget(bright_down)

        bright_label = QLabel("Bri")
        bright_label.setStyleSheet("color: #888; font-size: 9px;")
        ctrl.addWidget(bright_label)

        bright_up = self._btn("+", "#ff7800")
        bright_up.clicked.connect(lambda: self._brightness(10))
        ctrl.addWidget(bright_up)

        ctrl.addSpacing(8)

        vol_down = self._btn("-", "#00c8ff")
        vol_down.clicked.connect(lambda: self._volume(-5))
        ctrl.addWidget(vol_down)

        vol_label = QLabel("Vol")
        vol_label.setStyleSheet("color: #888; font-size: 9px;")
        ctrl.addWidget(vol_label)

        vol_up = self._btn("+", "#00c8ff")
        vol_up.clicked.connect(lambda: self._volume(5))
        ctrl.addWidget(vol_up)

        ctrl.addSpacing(8)

        dim_btn = self._btn("Dim", "#cc6600")
        dim_btn.clicked.connect(self._toggle_dim)
        ctrl.addWidget(dim_btn)

        lock_btn = self._btn("Lock", "#444")
        lock_btn.clicked.connect(self._lock)
        ctrl.addWidget(lock_btn)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        w.setFixedHeight(170)
        self.set_body_widget(w)

        self._poller = QTimer()
        self._poller.timeout.connect(self._poll)
        self._poller.start(5000)
        QTimer.singleShot(200, self._poll)

    def cleanup(self):
        self._poller.stop()

    def _btn(self, text: str, color: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(22)
        btn.setStyleSheet(
            f"QPushButton {{ background: #1c1e23; color: {color}; border: 1px solid #2a2d33; "
            f"border-radius: 3px; padding: 1px 8px; font-size: 10px; }}"
            f"QPushButton:hover {{ border-color: {color}; }}"
        )
        return btn

    def _poll(self):
        import subprocess
        state = {}

        # Display
        try:
            r = subprocess.run(["fauxnix-display"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    state[f"display_{k}"] = v
        except Exception:
            pass
        try:
            r = subprocess.run(["brightnessctl", "-m"], capture_output=True, text=True, timeout=5)
            if r.stdout:
                parts = r.stdout.strip().split(",")
                if len(parts) >= 4:
                    state["brightness_pct"] = parts[3].replace("%", "").strip()
        except Exception:
            pass

        # Audio
        try:
            r = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=5)
            sink = r.stdout.strip()
            r2 = subprocess.run(["pactl", "get-sink-volume", sink], capture_output=True, text=True, timeout=5)
            for line in r2.stdout.strip().split("\n"):
                if "/" in line and "%" in line:
                    parts = line.split("/")
                    if len(parts) >= 2:
                        state["audio_volume"] = parts[1].strip().replace("%", "")
            r3 = subprocess.run(["pactl", "get-sink-mute", sink], capture_output=True, text=True, timeout=5)
            state["audio_muted"] = "yes" if "Mute: yes" in r3.stdout else "no"
        except Exception:
            pass

        # Power
        try:
            r = subprocess.run(["fauxnix-power"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    state[f"power_{k}"] = v
        except Exception:
            pass

        # Weather
        try:
            w = get_weather()
            if w:
                state["weather_temperature"] = w.get("temperature", "")
                state["weather_condition"] = w.get("condition", "")
                state["weather_location"] = w.get("location", "")
        except Exception:
            pass

        self._settings_state = state
        self._update_display()

    def _update_display(self):
        s = self._settings_state
        lines = []

        disp = f'Display: {s.get("display_current", "?")}'
        bri = s.get("brightness_pct", "?")
        lines.append(f'<b style="color:#ff7800;">Display</b>  {disp}  brightness={bri}%')

        vol = s.get("audio_volume", "?")
        mute = " [MUTED]" if s.get("audio_muted") == "yes" else ""
        lines.append(f'<b style="color:#00c8ff;">Audio</b>  volume={vol}{mute}')

        timeout = s.get("power_timeout_seconds", "?")
        dim = s.get("power_dim_percent", "?")
        paused = s.get("power_paused", "no")
        lines.append(f'<b style="color:#cc6600;">Power</b>  timeout={timeout}s  dim={dim}%  paused={paused}')

        temp = s.get("weather_temperature", "?")
        cond = s.get("weather_condition", "?")
        loc = s.get("weather_location", "?")
        lines.append(f'<b style="color:#888;">Weather</b>  {temp} {cond} @ {loc}')

        self._display.setHtml("<br>".join(lines))

        for socket in self._sockets:
            if socket.label == "out":
                socket.push_data(s.copy() if s else {})

    def _brightness(self, delta: int):
        import subprocess
        try:
            subprocess.run(
                ["brightnessctl", "set", f"{delta}%"],
                capture_output=True, timeout=5,
            )
            QTimer.singleShot(500, self._poll)
        except Exception:
            pass

    def _volume(self, delta: int):
        import subprocess
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{delta:+d}%"],
                capture_output=True, timeout=5,
            )
            QTimer.singleShot(500, self._poll)
        except Exception:
            pass

    def _toggle_dim(self):
        import subprocess
        try:
            r = subprocess.run(["fauxnix-power"], capture_output=True, text=True, timeout=5)
            paused = "no"
            for line in r.stdout.strip().split("\n"):
                if line.startswith("paused="):
                    paused = line.split("=", 1)[1]
            action = "resume" if paused == "yes" else "pause"
            subprocess.run(["fauxnix-power", action], capture_output=True, timeout=5)
            QTimer.singleShot(500, self._poll)
        except Exception:
            pass

    def _lock(self):
        import subprocess
        try:
            subprocess.Popen(
                ["swaylock", "-c", "000000"],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def on_data_received(self, socket: SocketItem, data):
        """Handle commands from Chat/routing nodes via input socket."""
        if socket.label != "in":
            return
        action = data.get("action", "")
        value = data.get("value", None)
        import subprocess
        try:
            if action == "set_brightness" and value is not None:
                subprocess.run(["brightnessctl", "set", f"{value}%"], capture_output=True, timeout=5)
            elif action == "set_volume" and value is not None:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"], capture_output=True, timeout=5)
            elif action == "mute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], capture_output=True, timeout=5)
            elif action == "dim_pause":
                subprocess.run(["fauxnix-power", "pause"], capture_output=True, timeout=5)
            elif action == "dim_resume":
                subprocess.run(["fauxnix-power", "resume"], capture_output=True, timeout=5)
            elif action == "lock":
                subprocess.Popen(["swaylock", "-c", "000000"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif action == "set_display_mode" and value:
                subprocess.run(["fauxnix-display", "set", str(value)], capture_output=True, timeout=5)
            elif action == "set_weather_location" and value:
                subprocess.run(["fauxnix-settings", "weather", str(value)], capture_output=True, timeout=5)
            QTimer.singleShot(500, self._poll)
        except Exception:
            pass

    def output_data(self, socket: SocketItem) -> dict:
        return self._settings_state.copy()

    def serialize(self) -> dict:
        d = super().serialize()
        d["settings_state"] = self._settings_state
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._settings_state = data.get("settings_state", {})
        self._update_display()

    def tool_schema(self) -> dict | None:
        return {
            "type": "function",
            "function": {
                "name": "control_system",
                "description": "Control system settings: brightness, volume, display mode, dimming, or lock screen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["set_brightness", "set_volume", "mute", "dim_pause", "dim_resume", "lock", "set_weather_location"], "description": "The action to perform"},
                        "value": {"type": "string", "description": "Value for the action (e.g. 50 for brightness %, 45239 for weather location)"}
                    },
                    "required": ["action"]
                }
            }
        }

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "control_system":
            self.on_data_received(self._sockets[0] if self._sockets else None, arguments)
            return f"Action '{arguments.get('action')}' executed with value {arguments.get('value', 'N/A')}"
        return f"Unknown: {name}"


# ═══════════════════════════════════════════════════════════════════════
# Router Node — classify data by type, route to matching output socket
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Router", "Classify incoming data and route to matching typed output socket")
class RouterNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Router", QColor("#20201a"), 220)
        self._route_map: dict[str, SocketItem] = {}
        self._build_ui()
        self.add_socket("in", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        self._label = QLabel("Routes: none")
        self._label.setStyleSheet("color: #888; font-size: 10px;")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        w.setFixedHeight(35)
        self.set_body_widget(w)

        # Auto-create output sockets for all known types
        for dtype in ["text", "file", "image", "audio", "url", "event", "command", "data"]:
            sock = self.add_socket(dtype, dtype)
            self._route_map[dtype] = sock
        self._update_label()

    def _update_label(self):
        self._label.setText(f"Routes: text file image audio url event cmd data")

    def _classify(self, data: dict) -> str:
        """Inspect payload content and return the best-matching type."""
        # Check explicit type field first
        explicit = data.get("type", "")
        if explicit in self._route_map:
            return explicit

        # Check for file paths with extensions
        for key in ("file", "path", "files"):
            val = data.get(key, "")
            if isinstance(val, list):
                val = val[0] if val else ""
            if val:
                ext = str(val).lower().rsplit(".", 1)[-1] if "." in str(val) else ""
                if ext in ("jpg", "jpeg", "png", "gif", "bmp", "webp", "svg"):
                    return "image"
                if ext in ("mp3", "wav", "ogg", "flac", "aac", "m4a"):
                    return "audio"
                if ext in ("mp4", "mkv", "avi", "mov", "webm"):
                    return "file"
                return "file"

        # Check for text content
        if any(k in data for k in ("text", "content", "note", "prompt", "query", "response")):
            return "text"

        # Check for URL
        if any(k in data for k in ("url", "link", "href")):
            return "url"

        # Check for event
        if any(k in data for k in ("event", "action")):
            return "event"

        # Check for command
        if any(k in data for k in ("command", "cmd", "shell")):
            return "command"

        return "data"

    def on_data_received(self, socket: SocketItem, data):
        if socket.label != "in":
            return
        dtype = self._classify(data)
        if dtype in self._route_map:
            self._route_map[dtype].push_data(data)
        else:
            self._route_map["data"].push_data(data)

    def serialize(self) -> dict:
        d = super().serialize()
        d["route_count"] = len(self._sockets) - 1
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        for _ in range(data.get("route_count", 0)):
            self._add_route()


# ═══════════════════════════════════════════════════════════════════════
# Web Search Node — DuckDuckGo search, feeds results to Chat
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Web Search", "Search the web via DuckDuckGo and feed results to connected nodes")
class WebSearchNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Web Search", QColor("#1a2025"), 280)
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search query...")
        self._input.setStyleSheet(
            "QLineEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #ce93d8; }"
        )
        self._input.returnPressed.connect(self._search)
        layout.addWidget(self._input)

        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setMaximumHeight(100)
        self._results.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0c0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
        layout.addWidget(self._results)

        w.setFixedHeight(140)
        self.set_body_widget(w)

    def _search(self):
        query = self._input.text().strip()
        if not query:
            return
        self._results.clear()
        self._results.append(f'<i>Searching: {query}...</i>')
        try:
            import urllib.request, urllib.parse, json
            url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={"User-Agent": "fauxnix/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                # Extract result snippets
                import re
                results = re.findall(r'<a[^>]*class="[^"]*result-link[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
                snippets = re.findall(r'<td[^>]*class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>', html, re.DOTALL)
                self._results.clear()
                for i, (r, s) in enumerate(zip(results[:5], snippets[:5])):
                    title = re.sub(r'<[^>]+>', '', r).strip()
                    snippet = re.sub(r'<[^>]+>', '', s).strip()
                    self._results.append(f'<b>{i+1}. {title}</b><br>{snippet[:200]}<br>')
                for sock in self._sockets:
                    if sock.label == "out":
                        sock.push_data({"query": query, "results": [{"title": re.sub(r'<[^>]+>', '', r).strip(), "snippet": re.sub(r'<[^>]+>', '', s).strip()} for r, s in zip(results[:5], snippets[:5])], "type": "search"})
        except Exception as e:
            self._results.append(f'<span style="color:#ff4444;">Error: {e}</span>')

    def tool_schema(self) -> dict | None:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web using DuckDuckGo and return results",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"}
                    },
                    "required": ["query"]
                }
            }
        }

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "web_search":
            self._input.setText(arguments.get("query", ""))
            self._search()
            return self._results.toPlainText()[:1000]
        return f"Unknown: {name}"

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            query = data.get("text", data.get("query", ""))
            if query:
                self._input.setText(query)
                self._search()


# ═══════════════════════════════════════════════════════════════════════
# Memory Node — search persistent memories from past conversations
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Memory", "Search persistent memories from all conversations")
class MemoryNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Memory", QColor("#1a1020"), 280)
        self._build_ui()
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search memories...")
        self._input.setStyleSheet(
            "QLineEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #b366ff; }"
        )
        self._input.returnPressed.connect(self._search)
        layout.addWidget(self._input)

        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setMinimumHeight(60)
        self._results.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0c0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
        layout.addWidget(self._results)

        w.setFixedHeight(120)
        self.set_body_widget(w)
        QTimer.singleShot(200, self._search)

    def _search(self):
        query = self._input.text().strip()
        self._results.clear()
        try:
            notes = fd_get_notes()
            if notes:
                matches = notes if not query else [n for n in notes if query.lower() in str(n.get("title", "") + " " + n.get("content", "")).lower()]
                for n in matches[:5]:
                    title = n.get("title", n.get("content", ""))[:60]
                    self._results.append(f'<span style="color:#b366ff;">·</span> {title}')
                if not matches:
                    self._results.append('<span style="color:#666;">No memories found</span>')
                for sock in self._sockets:
                    if sock.label == "out":
                        sock.push_data({"memories": [n.get("title", n.get("content", "")) for n in matches[:5]], "count": len(matches), "type": "memory"})
            else:
                self._results.append('<span style="color:#666;">fauxd offline</span>')
        except Exception:
            self._results.append(f'<span style="color:#666;">fauxd offline</span>')

    def tool_schema(self) -> dict | None:
        return {
            "type": "function",
            "function": {
                "name": "search_memories",
                "description": "Search persistent memories and notes from past conversations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search terms to find relevant memories"}
                    },
                    "required": ["query"]
                }
            }
        }

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "search_memories":
            self._input.setText(arguments.get("query", ""))
            self._search()
            return self._results.toPlainText()[:1000]
        return f"Unknown: {name}"

    def output_data(self, socket: SocketItem) -> dict:
        return {"type": "memory", "ready": True}



# ═══════════════════════════════════════════════════════════════════════
# Preview Node — display text/images from connected nodes
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Preview", "Display text, images, or file content from connected nodes")
class PreviewNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Preview", QColor("#181818"), 320)
        self._build_ui()
        self.add_socket("in", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.setMinimumHeight(80)
        self._content.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 6px; font-size: 12px; }"
        )
        layout.addWidget(self._content)
        w.setFixedHeight(120)
        self.set_body_widget(w)

    def on_data_received(self, socket: SocketItem, data):
        text = data.get("text", data.get("content", str(data)))
        source = data.get("_from", "")
        self._content.clear()
        if source:
            self._content.append(f'<span style="color:#666;">From: {source}</span>')
        self._content.append(text[:2000])

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"preview_content","description":"Display text content for preview","parameters":{"type":"object","properties":{"text":{"type":"string","description":"Content to display"}},"required":["text"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "preview_content":
            self._content.setPlainText(arguments.get("text", ""))
            return "Content displayed"
        return f"Unknown: {name}"

    def serialize(self) -> dict:
        d = super().serialize()
        d["content"] = self._content.toPlainText()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        c = data.get("content", "")
        if c:
            self._content.setPlainText(c)


# ═══════════════════════════════════════════════════════════════════════
# Drag & Drop Node — accept files dropped from file manager
# ═══════════════════════════════════════════════════════════════════════

class _DropWidget(QWidget):
    """Custom widget that accepts file drops."""
    file_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.file_dropped.emit(paths)
            event.acceptProposedAction()


@register_node_type("Drag & Drop", "Accept files dropped from file manager — outputs file paths")
class DragDropNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Drag & Drop", QColor("#102020"), 260)
        self._files: list[str] = []
        self._build_ui()
        self.add_socket("out", "file")

    def _build_ui(self):
        self._drop_widget = _DropWidget()
        layout = QVBoxLayout(self._drop_widget)
        layout.setContentsMargins(6, 4, 6, 4)
        self._label = QLabel("Drop files here")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #666; font-size: 12px; padding: 16px; border: 2px dashed #2a2d33; border-radius: 8px;")
        self._label.setMinimumHeight(50)
        layout.addWidget(self._label)
        self._drop_widget.setFixedHeight(70)
        self._drop_widget.file_dropped.connect(self._on_drop)
        self.set_body_widget(self._drop_widget)

    def _on_drop(self, paths: list[str]):
        self._files = paths
        self._label.setText("\n".join([p.split("/")[-1][:30] for p in paths[:5]]))
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"files": paths, "type": "file"})

    def output_data(self, socket: SocketItem) -> dict:
        return {"files": self._files, "type": "file"}

    def serialize(self) -> dict:
        d = super().serialize()
        d["files"] = self._files
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._files = data.get("files", [])
        if self._files:
            self._label.setText("\n".join([p.split("/")[-1][:30] for p in self._files[:5]]))


# ═══════════════════════════════════════════════════════════════════════
# Process Node — track running desktop processes and foreground window
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Process", "Track running desktop processes and foreground window via Sway IPC")
class ProcessNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Process", QColor("#101a10"), 260)
        self._build_ui()
        self.add_socket("in", "command")
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        self._label = QLabel("Tracking...")
        self._label.setStyleSheet("color: #888; font-size: 10px;")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        w.setFixedHeight(30)
        self.set_body_widget(w)
        self._poller = QTimer()
        self._poller.timeout.connect(self._poll)
        self._poller.start(3000)
        QTimer.singleShot(200, self._poll)

    def cleanup(self):
        self._poller.stop()

    def _poll(self):
        try:
            import subprocess, json
            r = subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True, text=True, timeout=5)
            tree = json.loads(r.stdout)
            def find_focused(node):
                if node.get("focused"):
                    return node
                for c in node.get("nodes", []) + node.get("floating_nodes", []):
                    f = find_focused(c)
                    if f:
                        return f
                return None
            win = find_focused(tree)
            if win:
                name = win.get("name", "")[:80]
                app = win.get("app_id", "") or "unknown"
                pid = win.get("pid", 0)
                self._label.setText(f"Focus: {name}")
                for s in self._sockets:
                    if s.label == "out":
                        s.push_data({"app_id": app, "title": name, "pid": pid, "type": "process"})
        except Exception:
            pass

    def on_data_received(self, socket: SocketItem, data):
        pass

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"get_focused_window","description":"Get the currently focused window title and app","parameters":{"type":"object","properties":{}}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "get_focused_window":
            self._poll()
            return self._label.text()
        return f"Unknown: {name}"

    def output_data(self, socket: SocketItem) -> dict:
        return {"type": "process", "ready": true}


# ═══════════════════════════════════════════════════════════════════════
# Pinboard Node — persistent sticky note with rich text
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Pinboard", "Persistent sticky-note card with rich text")
class PinboardNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Pinboard", QColor("#202010"), 280)
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._editor = QTextEdit()
        self._editor.setPlaceholderText("Pin a note here...")
        self._editor.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 6px; font-size: 11px; }"
            "QTextEdit:focus { border-color: #ffd54f; }"
        )
        self._editor.setMinimumHeight(50)
        self._editor.textChanged.connect(self._on_change)
        layout.addWidget(self._editor)
        w.setFixedHeight(80)
        self.set_body_widget(w)

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            text = data.get("text", data.get("content", ""))
            if text:
                self._editor.setPlainText(text)

    def _on_change(self):
        text = self._editor.toPlainText()
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"text": text, "type": "pinboard"})

    def output_data(self, socket: SocketItem) -> dict:
        return {"text": self._editor.toPlainText(), "type": "pinboard"}

    def serialize(self) -> dict:
        d = super().serialize()
        d["content"] = self._editor.toHtml()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        c = data.get("content", "")
        if c:
            self._editor.setHtml(c)


# ═══════════════════════════════════════════════════════════════════════
# Bool Switch Node — toggleable true/false state that pushes on change
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Bool Switch", "Toggleable true/false state that pushes on change")
class BoolSwitchNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Bool Switch", QColor("#201a1a"), 180)
        self._state = False
        self._build_ui()
        self.add_socket("in", "command")
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
        self._btn = QPushButton("OFF")
        self._btn.setCheckable(True)
        self._btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #888; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 6px 20px; font-size: 14px; font-weight: bold; }"
            "QPushButton:checked { background: #00cc66; color: #080909; border-color: #00cc66; }"
        )
        self._btn.clicked.connect(self._toggle)
        layout.addWidget(self._btn)
        w.setFixedHeight(40)
        self.set_body_widget(w)

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            val = data.get("value", data.get("state"))
            if val is not None:
                self._state = bool(val)
                self._btn.setChecked(self._state)
                self._btn.setText("ON" if self._state else "OFF")
                for s in self._sockets:
                    if s.label == "out":
                        s.push_data({"value": self._state, "type": "bool"})

    def _toggle(self):
        self._state = self._btn.isChecked()
        self._btn.setText("ON" if self._state else "OFF")
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"value": self._state, "type": "bool"})

    def output_data(self, socket: SocketItem) -> dict:
        return {"value": self._state, "type": "bool"}

    def serialize(self) -> dict:
        d = super().serialize()
        d["state"] = self._state
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._state = data.get("state", False)
        self._btn.setChecked(self._state)
        self._btn.setText("ON" if self._state else "OFF")


# ═══════════════════════════════════════════════════════════════════════
# Momentary Button Node — push-to-activate trigger
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Button", "Push-to-activate trigger — fires on press and release")
class MomentaryButtonNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Button", QColor("#1a1a20"), 180)
        self._build_ui()
        self.add_socket("in", "event")
        self.add_socket("out", "event")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
        self._btn = QPushButton("Trigger")
        self._btn.setStyleSheet(
            "QPushButton { background: #ff4444; color: #080909; border: none; "
            "border-radius: 4px; padding: 6px 20px; font-size: 14px; font-weight: bold; }"
            "QPushButton:pressed { background: #cc0000; }"
            "QPushButton:hover { background: #ff6666; }"
        )
        self._btn.pressed.connect(self._on_press)
        self._btn.released.connect(self._on_release)
        layout.addWidget(self._btn)
        self._label = QLabel("")
        self._label.setStyleSheet("color: #666; font-size: 9px;")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        w.setFixedHeight(55)
        self.set_body_widget(w)

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in" and data.get("event") == "trigger":
            self._on_press()
            self._on_release()

    def _on_press(self):
        self._label.setText("pressed")
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"event": "press", "type": "button"})

    def _on_release(self):
        self._label.setText("released")
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"event": "release", "type": "button"})


# ═══════════════════════════════════════════════════════════════════════
# Fauxnix OTG Node — mobile dashboard server with QR code
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Fauxnix OTG", "Mobile dashboard server — scan QR code to access from your phone")
class FauxnixOTGNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Fauxnix OTG", QColor("#1a1020"), 300)
        self._server = None
        self._ips: dict = {}
        self._build_ui()
        self.add_socket("out", "data")
        self._start_server()

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._status_label = QLabel("Starting server...")
        self._status_label.setStyleSheet("color: #b366ff; font-size: 12px; font-weight: bold;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setMinimumHeight(160)
        self._qr_label.setStyleSheet("background: #fff; border-radius: 6px; padding: 8px;")
        layout.addWidget(self._qr_label)

        self._ips_label = QLabel("Detecting IPs...")
        self._ips_label.setStyleSheet("color: #888; font-size: 10px;")
        self._ips_label.setWordWrap(True)
        self._ips_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._ips_label)

        btn_row = QHBoxLayout()
        restart_btn = QPushButton("Restart")
        restart_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #b366ff; border: 1px solid #b366ff; "
            "border-radius: 4px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #b366ff; color: #080909; }"
        )
        restart_btn.clicked.connect(self._restart)
        btn_row.addWidget(restart_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #888; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { border-color: #ff4444; color: #ff4444; }"
        )
        stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(stop_btn)
        layout.addLayout(btn_row)

        w.setFixedHeight(240)
        self.set_body_widget(w)

        self._poller = QTimer()
        self._poller.timeout.connect(self._update_status)
        self._poller.start(10000)

    def _start_server(self):
        try:
            from ..otg_server import OTGServer, get_ips, generate_qr_svg
            self._server = OTGServer()
            self._server.start()
            self._ips = get_ips()
            self._update_status()

            # Push data to connected nodes
            for s in self._sockets:
                if s.label == "out":
                    s.push_data({"otg_url": f"http://{self._ips.get('lan', '?')}:8921", "type": "otg"})
        except Exception as e:
            self._status_label.setText(f"Error: {e}")
            self._status_label.setStyleSheet("color: #ff4444; font-size: 12px;")

    def _update_status(self):
        if not self._server or not self._server.running:
            self._status_label.setText("Server stopped")
            self._status_label.setStyleSheet("color: #888; font-size: 12px;")
            return
        try:
            from ..otg_server import get_ips, generate_qr_svg
            self._ips = get_ips()
            lan = self._ips.get("lan", "unknown")
            ts = self._ips.get("tailscale", "unknown")
            url = f"http://{lan}:8921"
            ts_url = f"http://{ts}:8921"

            self._status_label.setText(f"Active — {lan}:8921")
            self._status_label.setStyleSheet("color: #00cc66; font-size: 12px; font-weight: bold;")
            self._ips_label.setText(f"LAN: {lan}:8921\nTailscale: {ts}:8921")

            # Generate QR as pixmap from SVG
            svg = generate_qr_svg(url)
            from PyQt6.QtCore import QByteArray
            # Use QSvgRenderer to render to pixmap
            from PyQt6.QtSvg import QSvgRenderer
            from PyQt6.QtGui import QPixmap, QPainter
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            pixmap = QPixmap(160, 160)
            pixmap.fill(Qt.GlobalColor.white)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            self._qr_label.setPixmap(pixmap)
        except Exception:
            pass

    def _stop(self):
        if self._server:
            self._server.stop()
            self._status_label.setText("Server stopped")
            self._status_label.setStyleSheet("color: #888; font-size: 12px;")

    def _restart(self):
        self._stop()
        self._start_server()

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"get_otg_url","description":"Get the OTG mobile dashboard URL for phone access","parameters":{"type":"object","properties":{}}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "get_otg_url":
            return f"http://{self._ips.get("lan", "?")}:8921"
        return f"Unknown: {name}"

    def output_data(self, socket: SocketItem) -> dict:
        if self._ips:
            return {"otg_url": f"http://{self._ips.get('lan', '?')}:8921", "type": "otg"}
        return {"type": "otg"}

    def cleanup(self):
        self._poller.stop()
        self._stop()


# ═══════════════════════════════════════════════════════════════════════
# Screenshot Node — capture screen region via grim + slurp
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Screenshot", "Capture a screen region using grim + slurp")
class ScreenshotNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Screenshot", QColor("#201010"), 240)
        self._last_path = ""
        self._build_ui()
        self.add_socket("out", "file")

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"take_screenshot","description":"Capture a screenshot of a screen region","parameters":{"type":"object","properties":{}}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "take_screenshot":
            self._capture()
            return f"Screenshot: {self._last_path}"
        return f"Unknown: {name}"

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
        self._label = QLabel("No screenshot")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #888; font-size: 11px; padding: 12px; border: 2px dashed #2a2d33; border-radius: 8px;")
        self._label.setMinimumHeight(40)
        layout.addWidget(self._label)
        btn = QPushButton("Capture Region")
        btn.setStyleSheet(
            "QPushButton { background: #ff4444; color: #080909; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #ff6666; }"
        )
        btn.clicked.connect(self._capture)
        layout.addWidget(btn)
        w.setFixedHeight(80)
        self.set_body_widget(w)

    def _capture(self):
        import subprocess, time
        path = f"/tmp/fauxnix-screenshot-{int(time.time())}.png"
        try:
            subprocess.run(["grim", "-g", "$(slurp)", path], shell=True, timeout=30)
            if __import__("os").path.exists(path):
                self._last_path = path
                self._label.setText(f"Saved: {path.split('/')[-1]}")
                for s in self._sockets:
                    if s.label == "out":
                        s.push_data({"file": path, "type": "file", "screenshot": True})
        except Exception as e:
            self._label.setText(f"Error: {e}")

    def serialize(self) -> dict:
        d = super().serialize()
        d["last_path"] = self._last_path
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._last_path = data.get("last_path", "")


# ═══════════════════════════════════════════════════════════════════════
# Context Discovery Node — gathers context from all connected nodes
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Context", "Gather context from all connected nodes and present it for the assistant")
class ContextDiscoveryNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Context", QColor("#101a20"), 320)
        self._build_ui()
        self.add_socket("in", "data")
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.setMinimumHeight(80)
        self._content.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0c0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
        layout.addWidget(self._content)
        btn = QPushButton("Gather Context")
        btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; "
            "border-radius: 4px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #00c8ff; color: #080909; }"
        )
        btn.clicked.connect(self._gather)
        layout.addWidget(btn)
        w.setFixedHeight(130)
        self.set_body_widget(w)

    def _gather(self):
        self._content.clear()
        lines = ["Context Constellation:"]
        for data in self.input_data():
            source = data.get("_from", "?")
            socket = data.get("_socket", "?")
            for k, v in data.items():
                if not k.startswith("_"):
                    lines.append(f"  [{source}.{socket}] {k}: {str(v)[:120]}")
        text = "\n".join(lines)
        self._content.setPlainText(text)
        for s in self._sockets:
            if s.label == "out":
                s.push_data({"context": text, "type": "context"})

    def on_data_received(self, socket: SocketItem, data):
        self._gather()

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"gather_context","description":"Gather context from all connected nodes on the canvas","parameters":{"type":"object","properties":{}}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "gather_context":
            self._gather()
            return self._content.toPlainText()[:2000]
        return f"Unknown: {name}"

    def output_data(self, socket: SocketItem) -> dict:
        return {"context": self._content.toPlainText(), "type": "context"}


# ═══════════════════════════════════════════════════════════════════════
# TTS Node — speak text aloud via speech-dispatcher
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("TTS", "Text-to-speech — speaks text aloud using speech-dispatcher")
class TTSNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("TTS", QColor("#1a1025"), 280)
        self._speaking = False
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "event")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        self._label = QLabel("Ready")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #888; font-size: 12px; padding: 8px;")
        layout.addWidget(self._label)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type text to speak...")
        self._input.setStyleSheet(
            "QLineEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #ce93d8; }"
        )
        self._input.returnPressed.connect(self._speak_input)
        layout.addWidget(self._input)

        btn_row = QHBoxLayout()
        speak_btn = QPushButton("Speak")
        speak_btn.setStyleSheet(
            "QPushButton { background: #ce93d8; color: #080909; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #e1bee7; }"
        )
        speak_btn.clicked.connect(self._speak_input)
        btn_row.addWidget(speak_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #ff4444; border: 1px solid #ff4444; "
            "border-radius: 4px; padding: 4px 12px; font-size: 11px; }"
            "QPushButton:hover { background: #ff4444; color: #080909; }"
        )
        stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(stop_btn)
        layout.addLayout(btn_row)

        w.setFixedHeight(95)
        self.set_body_widget(w)

    def _speak_input(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._speak(text)

    def _speak(self, text: str):
        if self._speaking:
            self._stop()
        import subprocess, threading
        self._speaking = True
        self._label.setText(f'Speaking...')
        def run():
            try:
                subprocess.run(["spd-say", text], timeout=30)
            except Exception:
                pass
            self._speaking = False
            self._label.setText("Ready")
            for s in self._sockets:
                if s.label == "out":
                    s.push_data({"event": "spoken", "text": text[:100], "type": "audio"})
        threading.Thread(target=run, daemon=True).start()

    def _stop(self):
        import subprocess
        try:
            subprocess.run(["spd-say", "--stop"], timeout=5)
        except Exception:
            pass
        self._speaking = False
        self._label.setText("Ready")

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            text = data.get("text", data.get("content", ""))
            if text:
                self._speak(text)

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"speak_text","description":"Speak text aloud using speech synthesis","parameters":{"type":"object","properties":{"text":{"type":"string","description":"The text to speak aloud"}},"required":["text"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "speak_text":
            text = arguments.get("text", "")
            if text:
                self._speak(text)
                return f"Speaking: {text[:80]}"
        return f"Unknown: {name}"


# ═══════════════════════════════════════════════════════════════════════
# Audio Input Node — record from microphone via PipeWire
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Audio Input", "Record audio from microphone via PipeWire — outputs file path for transcription")
class AudioInputNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Audio Input", QColor("#102020"), 260)
        self._recording = False
        self._last_file = ""
        self._build_ui()
        self.add_socket("out", "file")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        self._label = QLabel("Ready")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #888; font-size: 12px; padding: 12px; border: 2px dashed #2a2d33; border-radius: 8px;")
        self._label.setMinimumHeight(40)
        layout.addWidget(self._label)

        btn_row = QHBoxLayout()
        record_btn = QPushButton("Record")
        record_btn.setStyleSheet(
            "QPushButton { background: #ef5350; color: #080909; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #ff7043; }"
            "QPushButton:checked { background: #c62828; }"
        )
        record_btn.setCheckable(True)
        record_btn.clicked.connect(self._toggle_record)
        self._record_btn = record_btn
        btn_row.addWidget(record_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #888; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px 12px; font-size: 11px; }"
            "QPushButton:hover { border-color: #ff4444; color: #ff4444; }"
        )
        stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(stop_btn)
        layout.addLayout(btn_row)

        w.setFixedHeight(85)
        self.set_body_widget(w)

    def _toggle_record(self):
        if self._recording:
            self._stop()
        else:
            self._start()

    def _start(self):
        import subprocess, threading, time
        ts = str(int(time.time()))
        self._last_file = f"/tmp/fauxnix-audio-{ts}.wav"
        self._recording = True
        self._record_btn.setChecked(True)
        self._label.setText("Recording...")
        self._process = subprocess.Popen(
            ["pw-record", self._last_file],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _stop(self):
        if not self._recording:
            return
        self._recording = False
        self._record_btn.setChecked(False)
        if hasattr(self, '_process') and self._process:
            self._process.terminate()
            self._process.wait(timeout=3)
        if self._last_file and __import__("os").path.exists(self._last_file):
            size = __import__("os").path.getsize(self._last_file)
            self._label.setText(f"Saved: {self._last_file.split('/')[-1]}\n{size} bytes")
            for s in self._sockets:
                if s.label == "out":
                    s.push_data({"file": self._last_file, "type": "audio", "size": size})
        else:
            self._label.setText("No audio captured")

    def output_data(self, socket: SocketItem) -> dict:
        return {"file": self._last_file, "type": "audio"}

    def serialize(self) -> dict:
        d = super().serialize()
        d["last_file"] = self._last_file
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._last_file = data.get("last_file", "")


# ═══════════════════════════════════════════════════════════════════════
# Audio Transcriber Node — speech-to-text via faster-whisper
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Transcriber", "Speech-to-text via faster-whisper. Drop an audio file or wire Audio Input for live transcription.")
class AudioTranscriberNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Transcriber", QColor("#102520"), 300)
        self._model = None
        self._last_text = ""
        self._build_ui()
        self.add_socket("in", "file")
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        self._label = QLabel("Ready — model: tiny")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #888; font-size: 11px; padding: 8px;")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMinimumHeight(60)
        self._output.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 11px; }"
        )
        layout.addWidget(self._output)

        btn_row = QHBoxLayout()
        model_combo = QComboBox()
        model_combo.addItems(["tiny", "base", "small"])
        model_combo.setCurrentText("tiny")
        model_combo.setStyleSheet(
            "QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 2px 6px; font-size: 10px; }"
        )
        model_combo.currentTextChanged.connect(self._set_model)
        btn_row.addWidget(model_combo)

        transcribe_btn = QPushButton("Transcribe")
        transcribe_btn.setStyleSheet(
            "QPushButton { background: #4fc3f7; color: #080909; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #81d4fa; }"
        )
        transcribe_btn.clicked.connect(self._transcribe_last)
        btn_row.addWidget(transcribe_btn)
        layout.addLayout(btn_row)

        w.setFixedHeight(140)
        self.set_body_widget(w)

    def _set_model(self, size: str):
        self._model = None
        self._label.setText(f"Ready — model: {size}")

    def _load_model(self, size: str = "tiny"):
        try:
            from faster_whisper import WhisperModel
            self._label.setText(f"Loading model {size}...")
            self._model = WhisperModel(size, device="cpu", compute_type="int8")
            self._label.setText(f"Ready — model: {size}")
        except Exception as e:
            self._label.setText(f"Error: {e}")

    def _transcribe_last(self):
        if not self._last_file:
            self._output.append('<span style="color:#666;">No audio file. Record or drop one first.</span>')
            return
        self._transcribe(self._last_file)

    def _transcribe(self, path: str):
        import subprocess
        # Convert to 16kHz mono WAV if needed
        tmp_path = "/tmp/fauxnix-transcribe-input.wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", tmp_path],
                capture_output=True, timeout=30,
            )
            path = tmp_path
        except Exception:
            pass  # Use original if ffmpeg not available

        if not self._model:
            self._load_model("tiny")
        if not self._model:
            self._output.append('<span style="color:#ff4444;">Model not loaded. Install faster-whisper.</span>')
            return

        self._label.setText("Transcribing...")
        try:
            segments, info = self._model.transcribe(path, beam_size=5)
            text_parts = []
            for seg in segments:
                text_parts.append(seg.text.strip())
            self._last_text = " ".join(text_parts)
            self._output.append(f'<b>Transcribed:</b> {self._last_text}')
            self._label.setText(f"Done — {info.language} ({info.duration:.1f}s)")
            for s in self._sockets:
                if s.label == "out":
                    s.push_data({"text": self._last_text, "language": info.language, "type": "text"})
        except Exception as e:
            self._label.setText(f"Error: {e}")
            self._output.append(f'<span style="color:#ff4444;">{e}</span>')

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            path = data.get("file", data.get("path", ""))
            if path:
                self._last_file = path
                self._label.setText(f"File: {path.split('/')[-1]}")
                self._transcribe(path)

    def output_data(self, socket: SocketItem) -> dict:
        return {"text": self._last_text, "type": "text"}

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"transcribe_audio","description":"Transcribe an audio file to text using faster-whisper","parameters":{"type":"object","properties":{"file":{"type":"string","description":"Path to the audio file"}},"required":["file"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "transcribe_audio":
            path = arguments.get("file", self._last_file)
            if path:
                self._transcribe(path)
                return self._last_text[:500]
            return "No audio file provided"
        return f"Unknown: {name}"

    def serialize(self) -> dict:
        d = super().serialize()
        d["last_text"] = self._last_text
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._last_text = data.get("last_text", "")
        if self._last_text:
            self._output.append(self._last_text)


# ═══════════════════════════════════════════════════════════════════════
# Nexus Connect Node — bridge to remote Nexus desktop for large models
# ═══════════════════════════════════════════════════════════════════════

@register_node_type("Nexus Connect", "Connect to your Nexus desktop for larger models. Route queries through the data socket.")
class NexusConnectNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Nexus Connect", QColor("#1a1025"), 340)
        self._nexus_ip = "100.126.117.60"
        self._nexus_port = 11434
        self._models: list[str] = []
        self._selected_model = ""
        self._connected = False
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "text")

        QTimer.singleShot(500, self._scan)

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Status header
        self._status = QLabel("Nexus: scanning...")
        self._status.setStyleSheet("color: #888; font-size: 12px; font-weight: bold;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # IP display
        ip_row = QHBoxLayout()
        self._ip_label = QLabel(self._nexus_ip)
        self._ip_label.setStyleSheet("color: #ce93d8; font-size: 11px;")
        ip_row.addWidget(self._ip_label)
        ip_row.addStretch()
        layout.addLayout(ip_row)

        # Model selector
        self._model_combo = QComboBox()
        self._model_combo.setStyleSheet(
            "QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 3px 6px; font-size: 10px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #141518; color: #d4d4d4; selection-background-color: #ff7800; }"
        )
        self._model_combo.currentTextChanged.connect(self._on_model_change)
        layout.addWidget(self._model_combo)

        # Quick test area
        self._response = QTextEdit()
        self._response.setReadOnly(True)
        self._response.setMaximumHeight(80)
        self._response.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0c0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
        layout.addWidget(self._response)

        # Buttons
        btn_row = QHBoxLayout()
        scan_btn = QPushButton("Scan")
        scan_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #ce93d8; border: 1px solid #ce93d8; "
            "border-radius: 4px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #ce93d8; color: #080909; }"
        )
        scan_btn.clicked.connect(self._scan)
        btn_row.addWidget(scan_btn)

        ping_btn = QPushButton("Ping")
        ping_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; "
            "border-radius: 4px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #00c8ff; color: #080909; }"
        )
        ping_btn.clicked.connect(self._ping)
        btn_row.addWidget(ping_btn)
        layout.addLayout(btn_row)

        w.setFixedHeight(190)
        self.set_body_widget(w)

    def _scan(self):
        self._status.setText("Nexus: scanning...")
        self._status.setStyleSheet("color: #888; font-size: 12px; font-weight: bold;")
        try:
            import urllib.request, json
            req = urllib.request.Request(f"http://{self._nexus_ip}:{self._nexus_port}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                self._models = [m["name"] for m in data.get("models", [])]
                self._connected = True
                self._model_combo.clear()
                self._model_combo.addItems(self._models)
                if self._models:
                    self._model_combo.setCurrentIndex(0)
                self._status.setText(f"Nexus: {len(self._models)} models")
                self._status.setStyleSheet("color: #00cc66; font-size: 12px; font-weight: bold;")
        except Exception:
            self._connected = False
            self._status.setText("Nexus: unreachable")
            self._status.setStyleSheet("color: #ff4444; font-size: 12px; font-weight: bold;")

    def _on_model_change(self, model: str):
        self._selected_model = model

    def _ping(self):
        if not self._connected:
            self._scan()
            return
        self._response.clear()
        self._response.append('<span style="color:#888;">Pinging...</span>')
        try:
            import urllib.request, json
            body = json.dumps({
                "model": self._selected_model or (self._models[0] if self._models else "qwen3:1.7b"),
                "prompt": "Say 'nexus online' in one word.",
                "stream": False,
                "options": {"num_predict": 10},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"http://{self._nexus_ip}:{self._nexus_port}/api/generate",
                data=body, method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                self._response.clear()
                self._response.append(data.get("response", "").strip())
                for s in self._sockets:
                    if s.label == "out":
                        s.push_data({"model": self._selected_model, "response": data.get("response", "").strip(), "source": "nexus", "type": "text"})
        except Exception as e:
            self._response.clear()
            self._response.append(f'<span style="color:#ff4444;">{e}</span>')

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            prompt = data.get("text", data.get("prompt", ""))
            if prompt:
                self._query_nexus(prompt)

    def _query_nexus(self, prompt: str):
        if not self._connected:
            self._response.append('<span style="color:#ff4444;">Nexus offline</span>')
            return
        self._response.clear()
        self._response.append('<span style="color:#888;">Nexus thinking...</span>')
        try:
            import urllib.request, json
            model = self._selected_model or (self._models[0] if self._models else "qwen3:1.7b")
            body = json.dumps({
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 512},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"http://{self._nexus_ip}:{self._nexus_port}/api/generate",
                data=body, method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                response = data.get("response", "").strip()
                self._response.clear()
                self._response.append(response)
                for s in self._sockets:
                    if s.label == "out":
                        s.push_data({"text": response, "model": model, "source": "nexus", "type": "text"})
        except Exception as e:
            self._response.clear()
            self._response.append(f'<span style="color:#ff4444;">{e}</span>')

    def output_data(self, socket: SocketItem) -> dict:
        return {"nexus_ip": self._nexus_ip, "connected": self._connected, "models": self._models, "type": "nexus"}

    def tool_schema(self) -> dict | None:
        return {"type":"function","function":{"name":"query_nexus","description":"Send a prompt to the Nexus desktop for large-model inference","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"The prompt to send to Nexus"}},"required":["prompt"]}}}

    def tool_invoke(self, name: str, arguments: dict) -> str:
        if name == "query_nexus":
            prompt = arguments.get("prompt", "")
            if prompt:
                self._query_nexus(prompt)
                return self._response.toPlainText()[:1000]
        return f"Unknown: {name}"

    def serialize(self) -> dict:
        d = super().serialize()
        d["nexus_ip"] = self._nexus_ip
        d["selected_model"] = self._selected_model
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._nexus_ip = data.get("nexus_ip", self._nexus_ip)
        self._selected_model = data.get("selected_model", "")
        QTimer.singleShot(500, self._scan)


@register_node_type("Group", "Visual container to anchor and organize nodes on the canvas")
class GroupNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Group", QColor("#2a1a3a"), 400)
        self._build_ui()
        self.add_socket("in", "data")
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)

        self._name_input = QLineEdit("Group")
        self._name_input.setStyleSheet(
            "QLineEdit { background: rgba(0,0,0,80); color: #d4d4d4; border: 1px solid #3a3050; "
            "border-radius: 3px; padding: 3px 6px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #b380ff; }"
        )
        self._name_input.textChanged.connect(lambda t: setattr(self, '_title', t or 'Group'))
        layout.addWidget(self._name_input)

        hint = QLabel("Place nodes on this card to group them. Drag the group to move them together.")
        hint.setStyleSheet("color: #555; font-size: 10px; padding: 12px 8px; background: transparent;")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch()
        self.set_body_widget(w)

    def serialize(self) -> dict:
        d = super().serialize()
        d["label"] = self._name_input.text()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._name_input.setText(data.get("label", "Group"))


@register_node_type("App Window", "Launch any app in its own Sway window — tracked from canvas")
class AppWindowNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("App Window", QColor("#1a2540"), 380)
        self._process = None
        self._win_id = 0
        self._tracked_ids = set()
        self._build_ui()
        self.add_socket("in", "command")
        self.add_socket("out", "event")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        row = QHBoxLayout()
        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("firefox / foot / gimp / chromium ...")
        self._cmd_input.setStyleSheet(
            "QLineEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 3px 6px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #00c8ff; }"
        )
        self._cmd_input.returnPressed.connect(self._launch)
        row.addWidget(self._cmd_input)

        launch_btn = QPushButton("Launch")
        launch_btn.setFixedHeight(22)
        launch_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 2px 8px; font-size: 10px; }"
            "QPushButton:hover { border-color: #00c8ff; color: #00c8ff; }"
        )
        launch_btn.clicked.connect(self._launch)
        row.addWidget(launch_btn)

        close_btn = QPushButton("Kill")
        close_btn.setFixedSize(32, 22)
        close_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #888; border: 1px solid #2a2d33; "
            "border-radius: 3px; font-size: 10px; }"
            "QPushButton:hover { background: #ff4444; color: white; }"
        )
        close_btn.clicked.connect(self._close_app)
        row.addWidget(close_btn)
        layout.addLayout(row)

        self._status = QLabel("Ready — type app name and launch")
        self._status.setStyleSheet("color: #666; font-size: 10px; padding: 4px; background: transparent;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch()
        self.set_body_widget(w)
        self._watchdog = QTimer(self.widget)
        self._watchdog.timeout.connect(self._check_alive)

    def _launch(self):
        cmd = self._cmd_input.text().strip()
        if not cmd:
            return
        import subprocess, shlex, os
        self._app_command = cmd
        try:
            args = shlex.split(cmd)
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":1")
            env.setdefault("WAYLAND_DISPLAY", "wayland-1")
            self._process = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
            )
            self._status.setText(f"Running: {cmd} (PID {self._process.pid})")
            self._status.setStyleSheet("color: #00cc66; font-size: 10px; padding: 4px; background: transparent;")
            self._poll_count = 0
            self._poll_timer = QTimer(self.widget)
            self._poll_timer.timeout.connect(self._find_and_track)
            self._poll_timer.start(300)
        except Exception as e:
            self._status.setText(f"Error: {e}")
            self._status.setStyleSheet("color: #ff4444; font-size: 10px; padding: 4px; background: transparent;")

    def _find_and_track(self):
        self._poll_count += 1
        if self._process and self._process.poll() is not None:
            self._poll_timer.stop()
            self._status.setText(f"Exited immediately: {self._app_command}")
            self._status.setStyleSheet("color: #ff4444; font-size: 10px; padding: 4px; background: transparent;")
            self._process = None
            return
        new_window = self._find_new_window()
        if new_window:
            self._poll_timer.stop()
            self._win_id = new_window
            self._move_to_app_workspace(new_window)
            self._status.setText(f"Active: {self._cmd_input.text().strip()} (con {new_window})")
            self._status.setStyleSheet("color: #00c8ff; font-size: 10px; padding: 4px; background: transparent;")
            self._watchdog.start(2000)
            return
        if self._poll_count > 25:
            self._poll_timer.stop()
            if self._process and self._process.poll() is None:
                self._status.setText(f"Launched (PID {self._process.pid}) - no window found")
            else:
                self._status.setText(f"Failed: {self._cmd_input.text().strip()}")
            self._status.setStyleSheet("color: #ff7800; font-size: 10px; padding: 4px; background: transparent;")

    def _find_new_window(self):
        import subprocess, json, os
        sock = os.environ.get("SWAYSOCK", "")
        if not sock:
            import glob
            socks = glob.glob("/run/user/1000/sway-ipc.*")
            if socks: sock = socks[0]
        if not sock:
            return 0
        try:
            out = subprocess.run(
                ["swaymsg", "-s", sock, "-t", "get_tree"],
                capture_output=True, text=True, timeout=2
            )
            d = json.loads(out.stdout)
            windows = []
            def walk(n):
                if n.get("type") in ("con", "floating_con") and n.get("name"):
                    windows.append((n.get("id", 0), n.get("name", ""), n.get("pid", 0)))
                for c in n.get("nodes", []) + n.get("floating_nodes", []):
                    walk(c)
            walk(d)
            windows.sort(key=lambda x: x[0], reverse=True)
            for con_id, name, pid in windows:
                if con_id not in self._tracked_ids and name not in ("Fauxnix Workspace", "root"):
                    self._tracked_ids.add(con_id)
                    return con_id
        except Exception:
            pass
        return 0

    def _move_to_app_workspace(self, con_id):
        import subprocess, os
        sock = os.environ.get("SWAYSOCK", "")
        if not sock:
            import glob
            socks = glob.glob("/run/user/1000/sway-ipc.*")
            if socks: sock = socks[0]
        if not sock:
            return
        ws_num = 10 + (con_id % 89)
        ws_name = f"{ws_num}:App"
        subprocess.run(["swaymsg", "-s", sock, f"[con_id={con_id}]", "move", "to", "workspace", ws_name],
                       capture_output=True, timeout=2)
        subprocess.run(["swaymsg", "-s", sock, f"[con_id={con_id}]", "fullscreen", "enable"],
                       capture_output=True, timeout=2)
        subprocess.run(["swaymsg", "-s", sock, "workspace", ws_name],
                       capture_output=True, timeout=2)

    def _check_alive(self):
        if self._process and self._process.poll() is not None:
            self._status.setText(f"Exited (code {self._process.returncode}): {self._app_command}")
            self._status.setStyleSheet("color: #888; font-size: 10px; padding: 4px; background: transparent;")
            self._watchdog.stop()
            self._process = None
            self._return_to_canvas()

    def _return_to_canvas(self):
        import subprocess, os
        sock = os.environ.get("SWAYSOCK", "")
        if not sock:
            import glob
            socks = glob.glob("/run/user/1000/sway-ipc.*")
            if socks: sock = socks[0]
        if sock:
            subprocess.run(["swaymsg", "-s", sock, "workspace", "2:Fauxnix"],
                           capture_output=True, timeout=2)

    def _close_app(self):
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._status.setText(f"Killed: {self._app_command}")
            self._status.setStyleSheet("color: #ff4444; font-size: 10px; padding: 4px; background: transparent;")
            self._process = None
        self._watchdog.stop()
        self._poll_timer.stop() if hasattr(self, '_poll_timer') and self._poll_timer.isActive() else None
        self._return_to_canvas()

    def on_data_received(self, socket, data):
        if socket.label == "in":
            cmd = data if isinstance(data, str) else data.get("command", "")
            if cmd:
                self._cmd_input.setText(str(cmd))
                self._launch()

    def cleanup(self):
        self._watchdog.stop()
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass

    def serialize(self) -> dict:
        d = super().serialize()
        d["app_command"] = self._cmd_input.text().strip()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        cmd = data.get("app_command", "")
        if cmd:
            self._cmd_input.setText(cmd)


# ═══════════════════════════════════════════════════════════════════════
# Window Card Node — manage real compositor windows as canvas cards
# ═══════════════════════════════════════════════════════════════════════

from ..window_manager import get_window_manager, ToplevelWindow


@register_node_type("Window", "Card representing a real app window — focus, minimize, close from the canvas")
class WindowCardNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Window", QColor("#1a2330"), 320)
        self._wm = get_window_manager()
        self._windows: list[ToplevelWindow] = []
        self._selected_title: str = ""
        self._build_ui()
        self.add_socket("out", "signal")
        self._tick()

    def refresh_layout(self, scale: float, pan_offset: QPoint):
        super().refresh_layout(scale, pan_offset)
        provider = getattr(self, "_provider", None)
        if provider is not None and self._body_widget is not None:
            provider.resize(self._body_widget.width(), self._body_widget.height())

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()}; color: {WHITE.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._combo = QComboBox()
        self._combo.setStyleSheet(
            "QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 2px 6px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #141518; color: #d4d4d4; "
            "selection-background-color: #ff7800; }"
        )
        self._combo.currentTextChanged.connect(self._on_select)
        layout.addWidget(self._combo)

        self._status = QLabel("Scanning windows...")
        self._status.setStyleSheet("color: #888; font-size: 10px; padding: 2px; background: transparent;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        for label, cb in [
            ("Focus", self._focus),
            ("Min", self._minimize),
            ("Max", self._maximize),
            ("Close", self._close),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
                "border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
                "QPushButton:hover { border-color: #ff7800; color: #ff7800; }"
            )
            btn.clicked.connect(cb)
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #888; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { border-color: #00c8ff; color: #00c8ff; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        layout.addWidget(refresh_btn)

        w.setMinimumHeight(140)
        self.set_body_widget(w)

    def _refresh(self):
        self._windows = self._wm.list_windows()
        current = self._combo.currentText()
        self._combo.blockSignals(True)
        self._combo.clear()
        titles = [f"{win.app_id}: {win.title}" for win in self._windows]
        self._combo.addItems(["(select a window)"] + titles)
        if current in titles:
            self._combo.setCurrentText(current)
        elif self._selected_title:
            for t in titles:
                if self._selected_title in t:
                    self._combo.setCurrentText(t)
                    break
        self._combo.blockSignals(False)
        self._status.setText(f"{len(self._windows)} window(s) found")

    def _on_select(self, text: str):
        if text.startswith("(select"):
            self._selected_title = ""
            return
        # Extract title after "app_id: "
        if ": " in text:
            self._selected_title = text.split(": ", 1)[1]
        else:
            self._selected_title = text

    def _current_title(self) -> str:
        return self._selected_title

    def _focus(self):
        title = self._current_title()
        if title and self._wm.focus(title):
            self._status.setText(f"Focused: {title}")
        else:
            self._status.setText("Focus failed")

    def _minimize(self):
        title = self._current_title()
        if title and self._wm.minimize(title):
            self._status.setText(f"Minimized: {title}")
        else:
            self._status.setText("Minimize failed")

    def _maximize(self):
        title = self._current_title()
        if title and self._wm.maximize(title):
            self._status.setText(f"Maximized: {title}")
        else:
            self._status.setText("Maximize failed")

    def _close(self):
        title = self._current_title()
        if title and self._wm.close(title):
            self._status.setText(f"Closed: {title}")
            self._refresh()
        else:
            self._status.setText("Close failed")

    def serialize(self) -> dict:
        d = super().serialize()
        d["selected_title"] = self._selected_title
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        title = data.get("selected_title", "")
        if title:
            self._selected_title = title
            self._refresh()


# ═══════════════════════════════════════════════════════════════════════
# Chromium Card Node — dedicated card for the Chromium browser window
# ═══════════════════════════════════════════════════════════════════════

import subprocess


@register_node_type("Chromium", "Dedicated card for the Chromium browser window")
class ChromiumCardNode(BaseNodeWidget):
    CHROMIUM_APPS = {"chromium", "chromium-browser", "google-chrome", "google-chrome-stable"}

    # Thumbnail refresh interval in milliseconds.
    THUMB_INTERVAL_MS = 1200

    def __init__(self):
        super().__init__("Chromium", QColor("#1a2530"), 320)
        self._wm = get_window_manager()
        self._process: subprocess.Popen | None = None
        self._window: ToplevelWindow | None = None
        self._zoom_mode: str = "thumb"  # thumb | window | fullscreen
        self._last_thumb: QPixmap | None = None
        self._build_ui()
        self.add_socket("out", "signal")
        self._tick()

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()}; color: {WHITE.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._title_label = QLabel("Chromium")
        self._title_label.setStyleSheet("color: #d4d4d4; font-weight: bold; font-size: 12px; background: transparent;")
        layout.addWidget(self._title_label)

        self._status = QLabel("Looking for Chromium...")
        self._status.setStyleSheet("color: #888; font-size: 10px; padding: 2px; background: transparent;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        for label, cb in [
            ("Launch", self._launch),
            ("Focus", self._focus),
            ("Window", lambda: self._apply_zoom_mode("window")),
            ("Fullscreen", lambda: self._apply_zoom_mode("fullscreen")),
            ("Min", self._minimize),
            ("Max", self._maximize),
            ("Close", self._close),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "QPushButton { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
                "border-radius: 3px; padding: 3px 8px; font-size: 11px; }"
                "QPushButton:hover { border-color: #ff7800; color: #ff7800; }"
            )
            btn.clicked.connect(cb)
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self._thumb_label = QLabel()
        self._thumb_label.setStyleSheet("background: #0d0e12; border: 1px solid #1e1e24; border-radius: 4px;")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setMinimumHeight(120)
        self._thumb_label.setWordWrap(True)
        self._thumb_label.setText("Thumbnail will appear when Chromium is running")
        layout.addWidget(self._thumb_label)

        w.setMinimumHeight(240)
        self.set_body_widget(w)

    def _find_window(self) -> ToplevelWindow | None:
        for app_id in self.CHROMIUM_APPS:
            win = self._wm.find_by_app_id(app_id)
            if win:
                return win
        return None

    def _canvas_scale(self) -> float:
        parent = self.widget.parentWidget()
        if parent and hasattr(parent, "_state"):
            return parent._state.get("scale", 1.0)
        return 1.0

    def _card_screen_geometry(self) -> tuple[int, int, int, int] | None:
        if not self.widget.parentWidget():
            return None
        pos = self.widget.mapToGlobal(QPoint(0, 0))
        return pos.x(), pos.y(), self.widget.width(), self.widget.height()

    def _tick(self):
        self._window = self._find_window()
        if self._window:
            self._title_label.setText(self._window.title or "Chromium")
        else:
            self._title_label.setText("Chromium")

        if self._window:
            self._capture_thumb()
            if not self.isSelected() and self._zoom_mode != "thumb":
                self._apply_zoom_mode("thumb")

        self._status.setText(
            f"{self._window.app_id if self._window else 'not running'} | zoom={self._canvas_scale():.2f} | {self._zoom_mode}"
        )
        QTimer.singleShot(self.THUMB_INTERVAL_MS, self._tick)

    def _capture_thumb(self):
        title = self._window.title if self._window else None
        app_id = None
        if self._window:
            aid = self._window.app_id
            if aid and aid.lower() in {a.lower() for a in self.CHROMIUM_APPS}:
                app_id = aid
        result = capture_thumbnail(app_id=app_id, title=title, max_size=280)
        if result is None:
            return
        data, w, h = result
        try:
            image = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888)
            pixmap = QPixmap.fromImage(image)
            self._last_thumb = pixmap
            self._thumb_label.setPixmap(pixmap.scaled(
                self._thumb_label.width(), self._thumb_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        except Exception:
            pass


    def _apply_zoom_mode(self, mode: str):
        self._zoom_mode = mode
        if not self._window:
            return
        title = self._window.title
        raw_app_id = self._window.app_id
        app_id = raw_app_id if (raw_app_id and raw_app_id.lower() in {a.lower() for a in self.CHROMIUM_APPS}) else None
        if mode == "thumb":
            self._wm.minimize(title)
        elif mode == "window":
            self._wm.focus(title)
            # Position the real Chromium window over the card. If the card is too
            # small, use a centered usable size instead.
            geom = self._card_screen_geometry()
            if geom:
                x, y, cw, ch = geom
                # Ensure a minimum usable size while keeping it centered on the card.
                nw = max(cw, 900)
                nh = max(ch, 600)
                x = max(0, x - (nw - cw) // 2)
                y = max(0, y - (nh - ch) // 2)
                move_resize_window(app_id=app_id, title=title, x=x, y=y, width=nw, height=nh)
            raise_window(app_id=app_id, title=title)
        elif mode == "fullscreen":
            self._wm.fullscreen(title)

    def _launch(self):
        if self._window:
            self._focus()
            return
        try:
            self._process = subprocess.Popen(
                ["chromium", "--ozone-platform=x11"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._status.setText("Launching Chromium...")
        except Exception as e:
            self._status.setText(f"Launch failed: {e}")

    def _ensure_window(self) -> bool:
        if not self._window:
            self._window = self._find_window()
        return self._window is not None

    def _focus(self):
        if self._ensure_window():
            if self._wm.focus(self._window.title):
                self._status.setText("Focused Chromium")
            else:
                self._status.setText("Focus failed")
        else:
            self._status.setText("No Chromium window")

    def _minimize(self):
        if self._ensure_window():
            if self._wm.minimize(self._window.title):
                self._status.setText("Minimized Chromium")
            else:
                self._status.setText("Minimize failed")
        else:
            self._status.setText("No Chromium window")

    def _maximize(self):
        if self._ensure_window():
            if self._wm.maximize(self._window.title):
                self._status.setText("Maximized Chromium")
            else:
                self._status.setText("Maximize failed")
        else:
            self._status.setText("No Chromium window")

    def _close(self):
        if self._ensure_window():
            if self._wm.close(self._window.title):
                self._status.setText("Closed Chromium")
                self._window = None
            else:
                self._status.setText("Close failed")
        else:
            self._status.setText("No Chromium window")

    def cleanup(self):
        # Return any raised Chromium window to a normal minimized state so it
        # does not stay floating over the workspace after the card is removed.
        if self._window:
            self._wm.minimize(self._window.title)

    def serialize(self) -> dict:
        d = super().serialize()
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)


# ═══════════════════════════════════════════════════════════════════════
# Environments Node — sub loader for macOS VM, Windows VM, GNOME, etc.
# ═══════════════════════════════════════════════════════════════════════

_ENVIRONMENTS: list[dict] = []
_ENVIRONMENTS_LOADED = False


def _load_environments() -> list[dict]:
    global _ENVIRONMENTS_LOADED
    if _ENVIRONMENTS_LOADED:
        return _ENVIRONMENTS

    defaults: list[dict] = [
        {
            "id": "macos-vm",
            "name": "macOS Sequoia",
            "kind": "looking-glass-vm",
            "surface_kind": "vm",
            "description": "macOS 15 VM via QEMU/KVM + OpenCore",
            "width": 1920,
            "height": 1080,
            "builder": "macos",
            "disk_path": "/home/chvk/macos-disk.qcow2",
            "opencore_iso": "/home/chvk/LongQT-OpenCore-v0.7.iso",
            "installer_iso": "/home/chvk/macOS-Sequoia-15.7.7.iso",
            "memory_mb": 8192,
            "smp_cores": 4,
            "vnc_display": 1,
            "vnc_listen": "100.97.123.113",
            "aspect": 16 / 9,
            "context": {
                "os": "macos",
                "hypervisor": "qemu",
                "vnc": "100.97.123.113:5901",
            },
        },
        {
            "id": "windows-vm",
            "name": "Windows 11",
            "kind": "looking-glass-vm",
            "surface_kind": "vm",
            "description": "Windows 11 VM via QEMU/KVM",
            "width": 1920,
            "height": 1080,
            "builder": "windows",
            "disk_path": "/home/chvk/win11.qcow2",
            "memory_mb": 8192,
            "smp_cores": 4,
            "vnc_display": 2,
            "vnc_listen": "100.97.123.113",
            "aspect": 16 / 9,
            "context": {"os": "windows", "hypervisor": "qemu"},
        },
        {
            "id": "nested-gnome",
            "name": "GNOME Desktop",
            "kind": "nested-gnome",
            "surface_kind": "desktop",
            "description": "Full GNOME session in a nested compositor",
            "width": 1280,
            "height": 720,
            "aspect": 16 / 9,
            "context": {"os": "linux", "desktop": "gnome"},
        },
        {
            "id": "fauxnix-workspace",
            "name": "Fauxnix Workspace",
            "kind": "self",
            "surface_kind": "workspace",
            "description": "Switch to the Fauxnix canvas workspace",
            "width": 0,
            "height": 0,
            "aspect": 16 / 9,
            "context": {"os": "fauxnix", "desktop": "workspace"},
        },
    ]

    # Try loading config file ~/.config/fauxnix/environments.json
    config_path = os.path.expanduser("~/.config/fauxnix/environments.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                parsed = json.loads(f.read())
            user_environments = parsed if isinstance(parsed, list) else parsed.get("environments", parsed.get("envs", []))
            if user_environments:
                _ENVIRONMENTS.extend(user_environments)
    except Exception:
        pass

    if not _ENVIRONMENTS:
        _ENVIRONMENTS.extend(defaults)

    _ENVIRONMENTS_LOADED = True
    return _ENVIRONMENTS


@register_node_type(
    "Environments",
    "Environment sub-loader — launch macOS, Windows, GNOME, or switch to Fauxnix workspace",
)
class EnvironmentsNode(BaseNodeWidget):
    """Environment sub-loader: grid of OS environments.

    Each environment can be:
      - A VM (backed by looking-glass-vm or qemu-vm provider)
      - A nested desktop (backed by nested-gnome provider)
      - The Fauxnix workspace itself (just activates the current tab)

    Clicking an environment spawns a DisplayCardNode with the appropriate
    source spec and launches it.
    """

    def __init__(self):
        super().__init__("Environments", QColor("#1a1a2e"), 420)
        self._build_ui()
        self.add_socket("out", "data")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        title = QLabel("Choose an Environment")
        title.setStyleSheet(
            "color: #d4d4d4; font-size: 14px; font-weight: bold; "
            "background: transparent; padding: 2px 0;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(6)

        envs = _load_environments()
        for idx, env in enumerate(envs):
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #14151e; border: 1px solid #2a2d3a; "
                "border-radius: 8px; }"
                "QFrame:hover { border-color: #ff7800; background: #1a1c26; }"
            )
            card.setFixedSize(180, 120)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(2)

            name_label = QLabel(env["name"])
            name_label.setStyleSheet(
                "color: #d4d4d4; font-size: 13px; font-weight: bold; "
                "background: transparent;"
            )
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(name_label)

            badge = QLabel(env["surface_kind"].upper())
            badge.setStyleSheet(
                "color: #5a7a9a; font-size: 9px; background: #0d1018; "
                "border: 1px solid #1e2834; border-radius: 3px; "
                "padding: 1px 6px;"
            )
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(badge)

            desc = QLabel(env["description"])
            desc.setStyleSheet(
                "color: #7a8a9a; font-size: 9px; background: transparent;"
            )
            desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc.setWordWrap(True)
            card_layout.addWidget(desc)

            card_layout.addStretch()
            card.mousePressEvent = lambda e, env=env: self._spawn_environment(env)
            grid.addWidget(card, idx // 2, idx % 2)

        layout.addLayout(grid)

        hint = QLabel(
            "Click an environment to launch it. Each VM or desktop "
            "gets its own Display card on the canvas."
        )
        hint.setStyleSheet(
            "color: #5a6a7a; font-size: 9px; background: transparent; "
            "padding: 4px 0;"
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "color: #b96a6a; font-size: 9px; background: transparent; "
            "padding: 2px 0;"
        )
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        w.setMinimumHeight(300)
        self.set_body_widget(w)

    def _find_canvas(self):
        w = self.widget
        while w:
            if hasattr(w, "_state") and "nodes" in w._state:
                return w
            w = w.parentWidget()
        return None

    def _find_main_window(self):
        w = self.widget
        while w:
            if hasattr(w, "_stack") and hasattr(w, "_tabs"):
                return w
            w = w.parentWidget()
        return None

    def _switch_to_main_tab(self, canvas):
        mw = self._find_main_window()
        if mw is not None and mw._stack is not None:
            mw._stack.setCurrentIndex(0)
            mw._update_tab_buttons()
            self._emit_output({}, {"action": "switch_tab", "target": "main"})

    def _spawn_environment(self, env: dict):
        canvas = self._find_canvas()
        if canvas is None:
            return

        env_id = env.get("id", "")
        env_name = env.get("name", "Environment")

        if env_id == "fauxnix-workspace":
            self._switch_to_main_tab(canvas)
            return

        source_spec = {
            "kind": env.get("kind", "looking-glass-vm"),
            "surface_name": env_name,
            "surface_kind": env.get("surface_kind", "vm"),
            "source_name": env_name,
            "source_kind": env.get("kind"),
            "card_title": env_name,
            "width": env.get("width", 1280),
            "height": env.get("height", 720),
            "aspect": env.get("aspect", 16 / 9),
            "context": dict(env.get("context", {})),
        }
        for key in ("qmp_path", "vnc_display", "vnc_listen", "vnc_host"):
            if key in env:
                source_spec[key] = env[key]

        # If the env config has a builder, generate qemu_argv from it
        if env.get("builder"):
            try:
                from ..surface_providers.vm_builder import build_env_qemu_argv
                qemu_argv = build_env_qemu_argv(env)
                if qemu_argv:
                    source_spec["qemu_argv"] = qemu_argv
                else:
                    raise RuntimeError(f"Unknown VM builder: {env.get('builder')}")
            except Exception as e:
                message = f"{env_name} config failed: {e}"
                if hasattr(self, "_status_label"):
                    self._status_label.setText(message)
                self._emit_output(env, {
                    "action": "builder_error",
                    "environment": env_id,
                    "error": str(e),
                })
                return
        elif env.get("kind") in {"looking-glass-vm", "qemu-vm"} and not source_spec.get("qemu_argv"):
            message = f"{env_name} is missing qemu_argv"
            if hasattr(self, "_status_label"):
                self._status_label.setText(message)
            self._emit_output(env, {
                "action": "builder_error",
                "environment": env_id,
                "error": "missing qemu_argv",
            })
            return

        if hasattr(self, "_status_label"):
            self._status_label.setText("")

        provider = create_source(source_spec)

        offset = 30 + (len(canvas._state.get("nodes", [])) % 8) * 30
        card = GenericSurfaceCardNode(
            provider=provider,
            source_spec=source_spec,
            surface_name=env_name,
            surface_kind=env.get("surface_kind", "vm"),
            width=480,
            node_title=env_name,
        )
        card.set_logical_pos(self._logical_x + offset, self._logical_y + offset)
        canvas._add_node(card)

        if canvas._state.get("selected_node"):
            canvas._state["selected_node"].deselect()
        canvas._state["selected_node"] = card
        card.select()
        canvas.update()

        card._launch()

        self._emit_output(env, {
            "action": "spawned",
            "environment": env_id,
            "source_spec": source_spec,
        })

    def _emit_output(self, env: dict, extra: dict | None = None):
        payload = {
            "type": "environment",
            "environment": env.get("id", ""),
            "name": env.get("name", ""),
        }
        if extra:
            payload.update(extra)
        for s in self._sockets:
            if s.label == "out":
                s.push_data(payload)

    def serialize(self) -> dict:
        return super().serialize()

    def deserialize(self, data: dict):
        super().deserialize(data)
