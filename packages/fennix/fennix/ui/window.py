from __future__ import annotations

try:
    from PyQt6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QTextEdit, QPushButton, QListWidget, QListWidgetItem,
        QSplitter, QTabWidget, QCheckBox, QFileDialog, QMessageBox,
    )
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QFont
    HAS_QT = True
except ImportError:
    HAS_QT = False

from fennix.assistant import answer, answer_with_file, get_conversation, list_conversations
from fennix.services import ServicesManager


class FennixWindow(QMainWindow):
    def __init__(self, services: ServicesManager):
        super().__init__()
        self._services = services
        self._conversation_id: str | None = None
        self.setWindowTitle("Fennix — FauxnixOS Assistant")
        self.resize(800, 600)
        self._setup_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(5000)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        tabs = QTabWidget()
        tabs.addTab(self._chat_tab(), "Chat")
        tabs.addTab(self._ingested_tab(), "Ingested Files")
        tabs.addTab(self._services_tab(), "Services")
        layout.addWidget(tabs)

    def _chat_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self._chat_history = QTextEdit()
        self._chat_history.setReadOnly(True)
        layout.addWidget(self._chat_history, 3)

        input_layout = QHBoxLayout()
        self._chat_input = QTextEdit()
        self._chat_input.setMaximumHeight(80)
        self._chat_input.setPlaceholderText("Ask Fennix. It knows your files, clipboard, and system...")
        input_layout.addWidget(self._chat_input, 4)

        btn_layout = QVBoxLayout()
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_chat)
        btn_layout.addWidget(send_btn)

        file_btn = QPushButton("+ File")
        file_btn.clicked.connect(self._send_with_file)
        btn_layout.addWidget(file_btn)
        input_layout.addLayout(btn_layout)
        layout.addLayout(input_layout)

        conv_layout = QHBoxLayout()
        conv_layout.addWidget(QLabel("Conversations:"))
        self._conv_list = QListWidget()
        self._conv_list.setMaximumHeight(100)
        self._conv_list.itemClicked.connect(self._load_conversation)
        conv_layout.addWidget(self._conv_list)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._new_chat)
        conv_layout.addWidget(new_btn)
        layout.addLayout(conv_layout)

        return w

    def _ingested_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Ingest File...")
        add_btn.clicked.connect(self._ingest_file)
        btn_layout.addWidget(add_btn)
        dir_btn = QPushButton("Ingest Directory...")
        dir_btn.clicked.connect(self._ingest_directory)
        btn_layout.addWidget(dir_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._ingested_list = QListWidget()
        self._ingested_list.itemDoubleClicked.connect(self._preview_ingested)
        layout.addWidget(self._ingested_list)

        self._ingested_preview = QTextEdit()
        self._ingested_preview.setReadOnly(True)
        layout.addWidget(self._ingested_preview)

        return w

    def _services_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Background Services"))
        layout.addWidget(QLabel("Toggle services on/off to control Fennix's awareness:"))

        self._service_checkboxes: dict[str, QCheckBox] = {}
        for svc_name in ["clipboard_watcher", "open_files_tracker",
                          "system_state_logger", "auto_ingestion_scanner",
                          "file_change_reconciler"]:
            cb = QCheckBox(svc_name.replace("_", " ").title())
            cb.setChecked(self._services.service_running(svc_name))
            cb.toggled.connect(lambda checked, n=svc_name: self._services.toggle_service(n, checked))
            layout.addWidget(cb)
            self._service_checkboxes[svc_name] = cb

        layout.addStretch()
        return w

    def _send_chat(self):
        text = self._chat_input.toPlainText().strip()
        if not text:
            return
        self._chat_input.clear()
        self._chat_history.append(f"<b>You:</b> {text}")
        self._chat_history.append("<i>Fennix is thinking...</i>")

        def _do():
            try:
                result = answer(text, self._conversation_id)
                self._conversation_id = result.get("conversation_id")
                reply = result.get("reply", "No response")
            except Exception as e:
                reply = f"Error: {e}"
            self._append_reply(reply)

        import threading
        t = threading.Thread(target=_do, daemon=True)
        t.start()

    def _send_with_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "",
            "All Files (*);;Text Files (*.txt *.md *.py *.js *.ts *.rs *.go *.json *.yaml *.yml *.toml *.html *.css *.csv *.log *.sh);;PDF Files (*.pdf)"
        )
        if not path:
            return
        text = self._chat_input.toPlainText().strip()
        if not text:
            self._chat_input.setPlainText(f"What's in {path.split('/')[-1]}?")
            return
        self._chat_input.clear()
        self._chat_history.append(f"<b>You:</b> {text} <i>(with {path.split('/')[-1]})</i>")
        self._chat_history.append("<i>Fennix is ingesting and thinking...</i>")

        def _do():
            try:
                result = answer_with_file(path, text, self._conversation_id)
                self._conversation_id = result.get("conversation_id")
                reply = result.get("reply", result.get("error", "No response"))
            except Exception as e:
                reply = f"Error: {e}"
            self._append_reply(reply)

        import threading
        t = threading.Thread(target=_do, daemon=True)
        t.start()

    def _append_reply(self, reply: str):
        cursor = self._chat_history.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._chat_history.setTextCursor(cursor)
        block = self._chat_history.document().lastBlock()
        if block.text() == "Fennix is thinking...":
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deletePreviousChar()
        self._chat_history.append(f"<b>Fennix:</b> {reply}<br>")

    def _new_chat(self):
        self._chat_history.clear()
        self._conversation_id = None

    def _load_conversation(self, item: QListWidgetItem):
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if not conv_id:
            return
        conv = get_conversation(conv_id)
        if not conv:
            return
        self._conversation_id = conv_id
        self._chat_history.clear()
        for msg in conv.get("messages", []):
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                self._chat_history.append(f"<b>You:</b> {content}")
            elif role == "assistant":
                self._chat_history.append(f"<b>Fennix:</b> {content}")
            self._chat_history.append("")

    def _ingest_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Ingest", "",
            "All Files (*);;Text Files (*.txt *.md *.py *.js *.ts *.rs *.go *.json *.yaml *.yml *.toml *.html *.css *.csv *.log *.sh);;PDF Files (*.pdf)"
        )
        if not path:
            return
        self._do_ingest(path)

    def _ingest_directory(self):
        from PyQt6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Select Directory to Ingest")
        if not path:
            return
        self._do_ingest(path)

    def _do_ingest(self, path: str):
        from pathlib import Path

        def _ingest():
            p = Path(path)
            if p.is_file():
                from fennix.ingestion.__init__ import ingest_content
                from fauxnix_tools.utils import sha256_file
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    file_hash = sha256_file(p)
                    ingest_content(str(p), file_hash, content, source="manual")
                except Exception:
                    return
            elif p.is_dir():
                from fennix.ingestion.__init__ import ingest_content
                from fauxnix_tools.utils import sha256_file
                max_size = 10 * 1024 * 1024
                exclude = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"}
                count = 0
                for entry in p.rglob("*"):
                    if entry.is_dir():
                        continue
                    if any(part in exclude for part in entry.parts):
                        continue
                    if entry.suffix not in {
                        ".txt", ".md", ".py", ".js", ".ts", ".rs", ".go",
                        ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
                        ".sh", ".bash", ".zsh", ".html", ".css", ".csv", ".log",
                    }:
                        continue
                    try:
                        if entry.stat().st_size > max_size:
                            continue
                    except OSError:
                        continue
                    try:
                        content = entry.read_text(encoding="utf-8", errors="replace")
                        file_hash = sha256_file(entry)
                        ingest_content(str(entry), file_hash, content, source="manual")
                        count += 1
                    except Exception:
                        continue

            self.update_ingested_list()

        import threading
        t = threading.Thread(target=_ingest, daemon=True)
        t.start()

    def _preview_ingested(self, item: QListWidgetItem):
        file_id = item.data(Qt.ItemDataRole.UserRole)
        if not file_id:
            return
        from fauxnix_tools.db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM fennix_file_chunks WHERE ingested_file_id = ? ORDER BY chunk_index ASC LIMIT 10",
            (file_id,),
        )
        rows = cur.fetchall()
        conn.close()
        preview = "\n\n---\n\n".join(r["content"][:500] for r in rows)
        self._ingested_preview.setPlainText(preview)

    def update_ingested_list(self):
        if not HAS_QT:
            return
        from fauxnix_tools.db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, file_path, title, mime_type, file_size, ingested_ts FROM fennix_ingested_files ORDER BY ingested_ts DESC LIMIT 30"
        )
        rows = cur.fetchall()
        conn.close()

        self._ingested_list.clear()
        for r in rows:
            size_kb = int((r["file_size"] or 0) / 1024)
            item_text = f"{r['title'] or r['file_path']} ({size_kb}KB)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self._ingested_list.addItem(item)

    def _refresh(self):
        if not HAS_QT:
            return

        for svc_name, cb in getattr(self, '_service_checkboxes', {}).items():
            cb.setChecked(self._services.service_running(svc_name))

        convs = list_conversations(limit=5)
        self._conv_list.clear()
        for c in convs:
            title = (c.get("title") or "Untitled")[:60]
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            self._conv_list.addItem(item)
