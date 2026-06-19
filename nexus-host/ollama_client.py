"""Ollama client for Nexus Host — model listing, chat streaming, health check."""

import json
import urllib.request
import urllib.error
import threading
from PyQt6.QtCore import QThread, pyqtSignal

OLLAMA_URL = "http://127.0.0.1:11434"
ADMIN_MODEL = "qwen3.5:0.8b"  # tiny assistant for settings — instant startup


class OllamaStreamThread(QThread):
    """Stream responses from Ollama in a background thread."""
    token = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, prompt: str, model: str = ADMIN_MODEL):
        super().__init__()
        self._prompt = prompt
        self._model = model

    def run(self):
        try:
            body = json.dumps({
                "model": self._model,
                "prompt": self._prompt,
                "stream": True,
                "options": {"num_predict": 1024, "num_ctx": 4096},
            }).encode("utf-8")
            req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            full = ""
            with urllib.request.urlopen(req, timeout=300) as resp:
                for line in resp:
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                        token = chunk.get("response", "")
                        full += token
                        self.token.emit(token)
                        if chunk.get("done"):
                            self.finished.emit(full)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            self.error.emit(str(e))


def get_models() -> list[str]:
    """Return list of installed Ollama model names."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def ollama_health() -> bool:
    """Check if Ollama is running and reachable."""
    try:
        req = urllib.request.Request(OLLAMA_URL)
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def get_model_info(model: str) -> dict | None:
    """Get detailed info about a specific model."""
    try:
        body = json.dumps({"name": model}).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_URL}/api/show", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None
