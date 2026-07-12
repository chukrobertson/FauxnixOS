from __future__ import annotations

from typing import List

from fauxnix_tools.llm.router import model_for_task

_ollama = None
try:
    import ollama as _ollama_mod
    _ollama = _ollama_mod
except Exception:
    pass


def _check():
    if _ollama is None:
        raise RuntimeError("Ollama package not installed. Run: pip install ollama")


def embed_text(text: str) -> List[float]:
    _check()
    text = (text or "")[:6000]
    model = model_for_task("embedding")
    res = _ollama.embeddings(model=model, prompt=text)
    return res["embedding"]


def chat_messages(messages: list[dict[str, str]], model: str | None = None, task: str | None = None, **kwargs) -> dict:
    _check()
    if model is None:
        model = model_for_task(task or "chat")
    res = _ollama.chat(model=model, messages=messages, **kwargs)
    if hasattr(res, "model_dump"):
        return res.model_dump()
    return res
